"""FastMCP-independent routing length-tuning rule service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..utils.sexpr import _sexpr_string

NetNamesProvider = Callable[[], set[str]]
TrackLengthProvider = Callable[[str], float]
RuleWriter = Callable[[str, str], Path]


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


def build_length_tune_rule(
    net_name: str,
    target_mm: float,
    tolerance_mm: float,
) -> tuple[str, str]:
    """Build the legacy single-net length-tuning rule body."""
    name = f"Length tune {net_name}"
    body = "\n".join(
        [
            f"(rule {_sexpr_string(name)}",
            f"  (condition \"A.NetName == '{net_name}'\")",
            f"  (constraint length (min {_mm(max(target_mm - tolerance_mm, 0.0))}) "
            f"(opt {_mm(target_mm)}) (max {_mm(target_mm + tolerance_mm)}))",
            ")",
        ]
    )
    return name, body


def build_diff_pair_length_rules(
    net_name_p: str,
    net_name_n: str,
    target_length_mm: float,
) -> list[tuple[str, str]]:
    """Build the legacy matched-length rule set for a differential pair."""
    rules = [
        build_length_tune_rule(net_name_p, target_length_mm, 0.1),
        build_length_tune_rule(net_name_n, target_length_mm, 0.1),
    ]
    pair_rule_name = f"Length match {net_name_p} {net_name_n}"
    pair_rule_body = "\n".join(
        [
            f"(rule {_sexpr_string(pair_rule_name)}",
            f"  (condition \"A.NetName == '{net_name_p}' || A.NetName == '{net_name_n}'\")",
            "  (constraint skew (max 0.1000mm))",
            ")",
        ]
    )
    rules.append((pair_rule_name, pair_rule_body))
    return rules


@dataclass(frozen=True)
class RoutingLengthTuningService:
    """Write length-tuning constraints without depending on FastMCP."""

    list_board_net_names: NetNamesProvider
    current_track_length_mm: TrackLengthProvider
    write_rule: RuleWriter

    def tune_net(
        self,
        net_name: str,
        target_mm: float,
        meander_amplitude_mm: float = 0.5,
        tolerance_mm: float = 0.1,
    ) -> str:
        board_nets = self.list_board_net_names()
        if net_name not in board_nets:
            return (
                "Length-tuning rule was not written. "
                f"Net '{net_name}' was not found on the active board."
            )

        current_length = self.current_track_length_mm(net_name)
        delta = target_mm - current_length
        rule_name, rule_body = build_length_tune_rule(net_name, target_mm, tolerance_mm)
        try:
            path = self.write_rule(rule_name, rule_body)
        except (OSError, ValueError) as exc:
            return f"Length-tuning rule update failed: {exc}"

        status = "within tolerance" if abs(delta) <= tolerance_mm else "needs tuning"
        return (
            f"Length-tuning rule '{rule_name}' written to {path}.\n"
            f"Current length: {current_length:.3f} mm\n"
            f"Target length: {target_mm:.3f} mm\n"
            f"Delta: {delta:.3f} mm ({status})\n"
            f"Suggested meander amplitude: {meander_amplitude_mm:.3f} mm"
        )

    def tune_diff_pair(
        self,
        net_name_p: str,
        net_name_n: str,
        target_length_mm: float,
    ) -> str:
        board_nets = self.list_board_net_names()
        missing = [name for name in (net_name_p, net_name_n) if name not in board_nets]
        if missing:
            return (
                "Differential-pair length tuning rules were not written. "
                f"Missing nets: {', '.join(missing)}"
            )

        written_paths: list[str] = []
        for rule_name, rule_body in build_diff_pair_length_rules(
            net_name_p,
            net_name_n,
            target_length_mm,
        ):
            try:
                path = self.write_rule(rule_name, rule_body)
            except (OSError, ValueError) as exc:
                return f"Differential-pair length tuning failed: {exc}"
            written_paths.append(str(path))

        current_p = self.current_track_length_mm(net_name_p)
        current_n = self.current_track_length_mm(net_name_n)
        skew = abs(current_p - current_n)
        return (
            "Differential-pair length rules updated.\n"
            f"Rules file: {written_paths[-1]}\n"
            f"{net_name_p}: {current_p:.3f} mm\n"
            f"{net_name_n}: {current_n:.3f} mm\n"
            f"Current skew: {skew:.3f} mm\n"
            f"Target length: {target_length_mm:.3f} mm"
        )
