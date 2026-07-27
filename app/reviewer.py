from __future__ import annotations

from app.config import Settings
from app.domain import Brand, MaterialType
from app.image_quality import ImagePublisher, ImageQualityChecker
from app.models import ReviewDecision
from app.providers.base import VisionProvider
from app.quality import inspect_quality


class MaterialReviewer:
    def __init__(
        self,
        provider: VisionProvider,
        settings: Settings,
        *,
        quality_checker: ImageQualityChecker | None = None,
        image_publisher: ImagePublisher | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.quality_checker = quality_checker
        self.image_publisher = image_publisher

    async def review(
        self,
        *,
        expected_brand: Brand,
        expected_material_type: MaterialType,
        image_bytes: bytes,
        mime_type: str,
        check_image_quality: bool = False,
        image_url: str | None = None,
    ) -> ReviewDecision:
        quality = inspect_quality(image_bytes)
        external_quality = None
        if check_image_quality:
            if self.quality_checker is None:
                raise RuntimeError("图片质量检查服务不可用")
            quality_url = image_url
            if not quality_url:
                if self.image_publisher is None:
                    raise RuntimeError("图片质量检查缺少图片 URL 发布服务")
                quality_url = await self.image_publisher.publish(image_bytes, mime_type)
            external_quality = await self.quality_checker.inspect(quality_url)
        detected = await self.provider.analyze(image_bytes, mime_type)

        reasons: list[str] = []
        if detected.brand is None:
            reasons.append("无法从图片中确认品牌")
        elif detected.brand != expected_brand:
            reasons.append(
                f"品牌不匹配：期望 {expected_brand.value}，识别为 {detected.brand.value}"
            )

        if detected.material_type is None:
            reasons.append("无法从图片中确认物料类型")
        elif detected.material_type != expected_material_type:
            reasons.append(
                "物料类型不匹配："
                f"期望 {expected_material_type.value}，识别为 {detected.material_type.value}"
            )

        if detected.confidence < self.settings.min_confidence:
            reasons.append(
                f"识别置信度 {detected.confidence:.0%} 低于"
                f" {self.settings.min_confidence:.0%}，需人工复核"
            )

        fully_matched = (
            detected.brand == expected_brand
            and detected.material_type == expected_material_type
        )
        if not fully_matched and detected.brand is not None and detected.material_type is not None:
            status = "rejected"
        elif fully_matched and detected.confidence >= self.settings.min_confidence:
            status = "passed"
            reasons.append("品牌与物料类型均与上传分组一致")
        else:
            status = "manual_review"

        if external_quality is not None and not external_quality.acceptable:
            reasons.append(
                f"图片质量检查结果为“{external_quality.description}”，需人工复核"
            )
            if status == "passed":
                status = "manual_review"

        merged_warnings = list(dict.fromkeys([*quality.warnings, *detected.warnings]))
        quality = quality.model_copy(update={"warnings": merged_warnings})
        return ReviewDecision(
            status=status,
            passed=status == "passed",
            expected_brand=expected_brand,
            expected_material_type=expected_material_type,
            detected_brand=detected.brand,
            detected_material_type=detected.material_type,
            confidence=detected.confidence,
            reasons=reasons,
            evidence=detected.evidence,
            quality=quality,
            quality_check=external_quality,
            provider=self.provider.name,
        )
