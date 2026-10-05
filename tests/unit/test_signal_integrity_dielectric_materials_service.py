from __future__ import annotations

from kicad_mcp.signal_integrity.dielectric_materials import (
    SignalIntegrityDielectricMaterialsService,
)


def test_list_materials_preserves_catalog_format() -> None:
    service = SignalIntegrityDielectricMaterialsService(
        materials_provider=lambda: [
            {
                "key": "fr4_standard",
                "name": "Standard FR4",
                "er": 4.2,
                "loss_tangent": 0.02,
                "description": "General-purpose laminate",
            },
            {
                "key": "ro4350b",
                "name": "Rogers RO4350B",
                "er": 3.48,
                "loss_tangent": 0.0037,
                "description": "Low-loss RF laminate",
            },
        ]
    )

    result = service.list_materials()

    assert result == "\n".join(
        [
            "Available dielectric materials (2 total):",
            "",
            "  [fr4_standard] Standard FR4  Er=4.2  tan_d=0.02",
            "    General-purpose laminate",
            "",
            "  [ro4350b] Rogers RO4350B  Er=3.48  tan_d=0.0037",
            "    Low-loss RF laminate",
            "",
            "Use key string with si_synthesize_stackup_for_interfaces().",
        ]
    )


def test_list_materials_preserves_empty_catalog_format() -> None:
    service = SignalIntegrityDielectricMaterialsService(materials_provider=lambda: [])

    assert service.list_materials() == (
        "Available dielectric materials (0 total):\n\n"
        "Use key string with si_synthesize_stackup_for_interfaces()."
    )
