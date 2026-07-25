"""标注结果与现有 POC 数据清单（dataset_manifest.csv）的联动。

现有 POC 通过 ``app.training.load_training_examples`` 与 ``scripts/evaluate.py``
读取 ``data/dataset_manifest.csv``，其列为 ``sample_id,brand,material_type,image_url,split``。
本模块提供一个清晰、可测试的更新入口：把标注结果按 ``image_url`` 匹配写回清单，
现有流程再次读取相关图片时即使用最新的品牌与物料标签。

规则：
- 只有品牌落在审核域 ``Brand``（皇家四子品牌）内的标注才能进入清单，其余品牌
  （竞品、其他、无法判断）不属于该 POC 的识别范围，直接跳过；
- 物料类型必须是审核六类之一；
- 通过 ``manifest_url`` 精确匹配已有行的 ``image_url`` 才更新，避免误伤；
  找不到匹配时按需追加新行（``split`` 默认 train），并保证 ``sample_id`` 不冲突；
- 只更新品牌与物料两列，不改动 ``split``，不触碰原始图片。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from app.domain import Brand, MaterialType
from app.labeling import LabelRecord

MANIFEST_FIELDS = ["sample_id", "brand", "material_type", "image_url", "split"]

# 仅皇家四子品牌可进入训练/评测清单。
ROYAL_BRAND_VALUES: frozenset[str] = frozenset(brand.value for brand in Brand)
MATERIAL_VALUES: frozenset[str] = frozenset(item.value for item in MaterialType)


@dataclass(slots=True)
class SyncResult:
    updated: int = 0
    appended: int = 0
    skipped_non_royal: int = 0
    skipped_incomplete: int = 0
    unmatched_urls: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.unmatched_urls is None:
            self.unmatched_urls = []

    def as_dict(self) -> dict[str, object]:
        return {
            "updated": self.updated,
            "appended": self.appended,
            "skipped_non_royal": self.skipped_non_royal,
            "skipped_incomplete": self.skipped_incomplete,
            "unmatched_urls": self.unmatched_urls,
        }


def _read_manifest(manifest: Path) -> list[dict[str, str]]:
    if not manifest.is_file():
        return []
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _next_sample_id(rows: list[dict[str, str]]) -> int:
    highest = 0
    for row in rows:
        sid = row.get("sample_id", "")
        if sid.startswith("MS-"):
            try:
                highest = max(highest, int(sid[3:]))
            except ValueError:
                continue
    return highest + 1


def sync_labels_to_manifest(
    manifest: Path,
    records: list[LabelRecord],
    *,
    append_missing: bool = False,
    default_split: str = "train",
) -> SyncResult:
    """把标注写回清单。返回统计结果；仅在有变更时写文件。"""

    rows = _read_manifest(manifest)
    by_url: dict[str, dict[str, str]] = {}
    for row in rows:
        url = (row.get("image_url") or "").strip()
        if url:
            by_url.setdefault(url, row)

    result = SyncResult()
    next_id = _next_sample_id(rows)
    changed = False

    for record in records:
        if not record.manifest_url:
            continue
        if not (record.brand and record.material_type):
            result.skipped_incomplete += 1
            continue
        if record.brand not in ROYAL_BRAND_VALUES or record.material_type not in MATERIAL_VALUES:
            result.skipped_non_royal += 1
            continue

        url = record.manifest_url.strip()
        existing = by_url.get(url)
        if existing is not None:
            if (
                existing.get("brand") != record.brand
                or existing.get("material_type") != record.material_type
            ):
                existing["brand"] = record.brand
                existing["material_type"] = record.material_type
                result.updated += 1
                changed = True
        elif append_missing:
            row = {
                "sample_id": f"MS-{next_id:04d}",
                "brand": record.brand,
                "material_type": record.material_type,
                "image_url": url,
                "split": default_split,
            }
            rows.append(row)
            by_url[url] = row
            next_id += 1
            result.appended += 1
            changed = True
        else:
            result.unmatched_urls.append(url)

    if changed:
        _write_manifest(manifest, rows)
    return result


def _write_manifest(manifest: Path, rows: list[dict[str, str]]) -> None:
    tmp = manifest.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})
    tmp.replace(manifest)
