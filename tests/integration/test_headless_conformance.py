"""Conformance of this fork against a headless KiCad 11-dev (10.99) build.

Covers the P0 conformance item (ROADMAP M0, work item 3): session spawn +
health against the real ``kicad-cli api-server``, project preloading, open
document enumeration, and DRC/ERC JSON report compatibility of the installed
CLI with the composition layer.

Runs only when a real kicad-cli binary is available — set
``KICAD_CONFORMANCE_CLI`` or have a usable binary on the config discovery
path. Skipped otherwise, so fast CI loops without KiCad stay green.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from kicad_mcp.config import get_config
from kicad_mcp.discovery import discover_kicad_cli
from kicad_mcp.ipc import SessionConfig, get_session_manager
from kicad_mcp.validation.verify_board import compose_board_verdict, summarize_check

pytestmark = [pytest.mark.slow]

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "kicad-fixtures"
    / "fixtures"
    / "multi-sheet-schematic"
)


def _real_cli() -> Path:
    candidates = [
        os.environ.get("KICAD_CONFORMANCE_CLI"),
        str(discover_kicad_cli()),
        str(get_config().kicad_cli),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    pytest.skip("no real kicad-cli binary available for conformance run")


@pytest.fixture()
def headless_session() -> Iterator[object]:
    cli = _real_cli()
    manager = get_session_manager()
    session = manager.start(
        "conformance",
        config=SessionConfig(
            kicad_cli=cli,
            socket_path=Path("/tmp/kicad/api-conformance.sock"),  # noqa: S108 - session-scoped
            preload=FIXTURE_DIR / "multi-sheet-schematic.kicad_pcb",
        ),
    )
    yield session
    manager.stop("conformance")


def test_headless_session_health_reports_11_dev(headless_session) -> None:
    from kipy import KiCad

    assert headless_session.running
    assert headless_session.health()["connected"] is True

    client = KiCad(socket_path=f"ipc://{headless_session.socket_path}")
    version = str(client.get_version())
    assert "10.99" in version, f"expected the 11-dev tree, got {version}"

    from kipy.proto.common import types as common_types

    open_pcbs = client.get_open_documents(common_types.DOCTYPE_PCB)
    assert len(list(open_pcbs)) == 1, "preloaded project board must be open"


def test_cli_drc_erc_reports_compose_on_installed_cli(tmp_path: Path) -> None:
    cli = _real_cli()
    board = FIXTURE_DIR / "multi-sheet-schematic.kicad_pcb"
    schematic = FIXTURE_DIR / "multi-sheet-schematic.kicad_sch"

    def run_report(args: list[str], out: Path) -> dict[str, object]:
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(cli), *args, "--output", str(out), "--format", "json", "--severity-all"],
            capture_output=True,
            text=True,
            check=False,
        )
        return json.loads(out.read_text(encoding="utf-8"))

    drc_report = run_report(
        ["pcb", "drc", "--exit-code-violations", str(board)], tmp_path / "drc.json"
    )
    erc_report = run_report(
        ["sch", "erc", "--exit-code-violations", str(schematic)], tmp_path / "erc.json"
    )

    checks = [
        summarize_check(
            "pcb_drc",
            status="clean",
            report=drc_report,
            unconnected_key="unconnected_items",
        ),
        summarize_check("sch_erc", status="clean", report=erc_report),
    ]
    verdict = compose_board_verdict(checks)

    assert verdict["overall"] in {"PASS", "WARN", "FAIL"}
    assert {check["check"] for check in verdict["checks"]} == {"pcb_drc", "sch_erc"}
    # The fixture intentionally contains shorts: the verdict must be able to fail.
    assert verdict["overall"] == "FAIL", json.dumps(verdict["summary"])
