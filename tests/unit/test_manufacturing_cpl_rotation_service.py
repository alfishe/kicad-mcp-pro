from __future__ import annotations

import csv
import importlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from kicad_mcp.manufacturing.cpl_rotation import ManufacturingCplRotationService


def _service_module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.manufacturing.cpl_rotation")
    assert spec is not None, "Manufacturing CPL rotation service module must be extracted"
    return importlib.import_module("kicad_mcp.manufacturing.cpl_rotation")


@pytest.fixture
def service(tmp_path: Path) -> ManufacturingCplRotationService:
    module = _service_module()
    table_path = tmp_path / "rotations.json"
    table_path.write_text(
        json.dumps(
            {
                "entries": [
                    {"pattern": "SOT-23", "offset_deg": 180},
                    {"pattern": "SOT-23-3", "offset_deg": 90},
                ]
            }
        ),
        encoding="utf-8",
    )
    return module.ManufacturingCplRotationService(
        resolve_path=lambda path: (tmp_path / path).resolve(),
        rotation_table_path=table_path,
    )


def _write_cpl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Ref,Val,Package,PosX,PosY,Rot,Side\nD1,LED,SOT-23-3,1,2,90,F\nR1,10k,R_0805,3,4,0,F\n",
        encoding="utf-8",
    )


def test_dry_run_preserves_preview_and_most_specific_rotation_match(
    service: ManufacturingCplRotationService,
    tmp_path: Path,
) -> None:
    cpl = tmp_path / "output" / "demo_cpl.csv"
    _write_cpl(cpl)

    result = service.correct("output/demo_cpl.csv")

    assert result.startswith("Dry run: 1 component(s) would be corrected.\n")
    assert f"Output would be: {tmp_path / 'output' / 'demo_cpl_jlcpcb_corrected.csv'}" in result
    assert "D1 | SOT-23-3 | 90.00° | +90° | 180.00°" in result
    assert "R1" not in result


def test_write_confirmation_and_overwrite_policy_are_preserved(
    service: ManufacturingCplRotationService,
    tmp_path: Path,
) -> None:
    cpl = tmp_path / "output" / "demo_cpl.csv"
    _write_cpl(cpl)

    refused = service.correct("output/demo_cpl.csv", dry_run=False)
    out_path = tmp_path / "output" / "demo_cpl_jlcpcb_corrected.csv"
    assert refused == (
        "CPL rotation correction writes a new CSV and requires explicit confirmation.\n"
        f"- Intended output: {out_path}\n"
        "Rerun with dry_run=false and confirm=true."
    )

    written = service.correct("output/demo_cpl.csv", dry_run=False, confirm=True)
    assert written.startswith("CPL rotation corrections applied: 1 component(s) corrected.\n")
    assert out_path.exists()

    with out_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["Rot"] == "180.00"
    assert rows[1]["Rot"] == "0"

    overwrite = service.correct("output/demo_cpl.csv", dry_run=False, confirm=True)
    assert overwrite == (
        "Refusing to overwrite an existing corrected CPL CSV.\n"
        f"- Existing file: {out_path}\n"
        "Choose a different output_path."
    )


def test_custom_output_and_validation_errors_are_preserved(
    service: ManufacturingCplRotationService,
    tmp_path: Path,
) -> None:
    missing = service.correct("output/missing.csv")
    assert missing == f"CPL file not found: {(tmp_path / 'output' / 'missing.csv').resolve()}"

    cpl = tmp_path / "output" / "bad.csv"
    cpl.parent.mkdir(parents=True, exist_ok=True)
    cpl.write_text("Ref,Package\nD1,SOT-23-3\n", encoding="utf-8")
    bad = service.correct("output/bad.csv")
    assert "Rotation column ('Rot') not found in CSV." in bad

    good = tmp_path / "output" / "demo_cpl.csv"
    _write_cpl(good)
    custom = service.correct(
        "output/demo_cpl.csv",
        output_path="release/cpl.csv",
        dry_run=True,
    )
    assert f"Output would be: {(tmp_path / 'release' / 'cpl.csv').resolve()}" in custom


def test_rotation_table_failures_and_non_numeric_rotation_are_preserved(
    service: ManufacturingCplRotationService,
    tmp_path: Path,
) -> None:
    module = _service_module()

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert module.load_rotation_table(malformed) == []

    non_list = tmp_path / "non-list.json"
    non_list.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    assert module.load_rotation_table(non_list) == []

    cpl = tmp_path / "output" / "invalid-rotation.csv"
    cpl.parent.mkdir(parents=True, exist_ok=True)
    cpl.write_text("Ref,Package,Rot\nD1,SOT-23-3,not-a-number\n", encoding="utf-8")
    assert (\n        service.correct("output/invalid-rotation.csv")\n        == "No rotation corrections needed for any component."\n    )
