from __future__ import annotations

import importlib
import inspect

from mcp.server.mcpserver import MCPServer as FastMCP


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def analyze(
        self,
        length_mm: float,
        data_rate_gbps: float,
        z0_ohm: float = 50.0,
        eps_eff: float = 3.8,
        loss_tangent: float = 0.02,
        trace_width_mm: float = 0.2,
        amplitude_v: float = 1.0,
        max_insertion_loss_db: float = 10.0,
    ) -> str:
        self.calls.append(
            (
                length_mm,
                data_rate_gbps,
                z0_ohm,
                eps_eff,
                loss_tangent,
                trace_width_mm,
                amplitude_v,
                max_insertion_loss_db,
            )
        )
        return "channel-result"


def test_registration_preserves_signature_docstring_order_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_high_speed_channel")
    server = FastMCP("si-high-speed-channel-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.SignalIntegrityHighSpeedChannelDependencies(service=service),
    )

    tool_list = server._tool_manager.list_tools()
    assert [tool.name for tool in tool_list] == ["si_analyze_high_speed_channel"]

    tool = tool_list[0]
    assert str(inspect.signature(tool.fn)) == (
        "(length_mm: 'float', data_rate_gbps: 'float', z0_ohm: 'float' = 50.0, "
        "eps_eff: 'float' = 3.8, loss_tangent: 'float' = 0.02, "
        "trace_width_mm: 'float' = 0.2, amplitude_v: 'float' = 1.0, "
        "max_insertion_loss_db: 'float' = 10.0) -> 'str'"
    )
    assert tool.fn.__doc__ is not None
    assert tool.fn.__doc__.startswith(
        "Estimate high-speed channel insertion loss and eye opening for a lossy trace."
    )

    assert tool.fn(40.0, 5.0, 55.0, 3.6, 0.015, 0.18, 0.8, 9.0) == "channel-result"
    assert service.calls == [(40.0, 5.0, 55.0, 3.6, 0.015, 0.18, 0.8, 9.0)]
