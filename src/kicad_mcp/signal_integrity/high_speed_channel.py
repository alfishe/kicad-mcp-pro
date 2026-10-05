"""FastMCP-independent high-speed channel analysis service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import get_config
from ..models.signal_integrity import HighSpeedChannelInput
from ..utils.channel import (
    ChannelMetrics,
    ChannelSpec,
    closed_form_channel_metrics,
    simulate_channel_insertion_loss,
)
from ..utils.ngspice import NgspiceRunner
from ..utils.solver_seams import channel_method, format_solver_verdict
from ..verdicts import three_level_verdict, warn_max_from


def _channel_output_dir() -> Path:
    return get_config().ensure_output_dir("channel")


def _ghz(freq_hz: float) -> str:
    return f"{freq_hz / 1e9:.3f} GHz"


def _format_channel_result(metrics: ChannelMetrics, max_insertion_loss_db: float) -> str:
    fail_il_db = warn_max_from(max_insertion_loss_db)
    verdict = three_level_verdict(
        metrics.insertion_loss_nyquist_db, pass_max=max_insertion_loss_db, warn_max=fail_il_db
    )
    lines = [
        "High-speed channel analysis:",
        f"- Nyquist frequency: {_ghz(metrics.nyquist_hz)}",
        f"- Insertion loss at Nyquist: {metrics.insertion_loss_nyquist_db:.2f} dB "
        f"({verdict}; PASS <= {max_insertion_loss_db:.1f} dB, WARN <= {fail_il_db:.1f} dB, "
        f"FAIL > {fail_il_db:.1f} dB)",
        f"- -3 dB bandwidth: {_ghz(metrics.bandwidth_3db_hz)}",
        f"- Eye height: {metrics.eye_height_v:.4f} V "
        f"({metrics.eye_height_ratio * 100.0:.1f}% of drive amplitude)",
    ]
    method = channel_method(metrics.source == "ngspice")
    lines.append(f"- Method: {method['method']} — {method['accuracy']}")
    lines.append(f"- {format_solver_verdict(method)}")
    lines.extend(f"- {note}" for note in metrics.notes)
    if not method["solver_grade"]:
        lines.append(f"- Note: {method['note']}")
    return "\n".join(lines)


@dataclass(frozen=True)
class SignalIntegrityHighSpeedChannelService:
    """Analyze a lossy high-speed channel without depending on FastMCP."""

    def analyze(
        self,
        length_mm: float,
        data_rate_gbps: float,
        z0_ohm: float = 50.0,
        eps_eff: float = 3.8,
        loss_tangent: float = 0.02,
        trace_width_mm: float = 0.2,
        amplitude_v: float = 1.0,
        max_insertion_loss_db: float = 10.0,
    ) -> str:
        payload = HighSpeedChannelInput(
            length_mm=length_mm,
            z0_ohm=z0_ohm,
            data_rate_gbps=data_rate_gbps,
            eps_eff=eps_eff,
            loss_tangent=loss_tangent,
            trace_width_mm=trace_width_mm,
            amplitude_v=amplitude_v,
            max_insertion_loss_db=max_insertion_loss_db,
        )
        spec = ChannelSpec(
            length_mm=payload.length_mm,
            z0_ohm=payload.z0_ohm,
            data_rate_gbps=payload.data_rate_gbps,
            eps_eff=payload.eps_eff,
            loss_tangent=payload.loss_tangent,
            trace_width_mm=payload.trace_width_mm,
            amplitude_v=payload.amplitude_v,
        )
        metrics = closed_form_channel_metrics(spec)
        cfg = get_config()
        measured = simulate_channel_insertion_loss(
            spec,
            NgspiceRunner(cfg.ngspice_cli, cfg.cli_timeout),
            _channel_output_dir(),
        )
        if measured is not None:
            metrics = measured
        return _format_channel_result(metrics, payload.max_insertion_loss_db)
