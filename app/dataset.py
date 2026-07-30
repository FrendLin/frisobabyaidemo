"""版本化数据准备：把客户补充的 URL 样本规范化、校验、去重后并入清单。

设计要点：
- 历史基线（220 张，训练 176 / 测试 44）作为独立版本保留，可追溯；补充样本写入
  带版本号的独立清单，不无说明地重洗历史测试集，保证基线可比。
- 规范化同义标签：``包柱`` → ``包柱画面``（复用审核标准标签）。
- 只接受审核域 ``Brand`` 四子品牌与 ``MaterialType`` 合法类型；非法/缺失行不静默
  吞掉，统一进入错误与统计输出。
- URL 去重：既对补充集内部去重，也排除与既有清单重复的 URL。
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.domain import Brand, MaterialType

# 同义物料标签规范化：把客户写法映射到审核标准标签。
MATERIAL_ALIASES: dict[str, str] = {
    "包柱": MaterialType.COLUMN_WRAP.value,
    "橱窗单透": MaterialType.WINDOW_OR_WALL.value,
    "墙贴": MaterialType.WINDOW_OR_WALL.value,
    "店招": MaterialType.EXTERIOR.value,
    "外立面广告": MaterialType.EXTERIOR.value,
    "店内海报": MaterialType.IN_STORE_POSTER.value,
    "嵌入柜": MaterialType.EMBEDDED_CABINET.value,
}

VALID_BRANDS: frozenset[str] = frozenset(brand.value for brand in Brand)
VALID_MATERIALS: frozenset[str] = frozenset(item.value for item in MaterialType)

MANIFEST_FIELDS = ["sample_id", "brand", "material_type", "image_url", "split"]


def normalize_material(raw: str) -> str:
    """把同义物料标签规范化为审核标准标签。"""

    text = (raw or "").strip()
    return MATERIAL_ALIASES.get(text, text)


@dataclass(slots=True)
class PreparedSample:
    sample_id: str
    brand: str
    material_type: str
    image_url: str
    split: str = "train"


@dataclass(slots=True)
class RowError:
    row_number: int
    reason: str
    brand: str
    material_type: str
    image_url: str


@dataclass(slots=True)
class PrepareResult:
    version: str
    samples: list[PreparedSample] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    duplicates_within: int = 0
    duplicates_existing: int = 0
    normalized: int = 0

    def brand_counts(self) -> dict[str, int]:
        return dict(Counter(s.brand for s in self.samples))

    def material_counts(self) -> dict[str, int]:
        return dict(Counter(s.material_type for s in self.samples))

    def joint_counts(self) -> dict[tuple[str, str], int]:
        return dict(Counter((s.brand, s.material_type) for s in self.samples))


def load_existing_urls(manifest: Path) -> set[str]:
    if not manifest.is_file():
        return set()
    urls: set[str] = set()
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            url = (row.get("image_url") or "").strip()
            if url:
                urls.add(url)
    return urls


def prepare_supplement(
    rows: list[tuple[str, str, str]],
    *,
    version: str,
    existing_urls: set[str] | None = None,
    id_prefix: str = "SUP",
    default_split: str = "train",
) -> PrepareResult:
    """规范化、校验、去重补充样本。

    ``rows`` 是 ``(brand, material_type, image_url)`` 三元组列表（已过滤空行）。
    校验失败（非法品牌/类型、缺失字段、重复 URL）进入 ``errors``，不写入样本。
    """

    existing = set(existing_urls or set())
    result = PrepareResult(version=version)
    seen_urls: set[str] = set()
    next_id = 1

    for offset, (raw_brand, raw_type, raw_url) in enumerate(rows, start=2):
        brand = (raw_brand or "").strip()
        url = (raw_url or "").strip()
        original_type = (raw_type or "").strip()
        material = normalize_material(original_type)

        if not brand or not original_type or not url:
            result.errors.append(
                RowError(offset, "品牌、物料类型或图片链接缺失", brand, original_type, url)
            )
            continue
        if brand not in VALID_BRANDS:
            result.errors.append(
                RowError(offset, f"非法品牌：{brand}", brand, original_type, url)
            )
            continue
        if material not in VALID_MATERIALS:
            result.errors.append(
                RowError(offset, f"非法物料类型：{original_type}", brand, original_type, url)
            )
            continue
        if url in existing:
            result.duplicates_existing += 1
            result.errors.append(
                RowError(offset, "与既有清单 URL 重复", brand, original_type, url)
            )
            continue
        if url in seen_urls:
            result.duplicates_within += 1
            result.errors.append(
                RowError(offset, "补充集内 URL 重复", brand, original_type, url)
            )
            continue

        if material != original_type:
            result.normalized += 1
        seen_urls.add(url)
        result.samples.append(
            PreparedSample(
                sample_id=f"{id_prefix}-{next_id:04d}",
                brand=brand,
                material_type=material,
                image_url=url,
                split=default_split,
            )
        )
        next_id += 1

    return result


def write_supplement_manifest(path: Path, result: PrepareResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for sample in result.samples:
            writer.writerow(
                {
                    "sample_id": sample.sample_id,
                    "brand": sample.brand,
                    "material_type": sample.material_type,
                    "image_url": sample.image_url,
                    "split": sample.split,
                }
            )
    tmp.replace(path)
