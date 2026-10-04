"""Advanced routing helpers, rule orchestration, and FreeRouting integration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from kipy.board_types import Net, Track
from mcp.server.mcpserver import Context
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..connection import get_board
from ..errors import ManualStepRequiredError
from ..models.tool_result import ArtifactRef, StateDelta, ToolResult
from ..pcb.board_access import board_nets_filtered, board_tracks
from ..pcb.geometry import track_segment_length_mm
from ..routing.specctra_staging import relative_project_path
from ..utils.freerouting import FreeRoutingRunner
from ..utils.router_core import apply_ses_to_pcb
from .export_support import _get_pcb_file
from .metadata import headless_compatible, requires_dependency, requires_kicad_running
from .pcb import _current_stackup_specs, _impedance_context_for_layer, _transactional_board_write
from .project import load_design_intent as _load_design_intent
from .routing_rules import _load_rules_content, _mm, _rules_file_path, _upsert_rule, _write_rule

__all__ = [
    "_load_rules_content",
    "_mm",
    "_rules_file_path",
    "_upsert_rule",
    "_write_rule",
]


def _list_board_net_names() -> set[str]:
    return {
        str(net.name)
        for net in cast(list[Net], board_nets_filtered(get_board(), netclass_filter=None))
        if getattr(net, "name", "")
    }


def _current_track_length_mm(net_name: str) -> float:
    length = 0.0
    for track in cast(list[Track], board_tracks(get_board())):
        track_net = getattr(getattr(track, "net", None), "name", "")
        if track_net == net_name:
            length += track_segment_length_mm(track)
    return length


def _current_track_length_for_pattern_mm(net_pattern: str) -> float:
    if "*" not in net_pattern:
        return _current_track_length_mm(net_pattern)
    regex = re.compile("^" + re.escape(net_pattern).replace(r"\*", ".*") + "$")
    matching_names = [name for name in _list_board_net_names() if regex.fullmatch(name) is not None]
    return sum(_current_track_length_mm(name) for name in matching_names)


def _relative_project_path(path: Path) -> str:
    return relative_project_path(path, get_config().project_root)


async def _report_progress(
    ctx: Context[Any, Any] | None,
    progress: float,
    total: float,
    message: str,
) -> None:
    if ctx is None:
        return
    try:
        await ctx.report_progress(progress, total, message)
    except ValueError:
        return


def register(mcp: FastMCP) -> None:
    """Register routing tools."""

    from . import routing_manual_tracks

    routing_manual_tracks.register(mcp)

    from . import routing_specctra_staging

    routing_specctra_staging.register(mcp)

    @mcp.tool()
    @headless_compatible
    def route_apply_ses(ses_path: str = "output/routing/board.ses") -> ToolResult:
        """Apply a routed Specctra SES to the active board headlessly -- no GUI step.

        KiCad has no headless SES import, so this parses the routed session and writes its
        segments and vias directly into the .kicad_pcb via the round-trip-safe S-expression
        layer; the rest of the board file is untouched. Re-applying the same session is
        deterministic and idempotent (it replaces, not duplicates, the routing). This closes
        the manual File > Import > Specctra Session step. Run run_drc() afterwards to verify.
        """
        cfg = get_config()
        try:
            resolved_ses = cfg.resolve_within_project(Path(ses_path))
        except (ValueError, OSError) as exc:
            return ToolResult.failure("route_apply_ses", f"Invalid SES path: {exc}")
        if not resolved_ses.exists():
            return ToolResult.failure(
                "route_apply_ses", f"Routed SES not found: {_relative_project_path(resolved_ses)}"
            )
        try:
            ses_text = resolved_ses.read_text(encoding="utf-8", errors="ignore")
        except (ValueError, OSError) as exc:
            return ToolResult.failure("route_apply_ses", f"Could not read the SES: {exc}")

        class _NoRouteInSessionError(ValueError):
            pass

        class _RouteAlreadyAppliedError(ValueError):
            pass

        route = None

        def apply_routing(current: str) -> str:
            nonlocal route
            updated, route = apply_ses_to_pcb(current, ses_text)
            if not route.segments and not route.vias:
                raise _NoRouteInSessionError
            if updated == current:
                raise _RouteAlreadyAppliedError
            return updated

        try:
            pcb_file = Path(_transactional_board_write(apply_routing))
        except _NoRouteInSessionError:
            return ToolResult.failure(
                "route_apply_ses",
                f"The session at {_relative_project_path(resolved_ses)} contained no routed "
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

        if route is None:  # pragma: no cover - set by the mutator on every success path
            return ToolResult.failure("route_apply_ses", "Routing produced no result to apply.")
        return ToolResult.success(
            "route_apply_ses",
            changed=True,
            artifacts=[ArtifactRef(path=str(pcb_file), kind="pcb")],
            state_delta=StateDelta(
                summary=(
                    f"Applied {len(route.segments)} segment(s) and {len(route.vias)} via(s) "
                    f"across {len(route.net_names)} net(s) to "
                    f"{_relative_project_path(pcb_file)} headlessly. "
                    "Run run_drc() to verify the routed board is clean."
                ),
                changed_files=[str(pcb_file)],
            ),
        )

    @mcp.tool()
    @headless_compatible
    @requires_dependency("freerouting")
    async def route_autoroute_freerouting(
        dsn_path: str = "output/routing/board.dsn",
        ses_path: str = "output/routing/board.ses",
        net_classes_to_ignore: list[str] | None = None,
        exclude_nets: list[str] | None = None,
        max_passes: int = 100,
        thread_count: int = 4,
        use_docker: bool = True,
        freerouting_jar_path: str | None = None,
        drc_report_path: str = "output/routing/freerouting.drc.json",
        ctx: Context[Any, Any] | None = None,
    ) -> ToolResult:
        """Run FreeRouting after placement, then surface the KiCad import step.

        DSN export is attempted headlessly; FreeRouting runs via Docker or a local JAR.
        Applying the routed SES session back to the board has no headless path in KiCad,
        so this returns a human-gated result (``human_gate_required=True``) describing the
        File > Import > Specctra Session step — it does not claim the board is routed when
        the session has only been staged. If headless DSN export is unavailable, the
        manual export step is surfaced instead of failing opaquely.

        When the experimental MCP Tasks extension is enabled
        (``KICAD_MCP_ENABLE_TASKS=1``), the routing runs in the background and a
        task reference is returned immediately. The caller can poll ``tasks/get``
        for completion and ``tasks/cancel`` to abort routing.
        """

        async def _run() -> ToolResult:
            """Inner coroutine that does the actual work."""
            cfg = get_config()
            runner = FreeRoutingRunner()
            pcb_file = _get_pcb_file()
            dsn_target = cfg.resolve_within_project(Path(dsn_path))
            ses_target = cfg.resolve_within_project(Path(ses_path))
            drc_target = (
                cfg.resolve_within_project(Path(drc_report_path)) if drc_report_path else None
            )

            try:
                import anyio

                await _report_progress(ctx, 10, 100, "Exporting DSN for FreeRouting...")
                dsn_file = await anyio.to_thread.run_sync(
                    lambda: runner.export_dsn(pcb_file, dsn_target)
                )
                await _report_progress(ctx, 40, 100, "Running FreeRouting...")
                result = await anyio.to_thread.run_sync(
                    lambda: runner.run_freerouting(
                        dsn_file,
                        ses_target,
                        max_passes=max_passes,
                        thread_count=thread_count,
                        use_docker=use_docker,
                        freerouting_jar_path=Path(freerouting_jar_path).expanduser()
                        if freerouting_jar_path
                        else None,
                        net_classes_to_ignore=net_classes_to_ignore,
                        exclude_nets=exclude_nets,
                        drc_report_path=drc_target,
                    )
                )
            except ManualStepRequiredError as exc:
                manual = ToolResult.failure("route_autoroute_freerouting", str(exc))
                manual.human_gate_required = True
                return manual
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                return ToolResult.failure(
                    "route_autoroute_freerouting", f"FreeRouting autoroute failed: {exc}"
                )

            if result.returncode != 0:
                return ToolResult.failure(
                    "route_autoroute_freerouting",
                    (
                        "FreeRouting autoroute failed.\n"
                        f"Mode: {result.mode}\n"
                        f"Command: {' '.join(result.command)}\n"
                        f"stderr: {result.stderr or 'unknown error'}"
                    ),
                )

            ses_output = result.output_ses
            ses_path_obj = Path(ses_output) if ses_output else None
            if ses_path_obj is None:
                return ToolResult.failure(
                    "route_autoroute_freerouting",
                    "FreeRouting autoroute failed: no SES output path was reported.",
                )
            ses_ok = ses_path_obj.exists() and ses_path_obj.stat().st_size > 0
            if not ses_ok:
                return ToolResult.failure(
                    "route_autoroute_freerouting",
                    (
                        "FreeRouting ran but the SES session file is missing or empty — "
                        "this is a known KiCad 10 / Specctra round-trip failure.\n"
                        "Workaround: open the PCB in KiCad GUI and import the DSN manually "
                        f"via File > Import > Specctra Session "
                        f"({_relative_project_path(dsn_file)}).\n"
                        f"SES path checked: {ses_path_obj}"
                    ),
                )

            ignore_text = (
                ", ".join([*(net_classes_to_ignore or []), *(exclude_nets or [])]) or "none"
            )
            route_stats = result
            apply_error: str | None = None
            applied_route = None
            applied_pcb_file: Path | None = None

            # Attempt headless SES apply via the round-trip-safe S-expression layer.
            # This closes the FreeRouting loop without a GUI step on supported KiCad versions.
            await _report_progress(ctx, 85, 100, "Applying SES to board headlessly...")
            try:
                ses_text = ses_path_obj.read_text(encoding="utf-8", errors="ignore")

                class _NoRouteError(ValueError):
                    pass

                class _AlreadyAppliedError(ValueError):
                    pass

                def _apply_ses(current: str) -> str:
                    nonlocal applied_route
                    updated, applied_route = apply_ses_to_pcb(current, ses_text)
                    if not applied_route.segments and not applied_route.vias:
                        raise _NoRouteError
                    if updated == current:
                        raise _AlreadyAppliedError
                    return updated

                applied_pcb_file = Path(
                    await anyio.to_thread.run_sync(lambda: _transactional_board_write(_apply_ses))
                )
            except (_NoRouteError, _AlreadyAppliedError, ValueError, OSError) as exc:
                apply_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                apply_error = f"Unexpected error during headless SES apply: {exc}"

            await _report_progress(ctx, 100, 100, "FreeRouting routing complete.")

            if apply_error is None and applied_pcb_file is not None and applied_route is not None:
                seg_count = len(applied_route.segments)
                via_count = len(applied_route.vias)
                net_count = len(applied_route.net_names)
                return ToolResult.success(
                    "route_autoroute_freerouting",
                    changed=True,
                    artifacts=[
                        ArtifactRef(path=str(dsn_file), kind="dsn"),
                        ArtifactRef(path=str(ses_path_obj), kind="ses"),
                        ArtifactRef(path=str(applied_pcb_file), kind="pcb"),
                    ],
                    state_delta=StateDelta(
                        summary=(
                            f"FreeRouting routed and applied: {seg_count} segment(s), "
                            f"{via_count} via(s), {net_count} net(s).\n"
                            f"Mode: {route_stats.mode}\n"
                            f"DSN: {_relative_project_path(dsn_file)}\n"
                            f"SES: {_relative_project_path(ses_path_obj)}\n"
                            f"Routed: {route_stats.routed_pct:.2f}% ({route_stats.total_nets} "
                            f"net(s), {len(route_stats.unrouted_nets)} unrouted)\n"
                            f"Pass count: {route_stats.pass_count}\n"
                            f"Wall time: {route_stats.wall_seconds:.3f}s\n"
                            f"Ignored net classes: {ignore_text}\n"
                            f"Thread count: {thread_count}\n"
                            "Next step: run run_drc() to verify the routed board, "
                            "then pcb_fill_all_zones() to fill copper pours.\n"
                            f"stdout tail: {route_stats.stdout_tail or '(empty)'}"
                        ),
                        changed_files=[str(applied_pcb_file)],
                    ),
                )

            # Headless apply failed — fall back to staging for the GUI import step.
            try:
                staged = await anyio.to_thread.run_sync(lambda: runner.stage_ses(ses_path_obj))
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                return ToolResult.failure(
                    "route_autoroute_freerouting",
                    f"FreeRouting autoroute failed while staging the SES file: {exc}",
                )

            fallback = ToolResult.success(
                "route_autoroute_freerouting",
                changed=False,
                artifacts=[
                    ArtifactRef(path=str(dsn_file), kind="dsn"),
                    ArtifactRef(path=str(staged), kind="ses"),
                ],
                state_delta=StateDelta(
                    summary=(
                        "FreeRouting produced a routed session; headless apply failed, "
                        "use File > Import > Specctra Session in KiCad GUI to finish.\n"
                        f"Headless apply error: {apply_error or 'unknown'}\n"
                        f"Mode: {route_stats.mode}\n"
                        f"DSN: {_relative_project_path(dsn_file)}\n"
                        f"SES: {_relative_project_path(staged)}\n"
                        f"Routed: {route_stats.routed_pct:.2f}% ({route_stats.total_nets} "
                        f"net(s), {len(route_stats.unrouted_nets)} unrouted)\n"
                        f"Pass count: {route_stats.pass_count}\n"
                        f"Wall time: {route_stats.wall_seconds:.3f}s\n"
                        f"Ignored net classes: {ignore_text}\n"
                        f"Thread count: {thread_count}\n"
                        "Manual step: open the PCB in KiCad and run "
                        "File > Import > Specctra Session, then save the board.\n"
                        f"stdout tail: {route_stats.stdout_tail or '(empty)'}"
                    ),
                    changed_files=[str(dsn_file), str(staged)],
                ),
            )
            fallback.human_gate_required = True
            return fallback

        return await _run()

    from . import routing_net_class_rules

    routing_net_class_rules.register(
        mcp,
        routing_net_class_rules.dependencies(_write_rule),
    )

    from . import routing_differential_pair

    routing_differential_pair.register(
        mcp,
        routing_differential_pair.dependencies(
            list_board_net_names=lambda: _list_board_net_names(),
            write_rule=lambda name, body: _write_rule(name, body),
        ),
    )

    from . import routing_length_tuning

    routing_length_tuning.register(
        mcp,
        routing_length_tuning.dependencies(
            list_board_net_names=lambda: _list_board_net_names(),
            current_track_length_mm=lambda net_name: _current_track_length_mm(net_name),
            write_rule=lambda name, body: _write_rule(name, body),
        ),
    )

    from . import routing_tuning_profiles

    routing_tuning_profiles.register(mcp)

    from . import routing_time_domain_tuning

    routing_time_domain_tuning.register(
        mcp,
        routing_time_domain_tuning.dependencies(
            current_track_length_for_pattern_mm=lambda net_pattern: (
                _current_track_length_for_pattern_mm(net_pattern)
            ),
            stackup_context_for_layer=lambda layer: _impedance_context_for_layer(
                _current_stackup_specs(),
                layer,
            ),
            write_rule=lambda name, body: _write_rule(name, body),
        ),
    )

    from . import routing_diff_pair_length

    routing_diff_pair_length.register(
        mcp,
        routing_diff_pair_length.dependencies(
            list_board_net_names=lambda: _list_board_net_names(),
            current_track_length_mm=lambda net_name: _current_track_length_mm(net_name),
            write_rule=lambda name, body: _write_rule(name, body),
        ),
    )

    from . import routing_board_constraints

    routing_board_constraints.register(
        mcp,
        routing_board_constraints.dependencies(
            load_design_intent=lambda: _load_design_intent(),
            write_rule=lambda name, body: _write_rule(name, body),
        ),
    )
