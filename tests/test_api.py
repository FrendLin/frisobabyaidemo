from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain import Brand, MaterialType
from app.main import create_app
from app.models import DetectedMaterial, ExternalImageQuality
from conftest import FakeProvider


def test_single_image_endpoint(image_bytes: bytes) -> None:
    provider = FakeProvider(
        DetectedMaterial(
            brand=Brand.ROYAL,
            material_type=MaterialType.HANGING_FLAG,
            confidence=0.96,
            evidence=["多张画面悬挂在天花板下"],
        )
    )
    client = TestClient(create_app(Settings(), provider))
    response = client.post(
        "/api/review",
        data={"brand": "皇家", "material_type": "吊旗"},
        files={"image": ("store.jpg", image_bytes, "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "passed"


def test_single_image_quality_toggle_uses_publisher_and_checker(
    image_bytes: bytes,
) -> None:
    provider = FakeProvider(
        DetectedMaterial(
            brand=Brand.ROYAL,
            material_type=MaterialType.LIGHTBOX,
            confidence=0.96,
        )
    )

    class FakePublisher:
        called = False

        async def publish(self, payload: bytes, mime_type: str) -> str:
            assert payload == image_bytes
            assert mime_type == "image/jpeg"
            self.called = True
            return "https://signed.example/image.jpg"

    class FakeQualityChecker:
        called_url = ""

        async def inspect(self, image_url: str) -> ExternalImageQuality:
            self.called_url = image_url
            return ExternalImageQuality(
                acceptable=False,
                description="中",
                blur=99.26,
            )

    publisher = FakePublisher()
    checker = FakeQualityChecker()
    client = TestClient(
        create_app(
            Settings(),
            provider,
            quality_checker=checker,
            image_publisher=publisher,
        )
    )

    response = client.post(
        "/api/review",
        data={
            "brand": "皇家",
            "material_type": "灯箱",
            "quality_check": "true",
        },
        files={"image": ("store.jpg", image_bytes, "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "manual_review"
    assert response.json()["quality_check"]["description"] == "中"
    assert publisher.called is True
    assert checker.called_url == "https://signed.example/image.jpg"


def test_missing_model_fails_closed(image_bytes: bytes) -> None:
    client = TestClient(create_app(Settings(vision_api_key="", vision_model="")))
    response = client.post(
        "/api/review",
        data={"brand": "皇家", "material_type": "灯箱"},
        files={"image": ("store.jpg", image_bytes, "image/jpeg")},
    )
    assert response.status_code == 503
    assert "不会在无模型时默认通过" in response.json()["detail"]


def test_template_download() -> None:
    client = TestClient(create_app(Settings()))
    response = client.get("/api/batch/template")
    assert response.status_code == 200
    assert response.content.startswith(b"PK")


def test_home_page_has_quality_toggle_without_evidence_sections() -> None:
    client = TestClient(create_app(Settings(), FakeProvider(DetectedMaterial(confidence=0))))

    response = client.get("/")

    assert response.status_code == 200
    assert "是否进行图片质量检查" in response.text
    assert "置信度与图片证据" not in response.text
