from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from kicad_mcp.signal_integrity import high_speed_channel as channel
from kicad_mcp.utils.channel import ChannelMetrics


def test_analyze_preserves_closed_form_output_contract(monkeypatch, tmp_path) -> None:
    metrics = ChannelMetrics(
        nyquist_hz=2.5e9,
        insertion_loss_nyquist_db=4.25,
        eye_height_v=0.6123,
        eye_height_ratio=0.6123,
        bandwidth_3db_hz=1.75e9,
        source="closed_form",
        notes=["fixture note"],
    )
    monkeypatch.setattr(channel, "closed_form_channel_metrics", lambda _spec: metrics)
    monkeypatch.setattr(channel, "simulate_channel_insertion_loss", lambda *_args: None)
    monkeypatch.setattr(
        channel,
        "get_config",
        lambda: SimpleNamespace(
            ngspice_cli="ngspice",
            cli_timeout=5.0,
            ensure_output_dir=lambda _name: tmp_path,
        ),
    )

    result = channel.SignalIntegrityHighSpeedChannelService().analyze(
        length_mm=40.0,
        data_rate_gbps=5.0,
        max_insertion_loss_db=10.0,
    )

    assert result.startswith("High-speed channel analysis:\n")
    assert "- Nyquist frequency: 2.500 GHz" in result
    assert "- Insertion loss at Nyquist: 4.25 dB (PASS;" in result
    assert "- -3 dB bandwidth: 1.750 GHz" in result
    assert "- Eye height: 0.6123 V (61.2% of drive amplitude)" in result
    assert "- fixture note" in result


def test_analyze_preserves_input_validation() -> None:
    service = channel.SignalIntegrityHighSpeedChannelService()

    with pytest.raises(ValidationError):
        service.analyze(length_mm=0.0, data_rate_gbps=5.0)
