from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from kicad_mcp.routing.board_constraints import (
    RoutingBoardConstraintsService,
    ipc_trace_width_mm,
)


def _intent(*, power_rails: list[object] | None = None, interfaces: list[object] | None = None):
    return SimpleNamespace(
        power_rails=[] if power_rails is None else power_rails,
        interfaces=[] if interfaces is None else interfaces,
    )


def test_ipc_trace_width_preserves_legacy_floor_and_formula() -> None:
    assert ipc_trace_width_mm(0.0) == 0.127
    assert ipc_trace_width_mm(-1.0) == 0.127
    assert ipc_trace_width_mm(0.5) > 0.127


def test_generate_preserves_power_and_interface_rule_contract(tmp_path: Path) -> None:
    writes: list[tuple[str, str]] = []
    rules_path = tmp_path / "demo.kicad_dru"
    intent = _intent(
        power_rails=[
            SimpleNamespace(name="+3V3", voltage_v=3.3, current_max_a=0.5),
            SimpleNamespace(name="+120V", voltage_v=120.0, current_max_a=1.0),
        ],
        interfaces=[
            SimpleNamespace(
                kind="usb2",
                net_prefix="USB_",
                differential=True,
                impedance_target_ohm=90.0,
                diff_skew_max_ps=5.0,
                length_target_mm=None,
                length_match_tolerance_mm=0.0,
            ),
            SimpleNamespace(
                kind="memory",
                net_prefix="DDR_",
                differential=False,
                impedance_target_ohm=None,
                diff_skew_max_ps=None,
                length_target_mm=45.0,
                length_match_tolerance_mm=0.5,
            ),
        ],
    )
    service = RoutingBoardConstraintsService(
        load_design_intent=lambda: intent,
        write_rule=lambda name, body: writes.append((name, body)) or rules_path,
    )

    result = service.generate()

    assert result.ok is True
    assert result.changed is True
    assert result.tool_name == "generate_board_constraints"
    assert [name for name, _ in writes] == [
        "pwr_3V3",
        "pwr_120V",
        "dp_USB",
        "len_DDR",
    ]
    by_name = dict(writes)
    assert '(condition "A.NetClass == \\"3V3\\"")' in by_name["pwr_3V3"]
    assert "(constraint clearance (min 0.6000mm))" in by_name["pwr_120V"]
    assert "(constraint diff_pair_gap (opt 0.1200mm))" in by_name["dp_USB"]
    assert "(constraint length (min 44.5000mm) (max 45.5000mm))" in by_name["len_DDR"]
    assert [(artifact.path, artifact.kind) for artifact in result.artifacts] == [
        (str(rules_path), "dru")
    ]
    assert result.state_delta.changed_files == [str(rules_path)]
    summary = result.state_delta.summary
    assert "Rail '+3V3':" in summary
    assert "HV note: 120.0V rail" in summary
    assert "Interface 'usb2' (USB_): diff-pair" in summary
    assert "Interface 'memory' (DDR_): length 45.0000mm ±0.5000mm" in summary


def test_generate_preserves_empty_intent_failure() -> None:
    service = RoutingBoardConstraintsService(
        load_design_intent=lambda: _intent(),
        write_rule=lambda _name, _body: Path("unused.kicad_dru"),
    )

    result = service.generate()

    assert result.ok is False
    assert result.changed is False
    assert result.errors == [
        "No power_rails or interfaces found in the design intent. "
        "Call import_design_spec() first to load your design requirements."
    ]


def test_generate_preserves_conflict_only_success_semantics() -> None:
    intent = _intent(power_rails=[SimpleNamespace(name="+5V", voltage_v=5.0, current_max_a=1.0)])

    def fail(_name: str, _body: str) -> Path:
        raise ValueError("write failed")

    service = RoutingBoardConstraintsService(
        load_design_intent=lambda: intent,
        write_rule=fail,
    )

    result = service.generate()

    assert result.ok is True
    assert result.changed is True
    assert result.artifacts == []
    assert result.state_delta.changed_files == []
    assert "Conflicts/errors (review manually):" in result.state_delta.summary
    assert "Rail '+5V': write failed" in result.state_delta.summary
