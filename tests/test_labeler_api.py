from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import labeling
from app.config import Settings
from app.main import create_app


def _make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        labeling_data_dir=str(tmp_path / "store"),
        labeling_manifest=str(tmp_path / "m.csv"),
    )
    return TestClient(create_app(settings))


def _make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (100, 100), "#123456")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    path.write_bytes(buffer.getvalue())


def test_labeler_page_served(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    response = client.get("/labeler")
    assert response.status_code == 200
    assert "图片标注" in response.text


def test_labeler_config_lists_brands_and_materials(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    data = client.get("/api/labeler/config").json()
    groups = {g["group"] for g in data["brand_catalog"]}
    assert "皇家美素" in groups
    assert "灯箱" in data["material_types"]
    assert len(data["material_types"]) == 6


def test_pick_directory_returns_absolute_path(
    tmp_path: Path, monkeypatch
) -> None:
    images = tmp_path / "负样本其他奶粉物料"
    images.mkdir()
    monkeypatch.setattr(labeling, "pick_directory_native", lambda: images.resolve())
    client = _make_client(tmp_path)

    response = client.post("/api/labeler/pick-directory")

    assert response.status_code == 200
    assert response.json() == {
        "cancelled": False,
        "directory": str(images.resolve()),
    }


def test_pick_directory_handles_cancel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(labeling, "pick_directory_native", lambda: None)
    client = _make_client(tmp_path)

    response = client.post("/api/labeler/pick-directory")

    assert response.status_code == 200
    assert response.json() == {"cancelled": True, "directory": None}


def test_scan_label_filter_export_flow(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _make_image(images / "a.jpg")
    _make_image(images / "b.jpg")
    client = _make_client(tmp_path)

    scan = client.get("/api/labeler/scan", params={"directory": str(images)}).json()
    assert scan["progress"] == {"total": 2, "labeled": 0, "unlabeled": 2}

    saved = client.post(
        "/api/labeler/label",
        json={
            "directory": str(images),
            "relpath": "a.jpg",
            "brand": "皇家",
            "material_type": "灯箱",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["record"]["brand"] == "皇家"

    # 重新扫描应恢复标注（持久化）。
    rescan = client.get("/api/labeler/scan", params={"directory": str(images)}).json()
    assert rescan["progress"]["labeled"] == 1

    # 图片可访问。
    img = client.get(
        "/api/labeler/image", params={"directory": str(images), "relpath": "a.jpg"}
    )
    assert img.status_code == 200

    # 导出 CSV 只含已标注。
    export = client.get(
        "/api/labeler/export",
        params={"directory": str(images), "fmt": "csv", "mode": "labeled"},
    )
    assert export.status_code == 200
    body = export.content.decode("utf-8-sig")
    assert "a.jpg" in body and "b.jpg" not in body


def test_scan_rejects_bad_directory(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    response = client.get(
        "/api/labeler/scan", params={"directory": str(tmp_path / "nope")}
    )
    assert response.status_code == 422


def test_image_rejects_traversal(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _make_image(images / "a.jpg")
    client = _make_client(tmp_path)
    response = client.get(
        "/api/labeler/image",
        params={"directory": str(images), "relpath": "../../etc/passwd"},
    )
    assert response.status_code == 422


def test_sync_manifest_endpoint(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _make_image(images / "a.jpg")
    manifest = tmp_path / "m.csv"
    manifest.write_text(
        "sample_id,brand,material_type,image_url,split\n"
        "MS-0001,皇家,包柱画面,https://static.51dh.com.cn/a.jpg,train\n",
        encoding="utf-8-sig",
    )
    client = _make_client(tmp_path)
    client.post(
        "/api/labeler/label",
        json={
            "directory": str(images),
            "relpath": "a.jpg",
            "brand": "皇家",
            "material_type": "灯箱",
            "manifest_url": "https://static.51dh.com.cn/a.jpg",
        },
    )
    response = client.post(
        "/api/labeler/sync-manifest", json={"directory": str(images)}
    )
    assert response.status_code == 200
    assert response.json()["result"]["updated"] == 1
