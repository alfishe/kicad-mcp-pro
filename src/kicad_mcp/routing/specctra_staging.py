"""FastMCP-independent Specctra DSN/SES staging service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..errors import ManualStepRequiredError
from ..models.tool_result import ArtifactRef, StateDelta, ToolResult


class SpecctraRunner(Protocol):
    """Minimal FreeRouting runner surface needed by DSN/SES staging tools."""

    def export_dsn(self, pcb_path: Path, dsn_path: Path) -> Path: ...

    def stage_ses(self, ses_path: Path) -> Path: ...


RunnerFactory = Callable[[], SpecctraRunner]
PcbFileProvider = Callable[[], Path]
ProjectPathResolver = Callable[[str | Path], Path]
ProjectRootProvider = Callable[[], Path]


def relative_project_path(path: Path, project_root: Path) -> str:
    """Render a path relative to the project root when possible."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(project_root))
    except ValueError:
        return str(resolved)


@dataclass(frozen=True)
class RoutingSpecctraStagingService:
    """Stage Specctra DSN/SES artifacts without depending on FastMCP."""

    runner_factory: RunnerFactory
    get_pcb_file: PcbFileProvider
    resolve_within_project: ProjectPathResolver
    get_project_root: ProjectRootProvider

    def export_dsn(
        self,
        output_path: str = "output/routing/board.dsn",
    ) -> ToolResult:
        runner = self.runner_factory()
        pcb_file = self.get_pcb_file()
        try:
            dsn_path = runner.export_dsn(pcb_file, Path(output_path))
        except ManualStepRequiredError as exc:
            manual = ToolResult.failure("route_export_dsn", str(exc))
            manual.human_gate_required = True
            return manual
        except (RuntimeError, ValueError) as exc:
            return ToolResult.failure(
                "route_export_dsn",
                f"Specctra DSN export is unavailable: {exc}",
            )

        return ToolResult.success(
            "route_export_dsn",
            changed=True,
            artifacts=[ArtifactRef(path=str(dsn_path), kind="dsn")],
            state_delta=StateDelta(
                summary=(
                    "Specctra DSN ready at "
                    f"{relative_project_path(dsn_path, self.get_project_root())}. "
                    "You can route it with route_autoroute_freerouting()."
                ),
                changed_files=[str(dsn_path)],
            ),
        )

    def import_ses(
        self,
        ses_path: str = "output/routing/board.ses",
    ) -> ToolResult:
        runner = self.runner_factory()
        try:
            resolved_ses = self.resolve_within_project(Path(ses_path))
            staged = runner.stage_ses(resolved_ses)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return ToolResult.failure(
                "route_import_ses",
                f"Specctra SES staging failed: {exc}",
            )

        result = ToolResult.success(
            "route_import_ses",
            changed=False,
            artifacts=[ArtifactRef(path=str(staged), kind="ses")],
            state_delta=StateDelta(
                summary=(
                    "Specctra SES session staged at "
                    f"{relative_project_path(staged, self.get_project_root())}. "
                    "KiCad has no headless SES import: open the PCB Editor and run "
                    "File > Import > Specctra Session to apply the routing, then save."
                ),
                changed_files=[str(staged)],
            ),
        )
        result.human_gate_required = True
        return result
