"""FastMCP-independent differential-pair routing-rule service."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..utils.sexpr import _sexpr_string

NetNamesProvider = Callable[[], set[str]]
RuleWriter = Callable[[str, str], Path]


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


def infer_diff_pair_base(net_p: str, net_n: str) -> str | None:
    """Infer the KiCad differential-pair base name from common suffix conventions."""
    candidates = [
        (r"(.+)_P$", r"(.+)_N$"),
        (r"(.+)_DP$", r"(.+)_DN$"),
        (r"(.+)\+$", r"(.+)-$"),
        (r"(.+)P$", r"(.+)N$"),
    ]
    for pattern_p, pattern_n in candidates:
        match_p = re.fullmatch(pattern_p, net_p)
        match_n = re.fullmatch(pattern_n, net_n)
        if match_p and match_n and match_p.group(1) == match_n.group(1):
            return match_p.group(1).rstrip("_-+/")
    return None


def build_differential_pair_rule(
    net_p: str,
    net_n: str,
    width_mm: float,
    gap_mm: float,
    length_tolerance_mm: float,
) -> tuple[str, str]:
    """Build the legacy differential-pair .kicad_dru rule body."""
    base_name = infer_diff_pair_base(net_p, net_n)
    condition = (
        f"A.inDiffPair('{base_name}')"
        if base_name is not None
        else f"A.NetName == '{net_p}' || A.NetName == '{net_n}'"
    )
    track_width_constraint = (
        f"  (constraint track_width (min {_mm(width_mm)}) "
        f"(opt {_mm(width_mm)}) (max {_mm(width_mm)}))"
    )
    gap_constraint = (
        f"  (constraint diff_pair_gap (min {_mm(gap_mm)}) (opt {_mm(gap_mm)}) (max {_mm(gap_mm)}))"
    )
    name = f"Differential pair {net_p} {net_n}"
    body = "\n".join(
        [
            f"(rule {_sexpr_string(name)}",
            f'  (condition "{condition}")',
            track_width_constraint,
            gap_constraint,
            f"  (constraint skew (max {_mm(length_tolerance_mm)}))",
            ")",
        ]
    )
    return name, body


@dataclass(frozen=True)
class RoutingDifferentialPairService:
    """Write differential-pair constraints without depending on FastMCP."""

    list_board_net_names: NetNamesProvider
    write_rule: RuleWriter

    def set_pair(
        self,
        net_p: str,
        net_n: str,
        layer: str = "F_Cu",
        width_mm: float = 0.2,
        gap_mm: float = 0.2,
        length_tolerance_mm: float = 0.1,
    ) -> str:
        board_nets = self.list_board_net_names()
        missing = [name for name in (net_p, net_n) if name not in board_nets]
        if missing:
            return (
                "Differential-pair routing rule was not written. "
                f"Missing nets: {', '.join(missing)}"
            )
        rule_name, rule_body = build_differential_pair_rule(
            net_p, net_n, width_mm, gap_mm, length_tolerance_mm
        )
        try:
            path = self.write_rule(rule_name, rule_body)
        except (OSError, ValueError) as exc:
            return f"Differential-pair rule update failed: {exc}"
        return (
            f"Differential-pair routing rule '{rule_name}' written to {path}.\n"
            f"Layer intent: {layer}, width: {_mm(width_mm)}, gap: {_mm(gap_mm)}, "
            f"max skew: {_mm(length_tolerance_mm)}."
        )
