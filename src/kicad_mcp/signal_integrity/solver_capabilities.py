"""FastMCP-independent signal-integrity solver capability service."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..utils.field_solver import impedance_method
from ..utils.solver_seams import (
    channel_method,
    emc_method,
    ir_drop_method,
    pdn_mesh_method,
    thermal_fd_method,
    thermal_method,
)

MethodProvider = Callable[[], dict[str, Any]]
ChannelMethodProvider = Callable[[bool], dict[str, Any]]


@dataclass(frozen=True)
class SignalIntegritySolverCapabilitiesService:
    """Render solver capability seams and release-signoff policy."""

    impedance_provider: MethodProvider = impedance_method
    ir_drop_provider: MethodProvider = ir_drop_method
    pdn_mesh_provider: MethodProvider = pdn_mesh_method
    thermal_provider: MethodProvider = thermal_method
    thermal_fd_provider: MethodProvider = thermal_fd_method
    emc_provider: MethodProvider = emc_method
    channel_provider: ChannelMethodProvider = channel_method

    def report(self) -> str:
        capabilities = {
            "trace_impedance_field_solver": self.impedance_provider(),
            "dc_ir_drop_field_solver": self.ir_drop_provider(),
            "pdn_mesh_solver": self.pdn_mesh_provider(),
            "thermal_closed_form": self.thermal_provider(),
            "thermal_plane_fd_solver": self.thermal_fd_provider(),
            "emc_full_wave_solver": self.emc_provider(),
            "high_speed_channel_closed_form": self.channel_provider(False),
        }
        return json.dumps(
            {
                "solver_capabilities": capabilities,
                "policy": {
                    "solver_unavailable_mode": True,
                    "release_signoff_requires_solver_grade": True,
                    "closed_form_results_are_critic_only": True,
                },
            },
            indent=2,
            sort_keys=True,
        )
