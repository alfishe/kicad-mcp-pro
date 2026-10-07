"""Combined board verification verdict: DRC + ERC + connectivity in one call.

Pure composition layer — no I/O. Callers run the individual checks (via
``drc_runner`` / kicad-cli ERC) and feed report dicts into :func:`summarize_check`
/ :func:`compose_board_verdict` to get a single machine-actionable verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..verdicts import Verdict
from .drc_report import normalize_report_severity, report_entries

CheckStatus = Literal["clean", "findings", "unavailable", "malformed", "error"]

_TOP_VIOLATION_LIMIT = 5


@dataclass(frozen=True, slots=True)
class VerifyCheck:
    """One verification check summarized to counts plus sample violations."""

    name: str
    status: CheckStatus
    errors: int = 0
    warnings: int = 0
    unconnected: int = 0
    detail: str | None = None
    top_violations: list[dict[str, Any]] = field(default_factory=list)

    def verdict(self) -> Verdict:
        if self.status in {"unavailable", "malformed", "error"}:
            return "FAIL"
        if self.errors > 0:
            return "FAIL"
        if self.warnings > 0:
            return "WARN"
        return "PASS"


def summarize_check(
    name: str,
    *,
    status: CheckStatus,
    report: dict[str, object] | None,
    error: str | None = None,
    violations_key: str = "violations",
    unconnected_key: str | None = None,
) -> VerifyCheck:
    """Build a :class:`VerifyCheck` from one kicad-cli JSON report."""
    if status in {"unavailable", "malformed", "error"}:
        return VerifyCheck(
            name=name,
            status=status,
            detail=error or f"{name} report unavailable",
        )
    if report is None:
        return VerifyCheck(
            name=name, status="error", detail=error or f"{name} report missing"
        )

    entries = report_entries(report, violations_key)
    errors = sum(
        1 for entry in entries if normalize_report_severity(entry.get("severity")) == "error"
    )
    warnings = len(entries) - errors

    unconnected = 0
    if unconnected_key is not None:
        unconnected = len(report_entries(report, unconnected_key))

    top = [
        {
            "type": entry.get("type") or entry.get("description") or "unknown",
            "severity": normalize_report_severity(entry.get("severity")),
            "description": entry.get("description"),
            "items": entry.get("items"),
        }
        for entry in entries[:_TOP_VIOLATION_LIMIT]
    ]

    return VerifyCheck(
        name=name,
        status="findings" if entries else "clean",
        errors=errors,
        warnings=warnings,
        unconnected=unconnected,
        detail=error,
        top_violations=top,
    )


def compose_board_verdict(checks: list[VerifyCheck]) -> dict[str, object]:
    """Fold per-check results into one overall PASS/WARN/FAIL verdict."""
    verdicts = [check.verdict() for check in checks]

    if "FAIL" in verdicts:
        overall: Verdict = "FAIL"
    elif "WARN" in verdicts:
        overall = "WARN"
    else:
        overall = "PASS"

    failed = [check.name for check, v in zip(checks, verdicts) if v == "FAIL"]
    warned = [check.name for check, v in zip(checks, verdicts) if v == "WARN"]

    if overall == "PASS":
        summary = "All verification checks passed."
    elif overall == "WARN":
        summary = f"Marginal: warnings in {', '.join(warned)}; no errors."
    else:
        blocking = ", ".join(failed)
        summary = f"Blocked by: {blocking}."

    return {
        "overall": overall,
        "summary": summary,
        "checks": [
            {
                "check": check.name,
                "verdict": check.verdict(),
                "status": check.status,
                "errors": check.errors,
                "warnings": check.warnings,
                **({"unconnected": check.unconnected} if check.unconnected else {}),
                **({"detail": check.detail} if check.detail else {}),
                **({"top_violations": check.top_violations} if check.top_violations else {}),
            }
            for check in checks
        ],
        "next_actions": _next_actions(checks),
    }


def _next_actions(checks: list[VerifyCheck]) -> list[str]:
    actions: list[str] = []
    for check in checks:
        if check.verdict() == "PASS":
            continue
        if check.name == "pcb_drc":
            actions.append("Fix DRC violations listed in top_violations, then re-run verify_board.")
        if check.name == "sch_erc":
            actions.append("Fix ERC violations in the schematic, then re-run verify_board.")
        if check.unconnected > 0:
            actions.append(
                f"Route {check.unconnected} unconnected connection(s) before export."
            )
        if check.status in {"unavailable", "malformed", "error"}:
            actions.append(
                f"{check.name} could not run: {check.detail or 'unknown reason'} — a blocked "
                "check blocks the verdict; fix the input and re-run."
            )
    return actions
