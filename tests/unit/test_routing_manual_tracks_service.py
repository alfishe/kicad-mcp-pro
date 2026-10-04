from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from kipy.board_types import Net
from kipy.geometry import Vector2

from kicad_mcp.models.common import _PadLike
from kicad_mcp.pcb.geometry import point_xy_mm
from kicad_mcp.routing.manual_tracks import MutationCommand, RoutingManualTrackService
from kicad_mcp.utils.layers import resolve_layer
from kicad_mcp.utils.units import mm_to_nm


class FakeBoard:
    def __init__(self) -> None:
        self.created: list[object] = []

    def create_items(self, items: list[object]) -> list[object]:
        self.created.extend(items)
        return items


def _pad(reference: str, number: str, x_mm: float, y_mm: float, net_name: str) -> _PadLike:
    net = Net()
    net.name = net_name
    return cast(
        _PadLike,
        SimpleNamespace(
            parent=SimpleNamespace(
                reference_field=SimpleNamespace(
                    text=SimpleNamespace(value=reference),
                )
            ),
            number=number,
            position=Vector2.from_xy_mm(x_mm, y_mm),
            net=net,
        ),
    )


def _service(
    pads: list[_PadLike] | None = None,
) -> tuple[RoutingManualTrackService, FakeBoard, list[str]]:
    board = FakeBoard()
    operations: list[str] = []

    def execute(operation: str, command: MutationCommand) -> object:
        operations.append(operation)
        return command(board)

    service = RoutingManualTrackService(
        resolve_layer=resolve_layer,
        list_pads=lambda: list(pads or []),
        execute_mutation=execute,
    )
    return service, board, operations


def test_route_single_preserves_track_geometry_net_and_response() -> None:
    service, board, operations = _service()

    result = service.route_single(
        1.0,
        2.0,
        5.0,
        8.0,
        "F_Cu",
        0.3,
        "USB_D+",
    )

    assert result == "Single track routed successfully."
    assert operations == ["route_single_track"]
    assert len(board.created) == 1
    track = board.created[0]
    assert point_xy_mm(track.start) == (1.0, 2.0)
    assert point_xy_mm(track.end) == (5.0, 8.0)
    assert track.layer == resolve_layer("F_Cu")
    assert track.width == mm_to_nm(0.3)
    assert track.net.name == "USB_D+"


def test_route_single_preserves_empty_net_behavior() -> None:
    service, board, _operations = _service()

    service.route_single(0.0, 0.0, 1.0, 1.0)

    track = board.created[0]
    assert not getattr(getattr(track, "net", None), "name", "")


def test_route_pad_to_pad_preserves_orthogonal_geometry_and_response() -> None:
    pads = [
        _pad("R1", "1", 1.0, 2.0, "DATA"),
        _pad("U2", "3", 5.0, 8.0, ""),
    ]
    service, board, operations = _service(pads)

    result = service.route_pad_to_pad("R1", "1", "U2", "3", "F_Cu", 0.25)

    assert result == (
        "Created an orthogonal two-segment route from R1:1 to U2:3. Run DRC to verify the path."
    )
    assert operations == ["route_from_pad_to_pad"]
    assert len(board.created) == 2
    first, second = board.created
    assert point_xy_mm(first.start) == (1.0, 2.0)
    assert point_xy_mm(first.end) == (5.0, 2.0)
    assert point_xy_mm(second.start) == (5.0, 2.0)
    assert point_xy_mm(second.end) == (5.0, 8.0)
    assert first.net.name == "DATA"
    assert second.net.name == "DATA"


def test_route_pad_to_pad_preserves_missing_pad_message_without_mutation() -> None:
    service, board, operations = _service([_pad("R1", "1", 1.0, 2.0, "DATA")])

    result = service.route_pad_to_pad("R1", "1", "U2", "3")

    assert result == "One or both pads were not found on the active board."
    assert operations == []
    assert board.created == []
