from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain import Brand, MaterialType


class DetectedMaterial(BaseModel):
    """单个可归属的品牌物料载体检测项。"""

    brand: Brand | None = None
    material_type: MaterialType | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list, max_length=8)
    region: str = Field(default="", max_length=200)
    rationale: str = Field(default="", max_length=1000)


class VisionResult(BaseModel):
    """视觉模型对一张图片的完整识别结果，可包含多个检测项。"""

    detections: list[DetectedMaterial] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=8)


class ImageQuality(BaseModel):
    width: int
    height: int
    brightness: float
    contrast: float
    sharpness: float
    warnings: list[str] = Field(default_factory=list)


class ExternalImageQuality(BaseModel):
    acceptable: bool
    description: str
    blur: float | None = None
    blur_description: str | None = None
    brightness: float | None = None
    brightness_description: str | None = None
    angle: float | None = None


class MaterialDetection(BaseModel):
    """审核结果中对外呈现的检测项，附带可靠性与匹配信息。"""

    brand: Brand | None = None
    material_type: MaterialType | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list, max_length=8)
    region: str = Field(default="", max_length=200)
    # 置信度是否达到阈值。
    reliable: bool = False
    # 仅审核模式有意义：该项是否匹配用户所选维度；识别模式为 None。
    matches_selection: bool | None = None


class ReviewDecision(BaseModel):
    # review：用户选择了品牌或类型中的至少一项；recognition：两项都未选。
    mode: Literal["review", "recognition"]
    # review 模式：passed / rejected / manual_review；recognition 模式：recognized / manual_review。
    status: Literal["passed", "rejected", "manual_review", "recognized"]
    # 纯识别模式下为 None，不得用 True 误导为审核通过。
    passed: bool | None = None
    expected_brand: Brand | None = None
    expected_material_type: MaterialType | None = None
    # 完整的多组合检测列表。
    detections: list[MaterialDetection] = Field(default_factory=list)
    # 兼容旧调用方的“主结果”：去重后置信度最高项，绝不替代完整列表。
    detected_brand: Brand | None = None
    detected_material_type: MaterialType | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    reasons: list[str]
    evidence: list[str]
    quality: ImageQuality
    quality_check: ExternalImageQuality | None = None
    provider: str
