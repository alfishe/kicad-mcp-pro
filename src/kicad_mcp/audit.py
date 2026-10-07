"""Append-only audit trail of tool invocations (ROADMAP M0 P0, gate G5).

Every tool registered through ``KiCadFastMCP.tool()`` is wrapped so each call
appends ``(seq, ts, tool, args, status, duration_ms)`` to a durable JSONL file.
Recent calls are kept in memory with their invocation closures so an agent can
``audit_replay`` them. The JSONL file is the durable evidence; replay works on
the live session's records.
"""

from __future__ import annotations

import datetime as _dt
import functools
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_LOG_LOCK = threading.Lock()
_MAX_MEMORY_RECORDS = 500


def _default_log_path() -> Path:
    override = os.environ.get("KICAD_MCP_AUDIT_LOG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".kicad-mcp" / "audit.jsonl"


def _audit_disabled() -> bool:
    return os.environ.get("KICAD_MCP_AUDIT_DISABLE", "").strip() in {"1", "true", "yes"}


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One completed tool invocation."""

    seq: int
    ts: str
    tool: str
    args: dict[str, Any]
    status: str
    duration_ms: float
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "seq": self.seq,
                "ts": self.ts,
                "tool": self.tool,
                "args": self.args,
                "status": self.status,
                "duration_ms": round(self.duration_ms, 2),
                **({"error": self.error} if self.error else {}),
            },
            ensure_ascii=False,
            default=repr,
        )


@dataclass
class _MemoryEntry:
    record: AuditRecord
    reinvoke: Callable[[dict[str, Any]], object]


class AuditLog:
    """Durable JSONL store plus an in-memory replay registry."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_log_path()
        self._lock = threading.Lock()
        self._seq = 0
        self._seq_initialized = False
        self._memory: deque[_MemoryEntry] = deque(maxlen=_MAX_MEMORY_RECORDS)

    @property
    def path(self) -> Path:
        return self._path

    def _next_seq(self) -> int:
        if not self._seq_initialized:
            with _LOG_LOCK:
                if self._path.exists():
                    with self._path.open("r", encoding="utf-8") as fh:
                        self._seq = sum(1 for line in fh if line.strip())
                else:
                    self._seq = 0
            self._seq_initialized = True
        self._seq += 1
        return self._seq

    def record(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        status: str,
        duration_ms: float,
        error: str | None = None,
        reinvoke: Callable[[dict[str, Any]], object] | None = None,
    ) -> AuditRecord | None:
        """Append one record; returns None when auditing is disabled."""
        if _audit_disabled():
            return None

        record = AuditRecord(
            seq=self._next_seq(),
            ts=_utc_now_iso(),
            tool=tool,
            args=args,
            status=status,
            duration_ms=duration_ms,
            error=error,
        )
        line = record.to_json()
        with _LOG_LOCK:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

        if reinvoke is not None:
            with _LOG_LOCK:
                self._memory.append(_MemoryEntry(record, reinvoke))
        else:
            with _LOG_LOCK:
                self._memory.append(_MemoryEntry(record, None))
        return record

    def tail(self, limit: int = 20) -> list[AuditRecord]:
        """Return the most recent in-memory records (oldest first)."""
        with _LOG_LOCK:
            entries = list(self._memory)
        return [entry.record for entry in entries[-limit:]]

    async def replay(
        self,
        since_seq: int = 0,
        *,
        limit: int = 50,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        """Re-invoke recorded calls with ``seq > since_seq`` (newest last).

        ``dry_run=True`` returns the plan without executing. Only records that
        carry an invocation closure are replayable.
        """
        with _LOG_LOCK:
            candidates = [
                entry
                for entry in self._memory
                if entry.record.seq > since_seq
                and entry.record.status == "ok"
                and entry.reinvoke is not None
            ]
            candidates = candidates[-limit:]

        if dry_run:
            return [
                {"seq": entry.record.seq, "tool": entry.record.tool, "args": entry.record.args}
                for entry in candidates
            ]

        results: list[dict[str, Any]] = []
        for entry in candidates:
            started = time.perf_counter()
            try:
                outcome = entry.reinvoke(entry.record.args)
                if hasattr(outcome, "__await__"):
                    await outcome
                status, error = "ok", None
            except Exception as exc:  # noqa: BLE001 - replay must not raise mid-batch
                status, error = "error", str(exc)
            results.append(
                {
                    "seq": entry.record.seq,
                    "tool": entry.record.tool,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    **({"error": error} if error else {}),
                }
            )
        return results


_log: AuditLog | None = None
_log_lock = threading.Lock()


def get_audit_log() -> AuditLog:
    global _log
    with _log_lock:
        if _log is None:
            _log = AuditLog()
        return _log


def reset_audit_log() -> None:
    global _log
    with _log_lock:
        _log = None


def _safe_args(args: dict[str, Any]) -> dict[str, Any]:
    """Keep only JSON-serializable values; frameworks may inject Context objects."""
    clean: dict[str, Any] = {}
    for key, value in args.items():
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            clean[key] = repr(value)[:200]
        else:
            clean[key] = value
    return clean


def wrap_tool_audit(
    tool_name: str, func: Callable[..., Any] | None = None
) -> Callable[..., Any]:
    """Wrap an (async) registered tool so each invocation is audited + replayable.

    Usable directly (``wrap_tool_audit(name, func)``) or as a decorator factory
    (``@wrap_tool_audit(name)``).
    """
    if func is None:

        def _decorator(target: Callable[..., Any]) -> Callable[..., Any]:
            return wrap_tool_audit(tool_name, target)

        return _decorator

    @functools.wraps(func)
    async def audited(*args: object, **kwargs: object) -> object:
        audit_args: dict[str, Any] = _safe_args({**kwargs})
        if args:
            audit_args["__positional"] = [repr(a)[:120] for a in args]

        def reinvoke(replay_args: dict[str, Any]) -> object:
            call_args = replay_args.get("__positional", [])
            clean = {k: v for k, v in replay_args.items() if k != "__positional"}
            return func(*call_args, **clean)

        started = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            get_audit_log().record(
                tool=tool_name,
                args=audit_args,
                status="error",
                duration_ms=(time.perf_counter() - started) * 1000,
                error=str(exc)[:500],
                reinvoke=reinvoke,
            )
            raise
        get_audit_log().record(
            tool=tool_name,
            args=audit_args,
            status="ok",
            duration_ms=(time.perf_counter() - started) * 1000,
            reinvoke=reinvoke,
        )
        return result

    return audited
