from __future__ import annotations

from pathlib import Path

import pytest

from app import labeling
from app.labeling import LabelingError, LabelStore


def _touch(path: Path, data: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_scan_ignores_non_images_and_sorts(tmp_path: Path) -> None:
    _touch(tmp_path / "b.jpg")
    _touch(tmp_path / "a.png")
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "sub" / "c.webp")
    items = labeling.scan_directory(tmp_path)
    assert [item.relpath for item in items] == ["a.png", "b.jpg", "sub/c.webp"]


def test_scan_empty_directory(tmp_path: Path) -> None:
    assert labeling.scan_directory(tmp_path) == []


def test_duplicate_names_detected(tmp_path: Path) -> None:
    _touch(tmp_path / "dup.jpg")
    _touch(tmp_path / "sub" / "dup.jpg")
    items = labeling.scan_directory(tmp_path)
    dups = labeling.find_duplicate_names(items)
    assert dups["dup.jpg"] == ["dup.jpg", "sub/dup.jpg"]


def test_resolve_directory_rejects_missing(tmp_path: Path) -> None:
    with pytest.raises(LabelingError):
        labeling.resolve_directory(str(tmp_path / "nope"))


def test_resolve_directory_rejects_file(tmp_path: Path) -> None:
    target = tmp_path / "file.jpg"
    _touch(target)
    with pytest.raises(LabelingError):
        labeling.resolve_directory(str(target))


def test_resolve_directory_rejects_empty() -> None:
    with pytest.raises(LabelingError):
        labeling.resolve_directory("   ")


def test_resolve_image_within_blocks_traversal(tmp_path: Path) -> None:
    _touch(tmp_path / "ok.jpg")
    with pytest.raises(LabelingError):
        labeling.resolve_image_within(tmp_path, "../../etc/passwd")
    with pytest.raises(LabelingError):
        labeling.resolve_image_within(tmp_path, "/etc/passwd")


def test_resolve_image_within_missing_file(tmp_path: Path) -> None:
    with pytest.raises(LabelingError):
        labeling.resolve_image_within(tmp_path, "ghost.jpg")


def test_label_store_save_and_restore(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _touch(images / "a.jpg")
    store = LabelStore(tmp_path / "store")
    store.set_label(
        images, "a.jpg", brand="皇家", material_type="灯箱", manifest_url=None, now="2026-07-25T00:00:00Z"
    )
    # 用新实例模拟重启后恢复。
    reopened = LabelStore(tmp_path / "store")
    records = reopened.load(images)
    assert records["a.jpg"].brand == "皇家"
    assert records["a.jpg"].material_type == "灯箱"
    assert records["a.jpg"].labeled


def test_label_store_update_overwrites(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _touch(images / "a.jpg")
    store = LabelStore(tmp_path / "store")
    store.set_label(images, "a.jpg", brand="皇家", material_type="灯箱", manifest_url=None, now="t1")
    store.set_label(images, "a.jpg", brand="旺玥", material_type="吊旗", manifest_url=None, now="t2")
    records = store.load(images)
    assert records["a.jpg"].brand == "旺玥"
    assert records["a.jpg"].material_type == "吊旗"


def test_label_store_rejects_unknown_values(tmp_path: Path) -> None:
    store = LabelStore(tmp_path / "store")
    with pytest.raises(LabelingError):
        store.set_label(tmp_path, "a.jpg", brand="不存在", material_type="灯箱", manifest_url=None, now="t")
    with pytest.raises(LabelingError):
        store.set_label(tmp_path, "a.jpg", brand="皇家", material_type="不存在", manifest_url=None, now="t")


def test_common_brand_allowed(tmp_path: Path) -> None:
    images = tmp_path / "images"
    _touch(images / "a.jpg")
    store = LabelStore(tmp_path / "store")
    record = store.set_label(
        images, "a.jpg", brand="爱他美", material_type="吊旗", manifest_url=None, now="t"
    )
    assert record.brand == "爱他美"


def test_filter_and_progress(tmp_path: Path) -> None:
    _touch(tmp_path / "a.jpg")
    _touch(tmp_path / "b.jpg")
    items = labeling.scan_directory(tmp_path)
    store = LabelStore(tmp_path / "store")
    store.set_label(tmp_path, "a.jpg", brand="皇家", material_type="灯箱", manifest_url=None, now="t")
    merged = labeling.merge_items_with_labels(items, store.load(tmp_path))

    prog = labeling.progress(merged)
    assert prog == {"total": 2, "labeled": 1, "unlabeled": 1}

    labeled = labeling.filter_records(merged, mode="labeled")
    assert [row["relpath"] for row in labeled] == ["a.jpg"]
    unlabeled = labeling.filter_records(merged, mode="unlabeled")
    assert [row["relpath"] for row in unlabeled] == ["b.jpg"]
    by_brand = labeling.filter_records(merged, brand="皇家")
    assert [row["relpath"] for row in by_brand] == ["a.jpg"]
    by_material = labeling.filter_records(merged, material_type="吊旗")
    assert by_material == []


def test_export_csv_and_json(tmp_path: Path) -> None:
    _touch(tmp_path / "a.jpg")
    items = labeling.scan_directory(tmp_path)
    store = LabelStore(tmp_path / "store")
    store.set_label(tmp_path, "a.jpg", brand="皇家", material_type="灯箱", manifest_url=None, now="t")
    merged = labeling.merge_items_with_labels(items, store.load(tmp_path))

    csv_bytes = labeling.export_csv(merged)
    text = csv_bytes.decode("utf-8-sig")
    assert "relpath,name,brand,material_type,manifest_url,updated_at" in text
    assert "皇家" in text and "灯箱" in text

    json_bytes = labeling.export_json(tmp_path, merged)
    assert b"\"count\": 1" in json_bytes
