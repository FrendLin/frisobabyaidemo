from __future__ import annotations

import json

from app.config import Settings
from app.domain import Brand, MaterialType
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.training import TrainingExample


def test_responses_request_and_content() -> None:
    provider = OpenAICompatibleProvider(
        Settings(
            vision_base_url="https://example.test/api/v3/responses",
            vision_api_style="auto",
            vision_model="vision-model",
        )
    )

    endpoint, payload = provider._build_request("data:image/jpeg;base64,abc")

    assert endpoint == "https://example.test/api/v3/responses"
    assert payload["model"] == "vision-model"
    assert payload["store"] is False
    assert payload["input"][0]["content"][1] == {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64,abc",
    }
    content = provider._extract_content(
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "brand": "皇家",
                                    "material_type": "灯箱",
                                    "confidence": 0.9,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ],
                }
            ]
        }
    )
    assert json.loads(content)["brand"] == "皇家"


def test_chat_completions_request_stays_compatible() -> None:
    provider = OpenAICompatibleProvider(
        Settings(
            vision_base_url="https://example.test/v1",
            vision_api_style="chat_completions",
            vision_model="vision-model",
        )
    )

    endpoint, payload = provider._build_request("data:image/jpeg;base64,abc")

    assert endpoint == "https://example.test/v1/chat/completions"
    assert payload["messages"][1]["content"][1]["type"] == "image_url"


def test_responses_request_includes_labeled_training_prototype() -> None:
    provider = OpenAICompatibleProvider(
        Settings(
            vision_base_url="https://example.test/api/v3/responses",
            vision_model="vision-model",
        ),
        [
            TrainingExample(
                sample_id="MS-0001",
                brand=Brand.ROYAL,
                material_type=MaterialType.LIGHTBOX,
                image_url="https://static.51dh.com.cn/train.jpg",
            )
        ],
    )

    _, payload = provider._build_request("data:image/jpeg;base64,target")

    content = payload["input"][0]["content"]
    assert "brand=皇家；material_type=灯箱" in content[1]["text"]
    assert content[2]["image_url"].endswith("/train.jpg")
    assert content[-1]["image_url"] == "data:image/jpeg;base64,target"
