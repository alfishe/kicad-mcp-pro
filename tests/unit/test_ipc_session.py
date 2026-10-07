"""Tests for headless kicad-cli api-server session management."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from kicad_mcp.ipc.errors import KiCadIpcUnavailableError
from kicad_mcp.ipc.session import (
    HeadlessServerSession,
    SessionConfig,
    SessionManager,
)

FAKE_SERVER = """#!/bin/sh
SOCK=""
PRELOAD=""
while [ $# -gt 0 ]; do
  case "$1" in
    --socket) SOCK="$2"; shift 2 ;;
    --socket=*) SOCK="${1#--socket=}" ; shift ;;
    api-server) shift ;;
    *) PRELOAD="$1"; shift ;;
  esac
done
[ -n "$PRELOAD" ] && echo "preloading $PRELOAD"
touch "$SOCK"
echo "KiCad API server listening at $SOCK"
trap 'exit 0' TERM
while :; do sleep 0.1; done
"""

EARLY_EXIT_SERVER = """#!/bin/sh
echo "bad arguments: simulation"
exit 3
"""

STUBBORN_SERVER = """#!/bin/sh
SOCK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --socket) SOCK="$2"; shift 2 ;;
    *) shift ;;
  esac
done
touch "$SOCK"
echo "KiCad API server listening at $SOCK"
trap '' TERM
while :; do sleep 0.1; done
"""


def _write_script(tmp_path: Path, name: str, body: str) -> Path:
    script = tmp_path / name
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _config(tmp_path: Path, script: Path, **overrides: object) -> SessionConfig:
    fields: dict[str, object] = {
        "kicad_cli": script,
        "socket_path": tmp_path / "session.sock",
        "ready_timeout": 10.0,
        "stop_timeout": 5.0,
    }
    fields.update(overrides)
    return SessionConfig(**fields)  # type: ignore[arg-type]


def test_start_health_stop_roundtrip(tmp_path: Path) -> None:
    script = _write_script(tmp_path, "fake-server", FAKE_SERVER)
    session = HeadlessServerSession(
        _config(tmp_path, script),
        name="t",
        health_prober=lambda path: {"connected": True, "socket": str(path)},
    )

    socket = session.start()
    assert socket == tmp_path / "session.sock"
    assert session.running

    report = session.health()
    assert report["connected"] is True

    assert session.stop() is True
    assert not session.running
    assert not socket.exists()


def test_start_reports_early_exit_with_log_tail(tmp_path: Path) -> None:
    script = _write_script(tmp_path, "early-exit", EARLY_EXIT_SERVER)
    session = HeadlessServerSession(_config(tmp_path, script), name="early")

    with pytest.raises(KiCadIpcUnavailableError, match="bad arguments"):
        session.start()
    assert not session.running
    assert "bad arguments: simulation" in session.log_tail


def test_start_rejects_existing_socket(tmp_path: Path) -> None:
    script = _write_script(tmp_path, "fake-server", FAKE_SERVER)
    socket = tmp_path / "session.sock"
    socket.touch()

    session = HeadlessServerSession(_config(tmp_path, script), name="busy")
    with pytest.raises(KiCadIpcUnavailableError, match="already exists"):
        session.start()


def test_start_rejects_missing_cli(tmp_path: Path) -> None:
    session = HeadlessServerSession(
        _config(tmp_path, tmp_path / "no-such-cli"), name="missing"
    )
    with pytest.raises(KiCadIpcUnavailableError, match="not found"):
        session.start()


def test_stop_escalates_to_sigkill_for_stubborn_process(tmp_path: Path) -> None:
    script = _write_script(tmp_path, "stubborn", STUBBORN_SERVER)
    session = HeadlessServerSession(
        _config(tmp_path, script, stop_timeout=0.5), name="stubborn"
    )
    session.start()

    assert session.stop() is False  # had to SIGKILL
    assert not session.running


def test_double_start_raises(tmp_path: Path) -> None:
    script = _write_script(tmp_path, "fake-server", FAKE_SERVER)
    session = HeadlessServerSession(_config(tmp_path, script), name="double")
    session.start()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            session.start()
    finally:
        session.stop()


def test_session_manager_registry(tmp_path: Path) -> None:
    script = _write_script(tmp_path, "fake-server", FAKE_SERVER)
    manager = SessionManager()

    session = manager.start(
        "alpha",
        kicad_cli=script,
        socket_path=tmp_path / "alpha.sock",
        ready_timeout=10.0,
        stop_timeout=5.0,
    )
    assert manager.get("alpha") is session
    assert manager.names == ["alpha"]

    with pytest.raises(RuntimeError, match="already running"):
        manager.start("alpha", kicad_cli=script, socket_path=tmp_path / "alpha2.sock")

    assert manager.stop("alpha") is True
    with pytest.raises(KeyError):
        manager.get("alpha")

    manager.start("beta", kicad_cli=script, socket_path=tmp_path / "beta.sock")
    manager.stop_all()
    assert manager.names == []


def test_context_manager_stops_on_exit(tmp_path: Path) -> None:
    script = _write_script(tmp_path, "fake-server", FAKE_SERVER)
    session = HeadlessServerSession(_config(tmp_path, script), name="ctx")

    with session as active:
        assert active.running
        assert os.path.exists(active.socket_path or "")
    assert not session.running
