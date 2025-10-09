"""采集+初步处理:生产配方数据集 → data/processed/recipes.json。

来源表:FactoryManualCraftTable × FactoryMachineCraftTable × SpaceshipManufactureFormulaTable
        × ItemTable(原料/产物命名) × I18nTextTable_CN
产物:按站点(manual/machine/spaceship)合并的配方;机器配方的可替代原料组保留为 options。
"""

from __future__ import annotations

from collection.common import I18n, dump, load_raw_tables

PRODUCT = "recipes"

REQUIRED_TABLES = ["FactoryManualCraftTable", "FactoryMachineCraftTable",
                                 "SpaceshipManufactureFormulaTable", "ItemTable", "I18nTextTable_CN"]


def build(raw: dict, t: I18n) -> list[dict]:
    item_name = {iid: t(it.get("name")) for iid, it in raw["ItemTable"].items() if t(it.get("name"))}

    def resolve_side(entries: list[dict]) -> list[dict]:
        """原料/产物条目 → [{count, options:[{id,name}]}];机器配方的 group 是可替代原料组。"""
        out = []
        for e in entries or []:
            if "group" in e:
                options = [{"id": o["id"], "name": item_name.get(o["id"]) or o["id"], "count": o.get("count", 1)}
                           for o in e["group"]]
            else:
                options = [{"id": e["id"], "name": item_name.get(e["id"]) or e["id"], "count": e.get("count", 1)}]
            out.append({"count": options[0]["count"], "options": options})
        return out

    recipes = []
    for rid, r in raw["FactoryManualCraftTable"].items():
        recipes.append({
            "id": rid, "station": "manual",
            "rarity": r.get("rarity"), "domainId": r.get("domainId"),
            "ingredients": resolve_side(r.get("ingredients")),
            "outcomes": resolve_side(r.get("outcomes")),
        })
    for rid, r in raw["FactoryMachineCraftTable"].items():
        recipes.append({
            "id": rid, "station": "machine", "machineId": r.get("machineId"),
            "rarity": r.get("rarity"),
            "ingredients": resolve_side(r.get("ingredients")),
            "outcomes": resolve_side(r.get("outcomes")),
        })
    for rid, r in raw["SpaceshipManufactureFormulaTable"].items():
        recipes.append({
            "id": rid, "station": "spaceship",
            "rarity": r.get("rarity"),
            "ingredients": [],
            "outcomes": resolve_side([{"id": r["outcomeItemId"], "count": r.get("perCapacity", 1)}]),
        })
    return recipes


def main() -> None:
    raw = load_raw_tables()
    dump(PRODUCT, build(raw, I18n(raw["I18nTextTable_CN"])))


if __name__ == "__main__":
    main()
