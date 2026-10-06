from __future__ import annotations

import pytest

from kicad_mcp.evals.semantic_differential_connectivity import (
    CONNECTIVITY_AUTHORITY,
    CONNECTIVITY_COMPARISON_METHOD,
    CONNECTIVITY_OPERATION,
    classify_connectivity_differential,
    connectivity_signature_hash,
    normalize_custom_connectivity,
    normalize_native_connectivity,
)

SOURCE_SHA = "a" * 40
FIXTURE_HASH = "sha256:" + "b" * 64

NATIVE_NETLIST = r"""
(export
  (nets
    (net (code "1") (name "/EN")
      (node (ref "C1") (pin "1") (pintype "passive"))
      (node (ref "U1") (pin "2") (pinfunction "EN") (pintype "input")))
    (net (code "2") (name "GND")
      (node (ref "C1") (pin "2") (pintype "passive"))
      (node (ref "U1") (pin "3") (pinfunction "GND") (pintype "power_in")))
    (net (code "3") (name "Net-(R1-Pad2)")
      (node (ref "R1") (pin "2") (pintype "passive"))
      (node (ref "SW1") (pin "2") (pintype "passive"))))
)
"""

CUSTOM_GROUPS = [
    {
        "names": ["EN"],
        "pins": [
            {"reference": "U1", "pin": "2"},
            {"reference": "C1", "pin": "1"},
        ],
    },
    {
        "names": ["GND"],
        "pins": [
            {"reference": "U1", "pin": "3"},
            {"reference": "C1", "pin": "2"},
        ],
    },
    {
        "names": [],
        "pins": [
            {"reference": "SW1", "pin": "2"},
            {"reference": "R1", "pin": "2"},
        ],
    },
]


def test_native_and_custom_connectivity_normalize_net_identity_and_pin_membership() -> None:
    native = normalize_native_connectivity(NATIVE_NETLIST)
    custom = normalize_custom_connectivity(CUSTOM_GROUPS)

    assert (
        native
        == custom
        == (
            ("EN", (("C1", "1"), ("U1", "2"))),
            ("GND", (("C1", "2"), ("U1", "3"))),
            (None, (("R1", "2"), ("SW1", "2"))),
        )
    )
    assert connectivity_signature_hash(native) == connectivity_signature_hash(custom)


def test_connectivity_classifier_detects_seeded_membership_divergence() -> None:
    divergent_groups = [
        CUSTOM_GROUPS[0],
        CUSTOM_GROUPS[1],
        {"names": [], "pins": [{"reference": "R1", "pin": "2"}]},
        {"names": [], "pins": [{"reference": "SW1", "pin": "2"}]},
    ]

    result = classify_connectivity_differential(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="connectivity-fixture",
        fixture_hash=FIXTURE_HASH,
        native_netlist_text=NATIVE_NETLIST,
        custom_groups=divergent_groups,
    )

    assert result.status == "divergence"
    assert result.native_result_hash != result.custom_result_hash
    assert result.operation == CONNECTIVITY_OPERATION
    assert result.authority == CONNECTIVITY_AUTHORITY
    assert result.comparison_method == CONNECTIVITY_COMPARISON_METHOD
    assert result.false_pass is False
    assert result.false_fail is False


def test_connectivity_classifier_detects_seeded_net_name_divergence() -> None:
    divergent_groups = [dict(CUSTOM_GROUPS[0], names=["WRONG_EN"]), *CUSTOM_GROUPS[1:]]

    result = classify_connectivity_differential(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="connectivity-fixture",
        fixture_hash=FIXTURE_HASH,
        native_netlist_text=NATIVE_NETLIST,
        custom_groups=divergent_groups,
    )

    assert result.status == "divergence"
    assert result.native_result_hash != result.custom_result_hash
    assert result.false_pass is False
    assert result.false_fail is False


def test_connectivity_classifier_matches_equal_semantics_on_preview_lane() -> None:
    result = classify_connectivity_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="connectivity-fixture",
        fixture_hash=FIXTURE_HASH,
        native_netlist_text=NATIVE_NETLIST,
        custom_groups=CUSTOM_GROUPS,
    )

    assert result.status == "match"
    assert result.native_result_hash == result.custom_result_hash
    assert result.lane == "preview"


def test_connectivity_classifier_fails_closed_when_native_authority_is_unavailable() -> None:
    result = classify_connectivity_differential(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="connectivity-fixture",
        fixture_hash=FIXTURE_HASH,
        native_netlist_text=None,
        custom_groups=CUSTOM_GROUPS,
        authority_available=False,
        reason="KiCad native netlist export unavailable.",
    )

    assert result.status == "unavailable-authority"
    assert result.native_result_hash is None
    assert result.custom_result_hash is not None
    assert result.reason == "KiCad native netlist export unavailable."


def test_connectivity_normalizers_reject_ambiguous_or_duplicate_membership() -> None:
    duplicate_native = NATIVE_NETLIST.replace(
        '(node (ref "C1") (pin "2") (pintype "passive"))',
        '(node (ref "C1") (pin "1") (pintype "passive"))',
    )
    duplicate_custom = [CUSTOM_GROUPS[0], CUSTOM_GROUPS[0]]
    ambiguous_names = [dict(CUSTOM_GROUPS[0], names=["EN", "ALIAS"])]

    for call in (
        lambda: normalize_native_connectivity(duplicate_native),
        lambda: normalize_custom_connectivity(duplicate_custom),
    ):
        with pytest.raises(ValueError, match="multiple connectivity groups"):
            call()

    with pytest.raises(ValueError, match="multiple net names"):
        normalize_custom_connectivity(ambiguous_names)


def test_equal_empty_connectivity_cannot_be_classified_as_match() -> None:
    with pytest.raises(ValueError, match="empty connectivity"):
        classify_connectivity_differential(
            source_sha=SOURCE_SHA,
            lane="stable",
            kicad_version="10.0.6",
            fixture_id="empty-fixture",
            fixture_hash=FIXTURE_HASH,
            native_netlist_text="(export (nets))",
            custom_groups=[],
        )
