"""Tests for the tool invocation audit trail."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp import audit as audit_module
from kicad_mcp.audit import AuditLog, get_audit_log, reset_audit_log, wrap_tool_audit


@pytest.fixture(autouse=True)
def _isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KICAD_MCP_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("KICAD_MCP_AUDIT_DISABLE", raising=False)
    reset_audit_log()
    yield
    reset_audit_log()


async def test_record_tail_and_persistence(tmp_path: Path) -> None:
    log = get_audit_log()
    first = log.record(tool="t1", args={"a": 1}, status="ok", duration_ms=1.5)
    second = log.record(tool="t2", args={"b": 2}, status="error", duration_ms=2.0, error="boom")

    assert first is not None and second is not None
    assert second.seq == first.seq + 1

    tail = log.tail(10)
    assert [r.tool for r in tail] == ["t1", "t2"]

    # A fresh instance reads the same file and continues the sequence.
    reopened = AuditLog(path=tmp_path / "audit.jsonl")
    third = reopened.record(tool="t3", args={}, status="ok", duration_ms=0.1)
    assert third is not None and third.seq == 3


async def test_wrap_tool_audit_records_ok_and_error(tmp_path: Path) -> None:
    log = get_audit_log()

    @wrap_tool_audit("sync_ok")
    async def ok_tool(a: int = 0) -> int:
        return a * 2

    @wrap_tool_audit("sync_boom")
    async def boom_tool() -> None:
        raise ValueError("kaboom")

    assert await ok_tool(a=21) == 42
    with pytest.raises(ValueError, match="kaboom"):
        await boom_tool()

    records = log.tail(10)
    assert [r.status for r in records] == ["ok", "error"]
    assert records[0].args == {"a": 21}
    assert records[1].error is not None and "kaboom" in records[1].error


async def test_replay_reexecutes_recorded_calls(tmp_path: Path) -> None:
    log = get_audit_log()
    calls: list[int] = []

    @wrap_tool_audit("add")
    async def add(a: int) -> int:
        calls.append(a)
        return a

    await add(a=1)
    await add(a=2)
    first_seq = log.tail(2)[0].seq

    plan = await log.replay(since_seq=first_seq, dry_run=True)
    assert [p["args"]["a"] for p in plan] == [2]
    assert calls == [1, 2]  # dry run must not execute

    results = await log.replay(since_seq=first_seq)
    assert [r["status"] for r in results] == ["ok"]
    assert calls == [1, 2, 2]


def test_audit_can_be_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KICAD_MCP_AUDIT_DISABLE", "1")
    log = get_audit_log()

    record = log.record(tool="t", args={}, status="ok", duration_ms=0.0)

    assert record is None
    assert log.tail(10) == []
    assert not (tmp_path / "audit.jsonl").exists()


def test_get_audit_log_is_singleton() -> None:
    assert get_audit_log() is get_audit_log()


def test_default_log_path_honors_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KICAD_MCP_AUDIT_LOG", str(tmp_path / "custom.jsonl"))
    assert audit_module._default_log_path() == tmp_path / "custom.jsonl"


async def test_wrap_tool_audit_sanitizes_unserializable_args() -> None:
    @wrap_tool_audit("with_ctx")
    async def tool(ctx: object = None) -> str:
        return "ran"

    assert await tool(ctx=object()) == "ran"

    record = get_audit_log().tail(1)[0]
    assert record.status == "ok"
    assert "object at" in str(record.args["ctx"])


def test_audit_tools_are_registered() -> None:
    import asyncio

    from mcp.server.mcpserver import MCPServer as FastMCP

    from kicad_mcp.tools import audit_tools

    mcp = FastMCP("smoke")
    audit_tools.register(mcp)
    loop = asyncio.new_event_loop()
    try:
        names = {tool.name for tool in loop.run_until_complete(mcp.list_tools())}
    finally:
        loop.close()

    assert {"audit_tail", "audit_replay"} <= names
