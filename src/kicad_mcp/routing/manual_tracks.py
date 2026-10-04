"""FastMCP-independent manual-track routing service."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from kipy.board_types import Net, Track
from kipy.geometry import Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer

from ..models.common import _PadLike
from ..models.pcb import AddTrackInput
from ..pcb.geometry import point_xy_mm
from ..utils.units import mm_to_nm

LayerResolver = Callable[[str], BoardLayer.ValueType]
PadProvider = Callable[[], Iterable[_PadLike]]
MutationCommand = Callable[[Any], list[Any]]
MutationExecutor = Callable[[str, MutationCommand], Any]


def _find_pad(
    pads: Iterable[_PadLike],
    reference: str,
    pad_number: str,
) -> _PadLike | None:
    for pad in pads:
        if pad.parent.reference_field.text.value == reference and str(pad.number) == str(
            pad_number
        ):
            return pad
    return None


def _track_from_payload(
    payload: AddTrackInput,
    resolve_layer: LayerResolver,
) -> Track:
    track = Track()
    track.start = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
    track.end = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
    track.layer = resolve_layer(payload.layer)
    track.width = mm_to_nm(payload.width_mm)
    if payload.net_name:
        net = Net()
        net.name = payload.net_name
        track.net = net
    return track


@dataclass(frozen=True)
class RoutingManualTrackService:
    """Create direct and pad-to-pad tracks through injected board infrastructure."""

    resolve_layer: LayerResolver
    list_pads: PadProvider
    execute_mutation: MutationExecutor

    def route_single(
        self,
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        net_name: str = "",
    ) -> str:
        payload = AddTrackInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            layer=layer,
            width_mm=width_mm,
            net_name=net_name,
        )
        track = _track_from_payload(payload, self.resolve_layer)
        self.execute_mutation(
            "route_single_track",
            lambda board: list(board.create_items([track])),
        )
        return "Single track routed successfully."

    def route_pad_to_pad(
        self,
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
    ) -> str:
        start_pad = _find_pad(self.list_pads(), ref1, pad1)
        end_pad = _find_pad(self.list_pads(), ref2, pad2)
        if start_pad is None or end_pad is None:
            return "One or both pads were not found on the active board."

        start_x, start_y = point_xy_mm(start_pad.position)
        end_x, end_y = point_xy_mm(end_pad.position)
        net_name = start_pad.net.name or end_pad.net.name or ""
        payloads = [
            AddTrackInput(
                x1_mm=start_x,
                y1_mm=start_y,
                x2_mm=end_x,
                y2_mm=start_y,
                layer=layer,
                width_mm=width_mm,
                net_name=net_name,
            ),
            AddTrackInput(
                x1_mm=end_x,
                y1_mm=start_y,
                x2_mm=end_x,
                y2_mm=end_y,
                layer=layer,
                width_mm=width_mm,
                net_name=net_name,
            ),
        ]
        tracks = [_track_from_payload(payload, self.resolve_layer) for payload in payloads]
        self.execute_mutation(
            "route_from_pad_to_pad",
            lambda board: list(board.create_items(tracks)),
        )
        return (
            f"Created an orthogonal two-segment route from {ref1}:{pad1} to {ref2}:{pad2}. "
            "Run DRC to verify the path."
        )
