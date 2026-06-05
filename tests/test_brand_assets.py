from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).parents[1]
BRAND_DIR = ROOT / "custom_components" / "circuitsetup_energy_analyzer" / "brand"


def test_integration_brand_images_are_valid_square_pngs() -> None:
    for image_name in ("icon.png", "logo.png"):
        data = (BRAND_DIR / image_name).read_bytes()

        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert data[12:16] == b"IHDR"
        width, height = struct.unpack(">II", data[16:24])
        assert width == height
        assert width >= 256
