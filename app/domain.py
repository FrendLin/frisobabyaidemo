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
        "固定在货架或墙体顶部、墙面或立柱旁的发光箱体；可横向也可竖向。",
        "优先寻找内发光、明显边框、箱体厚度或电线；即使位于店外，独立发光箱体仍判灯箱。",
        "客户标签把货架顶部或墙面上方的固定长方形广告板归为灯箱，即使照片中发光、电线或厚度不明显。",
    ),
    MaterialType.WINDOW_OR_WALL: (
        "橱窗单透应贴在玻璃上，或形成橱窗置景。",
        "墙贴是张贴在门店墙面的大型海报；满足二者之一即可。",
        "必须是直接贴合玻璃/墙面的平面画面；没有可见柱体弧面或相连侧面时绝不能判包柱。",
    ),
    MaterialType.IN_STORE_POSTER: (
        "必须位于店内，店外海报无效。",
        "只用于可辨认为薄的独立纸质海报或展示板；带边框/厚度/内发光的画面应判灯箱。",
        "整面墙贴或玻璃贴应判橱窗单透/墙贴，不能仅因画面在店内就判店内海报。",
    ),
    MaterialType.EXTERIOR: (
        "必须位于店外，店内画面无效。",
        "门店招牌需出现对应品牌物料或对应品牌奶粉罐。",
        "外立面广告可张贴于外墙或店外立式展示板；满足店招或外立面之一即可。",
        "若店外物料是有明显箱体/内发光的独立灯箱，优先判灯箱。",
    ),
    MaterialType.HANGING_FLAG: (
        "悬挂在店内天花板、通道上方或商品陈列区。",
        "通常批量错落悬挂，单独一个较少见。",
    ),
    MaterialType.COLUMN_WRAP: (
        "必须位于店内，店外包柱无效。",
        "海报或灯箱完整包裹立柱，形成圆柱或直立方柱形态。",
        "必须能看到同一立柱的弧面或至少两个相连侧面；单块竖版平面不是包柱。",
    ),
}
