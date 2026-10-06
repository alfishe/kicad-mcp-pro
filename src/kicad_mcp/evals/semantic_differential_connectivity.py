"""Connectivity-specific normalization for native KiCad semantic differentials."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..utils.sexpr import _extract_block, _unescape_sexpr_string
from .semantic_differential import (
    DifferentialLane,
    DifferentialResult,
    classify_differential_result,
)

CONNECTIVITY_OPERATION = "connectivity.net-compilation"
CONNECTIVITY_AUTHORITY = "kicad-cli:sch-export-netlist-kicadsexpr"
CONNECTIVITY_COMPARISON_METHOD = "named-pin-equivalence-sha256.v1"

ConnectivityPin = tuple[str, str]
ConnectivityGroup = tuple[ConnectivityPin, ...]
ConnectivityNet = tuple[str | None, ConnectivityGroup]
ConnectivitySignature = tuple[ConnectivityNet, ...]

_QUOTED_VALUE = r'"((?:\\.|[^"\\])*)"'
_NODE_PATTERN = re.compile(
    rf"\(node\s+\(ref\s+{_QUOTED_VALUE}\)\s+\(pin\s+{_QUOTED_VALUE}\)",
    re.MULTILINE,
)
_NAME_PATTERN = re.compile(rf"\(name\s+{_QUOTED_VALUE}\)", re.MULTILINE)
_GENERATED_NET_NAME = re.compile(r"^(?:Net|unconnected)-\(.+\)$", re.IGNORECASE)


def _pin(reference: object, pin: object) -> ConnectivityPin:
    ref = str(reference).strip()
    number = str(pin).strip()
    if not ref or not number:
        raise ValueError("Connectivity pin records require non-empty reference and pin values")
    return ref, number


def _canonical_native_name(raw: str) -> str | None:
    name = raw.strip()
    if not name:
        raise ValueError("Native connectivity net requires a non-empty net identity")
    if _GENERATED_NET_NAME.fullmatch(name):
        return None
    return name[1:] if name.startswith("/") else name


def _canonical_custom_name(raw_names: object) -> str | None:
    if not isinstance(raw_names, Sequence) or isinstance(raw_names, str | bytes):
        raise ValueError("Custom connectivity group names must be a sequence")
    names = {str(value).strip() for value in raw_names if str(value).strip()}
    if len(names) > 1:
        raise ValueError("Custom connectivity group carries multiple net names")
    if not names:
        return None
    name = next(iter(names))
    return name[1:] if name.startswith("/") else name


def _normalize_signature(groups: Iterable[ConnectivityNet]) -> ConnectivitySignature:
    normalized: list[ConnectivityNet] = []
    seen_pins: set[ConnectivityPin] = set()
    seen_names: set[str] = set()
    for name, raw_pins in groups:
        pins = tuple(sorted(set(raw_pins)))
        if not pins:
            continue
        overlap = seen_pins.intersection(pins)
        if overlap:
            duplicate = sorted(overlap)[0]
            raise ValueError(
                f"Pin {duplicate[0]}:{duplicate[1]} appears in multiple connectivity groups"
            )
        if name is not None:
            if name in seen_names:
                raise ValueError(f"Net name {name!r} appears in multiple connectivity groups")
            seen_names.add(name)
        seen_pins.update(pins)
        normalized.append((name, pins))
    return tuple(
        sorted(
            normalized,
            key=lambda item: (item[0] is None, item[0] or "", item[1]),
        )
    )


def normalize_native_connectivity(netlist_text: str) -> ConnectivitySignature:
    """Normalize KiCad native netlist output into named pin-equivalence classes."""
    groups: list[ConnectivityNet] = []
    cursor = 0
    while cursor < len(netlist_text):
        start = netlist_text.find("(net", cursor)
        if start < 0:
            break
        token_end = start + 4
        if token_end < len(netlist_text) and not netlist_text[token_end].isspace():
            cursor = token_end
            continue
        block, length = _extract_block(netlist_text, start)
        if not block or length <= 0:
            raise ValueError("Malformed native KiCad netlist: unbalanced net block")
        name_match = _NAME_PATTERN.search(block)
        if name_match is None:
            raise ValueError("Native connectivity net is missing a name")
        name = _canonical_native_name(_unescape_sexpr_string(name_match.group(1)))
        pins = tuple(
            _pin(
                _unescape_sexpr_string(match.group(1)),
                _unescape_sexpr_string(match.group(2)),
            )
            for match in _NODE_PATTERN.finditer(block)
        )
        if pins:
            groups.append((name, pins))
        cursor = start + length
    return _normalize_signature(groups)


def normalize_custom_connectivity(
    groups: Iterable[Mapping[str, Any]],
) -> ConnectivitySignature:
    """Normalize MCP Pro connectivity groups into named pin-equivalence classes."""
    normalized_groups: list[ConnectivityNet] = []
    for group in groups:
        raw_pins = group.get("pins", [])
        if not isinstance(raw_pins, Sequence) or isinstance(raw_pins, str | bytes):
            raise ValueError("Custom connectivity group pins must be a sequence")
        pins: list[ConnectivityPin] = []
        for raw_pin in raw_pins:
            if not isinstance(raw_pin, Mapping):
                raise ValueError("Custom connectivity pins must be mappings")
            pins.append(_pin(raw_pin.get("reference", ""), raw_pin.get("pin", "")))
        if pins:
            normalized_groups.append((_canonical_custom_name(group.get("names", [])), tuple(pins)))
    return _normalize_signature(normalized_groups)


def connectivity_signature_hash(signature: ConnectivitySignature) -> str:
    """Hash one normalized connectivity signature deterministically."""
    canonical = json.dumps(
        {
            "nets": [
                {
                    "name": name,
                    "pins": [list(pin) for pin in pins],
                }
                for name, pins in signature
            ]
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def fixture_file_hash(path: Path) -> str:
    """Return the report-compatible content hash for a differential fixture file."""
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def classify_connectivity_differential(
    *,
    source_sha: str,
    lane: DifferentialLane,
    kicad_version: str,
    fixture_id: str,
    fixture_hash: str,
    native_netlist_text: str | None,
    custom_groups: Iterable[Mapping[str, Any]] | None,
    authority_available: bool = True,
    infrastructure_valid: bool = True,
    reason: str | None = None,
) -> DifferentialResult:
    """Classify native-vs-custom net identity and pin-membership semantics."""
    if not infrastructure_valid:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=CONNECTIVITY_OPERATION,
            authority=CONNECTIVITY_AUTHORITY,
            comparison_method=CONNECTIVITY_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=None,
            authority_available=True,
            infrastructure_valid=False,
            reason=reason or "Connectivity differential infrastructure is invalid.",
        )

    if custom_groups is None:
        raise ValueError("Custom connectivity groups are required for a valid comparison")
    custom_signature = normalize_custom_connectivity(custom_groups)
    custom_hash = connectivity_signature_hash(custom_signature)

    if not authority_available:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=CONNECTIVITY_OPERATION,
            authority=CONNECTIVITY_AUTHORITY,
            comparison_method=CONNECTIVITY_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=custom_hash,
            authority_available=False,
            reason=reason or "KiCad native connectivity authority is unavailable.",
        )

    if native_netlist_text is None:
        raise ValueError("Native KiCad netlist text is required when authority is available")
    native_signature = normalize_native_connectivity(native_netlist_text)
    if not native_signature and not custom_signature:
        raise ValueError(
            "A valid connectivity comparison cannot classify empty connectivity as match"
        )
    native_hash = connectivity_signature_hash(native_signature)
    return classify_differential_result(
        source_sha=source_sha,
        lane=lane,
        kicad_version=kicad_version,
        fixture_id=fixture_id,
        fixture_hash=fixture_hash,
        operation=CONNECTIVITY_OPERATION,
        authority=CONNECTIVITY_AUTHORITY,
        comparison_method=CONNECTIVITY_COMPARISON_METHOD,
        native_result_hash=native_hash,
        custom_result_hash=custom_hash,
    )


__all__ = [
    "CONNECTIVITY_AUTHORITY",
    "CONNECTIVITY_COMPARISON_METHOD",
    "CONNECTIVITY_OPERATION",
    "ConnectivityGroup",
    "ConnectivityNet",
    "ConnectivityPin",
    "ConnectivitySignature",
    "classify_connectivity_differential",
    "connectivity_signature_hash",
    "fixture_file_hash",
    "normalize_custom_connectivity",
    "normalize_native_connectivity",
]
