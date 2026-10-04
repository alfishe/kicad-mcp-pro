"""FastMCP-independent routing tuning-profile state service."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

ProjectDirProvider = Callable[[], Path | None]
LayerResolver = Callable[[str], Any]

_STATE_DIRNAME = ".kicad-mcp"
_TUNING_PROFILES_FILENAME = "tuning_profiles.json"
_TUNING_ASSIGNMENTS_FILENAME = "tuning_profile_assignments.json"


def routing_state_dir(project_dir: Path | None) -> Path:
    """Return the project-local routing state directory, creating it when needed."""
    if project_dir is None:
        raise ValueError(
            "No active project directory is configured. Call kicad_set_project() first."
        )
    target = project_dir / _STATE_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def load_state_file(
    project_dir: Path | None,
    filename: str,
    default: dict[str, object],
) -> dict[str, object]:
    """Load a project-local routing JSON state file, creating its default when absent."""
    path = routing_state_dir(project_dir) / filename
    if not path.exists():
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return dict(default)
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def save_state_file(
    project_dir: Path | None,
    filename: str,
    payload: dict[str, object],
) -> Path:
    """Persist a project-local routing JSON state file."""
    path = routing_state_dir(project_dir) / filename
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_tuning_profiles(project_dir: Path | None) -> dict[str, dict[str, object]]:
    """Load configured tuning profiles for time-domain routing consumers."""
    state = load_state_file(project_dir, _TUNING_PROFILES_FILENAME, {"profiles": {}})
    return cast(dict[str, dict[str, object]], state.get("profiles", {}))


@dataclass(frozen=True)
class RoutingTuningProfileService:
    """Manage time-domain tuning profiles without depending on MCP transport types."""

    get_project_dir: ProjectDirProvider
    resolve_layer: LayerResolver

    def create(
        self,
        name: str,
        layer: str,
        trace_impedance_ohm: float,
        propagation_speed_factor: float,
    ) -> str:
        if not 0.05 <= propagation_speed_factor <= 1.0:
            raise ValueError("propagation_speed_factor must be between 0.05 and 1.0.")
        resolved_layer = self.resolve_layer(layer)
        _ = resolved_layer

        project_dir = self.get_project_dir()
        state = load_state_file(project_dir, _TUNING_PROFILES_FILENAME, {"profiles": {}})
        profiles = cast(dict[str, object], state.setdefault("profiles", {}))
        profiles[name] = {
            "layer": layer,
            "trace_impedance_ohm": trace_impedance_ohm,
            "propagation_speed_factor": propagation_speed_factor,
        }
        path = save_state_file(project_dir, _TUNING_PROFILES_FILENAME, state)
        return f"Tuning profile '{name}' saved to {path}."

    def list_profiles(self) -> str:
        project_dir = self.get_project_dir()
        state = load_state_file(project_dir, _TUNING_PROFILES_FILENAME, {"profiles": {}})
        return json.dumps(state.get("profiles", {}), indent=2)

    def apply(self, net_pattern: str, profile_name: str) -> str:
        project_dir = self.get_project_dir()
        profiles = load_tuning_profiles(project_dir)
        profile = profiles.get(profile_name)
        if profile is None:
            return f"Tuning profile '{profile_name}' was not found."

        assignments_state = load_state_file(
            project_dir,
            _TUNING_ASSIGNMENTS_FILENAME,
            {"assignments": {}},
        )
        assignments = cast(
            dict[str, object],
            assignments_state.setdefault("assignments", {}),
        )
        assignments[net_pattern] = {
            "profile_name": profile_name,
            "layer": profile.get("layer", ""),
        }
        path = save_state_file(
            project_dir,
            _TUNING_ASSIGNMENTS_FILENAME,
            assignments_state,
        )
        return (
            f"Tuning profile '{profile_name}' assigned to '{net_pattern}'.\n"
            f"Assignments file: {path}"
        )
