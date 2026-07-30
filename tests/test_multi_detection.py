"""WS-30 验收测试：可选条件、双模式、多组合、去重、嵌柜/灯箱边界。"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain import Brand, MaterialType
from app.models import DetectedMaterial, VisionResult
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.reviewer import MaterialReviewer
from conftest import FakeProvider


def _make_image() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (400, 400), "#c8a24a").save(buffer, format="JPEG")
    return buffer.getvalue()


def _vision(*detections: DetectedMaterial, warnings=None) -> VisionResult:
    return VisionResult(detections=list(detections), warnings=warnings or [])


async def _review(vision: VisionResult, **kwargs) -> object:
    settings = kwargs.pop("settings", Settings())
    return await MaterialReviewer(FakeProvider(vision), settings).review(
        image_bytes=_make_image(),
        mime_type="image/jpeg",
        **kwargs,
    )


# --- 两项都选 ---


@pytest.mark.asyncio
async def test_both_selected_target_present_passes(image_bytes: bytes) -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.ROYAL, material_type=MaterialType.LIGHTBOX, confidence=0.9),
        DetectedMaterial(brand=Brand.ZUNYUE, material_type=MaterialType.LIGHTBOX, confidence=0.88),
    )
    result = await _review(
        vision,
        expected_brand=Brand.ROYAL,
        expected_material_type=MaterialType.LIGHTBOX,
    )
    assert result.mode == "review"
    assert result.status == "passed"
    assert result.passed is True


@pytest.mark.asyncio
async def test_both_selected_target_absent_rejected() -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.YUANYUE, material_type=MaterialType.LIGHTBOX, confidence=0.9),
    )
    result = await _review(
        vision,
        expected_brand=Brand.ROYAL,
        expected_material_type=MaterialType.LIGHTBOX,
    )
    assert result.status == "rejected"
    assert result.passed is False


@pytest.mark.asyncio
async def test_both_selected_low_confidence_manual_review() -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.ROYAL, material_type=MaterialType.LIGHTBOX, confidence=0.4),
    )
    result = await _review(
        vision,
        expected_brand=Brand.ROYAL,
        expected_material_type=MaterialType.LIGHTBOX,
    )
    assert result.status == "manual_review"
    assert result.passed is False


# --- 只选品牌 ---


@pytest.mark.asyncio
async def test_brand_only_pass_ignores_other_brands() -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.ROYAL, material_type=MaterialType.HANGING_FLAG, confidence=0.9),
        DetectedMaterial(brand=Brand.YUANYUE, material_type=MaterialType.LIGHTBOX, confidence=0.92),
    )
    result = await _review(vision, expected_brand=Brand.ROYAL)
    assert result.status == "passed"
    assert result.passed is True


@pytest.mark.asyncio
async def test_brand_only_reject_when_absent() -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.YUANYUE, material_type=MaterialType.LIGHTBOX, confidence=0.92),
    )
    result = await _review(vision, expected_brand=Brand.ROYAL)
    assert result.status == "rejected"


# --- 只选类型 ---


@pytest.mark.asyncio
async def test_type_only_pass_ignores_other_types() -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.ROYAL, material_type=MaterialType.EMBEDDED_CABINET, confidence=0.9),
        DetectedMaterial(brand=Brand.ROYAL, material_type=MaterialType.LIGHTBOX, confidence=0.85),
    )
    result = await _review(vision, expected_material_type=MaterialType.EMBEDDED_CABINET)
    assert result.status == "passed"
    assert result.passed is True


# --- 两项都不选：识别模式 ---


@pytest.mark.asyncio
async def test_recognition_single_reliable() -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.ROYAL, material_type=MaterialType.LIGHTBOX, confidence=0.9),
    )
    result = await _review(vision)
    assert result.mode == "recognition"
    assert result.status == "recognized"
    assert result.passed is None


@pytest.mark.asyncio
async def test_recognition_multiple_combos() -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.ROYAL, material_type=MaterialType.LIGHTBOX, confidence=0.9),
        DetectedMaterial(brand=Brand.ZUNYUE, material_type=MaterialType.LIGHTBOX, confidence=0.88),
    )
    result = await _review(vision)
    assert result.mode == "recognition"
    assert result.status == "recognized"
    assert result.passed is None
    combos = {(d.brand, d.material_type) for d in result.detections}
    assert (Brand.ROYAL, MaterialType.LIGHTBOX) in combos
    assert (Brand.ZUNYUE, MaterialType.LIGHTBOX) in combos


@pytest.mark.asyncio
async def test_recognition_zero_reliable_manual_review() -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.ROYAL, material_type=MaterialType.LIGHTBOX, confidence=0.3),
    )
    result = await _review(vision)
    assert result.mode == "recognition"
    assert result.status == "manual_review"
    assert result.passed is None


@pytest.mark.asyncio
async def test_recognition_empty_detections_manual_review() -> None:
    result = await _review(_vision())
    assert result.mode == "recognition"
    assert result.status == "manual_review"
    assert result.passed is None
    assert result.detections == []


# --- 主结果兼容字段 ---


@pytest.mark.asyncio
async def test_main_result_is_highest_confidence() -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.ROYAL, material_type=MaterialType.LIGHTBOX, confidence=0.7),
        DetectedMaterial(brand=Brand.ZUNYUE, material_type=MaterialType.HANGING_FLAG, confidence=0.95),
    )
    result = await _review(vision)
    assert result.detected_brand == Brand.ZUNYUE
    assert result.detected_material_type == MaterialType.HANGING_FLAG
    assert result.confidence == pytest.approx(0.95)
    # 主结果不替代完整列表。
    assert len(result.detections) == 2


# --- 多组合去重 ---


def test_provider_dedupes_by_brand_and_type() -> None:
    provider = OpenAICompatibleProvider(Settings())
    parsed = {
        "detections": [
            {"brand": "皇家", "material_type": "灯箱", "confidence": 0.6, "evidence": ["a"]},
            {"brand": "皇家", "material_type": "灯箱", "confidence": 0.85, "evidence": ["a", "b"]},
            {"brand": "尊悦", "material_type": "灯箱", "confidence": 0.7},
        ]
    }
    result = provider._build_result(parsed)
    combos = [(d.brand, d.material_type) for d in result.detections]
    assert combos.count((Brand.ROYAL, MaterialType.LIGHTBOX)) == 1
    royal = next(d for d in result.detections if d.brand == Brand.ROYAL)
    # 去重保留置信度更高、证据更完整的一项。
    assert royal.confidence == pytest.approx(0.85)
    assert len(royal.evidence) == 2


def test_provider_normalizes_column_wrap_and_embedded_cabinet() -> None:
    provider = OpenAICompatibleProvider(Settings())
    parsed = {
        "detections": [
            {"brand": "源悦", "material_type": "包柱", "confidence": 0.8},
            {"brand": "皇家", "material_type": "陈列柜", "confidence": 0.8},
        ]
    }
    result = provider._build_result(parsed)
    types = {d.material_type for d in result.detections}
    assert MaterialType.COLUMN_WRAP in types
    assert MaterialType.EMBEDDED_CABINET in types


def test_provider_drops_invalid_enums_and_partial_items() -> None:
    provider = OpenAICompatibleProvider(Settings())
    parsed = {
        "detections": [
            {"brand": "外星品牌", "material_type": "灯箱", "confidence": 0.9},
            {"brand": "皇家", "material_type": "不存在类型", "confidence": 0.9},
            "not-a-dict",
        ]
    }
    result = provider._build_result(parsed)
    # 非法枚举被降为 None，不会伪造成合法组合。
    for d in result.detections:
        if d.brand is None:
            assert d.material_type == MaterialType.LIGHTBOX
        if d.material_type is None:
            assert d.brand == Brand.ROYAL


def test_provider_backward_compatible_single_object() -> None:
    provider = OpenAICompatibleProvider(Settings())
    parsed = {"brand": "皇家", "material_type": "灯箱", "confidence": 0.9}
    result = provider._build_result(parsed)
    assert len(result.detections) == 1
    assert result.detections[0].brand == Brand.ROYAL


def test_provider_max_detections_capped() -> None:
    provider = OpenAICompatibleProvider(Settings())
    detections = [
        {"brand": "皇家", "material_type": "灯箱", "confidence": 0.5, "region": str(i)}
        for i in range(20)
    ]
    # 全部同组合，去重后应仅剩 1。
    result = provider._build_result({"detections": detections})
    assert len(result.detections) == 1


# --- 同图“皇家-灯箱、尊悦-灯箱”多组合案例 ---


@pytest.mark.asyncio
async def test_same_image_royal_and_zunyue_lightbox_recognition() -> None:
    vision = _vision(
        DetectedMaterial(brand=Brand.ROYAL, material_type=MaterialType.LIGHTBOX, confidence=0.9,
                         region="画面左侧"),
        DetectedMaterial(brand=Brand.ZUNYUE, material_type=MaterialType.LIGHTBOX, confidence=0.87,
                         region="画面右侧"),
    )
    result = await _review(vision)
    assert result.status == "recognized"
    described = {(d.brand, d.material_type) for d in result.detections if d.reliable}
    assert (Brand.ROYAL, MaterialType.LIGHTBOX) in described
    assert (Brand.ZUNYUE, MaterialType.LIGHTBOX) in described


# --- 嵌柜类型是合法枚举 ---


def test_embedded_cabinet_is_valid_material_type() -> None:
    assert MaterialType("嵌柜") == MaterialType.EMBEDDED_CABINET
    assert MaterialType.EMBEDDED_CABINET.value == "嵌柜"
