from __future__ import annotations

import pytest

from app.config import Settings
from app.domain import Brand, MaterialType
from app.models import DetectedMaterial
from app.reviewer import MaterialReviewer
from conftest import FakeProvider


@pytest.mark.asyncio
async def test_matching_brand_and_type_pass(image_bytes: bytes) -> None:
    provider = FakeProvider(
        DetectedMaterial(
            brand=Brand.ROYAL,
            material_type=MaterialType.LIGHTBOX,
            confidence=0.93,
            evidence=["可见皇家产品罐", "画面位于有厚度的发光箱体"],
        )
    )
    result = await MaterialReviewer(provider, Settings()).review(
        expected_brand=Brand.ROYAL,
        expected_material_type=MaterialType.LIGHTBOX,
        image_bytes=image_bytes,
        mime_type="image/jpeg",
    )
    assert result.status == "passed"
    assert result.passed is True


@pytest.mark.asyncio
async def test_mismatch_is_rejected(image_bytes: bytes) -> None:
    provider = FakeProvider(
        DetectedMaterial(
            brand=Brand.YUANYUE,
            material_type=MaterialType.LIGHTBOX,
            confidence=0.94,
        )
    )
    result = await MaterialReviewer(provider, Settings()).review(
        expected_brand=Brand.ROYAL,
        expected_material_type=MaterialType.LIGHTBOX,
        image_bytes=image_bytes,
        mime_type="image/jpeg",
    )
    assert result.status == "rejected"
    assert "品牌不匹配" in result.reasons[0]


@pytest.mark.asyncio
async def test_low_confidence_goes_to_manual_review(image_bytes: bytes) -> None:
    provider = FakeProvider(
        DetectedMaterial(
            brand=Brand.ROYAL,
            material_type=MaterialType.LIGHTBOX,
            confidence=0.51,
        )
    )
    result = await MaterialReviewer(provider, Settings(min_confidence=0.7)).review(
        expected_brand=Brand.ROYAL,
        expected_material_type=MaterialType.LIGHTBOX,
        image_bytes=image_bytes,
        mime_type="image/jpeg",
    )
    assert result.status == "manual_review"
    assert result.passed is False

