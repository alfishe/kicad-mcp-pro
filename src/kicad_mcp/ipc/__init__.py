"""KiCad IPC client, discovery, session, and capability helpers."""

from .capabilities import (
    REQUIRED_LIVE_EDITING_TOOLS,
    KiCadIpcCapabilityState,
    get_ipc_capability_state,
)
from .client import KiCadIpcClient
from .command_queue import (
    JournalEntry,
    KiCadCommandQueue,
    RetryClass,
    classify_error,
    get_command_queue,
    reset_command_queue,
)
from .discovery import KiCadIpcDiscovery, KiCadIpcEndpoint, discover_socket_candidates
from .errors import (
    KiCadIpcBusyError,
    KiCadIpcError,
    KiCadIpcTimeoutError,
    KiCadIpcUnavailableError,
)
from .session import (
    HeadlessServerSession,
    SessionConfig,
    SessionManager,
    get_session_manager,
    reset_session_manager,
)

__all__ = [
    "REQUIRED_LIVE_EDITING_TOOLS",
    "HeadlessServerSession",
    "JournalEntry",
    "KiCadCommandQueue",
    "KiCadIpcCapabilityState",
    "KiCadIpcClient",
    "KiCadIpcBusyError",
    "KiCadIpcDiscovery",
    "KiCadIpcEndpoint",
    "KiCadIpcError",
    "KiCadIpcTimeoutError",
    "KiCadIpcUnavailableError",
    "RetryClass",
    "SessionConfig",
    "SessionManager",
    "classify_error",
    "discover_socket_candidates",
    "get_command_queue",
    "get_ipc_capability_state",
    "get_session_manager",
    "reset_command_queue",
    "reset_session_manager",
]
