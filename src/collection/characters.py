"""采集+初步处理:干员数据集 → data/processed/characters.json。

来源表:CharacterTable × CharProfessionTable × CharBreakTable × I18nTextTable_CN
产物:id/名称/职业/稀有度/武器类型/CV、1 级与满级面板、头像与职业图标直链。
"""

from __future__ import annotations

from tools.common import (
    ATTRACTIONS_OF_INTEREST,
    I18n,
    dump,
    flat_attrs,
    load_raw_tables,
    load_vfs_config,
    vfs_url,
)

PRODUCT = "characters"

REQUIRED_TABLES = ["CharacterTable", "CharProfessionTable", "CharBreakTable", "I18nTextTable_CN"]


def build(raw: dict, t: I18n) -> list[dict]:
    professions = {v["profession"]: (t(v.get("name")), v.get("iconId"))
                   for v in raw["CharProfessionTable"].values()}
    max_level = max(int(v.get("maxLevel", 0)) for v in raw["CharBreakTable"].values())
    characters = []
    for cid, c in raw["CharacterTable"].items():
        # attributes 按 breakStage 分段,每段是 {Attribute: {attrs: [...]}, breakStage}
        lv1, lv_max = {}, {}
        for seg in c.get("attributes", []):
            attrs = flat_attrs((seg.get("Attribute") or {}).get("attrs"))
            if attrs.get("Level") == 1 and not lv1:
                lv1 = attrs
            lv_max = attrs or lv_max
        _prof_name, _prof_icon = professions.get(c.get("profession"), (None, None))
        characters.append({
            "id": cid,
            "name": t(c.get("name")) or cid,
            "enName": c.get("engName"),
            "profession": c.get("profession"),
            "professionName": _prof_name,
            "professionIcon": vfs_url("profession_icon", iconId=_prof_icon),
            "icon": vfs_url("char_icon", id=cid),
            "rarity": c.get("rarity"),
            "weaponType": c.get("weaponType"),
            "cv": c.get("cvName"),
            "maxLevel": max_level,
            "lv1": {k: lv1.get(k) for k in ATTRACTIONS_OF_INTEREST},
            "lvMax": {k: lv_max.get(k) for k in ATTRACTIONS_OF_INTEREST},
        })
    characters.sort(key=lambda x: (-(x["rarity"] or 0), x["id"]))
    return characters


def main() -> None:
    load_vfs_config()
    raw = load_raw_tables()
    dump(PRODUCT, build(raw, I18n(raw["I18nTextTable_CN"])))


if __name__ == "__main__":
    main()
