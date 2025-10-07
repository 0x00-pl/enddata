"""采集+初步处理:装备与套装数据集 → data/processed/equips.json。

来源表:EquipTable × EquipSuitTable × ItemTable(命名/稀有度/图标) × I18nTextTable_CN
产物:
    - equips:部位(自 id 解析 body/hand/edc)、所属套装、词条(attrType 枚举翻译)、基础属性
    - suits:套装名称、成员数、按件数分档的被动技能
"""

from __future__ import annotations

from collection.common import I18n, attr_name, dump, load_raw_tables, load_vfs_config, vfs_url

PRODUCT = "equips"


def build(raw: dict, t: I18n) -> dict:
    # partType 整数 → 部位标签(从装备 id 中的 _body_/_hand_/_edc_ 反推)
    part_by_int: dict = {}
    for eid, e in raw["EquipTable"].items():
        for tag in ("body", "hand", "edc"):
            if f"_{tag}_" in eid:
                part_by_int.setdefault(e.get("partType"), tag)

    equips = []
    for eid, e in raw["EquipTable"].items():
        iid = e.get("itemId") or eid
        item = raw["ItemTable"].get(iid, {})
        part = next((tag for tag in ("body", "hand", "edc") if f"_{tag}_" in eid),
                    part_by_int.get(e.get("partType"), e.get("partType")))
        mods = [{"type": attr_name(m.get("attrType")) or f"attr{m.get('attrType')}",
                 "value": m.get("attrValue")}
                for m in e.get("displayAttrModifiers") or []]
        base = e.get("displayBaseAttrModifier") or None
        equips.append({
            "id": eid,
            "name": t(item.get("name")) or eid,
            "part": part,
            "suit": e.get("suitID") or None,
            "rarity": item.get("rarity"),
            "minWearLv": e.get("minWearLv"),
            "icon": vfs_url("item_icon", iconId=item.get("iconId")),
            "baseAttr": {"type": attr_name(base.get("attrType")), "value": base.get("attrValue")} if base else None,
            "attrs": mods,
        })
    equips.sort(key=lambda x: (x["suit"] or "", x["part"] or "", x["id"]))

    suits = []
    for sid, s in raw["EquipSuitTable"].items():
        tiers = s.get("list") or []
        suits.append({
            "id": sid,
            "name": t((tiers[0] if tiers else {}).get("suitName")) or sid,
            "logo": (tiers[0] if tiers else {}).get("suitLogoName"),
            "members": len(s.get("equipList") or []),
            "effects": [{"count": x.get("equipCnt"), "skill": x.get("skillID"), "lv": x.get("skillLv")}
                        for x in tiers],
        })
    suits.sort(key=lambda x: x["id"])
    return {"equips": equips, "suits": suits}


def main() -> None:
    load_vfs_config()
    raw = load_raw_tables()
    dump(PRODUCT, build(raw, I18n(raw["I18nTextTable_CN"])))


if __name__ == "__main__":
    main()
