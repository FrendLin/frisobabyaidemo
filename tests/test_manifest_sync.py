from __future__ import annotations

from pathlib import Path

from app.labeling import LabelRecord
from app.manifest_sync import sync_labels_to_manifest


MANIFEST = (
    "sample_id,brand,material_type,image_url,split\n"
    "MS-0001,皇家,包柱画面,https://static.51dh.com.cn/a.jpg,train\n"
    "MS-0002,旺玥,灯箱,https://static.51dh.com.cn/b.jpg,test\n"
)


def _write_manifest(path: Path) -> None:
    path.write_text(MANIFEST, encoding="utf-8-sig")


def _read_rows(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open(encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def test_sync_updates_matching_url(tmp_path: Path) -> None:
    manifest = tmp_path / "m.csv"
    _write_manifest(manifest)
    records = [
        LabelRecord(
            relpath="a.jpg",
            brand="皇家",
            material_type="灯箱",  # 与清单里的“包柱画面”不同 → 应更新
            manifest_url="https://static.51dh.com.cn/a.jpg",
        )
    ]
    result = sync_labels_to_manifest(manifest, records)
    assert result.updated == 1
    rows = _read_rows(manifest)
    row = next(r for r in rows if r["image_url"].endswith("a.jpg"))
    assert row["material_type"] == "灯箱"
    assert row["split"] == "train"  # split 不变


def test_sync_skips_non_royal_brand(tmp_path: Path) -> None:
    manifest = tmp_path / "m.csv"
    _write_manifest(manifest)
    records = [
        LabelRecord(
            relpath="x.jpg",
            brand="爱他美",
            material_type="灯箱",
            manifest_url="https://static.51dh.com.cn/a.jpg",
        )
    ]
    result = sync_labels_to_manifest(manifest, records)
    assert result.skipped_non_royal == 1
    assert result.updated == 0


def test_sync_skips_incomplete(tmp_path: Path) -> None:
    manifest = tmp_path / "m.csv"
    _write_manifest(manifest)
    records = [
        LabelRecord(
            relpath="a.jpg",
            brand="皇家",
            material_type=None,
            manifest_url="https://static.51dh.com.cn/a.jpg",
        )
    ]
    result = sync_labels_to_manifest(manifest, records)
    assert result.skipped_incomplete == 1


def test_sync_unmatched_without_append(tmp_path: Path) -> None:
    manifest = tmp_path / "m.csv"
    _write_manifest(manifest)
    records = [
        LabelRecord(
            relpath="new.jpg",
            brand="皇家",
            material_type="灯箱",
            manifest_url="https://static.51dh.com.cn/new.jpg",
        )
    ]
    result = sync_labels_to_manifest(manifest, records, append_missing=False)
    assert result.unmatched_urls == ["https://static.51dh.com.cn/new.jpg"]
    assert len(_read_rows(manifest)) == 2


def test_sync_appends_when_requested(tmp_path: Path) -> None:
    manifest = tmp_path / "m.csv"
    _write_manifest(manifest)
    records = [
        LabelRecord(
            relpath="new.jpg",
            brand="源悦",
            material_type="吊旗",
            manifest_url="https://static.51dh.com.cn/new.jpg",
        )
    ]
    result = sync_labels_to_manifest(manifest, records, append_missing=True)
    assert result.appended == 1
    rows = _read_rows(manifest)
    assert len(rows) == 3
    new_row = next(r for r in rows if r["image_url"].endswith("new.jpg"))
    assert new_row["sample_id"] == "MS-0003"
    assert new_row["brand"] == "源悦"
