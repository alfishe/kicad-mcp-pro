from __future__ import annotations

import importlib
import inspect

from mcp.server.mcpserver import MCPServer as FastMCP


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def calculate_trace_impedance(
        self,
        width_mm: float,
        height_mm: float,
        er: float,
        trace_type: str,
        copper_oz: float,
        spacing_mm: float,
    ) -> str:
        self.calls.append(("impedance", width_mm, height_mm, er, trace_type, copper_oz, spacing_mm))
        return "impedance-result"

    def calculate_trace_width_for_impedance(
        self,
        target_ohm: float,
        height_mm: float,
        er: float,
        trace_type: str,
        copper_oz: float,
        spacing_mm: float,
    ) -> str:
        self.calls.append(("width", target_ohm, height_mm, er, trace_type, copper_oz, spacing_mm))
        return "width-result"


def test_registration_preserves_order_signatures_docstrings_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_impedance")
    server = FastMCP("si-impedance-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.SignalIntegrityImpedanceDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == [
        "si_calculate_trace_impedance",
        "si_calculate_trace_width_for_impedance",
    ]

    impedance, width = tools
    assert str(inspect.signature(impedance.fn)) == (
        "(width_mm: 'float', height_mm: 'float', er: 'float' = 4.2, "
        "trace_type: 'str' = 'microstrip', copper_oz: 'float' = 1.0, "
        "spacing_mm: 'float' = 0.2) -> 'str'"
    )
    assert str(inspect.signature(width.fn)) == (
        "(target_ohm: 'float', height_mm: 'float', er: 'float' = 4.2, "
        "trace_type: 'str' = 'microstrip', copper_oz: 'float' = 1.0, "
        "spacing_mm: 'float' = 0.2) -> 'str'"
    )
    assert "Estimate PCB trace impedance" in (impedance.fn.__doc__ or "")
    assert "Solve for a trace width" in (width.fn.__doc__ or "")

    assert impedance.fn(0.34, 0.18) == "impedance-result"
    assert width.fn(50.0, 0.18) == "width-result"
    assert service.calls == [
        ("impedance", 0.34, 0.18, 4.2, "microstrip", 1.0, 0.2),
        ("width", 50.0, 0.18, 4.2, "microstrip", 1.0, 0.2),
    ]
