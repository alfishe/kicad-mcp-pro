"""Tests for the combined verify_board composition layer."""

from __future__ import annotations

from kicad_mcp.validation.verify_board import (
    VerifyCheck,
    compose_board_verdict,
    summarize_check,
)


def _report(*severities: str) -> dict[str, object]:
    return {
        "violations": [
            {"severity": severity, "type": f"violation_{i}", "description": f"d{i}"}
            for i, severity in enumerate(severities)
        ]
    }


def test_clean_report_is_pass() -> None:
    check = summarize_check(
        "pcb_drc", status="clean", report=_report(), unconnected_key="unconnected_items"
    )

    assert check.verdict() == "PASS"
    assert check.errors == 0
    assert check.warnings == 0
    assert check.unconnected == 0


def test_findings_count_errors_and_warnings() -> None:
    report = dict(_report("error", "warning", "warning", "error"))
    report["unconnected_items"] = [{"a": 1}, {"a": 2}]

    check = summarize_check(
        "pcb_drc", status="clean", report=report, unconnected_key="unconnected_items"
    )

    assert check.status == "findings"
    assert check.errors == 2
    assert check.warnings == 2
    assert check.unconnected == 2
    assert check.verdict() == "FAIL"


def test_warnings_only_is_warn() -> None:
    check = summarize_check("pcb_drc", status="clean", report=_report("warning"))

    assert check.verdict() == "WARN"


def test_top_violations_are_capped() -> None:
    severities = tuple(["error"] * 12)
    check = summarize_check("pcb_drc", status="clean", report=_report(*severities))

    assert len(check.top_violations) == 5
    assert check.errors == 12


def test_unavailable_check_is_fail_with_detail() -> None:
    check = summarize_check("pcb_drc", status="unavailable", report=None, error="no board")

    assert check.verdict() == "FAIL"
    assert check.detail == "no board"
    assert compose_board_verdict([check])["overall"] == "FAIL"


def test_malformed_status_maps_to_fail() -> None:
    check = summarize_check("sch_erc", status="malformed", report=None, error="bad schema")

    assert check.verdict() == "FAIL"


def test_compose_overall_pass() -> None:
    checks = [
        VerifyCheck(name="pcb_drc", status="clean"),
        VerifyCheck(name="sch_erc", status="clean"),
    ]
    verdict = compose_board_verdict(checks)

    assert verdict["overall"] == "PASS"
    assert verdict["next_actions"] == []
    assert len(verdict["checks"]) == 2


def test_compose_overall_warn_lists_sources() -> None:
    checks = [
        VerifyCheck(name="pcb_drc", status="clean"),
        VerifyCheck(name="sch_erc", status="findings", errors=0, warnings=3),
    ]
    verdict = compose_board_verdict(checks)

    assert verdict["overall"] == "WARN"
    assert "sch_erc" in str(verdict["summary"])
    assert any("ERC" in action for action in verdict["next_actions"])


def test_compose_overall_fail_blocks_and_suggests_actions() -> None:
    checks = [
        summarize_check(
            "pcb_drc",
            status="clean",
            report={
                "violations": [{"severity": "error", "type": "clearance"}],
                "unconnected_items": [{"a": 1}],
            },
            unconnected_key="unconnected_items",
        ),
        VerifyCheck(name="sch_erc", status="clean"),
    ]
    verdict = compose_board_verdict(checks)

    assert verdict["overall"] == "FAIL"
    actions = " ".join(str(a) for a in verdict["next_actions"])
    assert "DRC" in actions
    assert "unconnected" in actions
