from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain import Brand, MaterialType


class DetectedMaterial(BaseModel):
    brand: Brand | None = None
    material_type: MaterialType | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list, max_length=8)
    warnings: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(default="", max_length=1000)


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
    brightness: float | None = None
    brightness_description: str | None = None
    angle: float | None = None


class ReviewDecision(BaseModel):
    status: Literal["passed", "rejected", "manual_review"]
    passed: bool
    expected_brand: Brand
    expected_material_type: MaterialType
    detected_brand: Brand | None
    detected_material_type: MaterialType | None
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    evidence: list[str]
    quality: ImageQuality
    quality_check: ExternalImageQuality | None = None
    provider: str
