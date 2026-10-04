from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.routing.tuning_profiles import (
    RoutingTuningProfileService,
    load_tuning_profiles,
)


def _service(
    project_dir: Path | None,
    resolved_layers: list[str] | None = None,
) -> RoutingTuningProfileService:
    calls = resolved_layers if resolved_layers is not None else []
    return RoutingTuningProfileService(
        get_project_dir=lambda: project_dir,
        resolve_layer=lambda layer: calls.append(layer) or layer,
    )


def test_create_list_and_apply_preserve_state_file_contract(tmp_path: Path) -> None:
    resolved_layers: list[str] = []
    service = _service(tmp_path, resolved_layers)

    created = service.create("fast", "F.Cu", 90.0, 0.6)
    listed = service.list_profiles()
    applied = service.apply("DATA*", "fast")

    state_dir = tmp_path / ".kicad-mcp"
    profiles_path = state_dir / "tuning_profiles.json"
    assignments_path = state_dir / "tuning_profile_assignments.json"

    assert resolved_layers == ["F.Cu"]
    assert created == f"Tuning profile 'fast' saved to {profiles_path}."
    assert json.loads(listed) == {
        "fast": {
            "layer": "F.Cu",
            "trace_impedance_ohm": 90.0,
            "propagation_speed_factor": 0.6,
        }
    }
    assert applied == (
        f"Tuning profile 'fast' assigned to 'DATA*'.\nAssignments file: {assignments_path}"
    )
    profiles_payload = json.loads(profiles_path.read_text(encoding="utf-8"))
    assert profiles_payload["profiles"]["fast"]["layer"] == "F.Cu"
    assert json.loads(assignments_path.read_text(encoding="utf-8")) == {
        "assignments": {
            "DATA*": {
                "profile_name": "fast",
                "layer": "F.Cu",
            }
        }
    }


def test_missing_profile_preserves_message_and_does_not_create_assignments(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    result = service.apply("DATA*", "slow")

    assert result == "Tuning profile 'slow' was not found."
    assert (tmp_path / ".kicad-mcp" / "tuning_profiles.json").exists()
    assert not (tmp_path / ".kicad-mcp" / "tuning_profile_assignments.json").exists()


def test_create_preserves_speed_factor_validation(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(
        ValueError,
        match="propagation_speed_factor must be between 0.05 and 1.0",
    ):
        service.create("bad", "F.Cu", 50.0, 0.01)


def test_state_access_preserves_missing_project_error() -> None:
    service = _service(None)

    with pytest.raises(
        ValueError,
        match=r"No active project directory is configured\. Call kicad_set_project\(\) first\.",
    ):
        service.list_profiles()


def test_load_tuning_profiles_is_canonical_reader_for_time_domain(tmp_path: Path) -> None:
    state_dir = tmp_path / ".kicad-mcp"
    state_dir.mkdir(parents=True)
    (state_dir / "tuning_profiles.json").write_text(
        json.dumps(
            {
                "profiles": {
                    "usb": {
                        "layer": "F.Cu",
                        "trace_impedance_ohm": 90.0,
                        "propagation_speed_factor": 0.6,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    profiles = load_tuning_profiles(tmp_path)

    assert profiles["usb"]["propagation_speed_factor"] == 0.6


def test_malformed_state_preserves_json_decode_error(tmp_path: Path) -> None:
    state_dir = tmp_path / ".kicad-mcp"
    state_dir.mkdir(parents=True)
    (state_dir / "tuning_profiles.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_tuning_profiles(tmp_path)
