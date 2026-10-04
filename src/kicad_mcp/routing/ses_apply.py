"""FastMCP-independent headless Specctra SES apply service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..models.tool_result import ArtifactRef, StateDelta, ToolResult
from ..utils.router_core import SesRoute, apply_ses_to_pcb

ProjectPathResolver = Callable[[str | Path], Path]
RelativePathFormatter = Callable[[Path], str]
BoardMutator = Callable[[str], str]
TransactionalBoardWriter = Callable[[BoardMutator], str]


class _NoRouteInSessionError(ValueError):
    pass


class _RouteAlreadyAppliedError(ValueError):
    pass


@dataclass(frozen=True)
class RoutingSesApplyService:
    """Apply routed SES content through an injected transactional board writer."""

    resolve_within_project: ProjectPathResolver
    relative_project_path: RelativePathFormatter
    transactional_board_write: TransactionalBoardWriter

    def apply(self, ses_path: str = "output/routing/board.ses") -> ToolResult:
        try:
            resolved_ses = self.resolve_within_project(Path(ses_path))
        except (ValueError, OSError) as exc:
            return ToolResult.failure("route_apply_ses", f"Invalid SES path: {exc}")

        if not resolved_ses.exists():
            return ToolResult.failure(
                "route_apply_ses",
                f"Routed SES not found: {self.relative_project_path(resolved_ses)}",
            )

        try:
            ses_text = resolved_ses.read_text(encoding="utf-8", errors="ignore")
        except (ValueError, OSError) as exc:
            return ToolResult.failure("route_apply_ses", f"Could not read the SES: {exc}")

        route: SesRoute | None = None

        def apply_routing(current: str) -> str:
            nonlocal route
            updated, route = apply_ses_to_pcb(current, ses_text)
            if not route.segments and not route.vias:
                raise _NoRouteInSessionError
            if updated == current:
                raise _RouteAlreadyAppliedError
            return updated

        try:
            pcb_file = Path(self.transactional_board_write(apply_routing))
        except _NoRouteInSessionError:
            return ToolResult.failure(
                "route_apply_ses",
                f"The session at {self.relative_project_path(resolved_ses)} contained no routed "
                "segments or vias.",
            )
        except _RouteAlreadyAppliedError:
            return ToolResult.success(
                "route_apply_ses",
                changed=False,
                state_delta=StateDelta(
                    summary="Routing already applied; the board is unchanged (idempotent)."
                ),
            )
        except (ValueError, OSError) as exc:
            return ToolResult.failure("route_apply_ses", f"Could not apply the SES: {exc}")

        if route is None:
            return ToolResult.failure("route_apply_ses", "Routing produced no result to apply.")

        return ToolResult.success(
            "route_apply_ses",
            changed=True,
            artifacts=[ArtifactRef(path=str(pcb_file), kind="pcb")],
            state_delta=StateDelta(
                summary=(
                    f"Applied {len(route.segments)} segment(s) and {len(route.vias)} via(s) "
                    f"across {len(route.net_names)} net(s) to "
                    f"{self.relative_project_path(pcb_file)} headlessly. "
                    "Run run_drc() to verify the routed board is clean."
                ),
                changed_files=[str(pcb_file)],
            ),
        )
