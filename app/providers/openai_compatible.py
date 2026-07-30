from __future__ import annotations

import base64
import json
import re
from collections.abc import Sequence
from typing import Any

import httpx

from app.config import Settings
from app.domain import Brand, MATERIAL_RULES, MaterialType
from app.models import DetectedMaterial, VisionResult
from app.providers.base import ProviderError, VisionProvider
from app.training import TrainingExample


# 单张图片最多返回的检测项数量，避免模型返回无界列表。
MAX_DETECTIONS = 8


class OpenAICompatibleProvider(VisionProvider):
    name = "openai_compatible"

    def __init__(
        self,
        settings: Settings,
        training_examples: Sequence[TrainingExample] = (),
    ) -> None:
        self.settings = settings
        self.training_examples = tuple(training_examples)

    async def analyze(self, image_bytes: bytes, mime_type: str) -> VisionResult:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime_type};base64,{encoded}"
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                return await self._analyze_once(
                    client,
                    data_url,
                )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProviderError(f"视觉识别服务调用失败：{error}") from error

    async def _analyze_once(
        self,
        client: httpx.AsyncClient,
        data_url: str,
        *,
        training_examples: Sequence[TrainingExample] | None = None,
        calibration_brand: Brand | None = None,
    ) -> VisionResult:
        endpoint, payload = self._build_request(
            data_url,
            training_examples=training_examples,
            calibration_brand=calibration_brand,
        )
        response = await client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.settings.vision_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        parsed = self._parse_json(self._extract_content(response.json()))
        return self._build_result(parsed)

    def _build_result(self, parsed: dict[str, Any]) -> VisionResult:
        raw_items = parsed.get("detections")
        if not isinstance(raw_items, list):
            # 兼容仅返回单组合的旧模型输出。
            if parsed.get("brand") is not None or parsed.get("material_type") is not None:
                raw_items = [parsed]
            else:
                raw_items = []
        detections: list[DetectedMaterial] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            detections.append(
                DetectedMaterial(
                    brand=self._normalize_brand(item.get("brand")),
                    material_type=self._normalize_type(item.get("material_type")),
                    confidence=self._as_confidence(item.get("confidence")),
                    evidence=self._as_text_list(item.get("evidence")),
                    region=str(item.get("region", ""))[:200],
                    rationale=str(item.get("rationale", ""))[:1000],
                )
            )
        deduped = self._dedupe(detections)
        return VisionResult(
            detections=deduped,
            warnings=self._as_text_list(parsed.get("warnings")),
        )

    @staticmethod
    def _dedupe(detections: list[DetectedMaterial]) -> list[DetectedMaterial]:
        """按“品牌 + 类型”去重，保留置信度更高、证据更完整的一项。"""

        best: dict[tuple[str | None, str | None], DetectedMaterial] = {}
        for item in detections:
            key = (
                item.brand.value if item.brand else None,
                item.material_type.value if item.material_type else None,
            )
            current = best.get(key)
            if current is None:
                best[key] = item
                continue
            better = (item.confidence, len(item.evidence)) > (
                current.confidence,
                len(current.evidence),
            )
            if better:
                best[key] = item
        ordered = sorted(best.values(), key=lambda d: d.confidence, reverse=True)
        return ordered[:MAX_DETECTIONS]

    def _build_request(
        self,
        data_url: str,
        *,
        training_examples: Sequence[TrainingExample] | None = None,
        calibration_brand: Brand | None = None,
    ) -> tuple[str, dict[str, Any]]:
        base_url = self.settings.vision_base_url.rstrip("/")
        api_style = self.settings.vision_api_style
        if api_style == "auto":
            api_style = "responses" if base_url.endswith("/responses") else "chat_completions"
        if api_style == "responses":
            endpoint = base_url if base_url.endswith("/responses") else f"{base_url}/responses"
            payload = {
                "model": self.settings.vision_model,
                "temperature": 0,
                "thinking": {"type": "disabled"},
                "store": False,
                "input": [
                    {
                        "role": "user",
                        "content": self._responses_content(
                            data_url,
                            training_examples=training_examples,
                            calibration_brand=calibration_brand,
                        ),
                    }
                ],
            }
            return endpoint, payload

        if api_style != "chat_completions":
            raise ValueError(f"不支持的 VISION_API_STYLE：{api_style}")
        return (
            f"{base_url}/chat/completions",
            {
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
            },
        )

    def _extract_content(self, body: dict[str, Any]) -> str:
        api_style = self.settings.vision_api_style
        if api_style == "auto":
            api_style = (
                "responses"
                if self.settings.vision_base_url.rstrip("/").endswith("/responses")
                else "chat_completions"
            )
        if api_style == "responses":
            texts = [
                block.get("text", "")
                for item in body["output"]
                if isinstance(item, dict) and item.get("type") == "message"
                for block in item.get("content", [])
                if isinstance(block, dict) and block.get("type") == "output_text"
            ]
            if not texts:
                raise KeyError("Responses API 未返回 output_text")
            return "".join(texts)

        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            return "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        return str(content)

    def _responses_content(
        self,
        data_url: str,
        *,
        training_examples: Sequence[TrainingExample] | None = None,
        calibration_brand: Brand | None = None,
    ) -> list[dict[str, str]]:
        examples = (
            self.training_examples
            if training_examples is None
            else tuple(training_examples)
        )
        content: list[dict[str, str]] = [
            {
                "type": "input_text",
                "text": (
                    "你是线下母婴门店大型品牌物料审核员。"
                    "只根据图片可见证据判断，不确定时返回 null，禁止猜测。"
                    "输出必须是一个 JSON 对象。\n\n" + self._prompt()
                ),
            }
        ]
        if examples:
            calibrated_types = sorted(
                {example.material_type.value for example in examples}
            )
            missing_types = sorted(
                set(item.value for item in MaterialType) - set(calibrated_types)
            )
            content[0]["text"] += (
                "\n\n下面是从 80% 训练集中按联合标签抽取的人工标注原型。"
                "它们只用于学习品牌和物料标签口径，不代表待审核图片。"
                f"\n训练原型已覆盖物料类型：{'、'.join(calibrated_types)}。"
            )
            if missing_types:
                content[0]["text"] += (
                    f"\n训练原型未覆盖：{'、'.join(missing_types)}。"
                    "没有训练样本的类型不得自动输出；若图片只符合未覆盖类型，"
                    "material_type 返回 null 并交人工复核。"
                )
            if calibration_brand is not None:
                content[0]["text"] += (
                    f"\n第一阶段独立识别品牌为“{calibration_brand.value}”。"
                    "以下只提供该品牌的物料原型；仍需根据目标图片复核品牌，"
                    "重点校准物料类型。"
                )
            for index, example in enumerate(examples, start=1):
                content.extend(
                    [
                        {
                            "type": "input_text",
                            "text": (
                                f"训练原型 {index}：brand={example.brand.value}；"
                                f"material_type={example.material_type.value}"
                            ),
                        },
                        {"type": "input_image", "image_url": example.image_url},
                    ]
                )
            content.append(
                {
                    "type": "input_text",
                    "text": "训练原型结束。现在只判断下面这一张目标图片。",
                }
            )
        content.append({"type": "input_image", "image_url": data_url})
        return content

    @staticmethod
    def _as_text_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item)[:300] for item in value[:8]]

    @staticmethod
    def _as_confidence(value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0
        return min(1.0, max(0.0, score))

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
            "嵌入柜": MaterialType.EMBEDDED_CABINET,
            "陈列柜": MaterialType.EMBEDDED_CABINET,
            "陈列墙": MaterialType.EMBEDDED_CABINET,
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
任务：识别图片中所有可归属的美素佳儿子品牌大型物料载体，并逐个给出“品牌 + 物料类型”组合。

候选品牌仅限：{brands}。
候选物料类型仅限：{material_types}。

品牌判定线索（文字优先于颜色）：
- 皇家：常见 Friso PRESTIGE、皇家美素佳儿/皇家美素力、“双硬核 强内护”，白金罐体带绿色圆环。
- 旺玥：常见皇家美素佳儿旺玥、“3岁+ 超群强护 进阶成长”，暖金/米白画面。
- 源悦：常见 Friso NATURA、美素佳儿源悦、“自然源生力/5维实证”，蓝绿草地画面。
- 尊悦：常见 Friso PRESTIGE X、皇家美素佳儿尊悦、“为宝宝筑起第一道自护防线”，举起双臂的儿童；出现 X 或“尊悦”时不要判成皇家。

物料判定规则：
{rules}

识别要求：
1. 逐个识别图片中可见、可归属到候选品牌的大型物料载体（灯箱、吊旗、包柱、嵌柜、店招/外立面、橱窗/墙贴、店内海报等）。
2. 同一张图可以有多个组合，例如“皇家-灯箱”和“尊悦-灯箱”，请分别作为独立检测项返回。
3. 普通货架上的单个奶粉商品罐、竞品、背景广告不是独立的大型物料结果，不要作为检测项返回。
4. 嵌柜是整体定制/固定式品牌陈列柜（含连续货架、品牌楣头、背板/侧板、灯带等）；柜内单独的发光画面不要因此误判为“灯箱”，若目标载体覆盖完整柜体优先判嵌柜。
5. 每个检测项的品牌只依据该载体上的品牌名、罐体、主视觉或明确品牌资产判断；无法确定的字段返回 null，不要猜测。
6. 对每个检测项给出 confidence（0~1）、evidence（图片可见证据）和 region（该载体在画面中的大致位置，如“画面左侧立柱”）。

仅返回以下 JSON：
{{
  "detections": [
    {{
      "brand": "候选品牌之一或 null",
      "material_type": "候选物料类型之一或 null",
      "confidence": 0.0,
      "evidence": ["最多 5 条图片可见证据"],
      "region": "该载体在画面中的位置描述",
      "rationale": "不超过 60 字"
    }}
  ],
  "warnings": ["昏暗、过曝、模糊、遮挡等整体画质问题"]
}}
如果图片中没有可归属的大型品牌物料，detections 返回空数组 []。
""".strip()
