from __future__ import annotations

from enum import StrEnum


class Brand(StrEnum):
    ROYAL = "皇家"
    WANGYUE = "旺玥"
    YUANYUE = "源悦"
    ZUNYUE = "尊悦"


class MaterialType(StrEnum):
    LIGHTBOX = "灯箱"
    WINDOW_OR_WALL = "橱窗单透/墙贴"
    IN_STORE_POSTER = "店内海报（非货架）"
    EXTERIOR = "店招/外立面广告"
    HANGING_FLAG = "吊旗"
    COLUMN_WRAP = "包柱画面"


MATERIAL_RULES: dict[MaterialType, tuple[str, ...]] = {
    MaterialType.LIGHTBOX: (
        "通常位于货架或墙体顶部，有灯光；无灯光时应能看到电线。",
        "有厚度，通常为长方形或圆形。",
    ),
    MaterialType.WINDOW_OR_WALL: (
        "橱窗单透应贴在玻璃上，或形成橱窗置景。",
        "墙贴是张贴在门店墙面的大型海报；满足二者之一即可。",
    ),
    MaterialType.IN_STORE_POSTER: (
        "必须位于店内，店外海报无效。",
        "通常贴于墙面、柜台侧面或店内展示板，不属于货架本体。",
    ),
    MaterialType.EXTERIOR: (
        "必须位于店外，店内画面无效。",
        "门店招牌需出现对应品牌物料或对应品牌奶粉罐。",
        "外立面广告可张贴于外墙或店外立式展示板；满足店招或外立面之一即可。",
    ),
    MaterialType.HANGING_FLAG: (
        "悬挂在店内天花板、通道上方或商品陈列区。",
        "通常批量错落悬挂，单独一个较少见。",
    ),
    MaterialType.COLUMN_WRAP: (
        "必须位于店内，店外包柱无效。",
        "海报或灯箱完整包裹立柱，形成圆柱或直立方柱形态。",
    ),
}

