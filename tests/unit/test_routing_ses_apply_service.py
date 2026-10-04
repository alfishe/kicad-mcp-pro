from __future__ import annotations

from pathlib import Path

from kicad_mcp.routing.ses_apply import RoutingSesApplyService

PCB = '(kicad_pcb\n\t(version 20250216)\n\t(net 0 "")\n\t(net 1 "GND")\n)\n'

SES = (
    "(session t.dsn (routes (resolution um 10) (network_out "
    '(net "GND" (wire (path F.Cu 250 2500 -5000 11000 -5000)) '
    '(via "Via[0-1]_600:300_um" 11000 -5000)))))'
)


def _service(tmp_path: Path, current: str = PCB) -> tuple[RoutingSesApplyService, list[str]]:
    writes: list[str] = []

    def transaction(mutator):
        updated = mutator(current)
        writes.append(updated)
        return str(tmp_path / "demo.kicad_pcb")

    return (
        RoutingSesApplyService(
            resolve_within_project=lambda path: tmp_path / Path(path),
            relative_project_path=lambda path: str(path.relative_to(tmp_path)),
            transactional_board_write=transaction,
        ),
        writes,
    )


def test_apply_preserves_success_contract(tmp_path: Path) -> None:
    ses = tmp_path / "output" / "routing" / "board.ses"
    ses.parent.mkdir(parents=True)
    ses.write_text(SES, encoding="utf-8")
    service, writes = _service(tmp_path)

    result = service.apply()

    assert result.ok is True
    assert result.changed is True
    assert result.tool_name == "route_apply_ses"
    assert writes
    assert result.artifacts[0].kind == "pcb"
    assert "Applied 1 segment(s)" in result.state_delta.summary
    assert result.state_delta.changed_files == [str(tmp_path / "demo.kicad_pcb")]


def test_apply_preserves_missing_file_message(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    result = service.apply()

    assert result.ok is False
    assert result.errors == ["Routed SES not found: output/routing/board.ses"]


def test_apply_preserves_invalid_path_message(tmp_path: Path) -> None:
    def invalid(_path):
        raise ValueError("outside project")

    service = RoutingSesApplyService(
        resolve_within_project=invalid,
        relative_project_path=str,
        transactional_board_write=lambda mutator: str(tmp_path / "demo.kicad_pcb"),
    )

    result = service.apply()

    assert result.errors == ["Invalid SES path: outside project"]
