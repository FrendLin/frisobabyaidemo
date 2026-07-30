from __future__ import annotations

from app.config import Settings
from app.domain import Brand, MaterialType
from app.image_quality import ImagePublisher, ImageQualityChecker
from app.models import MaterialDetection, ReviewDecision
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
        expected_brand: Brand | None = None,
        expected_material_type: MaterialType | None = None,
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

        vision = await self.provider.analyze(image_bytes, mime_type)

        # 任一条件有值即为审核模式；两项均空为纯识别模式。
        mode = "recognition" if expected_brand is None and expected_material_type is None else "review"
        threshold = self.settings.min_confidence

        detections: list[MaterialDetection] = []
        for item in vision.detections:
            reliable = item.confidence >= threshold and (
                item.brand is not None or item.material_type is not None
            )
            matches = None
            if mode == "review":
                matches = self._matches_selection(
                    item.brand,
                    item.material_type,
                    expected_brand,
                    expected_material_type,
                )
            detections.append(
                MaterialDetection(
                    brand=item.brand,
                    material_type=item.material_type,
                    confidence=item.confidence,
                    evidence=item.evidence,
                    region=item.region,
                    reliable=reliable,
                    matches_selection=matches,
                )
            )

        reliable_items = [d for d in detections if d.reliable]

        if mode == "review":
            status, passed, reasons = self._review_status(
                detections=detections,
                reliable_items=reliable_items,
                expected_brand=expected_brand,
                expected_material_type=expected_material_type,
            )
        else:
            status, passed, reasons = self._recognition_status(reliable_items)

        # 主结果：去重后置信度最高项，兼容旧调用方，不替代完整列表。
        main = max(detections, key=lambda d: d.confidence, default=None)
        detected_brand = main.brand if main else None
        detected_material_type = main.material_type if main else None
        main_confidence = main.confidence if main else 0.0

        aggregated_evidence: list[str] = []
        for item in detections:
            for text in item.evidence:
                if text not in aggregated_evidence:
                    aggregated_evidence.append(text)

        if external_quality is not None and not external_quality.acceptable:
            quality_reasons = []
            if external_quality.blur_description == "模糊":
                quality_reasons.append("模糊程度为“模糊”")
            if external_quality.brightness_description not in {None, "正常"}:
                quality_reasons.append(
                    f"明亮度为“{external_quality.brightness_description}”"
                )
            detail = "、".join(quality_reasons) or (
                f"接口描述为“{external_quality.description}”"
            )
            reasons.append(f"图片质量检查未通过（{detail}），需人工复核")
            if status in {"passed", "recognized"}:
                status = "manual_review"
                if mode == "review":
                    passed = False

        merged_warnings = list(dict.fromkeys([*quality.warnings, *vision.warnings]))
        quality = quality.model_copy(update={"warnings": merged_warnings})
        return ReviewDecision(
            mode=mode,
            status=status,
            passed=passed,
            expected_brand=expected_brand,
            expected_material_type=expected_material_type,
            detections=detections,
            detected_brand=detected_brand,
            detected_material_type=detected_material_type,
            confidence=main_confidence,
            reasons=reasons,
            evidence=aggregated_evidence[:8],
            quality=quality,
            quality_check=external_quality,
            provider=self.provider.name,
        )

    @staticmethod
    def _matches_selection(
        brand: Brand | None,
        material_type: MaterialType | None,
        expected_brand: Brand | None,
        expected_material_type: MaterialType | None,
    ) -> bool:
        if expected_brand is not None and brand != expected_brand:
            return False
        if expected_material_type is not None and material_type != expected_material_type:
            return False
        return True

    def _review_status(
        self,
        *,
        detections: list[MaterialDetection],
        reliable_items: list[MaterialDetection],
        expected_brand: Brand | None,
        expected_material_type: MaterialType | None,
    ) -> tuple[str, bool, list[str]]:
        selected_parts = []
        if expected_brand is not None:
            selected_parts.append(f"品牌 {expected_brand.value}")
        if expected_material_type is not None:
            selected_parts.append(f"物料类型 {expected_material_type.value}")
        selected_desc = "、".join(selected_parts)

        matched = [d for d in reliable_items if d.matches_selection]
        if matched:
            return (
                "passed",
                True,
                [f"识别到达到阈值且匹配所选{selected_desc}的组合，审核通过"],
            )
        if reliable_items:
            found = "、".join(
                self._describe(d) for d in reliable_items[:5]
            )
            return (
                "rejected",
                False,
                [f"识别到可靠组合（{found}），但没有匹配所选{selected_desc}的项，审核驳回"],
            )
        reasons = []
        if not detections:
            reasons.append("未识别到可归属的大型品牌物料，证据不足，转人工复核")
        else:
            reasons.append(
                f"识别置信度均低于 {self.settings.min_confidence:.0%}，证据不足，转人工复核"
            )
        return "manual_review", False, reasons

    def _recognition_status(
        self, reliable_items: list[MaterialDetection]
    ) -> tuple[str, None, list[str]]:
        if reliable_items:
            found = "、".join(self._describe(d) for d in reliable_items[:5])
            return "recognized", None, [f"识别到可靠组合：{found}"]
        return (
            "manual_review",
            None,
            ["未识别到达到阈值的可靠组合，转人工复核"],
        )

    @staticmethod
    def _describe(detection: MaterialDetection) -> str:
        brand = detection.brand.value if detection.brand else "未知品牌"
        material = (
            detection.material_type.value if detection.material_type else "未知类型"
        )
        return f"{brand} · {material}"
