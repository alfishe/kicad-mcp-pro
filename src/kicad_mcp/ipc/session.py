"""Headless KiCad API server session management (``kicad-cli api-server``).

Spawns, monitors, and stops headless KiCad API server processes so agents can
run against isolated instances (unique sockets) without a GUI. Readiness is
detected from the server's stdout marker ("KiCad API server listening at ...")
and confirmed via an IPC health probe.
"""

from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .errors import KiCadIpcUnavailableError

_READY_MARKER = "listening at"
_LOG_TAIL_LINES = 50


@dataclass
class SessionConfig:
    """Parameters for one headless ``kicad-cli api-server`` process."""

    kicad_cli: Path | None = None
    socket_path: Path | None = None
    preload: Path | None = None
    ready_timeout: float = 30.0
    stop_timeout: float = 10.0
    env: dict[str, str] = field(default_factory=dict)


def _resolve_kicad_cli(explicit: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    from ..config import get_config

    return Path(get_config().kicad_cli)


def _default_socket_path(name: str) -> Path:
    return Path(tempfile.gettempdir()) / "kicad" / f"api-mcp-{name}.sock"


HealthProber = Callable[[Path], dict[str, object]]


def _default_health_prober(socket_path: Path) -> dict[str, object]:
    """Health-check a socket with a dedicated kipy connection (no globals)."""
    try:
        from kipy import KiCad
    except Exception as exc:  # pragma: no cover - optional kipy boundary
        raise KiCadIpcUnavailableError(f"kipy is unavailable: {exc}") from exc

    try:
        client = KiCad(
            socket_path=f"ipc://{socket_path}",
            client_name=f"kicad-mcp-session-{uuid.uuid4().hex[:8]}",
        )
        version = client.get_version()
        ping = getattr(client, "ping", None)
        if callable(ping):
            ping()
    except Exception as exc:
        raise KiCadIpcUnavailableError(
            f"Headless KiCad session not healthy on {socket_path}: {exc}"
        ) from exc

    return {"connected": True, "socket": str(socket_path), "version": str(version)}


class HeadlessServerSession:
    """One spawned ``kicad-cli api-server`` process and its lifecycle."""

    def __init__(
        self,
        config: SessionConfig | None = None,
        *,
        name: str = "session",
        health_prober: HealthProber | None = None,
    ) -> None:
        self._config = config or SessionConfig()
        self._name = name
        self._health_prober = health_prober or _default_health_prober
        self._proc: subprocess.Popen[str] | None = None
        self._socket_path: Path | None = None
        self._line_queue: queue.Queue[str] = queue.Queue()
        self._log_tail: deque[str] = deque(maxlen=_LOG_TAIL_LINES)
        self._reader: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def socket_path(self) -> Path | None:
        return self._socket_path

    @property
    def log_tail(self) -> list[str]:
        return list(self._log_tail)

    def start(self) -> Path:
        """Spawn the server and block until it reports its listening socket."""
        if self.running:
            raise RuntimeError(f"session {self._name!r} is already running")

        cli = _resolve_kicad_cli(self._config.kicad_cli)
        if not cli.exists():
            raise KiCadIpcUnavailableError(
                f"kicad-cli not found at {cli}; set KICAD_CLI_PATH or install KiCad"
            )

        socket_path = self._config.socket_path or _default_socket_path(
            f"{self._name}-{uuid.uuid4().hex[:8]}"
        )
        socket_path = Path(socket_path).expanduser()
        if socket_path.exists():
            raise KiCadIpcUnavailableError(
                f"socket {socket_path} already exists; pick a unique session socket"
            )
        socket_path.parent.mkdir(parents=True, exist_ok=True)

        argv = [str(cli), "api-server", "--socket", str(socket_path)]
        if self._config.preload is not None:
            argv.append(str(self._config.preload))

        env = {**os.environ, **self._config.env}

        try:
            self._proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
        except OSError as exc:
            raise KiCadIpcUnavailableError(f"failed to spawn {cli}: {exc}") from exc

        self._socket_path = socket_path
        self._reader = threading.Thread(
            target=self._drain_output, args=(self._proc,), daemon=True
        )
        self._reader.start()

        try:
            self._wait_ready()
        except Exception:
            self.stop()
            raise

        return self._socket_path

    def health(
        self,
        *,
        retries: int = 20,
        retry_delay: float = 0.25,
    ) -> dict[str, object]:
        """Probe the session over IPC; raises KiCadIpcUnavailableError if dead.

        Retries transient failures (the server answers "not ready to reply"
        while it is still preloading documents after the socket appears).
        """
        if not self.running or self._socket_path is None:
            raise KiCadIpcUnavailableError(f"session {self._name!r} is not running")

        last_error: Exception | None = None
        for _ in range(max(1, retries)):
            try:
                return self._health_prober(self._socket_path)
            except KiCadIpcUnavailableError as exc:
                last_error = exc
                time.sleep(retry_delay)
        raise KiCadIpcUnavailableError(
            f"session {self._name!r} did not become healthy: {last_error}"
        )

    def stop(self) -> bool:
        """Terminate the server; returns True when it exited within the budget."""
        proc = self._proc
        if proc is None:
            return True

        exited_cleanly = True
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=self._config.stop_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=self._config.stop_timeout)
                exited_cleanly = False

        if self._reader is not None:
            self._reader.join(timeout=1.0)
            self._reader = None

        if self._socket_path is not None:
            self._socket_path.unlink(missing_ok=True)

        self._proc = None
        return exited_cleanly

    def __enter__(self) -> HeadlessServerSession:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    # -- internals ---------------------------------------------------------

    def _drain_output(self, proc: subprocess.Popen[str]) -> None:
        stream = proc.stdout
        if stream is None:
            return
        for line in stream:
            stripped = line.rstrip("\n")
            self._log_tail.append(stripped)
            self._line_queue.put(stripped)

    def _wait_ready(self) -> None:
        if self._proc is None or self._socket_path is None:
            raise RuntimeError("_wait_ready called before the process was spawned")
        deadline = time.monotonic() + self._config.ready_timeout

        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise KiCadIpcUnavailableError(
                    f"headless KiCad exited early (code {self._proc.returncode}): "
                    + (" | ".join(self._log_tail) or "no output")
                )
            try:
                line = self._line_queue.get(timeout=0.1)
            except queue.Empty:
                line = None
            if line and _READY_MARKER in line:
                reported = line.split(_READY_MARKER, 1)[1].strip()
                if reported:
                    self._socket_path = Path(reported)
                return
            # stdout may stay fully buffered when piped; the socket file is the
            # authoritative readiness signal (KINNG creates it before accepting).
            if self._socket_path.exists():
                return

        raise KiCadIpcUnavailableError(
            f"headless KiCad not ready within {self._config.ready_timeout:g}s: "
            + (" | ".join(self._log_tail) or "no output")
        )


class SessionManager:
    """Named registry of headless sessions (per-project isolation)."""

    def __init__(self) -> None:
        self._sessions: dict[str, HeadlessServerSession] = {}

    def start(
        self,
        name: str,
        config: SessionConfig | None = None,
        **overrides: object,
    ) -> HeadlessServerSession:
        if name in self._sessions and self._sessions[name].running:
            raise RuntimeError(f"session {name!r} is already running")
        if config is not None and overrides:
            raise ValueError("pass either config or field overrides, not both")

        if config is None:
            config = SessionConfig(**overrides)  # type: ignore[arg-type]
        session = HeadlessServerSession(config, name=name)
        session.start()
        self._sessions[name] = session
        return session

    def get(self, name: str) -> HeadlessServerSession:
        return self._sessions[name]

    def stop(self, name: str) -> bool:
        session = self._sessions.pop(name)
        return session.stop()

    def stop_all(self) -> None:
        for name in list(self._sessions):
            self.stop(name)

    @property
    def names(self) -> list[str]:
        return list(self._sessions)


_manager: SessionManager | None = None
_manager_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = SessionManager()
        return _manager


def reset_session_manager() -> None:
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.stop_all()
        _manager = None
