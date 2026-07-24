from __future__ import annotations

import base64
import json
import re
from typing import Any

import httpx

from app.config import Settings
from app.domain import Brand, MATERIAL_RULES, MaterialType
from app.models import DetectedMaterial
from app.providers.base import ProviderError, VisionProvider


class OpenAICompatibleProvider(VisionProvider):
    name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def analyze(self, image_bytes: bytes, mime_type: str) -> DetectedMaterial:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime_type};base64,{encoded}"
        endpoint = f'{self.settings.vision_base_url.rstrip("/")}/chat/completions'
        payload = {
            "model": self.settings.vision_model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是线下母婴门店大型品牌物料审核员。只根据图片可见证据判断，"
                        "不确定时返回 null，禁止猜测。输出必须是一个 JSON 对象。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._prompt()},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.settings.vision_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    block.get("text", "") for block in content if isinstance(block, dict)
                )
            parsed = self._parse_json(str(content))
            return DetectedMaterial(
                brand=self._normalize_brand(parsed.get("brand")),
                material_type=self._normalize_type(parsed.get("material_type")),
                confidence=float(parsed.get("confidence", 0)),
                evidence=self._as_text_list(parsed.get("evidence")),
                warnings=self._as_text_list(parsed.get("warnings")),
                rationale=str(parsed.get("rationale", "")),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProviderError(f"视觉识别服务调用失败：{error}") from error

    @staticmethod
    def _as_text_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item)[:300] for item in value[:8]]

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        cleaned = content.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        if not cleaned.startswith("{"):
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if not match:
                raise json.JSONDecodeError("No JSON object", cleaned, 0)
            cleaned = match.group(0)
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise TypeError("Model response is not an object")
        return parsed

    @staticmethod
    def _normalize_brand(value: Any) -> Brand | None:
        if value is None:
            return None
        text = str(value).strip()
        aliases = {
            "皇家美素佳儿": Brand.ROYAL,
            "皇家美素力": Brand.ROYAL,
            "Friso Prestige": Brand.ROYAL,
        }
        if text in aliases:
            return aliases[text]
        try:
            return Brand(text)
        except ValueError:
            return None

    @staticmethod
    def _normalize_type(value: Any) -> MaterialType | None:
        if value is None:
            return None
        text = str(value).strip()
        aliases = {
            "包柱": MaterialType.COLUMN_WRAP,
            "橱窗单透": MaterialType.WINDOW_OR_WALL,
            "墙贴": MaterialType.WINDOW_OR_WALL,
            "店招": MaterialType.EXTERIOR,
            "外立面广告": MaterialType.EXTERIOR,
            "店内海报": MaterialType.IN_STORE_POSTER,
        }
        if text in aliases:
            return aliases[text]
        try:
            return MaterialType(text)
        except ValueError:
            return None

    @staticmethod
    def _prompt() -> str:
        rules = "\n".join(
            f"- {material_type.value}：" + "；".join(items)
            for material_type, items in MATERIAL_RULES.items()
        )
        brands = "、".join(brand.value for brand in Brand)
        material_types = "、".join(item.value for item in MaterialType)
        return f"""
任务：识别图片中的美素佳儿子品牌与大型物料类型。

候选品牌仅限：{brands}。
候选物料类型仅限：{material_types}。

物料判定规则：
{rules}

品牌必须由图片中可见的品牌名、产品罐体、主视觉或明确品牌资产确认。
场景、位置与物料结构是类型判断的必要证据；不要只按海报颜色判断。

仅返回以下 JSON：
{{
  "brand": "候选品牌之一或 null",
  "material_type": "候选物料类型之一或 null",
  "confidence": 0.0,
  "evidence": ["最多 5 条图片可见证据"],
  "warnings": ["昏暗、过曝、模糊、遮挡等"],
  "rationale": "不超过 120 字"
}}
""".strip()

