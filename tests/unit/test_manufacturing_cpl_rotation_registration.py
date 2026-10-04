from __future__ import annotations

import importlib
import importlib.util
import inspect
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.manufacturing_cpl_rotation")
    assert spec is not None, "Manufacturing CPL rotation adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.manufacturing_cpl_rotation")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool, bool]] = []

    def correct(
        self,
        cpl_csv_path: str,
        *,
        output_path: str = "",
        dry_run: bool = True,
        confirm: bool = False,
    ) -> str:
        self.calls.append((cpl_csv_path, output_path, dry_run, confirm))
        return "corrected-cpl"


def test_registration_preserves_public_signature_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("manufacturing-cpl-rotation-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.ManufacturingCplRotationDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["mfg_correct_cpl_rotations"]
    tool = tools[0]
    assert (
        str(inspect.signature(tool.fn))
        == "(cpl_csv_path: 'str', output_path: 'str' = '', dry_run: 'bool' = True, "
        "confirm: 'bool' = False) -> 'str'"
    )
    assert "Apply JLCPCB CPL rotation corrections" in (tool.fn.__doc__ or "")

    metadata = get_tool_metadata("mfg_correct_cpl_rotations")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False

    result = tool.fn(
        "output/demo_cpl.csv",
        output_path="release/cpl.csv",
        dry_run=False,
        confirm=True,
    )
    assert result == "corrected-cpl"
    assert service.calls == [("output/demo_cpl.csv", "release/cpl.csv", False, True)]
