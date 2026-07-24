from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain import Brand, MaterialType
from app.main import create_app
from app.models import DetectedMaterial
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

