"""版本化数据准备的单元测试：规范化、校验、去重、统计。"""

from __future__ import annotations

from app.dataset import normalize_material, prepare_supplement


def test_normalize_column_wrap_alias() -> None:
    assert normalize_material("包柱") == "包柱画面"
    assert normalize_material("包柱画面") == "包柱画面"
    assert normalize_material("灯箱") == "灯箱"


def test_prepare_normalizes_and_counts() -> None:
    rows = [
        ("源悦", "包柱", "https://static.51dh.com.cn/a.jpg"),
        ("皇家", "吊旗", "https://static.51dh.com.cn/b.jpg"),
    ]
    result = prepare_supplement(rows, version="v1")
    assert len(result.samples) == 2
    assert result.normalized == 1
    materials = result.material_counts()
    assert materials["包柱画面"] == 1
    assert materials["吊旗"] == 1


def test_prepare_flags_invalid_brand_and_type() -> None:
    rows = [
        ("外星品牌", "灯箱", "https://static.51dh.com.cn/a.jpg"),
        ("皇家", "不存在", "https://static.51dh.com.cn/b.jpg"),
        ("皇家", "灯箱", ""),
    ]
    result = prepare_supplement(rows, version="v1")
    assert result.samples == []
    assert len(result.errors) == 3
    reasons = " ".join(e.reason for e in result.errors)
    assert "非法品牌" in reasons
    assert "非法物料类型" in reasons
    assert "缺失" in reasons


def test_prepare_dedupes_within_and_against_existing() -> None:
    rows = [
        ("皇家", "灯箱", "https://static.51dh.com.cn/dup.jpg"),
        ("皇家", "灯箱", "https://static.51dh.com.cn/dup.jpg"),
        ("皇家", "灯箱", "https://static.51dh.com.cn/exist.jpg"),
    ]
    result = prepare_supplement(
        rows,
        version="v1",
        existing_urls={"https://static.51dh.com.cn/exist.jpg"},
    )
    assert len(result.samples) == 1
    assert result.duplicates_within == 1
    assert result.duplicates_existing == 1


def test_prepare_embedded_cabinet_is_valid() -> None:
    rows = [("皇家", "嵌柜", "https://static.51dh.com.cn/c.jpg")]
    result = prepare_supplement(rows, version="v1")
    assert len(result.samples) == 1
    assert result.samples[0].material_type == "嵌柜"
