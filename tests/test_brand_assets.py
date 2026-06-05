from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).parents[1]
BRAND_DIR = ROOT / "custom_components" / "circuitsetup_energy_analyzer" / "brand"


def test_integration_brand_icon_is_valid_square_png() -> None:
    icon_path = BRAND_DIR / "icon.png"
    data = icon_path.read_bytes()

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[12:16] == b"IHDR"
    width, height = struct.unpack(">II", data[16:24])
    assert width == height
    assert width >= 256
