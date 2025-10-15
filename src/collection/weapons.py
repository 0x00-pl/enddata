"""采集+初步处理:武器数据集 → data/processed/weapons.json。

来源表:WeaponBasicTable × I18nTextTable_CN
产物:id/名称/稀有度/类型/满级。
"""

from __future__ import annotations

from tools.common import I18n, dump, load_raw_tables

PRODUCT = "weapons"

REQUIRED_TABLES = ["WeaponBasicTable", "I18nTextTable_CN"]


def build(raw: dict, t: I18n) -> list[dict]:
    weapons = []
    for wid, w in raw["WeaponBasicTable"].items():
        weapons.append({
            "id": wid,
            "name": t(w.get("engName")) or wid,
            "rarity": w.get("rarity"),
            "weaponType": w.get("weaponType"),
            "maxLevel": w.get("maxLv"),
        })
    weapons.sort(key=lambda x: (-(x["rarity"] or 0), x["id"]))
    return weapons


def main() -> None:
    raw = load_raw_tables()
    dump(PRODUCT, build(raw, I18n(raw["I18nTextTable_CN"])))


if __name__ == "__main__":
    main()
