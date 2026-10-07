"""Tests for filesystem KiCad IPC socket discovery (multi-instance api-{PID}.sock)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from kicad_mcp.ipc.discovery import KiCadIpcDiscovery, discover_socket_candidates


@dataclass(frozen=True)
class _FakeConfig:
    kicad_socket_path: str | Path | None = None
    kicad_token: str | None = None
    ipc_connection_timeout: float = 2.0


def _make_socket(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_canonical_socket_comes_first(tmp_path: Path) -> None:
    _make_socket(tmp_path / "api-123.sock")
    _make_socket(tmp_path / "api.sock")

    candidates = discover_socket_candidates(base_dirs=[tmp_path])

    assert candidates == [tmp_path / "api.sock", tmp_path / "api-123.sock"]


def test_pid_sockets_ordered_newest_mtime_first(tmp_path: Path) -> None:
    old = _make_socket(tmp_path / "api-100.sock")
    new = _make_socket(tmp_path / "api-200.sock")
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))

    candidates = discover_socket_candidates(base_dirs=[tmp_path])

    assert candidates == [new, old]


def test_missing_base_dirs_are_skipped(tmp_path: Path) -> None:
    candidates = discover_socket_candidates(base_dirs=[tmp_path / "nope", tmp_path / "kicad"])

    assert candidates == []


def test_nonexistent_sockets_are_ignored(tmp_path: Path) -> None:
    # glob() can match nothing; ensure a bare directory yields no candidates.
    candidates = discover_socket_candidates(base_dirs=[tmp_path])

    assert candidates == []


def test_discover_falls_back_to_filesystem_socket(tmp_path: Path, monkeypatch) -> None:
    socket = _make_socket(tmp_path / "kicad" / "api-777.sock")
    monkeypatch.setattr(
        "kicad_mcp.ipc.discovery.discover_socket_candidates",
        lambda base_dirs=None: [socket],
    )

    endpoint = KiCadIpcDiscovery(config_factory=lambda: _FakeConfig()).discover()

    assert endpoint.socket_path == socket
    assert endpoint.source == "discovered"


def test_discover_prefers_config_over_filesystem(tmp_path: Path, monkeypatch) -> None:
    configured = tmp_path / "explicit.sock"
    monkeypatch.setattr(
        "kicad_mcp.ipc.discovery.discover_socket_candidates",
        lambda base_dirs=None: [tmp_path / "api.sock"],
    )

    endpoint = KiCadIpcDiscovery(
        config_factory=lambda: _FakeConfig(kicad_socket_path=str(configured))
    ).discover()

    assert endpoint.socket_path == str(configured)
    assert endpoint.source == "config"


def test_discover_returns_default_when_nothing_found(monkeypatch) -> None:
    # Deterministic even on machines with live KiCad instances in /tmp/kicad.
    monkeypatch.setattr(
        "kicad_mcp.ipc.discovery.discover_socket_candidates",
        lambda base_dirs=None: [],
    )

    endpoint = KiCadIpcDiscovery(config_factory=lambda: _FakeConfig()).discover()

    assert endpoint.socket_path is None
    assert endpoint.source == "default"
