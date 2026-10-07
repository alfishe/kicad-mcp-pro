"""KiCad IPC endpoint discovery."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

EndpointSource = Literal["config", "environment", "discovered", "default"]


class IpcDiscoveryConfig(Protocol):
    """Configuration protocol used by KiCadIpcDiscovery."""

    kicad_socket_path: str | Path | None
    kicad_token: str | None
    ipc_connection_timeout: float


ConfigFactory = Callable[[], IpcDiscoveryConfig]


@dataclass(frozen=True)
class KiCadIpcEndpoint:
    """Resolved KiCad IPC endpoint metadata."""

    socket_path: str | Path | None
    source: EndpointSource
    token_configured: bool
    timeout_ms: int


def _normalize_endpoint(value: str) -> str | Path:
    """Preserve URI endpoints and expand plain filesystem socket paths."""
    endpoint = value.strip()
    if "://" in endpoint:
        return endpoint
    return Path(endpoint).expanduser()


def _endpoints_equal(raw: str, configured: str | Path) -> bool:
    """Compare an environment endpoint with its normalized config value."""
    normalized = _normalize_endpoint(raw)
    return normalized == configured


def _default_config() -> IpcDiscoveryConfig:
    from ..config import get_config

    return get_config()


def _socket_search_dirs() -> list[Path]:
    # KiCad (common/api/api_server.cpp, StandardSocketPath) uses /tmp/kicad on macOS
    # and $TMPDIR/kicad elsewhere; probe both so a socket is found regardless of platform.
    dirs = [Path("/tmp") / "kicad", Path(tempfile.gettempdir()) / "kicad"]
    unique: list[Path] = []
    for directory in dirs:
        if directory not in unique:
            unique.append(directory)
    return unique


def discover_socket_candidates(
    base_dirs: Iterable[Path] | None = None,
) -> list[Path]:
    """Probe the filesystem for live KiCad API sockets, multi-instance aware.

    The first KiCad instance listens on ``<tmpdir>/kicad/api.sock``; additional
    instances fall back to ``api-{PID}.sock`` in the same directory (see
    ``KICAD_API_SERVER::Start()``). Candidates are ordered: the canonical
    ``api.sock`` first, then ``api-*.sock`` by newest mtime, so a freshly spawned
    headless server wins over long-running GUI instances.
    """
    if base_dirs is None:
        base_dirs = _socket_search_dirs()

    candidates: list[Path] = []
    seen: set[Path] = set()

    for base in base_dirs:
        if not base.is_dir():
            continue

        canonical = base / "api.sock"
        if canonical.exists() and canonical not in seen:
            candidates.append(canonical)
            seen.add(canonical)

        pid_sockets = [path for path in base.glob("api-*.sock") if path.exists() and path not in seen]
        pid_sockets.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        candidates.extend(pid_sockets)
        seen.update(pid_sockets)

    return candidates


class KiCadIpcDiscovery:
    """Discover how the server should connect to the running KiCad IPC API."""

    def __init__(self, *, config_factory: ConfigFactory = _default_config) -> None:
        self._config_factory = config_factory

    def discover(self) -> KiCadIpcEndpoint:
        """Return configured, environment, or default KiCad IPC endpoint metadata."""
        cfg = self._config_factory()
        env_socket = os.environ.get("KICAD_API_SOCKET")
        if cfg.kicad_socket_path is not None:
            return KiCadIpcEndpoint(
                socket_path=cfg.kicad_socket_path,
                source="environment"
                if env_socket and _endpoints_equal(env_socket, cfg.kicad_socket_path)
                else "config",
                token_configured=bool(cfg.kicad_token),
                timeout_ms=int(cfg.ipc_connection_timeout * 1000),
            )

        if env_socket:
            return KiCadIpcEndpoint(
                socket_path=_normalize_endpoint(env_socket),
                source="environment",
                token_configured=bool(cfg.kicad_token or os.environ.get("KICAD_API_TOKEN")),
                timeout_ms=int(cfg.ipc_connection_timeout * 1000),
            )

        candidates = discover_socket_candidates()
        if candidates:
            return KiCadIpcEndpoint(
                socket_path=candidates[0],
                source="discovered",
                token_configured=bool(cfg.kicad_token or os.environ.get("KICAD_API_TOKEN")),
                timeout_ms=int(cfg.ipc_connection_timeout * 1000),
            )

        return KiCadIpcEndpoint(
            socket_path=None,
            source="default",
            token_configured=bool(cfg.kicad_token or os.environ.get("KICAD_API_TOKEN")),
            timeout_ms=int(cfg.ipc_connection_timeout * 1000),
        )
