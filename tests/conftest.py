from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.models import DetectedMaterial, VisionResult
from app.providers.base import VisionProvider


class FakeProvider(VisionProvider):
    name = "fake"

    def __init__(self, result: VisionResult | DetectedMaterial) -> None:
        # 兼容旧用法：单个 DetectedMaterial 自动包装成 VisionResult。
        if isinstance(result, DetectedMaterial):
            result = VisionResult(detections=[result])
        self.result = result

    async def analyze(self, image_bytes: bytes, mime_type: str) -> VisionResult:
        assert image_bytes
        assert mime_type.startswith("image/")
        return self.result


@pytest.fixture
def image_bytes() -> bytes:
    image = Image.new("RGB", (900, 900), "#e6bb4a")
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 120, 780, 780), outline="#063f70", width=30)
    draw.line((120, 120, 780, 780), fill="#ffffff", width=18)
    output = BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()

