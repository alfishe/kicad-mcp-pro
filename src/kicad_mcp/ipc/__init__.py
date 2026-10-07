"""KiCad IPC client, discovery, and capability helpers."""

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

__all__ = [
    "REQUIRED_LIVE_EDITING_TOOLS",
    "JournalEntry",
    "KiCadCommandQueue",
    "KiCadIpcCapabilityState",
    "KiCadIpcClient",
    "KiCadIpcBusyError",
    "KiCadIpcDiscovery",
    "KiCadIpcEndpoint",
    "discover_socket_candidates",
    "KiCadIpcError",
    "KiCadIpcTimeoutError",
    "KiCadIpcUnavailableError",
    "RetryClass",
    "classify_error",
    "get_command_queue",
    "get_ipc_capability_state",
    "reset_command_queue",
]
