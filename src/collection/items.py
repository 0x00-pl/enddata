"""采集+初步处理:物品数据集 → data/processed/items.json。

来源表:ItemTable × ItemTypeTable × I18nTextTable_CN
产物:id/名称/类型/稀有度/描述/图标 ID 与直链。
"""

from __future__ import annotations

from collection.common import I18n, dump, load_raw_tables, load_vfs_config, vfs_url

PRODUCT = "items"

REQUIRED_TABLES = ["ItemTable", "ItemTypeTable", "I18nTextTable_CN"]


def build(raw: dict, t: I18n) -> list[dict]:
    type_names = {v.get("itemType"): t(v.get("name")) for v in raw["ItemTypeTable"].values()}
    items = []
    for iid, it in raw["ItemTable"].items():
        items.append({
            "id": iid,
            "name": t(it.get("name")),
            "type": it.get("type"),
            "typeName": type_names.get(it.get("type")),
            "rarity": it.get("rarity"),
            "showingType": it.get("showingType"),
            "desc": t(it.get("desc")),
            "icon": it.get("iconId"),
            "iconUrl": vfs_url("item_icon", iconId=it.get("iconId")),
        })
    items.sort(key=lambda x: (str(x["showingType"] or ""), -(x["rarity"] or 0), x["id"]))
    return items


def main() -> None:
    load_vfs_config()
    raw = load_raw_tables()
    dump(PRODUCT, build(raw, I18n(raw["I18nTextTable_CN"])))


if __name__ == "__main__":
    main()
