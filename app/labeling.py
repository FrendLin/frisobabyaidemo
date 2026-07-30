"""本地图片标注筛选器的领域模型与持久化。

设计要点：
- 品牌目录是审核用 ``Brand`` 四个子品牌的超集，额外包含市面常见奶粉品牌与
  “其他/无法判断”辅助项，供人工标注选择；只有落在 ``Brand`` 中的四个皇家子品牌
  才能进入训练/评测清单（见 ``manifest``）。
- 物料类型严格复用审核标准的 ``MaterialType`` 全部类型。
- 标注结果保存在独立的数据目录，绝不写入用户原始图片目录，也不修改原图。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.domain import Brand, MaterialType

# 支持的图片扩展名（小写，含点）。
IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
)

# 皇家美素四个子品牌，直接来自审核域模型，保证与训练清单口径一致。
ROYAL_BRANDS: tuple[str, ...] = tuple(brand.value for brand in Brand)

# 市面常见奶粉品牌，仅用于人工标注竞品，不进入训练清单。
COMMON_BRANDS: tuple[str, ...] = (
    "爱他美",
    "飞鹤",
    "金领冠",
    "启赋",
    "a2",
    "雀巢",
    "美赞臣",
    "君乐宝",
    "合生元",
)

# 辅助项。
AUXILIARY_BRANDS: tuple[str, ...] = ("其他", "无法判断")

# 分组后的品牌目录，供前端渲染。
BRAND_CATALOG: tuple[dict[str, object], ...] = (
    {"group": "皇家美素", "items": list(ROYAL_BRANDS)},
    {"group": "常见品牌", "items": list(COMMON_BRANDS)},
    {"group": "辅助", "items": list(AUXILIARY_BRANDS)},
)

# 全部合法品牌取值。
ALL_BRANDS: frozenset[str] = frozenset(ROYAL_BRANDS + COMMON_BRANDS + AUXILIARY_BRANDS)

# 标准物料类型，直接来自审核标准。
MATERIAL_TYPES: tuple[str, ...] = tuple(item.value for item in MaterialType)
ALL_MATERIALS: frozenset[str] = frozenset(MATERIAL_TYPES)


class LabelingError(ValueError):
    """标注流程中的可预期错误，路由层据此返回 4xx。"""


@dataclass(frozen=True, slots=True)
class ImageItem:
    """扫描到的一张待标注图片。"""

    relpath: str  # 相对所选目录的 POSIX 路径，作为稳定主键。
    name: str
    size: int


@dataclass(slots=True)
class LabelRecord:
    """一张图片的多标签结果，并兼容旧版单标签字段。"""

    relpath: str
    brands: list[str] = field(default_factory=list)
    material_types: list[str] = field(default_factory=list)
    # 旧字段保留为兼容入口；仅有一个标签时同步为该值，多标签时为 None。
    brand: str | None = None
    material_type: str | None = None
    # 该图片在现有 POC 数据流程中的对应地址（清单 image_url）；
    # 有值且品牌为皇家子品牌时可同步进训练/评测清单。
    manifest_url: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if not self.brands and self.brand:
            self.brands = [self.brand]
        if not self.material_types and self.material_type:
            self.material_types = [self.material_type]
        self.brand = self.brands[0] if len(self.brands) == 1 else None
        self.material_type = (
            self.material_types[0] if len(self.material_types) == 1 else None
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "relpath": self.relpath,
            "brands": list(self.brands),
            "material_types": list(self.material_types),
            "brand": self.brand,
            "material_type": self.material_type,
            "manifest_url": self.manifest_url,
            "updated_at": self.updated_at,
        }

    @property
    def labeled(self) -> bool:
        return bool(self.brands) and bool(self.material_types)


def _validate_selections(
    values: object,
    *,
    allowed: frozenset[str],
    label: str,
) -> list[str]:
    if values in (None, ""):
        return []
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, (list, tuple)):
        raw_values = list(values)
    else:
        raise LabelingError(f"{label}必须是字符串数组")

    selections: list[str] = []
    for value in raw_values:
        if not isinstance(value, str) or not value:
            raise LabelingError(f"{label}包含非法值")
        if value not in allowed:
            raise LabelingError(f"未知{label}：{value}")
        if value not in selections:
            selections.append(value)
    return selections


def validate_brands(values: object) -> list[str]:
    return _validate_selections(values, allowed=ALL_BRANDS, label="品牌")


def validate_materials(values: object) -> list[str]:
    return _validate_selections(values, allowed=ALL_MATERIALS, label="物料类型")


def resolve_directory(raw: str) -> Path:
    """把用户输入解析为一个存在、可读的目录，拦截非法路径。"""

    if not raw or not raw.strip():
        raise LabelingError("目录路径不能为空")
    text = raw.strip()
    if "\x00" in text:
        raise LabelingError("目录路径包含非法字符")
    candidate = Path(text).expanduser()
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise LabelingError(f"无法解析目录：{error}") from error
    if not resolved.exists():
        raise LabelingError("目录不存在")
    if not resolved.is_dir():
        raise LabelingError("路径不是目录")
    if not os.access(resolved, os.R_OK | os.X_OK):
        raise LabelingError("目录不可读")
    return resolved


def pick_directory_native() -> Path | None:
    """在 macOS 本机打开系统目录选择器，返回经过校验的绝对路径。

    浏览器的 ``webkitdirectory`` 出于安全限制只暴露相对目录名，不能满足
    后端按本机路径扫描的契约。本工具是本机 POC，因此由服务端调用系统选择器；
    用户取消时返回 ``None``，无图形界面或非 macOS 环境则给出明确错误。
    """

    if sys.platform != "darwin":
        raise LabelingError("当前系统不支持原生目录选择器，请手工粘贴目录绝对路径")
    script = 'POSIX path of (choose folder with prompt "请选择待标注图片目录")'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError as error:
        raise LabelingError("系统目录选择器不可用，请手工粘贴目录绝对路径") from error
    except subprocess.TimeoutExpired as error:
        raise LabelingError("系统目录选择器等待超时，请重试") from error

    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        if "(-128)" in detail or "User canceled" in detail:
            return None
        raise LabelingError(f"系统目录选择器失败：{detail or '未知错误'}")
    selected = result.stdout.strip()
    if not selected:
        return None
    return resolve_directory(selected)


def resolve_image_within(directory: Path, relpath: str) -> Path:
    """把相对路径安全地解析到目录内部，拦截 ../ 逃逸与绝对路径。"""

    if not relpath or "\x00" in relpath:
        raise LabelingError("非法文件路径")
    rel = Path(relpath)
    if rel.is_absolute():
        raise LabelingError("非法文件路径")
    base = directory.resolve(strict=False)
    target = (base / rel).resolve(strict=False)
    if base != target and base not in target.parents:
        raise LabelingError("非法文件路径")
    if not target.is_file():
        raise LabelingError("文件不存在")
    return target


def scan_directory(directory: Path) -> list[ImageItem]:
    """递归扫描目录，返回按相对路径排序的图片列表。

    - 忽略非图片文件；
    - 相对路径作为主键，天然区分不同子目录下的同名文件；
    - 不打开图片内容，损坏图片在预览/导出时再暴露，避免大目录卡顿。
    """

    items: list[ImageItem] = []
    for root, dirnames, filenames in os.walk(directory):
        # 跳过隐藏目录与本工具自身的数据目录残留。
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            suffix = Path(filename).suffix.lower()
            if suffix not in IMAGE_EXTENSIONS:
                continue
            full = Path(root) / filename
            try:
                size = full.stat().st_size
            except OSError:
                continue
            rel = full.relative_to(directory).as_posix()
            items.append(ImageItem(relpath=rel, name=filename, size=size))
    items.sort(key=lambda item: item.relpath)
    return items


def find_duplicate_names(items: list[ImageItem]) -> dict[str, list[str]]:
    """返回同名文件（跨子目录）分组，供前端提示歧义。"""

    grouped: dict[str, list[str]] = {}
    for item in items:
        grouped.setdefault(item.name, []).append(item.relpath)
    return {name: paths for name, paths in grouped.items() if len(paths) > 1}


class LabelStore:
    """按目录持久化标注结果的 JSON 存储。

    每个被标注的目录对应 ``<data_dir>/<sha1(abspath)>.json`` 一个文件，
    绝不写入用户原始目录，刷新与重启后可恢复。
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _store_path(self, directory: Path) -> Path:
        key = hashlib.sha1(str(directory).encode("utf-8")).hexdigest()
        return self._data_dir / f"{key}.json"

    def load(self, directory: Path) -> dict[str, LabelRecord]:
        path = self._store_path(directory)
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        records: dict[str, LabelRecord] = {}
        for relpath, payload in raw.get("labels", {}).items():
            if not isinstance(payload, dict):
                continue
            try:
                brands = validate_brands(
                    payload.get("brands", payload.get("brand"))
                )
                material_types = validate_materials(
                    payload.get("material_types", payload.get("material_type"))
                )
            except LabelingError:
                continue
            records[relpath] = LabelRecord(
                relpath=relpath,
                brands=brands,
                material_types=material_types,
                manifest_url=payload.get("manifest_url"),
                updated_at=payload.get("updated_at"),
            )
        return records

    def _write(self, directory: Path, records: dict[str, LabelRecord]) -> None:
        path = self._store_path(directory)
        payload = {
            "directory": str(directory),
            "labels": {rel: rec.to_dict() for rel, rec in records.items()},
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)

    def set_label(
        self,
        directory: Path,
        relpath: str,
        *,
        brands: object = None,
        material_types: object = None,
        brand: str | None = None,
        material_type: str | None = None,
        manifest_url: str | None,
        now: str,
    ) -> LabelRecord:
        selected_brands = validate_brands(brands if brands is not None else brand)
        selected_materials = validate_materials(
            material_types if material_types is not None else material_type
        )
        records = self.load(directory)
        existing = records.get(relpath)
        record = LabelRecord(
            relpath=relpath,
            brands=selected_brands,
            material_types=selected_materials,
            manifest_url=manifest_url or (existing.manifest_url if existing else None),
            updated_at=now,
        )
        records[relpath] = record
        self._write(directory, records)
        return record


def merge_items_with_labels(
    items: list[ImageItem], records: dict[str, LabelRecord]
) -> list[dict[str, object]]:
    """把扫描结果与已存标注合并成前端可直接消费的列表。"""

    merged: list[dict[str, object]] = []
    for item in items:
        record = records.get(item.relpath)
        merged.append(
            {
                "relpath": item.relpath,
                "name": item.name,
                "size": item.size,
                "brands": list(record.brands) if record else [],
                "material_types": list(record.material_types) if record else [],
                "brand": record.brand if record else None,
                "material_type": record.material_type if record else None,
                "manifest_url": record.manifest_url if record else None,
                "updated_at": record.updated_at if record else None,
                "labeled": bool(record and record.labeled),
            }
        )
    return merged


def filter_records(
    merged: list[dict[str, object]],
    *,
    mode: str = "all",
    brand: str | None = None,
    material_type: str | None = None,
) -> list[dict[str, object]]:
    """按“全部/未标注/已标注/按品牌/按物料类型”筛选。"""

    def keep(row: dict[str, object]) -> bool:
        if mode == "labeled" and not row["labeled"]:
            return False
        if mode == "unlabeled" and row["labeled"]:
            return False
        if brand and brand not in (row.get("brands") or []):
            return False
        if material_type and material_type not in (row.get("material_types") or []):
            return False
        return True

    return [row for row in merged if keep(row)]


def progress(merged: list[dict[str, object]]) -> dict[str, int]:
    total = len(merged)
    labeled = sum(1 for row in merged if row["labeled"])
    return {"total": total, "labeled": labeled, "unlabeled": total - labeled}


def export_csv(merged: list[dict[str, object]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "relpath",
            "name",
            "brands",
            "material_types",
            "manifest_url",
            "updated_at",
        ]
    )
    for row in merged:
        writer.writerow(
            [
                row["relpath"],
                row["name"],
                "|".join(row.get("brands") or []),
                "|".join(row.get("material_types") or []),
                row.get("manifest_url") or "",
                row.get("updated_at") or "",
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")


def export_json(directory: Path, merged: list[dict[str, object]]) -> bytes:
    payload = {
        "directory": str(directory),
        "count": len(merged),
        "labels": merged,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
