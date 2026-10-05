from __future__ import annotations

import json

from kicad_mcp.signal_integrity.solver_capabilities import (
    SignalIntegritySolverCapabilitiesService,
)


def test_report_preserves_capability_mapping_policy_and_json_format() -> None:
    calls: list[str] = []

    def provider(name: str):
        def inner() -> dict[str, object]:
            calls.append(name)
            return {"method": name, "solver_grade": False}

        return inner

    def channel_provider(measured: bool) -> dict[str, object]:
        calls.append(f"channel:{measured}")
        return {"method": "channel", "solver_grade": measured}

    service = SignalIntegritySolverCapabilitiesService(
        impedance_provider=provider("impedance"),
        ir_drop_provider=provider("ir-drop"),
        pdn_mesh_provider=provider("pdn-mesh"),
        thermal_provider=provider("thermal"),
        thermal_fd_provider=provider("thermal-fd"),
        emc_provider=provider("emc"),
        channel_provider=channel_provider,
    )

    result = service.report()

    expected = {
        "solver_capabilities": {
            "trace_impedance_field_solver": {
                "method": "impedance",
                "solver_grade": False,
            },
            "dc_ir_drop_field_solver": {
                "method": "ir-drop",
                "solver_grade": False,
            },
            "pdn_mesh_solver": {
                "method": "pdn-mesh",
                "solver_grade": False,
            },
            "thermal_closed_form": {
                "method": "thermal",
                "solver_grade": False,
            },
            "thermal_plane_fd_solver": {
                "method": "thermal-fd",
                "solver_grade": False,
            },
            "emc_full_wave_solver": {
                "method": "emc",
                "solver_grade": False,
            },
            "high_speed_channel_closed_form": {
                "method": "channel",
                "solver_grade": False,
            },
        },
        "policy": {
            "solver_unavailable_mode": True,
            "release_signoff_requires_solver_grade": True,
            "closed_form_results_are_critic_only": True,
        },
    }
    assert result == json.dumps(expected, indent=2, sort_keys=True)
    assert calls == [
        "impedance",
        "ir-drop",
        "pdn-mesh",
        "thermal",
        "thermal-fd",
        "emc",
        "channel:False",
    ]
