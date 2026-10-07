"""Audit trail inspection and replay tools."""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer as FastMCP

from ..audit import get_audit_log


def register(mcp: FastMCP) -> None:
    """Register audit inspection and replay tools."""

    @mcp.tool()
    def audit_tail(limit: int = 20) -> str:
        """Show the most recent audited tool invocations.

        Returns seq, timestamp, tool name, arguments, status, and duration per
        record. Durable JSONL evidence lives at KICAD_MCP_AUDIT_LOG (default
        ~/.kicad-mcp/audit.jsonl).
        """
        records = get_audit_log().tail(max(1, min(limit, 200)))
        return json.dumps([json.loads(r.to_json()) for r in records], indent=2)

    @mcp.tool()
    async def audit_replay(since_seq: int = 0, limit: int = 50, dry_run: bool = False) -> str:
        """Re-execute audited successful tool calls with seq greater than since_seq.

        Re-runs each call with its original arguments in the recorded order and
        reports per-call status. Use dry_run=true to inspect the plan first.
        Only records from the current server process are replayable; the JSONL
        file remains as durable evidence.
        """
        results = get_audit_log().replay(
            since_seq=since_seq, limit=max(1, min(limit, 200)), dry_run=dry_run
        )
        return json.dumps(
            {"replayed": len(results), "dry_run": dry_run, "results": results}, indent=2
        )
