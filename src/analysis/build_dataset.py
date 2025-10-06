#!/usr/bin/env python3
"""数据分析:把 data/raw/ 下的原始 TableCfg 加工为数据集(生成的报告)。

产出:
    - data/processed/*.json        数据集(由 site/ 网页展示消费)
    - reports/build-report.md      人类可读的构建报告

流水线:
    1. 加载 i18n 中文表,把所有 {id: 哈希} 文本引用解析成中文名
    2. 角色表 × 职业表 → characters.json(含 1 级面板)
    3. 物品表 × 物品类型表 → items.json
    4. 手工/机器/飞船配方合并 → recipes.json(机器配方的可选原料组保留为 options)
    5. 武器表 → weapons.json
    6. 装备表 × 套装表 → equips.json(含词条与套装效果)
    7. 敌人表 × 显示信息 × 属性模板 → enemies.json(含等级曲线摘要与抗性)
    8. meta.json(构建信息与统计)+ 构建报告 markdown

用法: python3 src/analysis/build_dataset.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from collection.enddata_http import PROJECT_ROOT, RAW_DIR, info, load_json


def raw_dir() -> Path:
    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["tablecfg"]
    return RAW_DIR / "tablecfg" / cfg["repo"].replace("/", "__") / cfg["branch"]


BRANCH_DIR = raw_dir()
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"

ATTRACTIONS_OF_INTEREST = ["MaxHp", "Atk", "Def", "Str", "Agi", "Wisd", "Will"]

# rmxlinux 新版把 attrType 从字符串改成了整数枚举(AttributeMetaTable.iconName 反查 + 数值交叉验证)
INT_ATTR_MAP = {
    0: "Level", 1: "MaxHp", 2: "Atk", 3: "Def",
    9: "CriticalRate", 10: "CriticalDamageIncrease",
    39: "Str", 40: "Agi", 41: "Wisd", 42: "Will",
    4: "PhysicalDamageTakenScalar", 5: "FireDamageTakenScalar",
    6: "PulseDamageTakenScalar", 7: "CrystDamageTakenScalar",
    55: "EtherDamageTakenScalar", 48: "NaturalDamageTakenScalar",
    # 以下取自 AttributeMetaTable 的 iconName(装备词条常见效率类)
    17: "NormalAtkEfficiency", 28: "UltimateSkillEfficiency", 32: "NormalSkillEfficiency",
    33: "ComboSkillEfficiency", 44: "UltimateSpGainScalar", 47: "ComboSkillCooldown",
    29: "HealOutputIncrease", 30: "HealTakenIncrease", 26: "PoiseEfficiency",
    50: "PhysicalDamageIncrease", 51: "FireDamageIncrease", 52: "PulseDamageIncrease",
    53: "CrystDamageIncrease", 54: "NaturalDamageIncrease", 61: "DamageToBrokenUnitIncrease",
    87: "OriginiumArts",
}


def attr_name(t) -> str | None:
    if isinstance(t, int):
        return INT_ATTR_MAP.get(t)
    return t


def vfs_url(kind: str, **params) -> str | None:
    """按 config/sources.json 的 fffdan_vfs 注册项拼资源 URL(宏山档案局资源镜像,WebP)。"""
    path = vfs_url.patterns.get(kind)
    if vfs_url.base is None or not path:
        return None
    for k, v in params.items():
        if v is None or v == "":
            return None
        path = path.replace("{" + k + "}", str(v))
    return f"{vfs_url.base}{vfs_url.prefix}/{path}"


vfs_url.base = None
vfs_url.prefix = None
vfs_url.patterns = {}


def load_vfs_config() -> None:
    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"].get("fffdan_vfs")
    if not cfg:
        return
    vfs_url.base = cfg["hosts"][0]
    vfs_url.prefix = cfg["vfs_prefix"]
    vfs_url.patterns = cfg["paths"]


class I18n:
    def __init__(self, table: dict):
        self.table = table
        self.misses = 0

    def __call__(self, ref: dict | None) -> str | None:
        """把 {id: 哈希, text: null} 的文本引用解析为中文,失败返回 None。"""
        if not isinstance(ref, dict):
            return None
        if ref.get("text"):
            return ref["text"]
        hid = ref.get("id")
        if not hid:
            return None
        text = self.table.get(str(hid))
        if text is None:
            self.misses += 1
        return text


def dump(name: str, payload):
    dest = PROCESSED_DIR / f"{name}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    info(f"  -> {dest.relative_to(PROJECT_ROOT)} ({dest.stat().st_size/1024:.0f} KB, {len(payload) if isinstance(payload, list) else '...'} 条)")


def attr_map(attr_list: list[dict]) -> dict:
    """[{attrs: [{attrType, attrValue}]}] 形式(敌人等级曲线)拍平成 {attrType: value}。"""
    out = {}
    for entry in attr_list or []:
        for a in entry.get("attrs", []):
            t, v = attr_name(a.get("attrType")), a.get("attrValue")
            if t:
                out[t] = v
    return out


def flat_attrs(attrs: list[dict] | None) -> dict:
    """[{attrType, attrValue}] 形式(角色分段面板)拍平成 {attrType: value}。"""
    return {attr_name(a["attrType"]): a["attrValue"] for a in attrs or [] if a.get("attrType") is not None}


def main() -> None:
    t0 = datetime.now(timezone.utc)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    load_vfs_config()
    raw = {p.stem: load_json(p) for p in BRANCH_DIR.glob("*.json")}
    info(f"加载原始表: {len(raw)} 张")

    t = I18n(raw["I18nTextTable_CN"])

    # ---- 角色 ----
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
    dump("characters", characters)

    # ---- 物品 ----
    type_names = {v.get("itemType"): t(v.get("name")) for v in raw["ItemTypeTable"].values()}
    items = []
    for iid, it in raw["ItemTable"].items():
        name = t(it.get("name"))
        items.append({
            "id": iid,
            "name": name,
            "type": it.get("type"),
            "typeName": type_names.get(it.get("type")),
            "rarity": it.get("rarity"),
            "showingType": it.get("showingType"),
            "desc": t(it.get("desc")),
            "icon": it.get("iconId"),
            "iconUrl": vfs_url("item_icon", iconId=it.get("iconId")),
        })
    items.sort(key=lambda x: (str(x["showingType"] or ""), -(x["rarity"] or 0), x["id"]))
    dump("items", items)
    item_name = {i["id"]: i["name"] for i in items if i["name"]}

    # ---- 配方(手工 + 机器 + 飞船制造) ----
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
    dump("recipes", recipes)

    # ---- 武器 ----
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
    dump("weapons", weapons)

    # ---- 装备(EquipTable)与套装(EquipSuitTable) ----
    PART_BY_INT = {}
    for eid2, e2 in raw["EquipTable"].items():
        for tag in ("body", "hand", "edc"):
            if f"_{tag}_" in eid2:
                PART_BY_INT.setdefault(e2.get("partType"), tag)
    equips = []
    for eid2, e2 in raw["EquipTable"].items():
        iid = e2.get("itemId") or eid2
        item = raw["ItemTable"].get(iid, {})
        part = next((tag for tag in ("body", "hand", "edc") if f"_{tag}_" in eid2),
                    PART_BY_INT.get(e2.get("partType"), e2.get("partType")))
        mods = []
        for m in e2.get("displayAttrModifiers") or []:
            mods.append({
                "type": attr_name(m.get("attrType")) or f"attr{m.get('attrType')}",
                "value": m.get("attrValue"),
            })
        base = e2.get("displayBaseAttrModifier") or None
        equips.append({
            "id": eid2,
            "name": t(item.get("name")) or eid2,
            "part": part,
            "suit": e2.get("suitID") or None,
            "rarity": item.get("rarity"),
            "minWearLv": e2.get("minWearLv"),
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
    dump("equips", {"equips": equips, "suits": suits})

    # ---- 敌人 ----
    display = raw["EnemyDisplayInfoTable"]
    enemies = []
    for eid, e in raw["EnemyTable"].items():
        d = display.get(eid, {})
        template = raw["EnemyAttributeTemplateTable"].get(e.get("attrTemplateId"), {})
        curve = template.get("levelDependentAttributes") or []
        lv_max = attr_map(curve[-1:]) if curve else {}
        # 抗性:新版是具名百分数字段(0-100),旧版是 *ResistScalar(受伤倍率);
        # 统一归一化为「减伤比例」0-1 输出
        resists = {}
        for k, v in template.items():
            if k.endswith("Resistance") and isinstance(v, (int, float)) and v:
                resists[k.replace("Resistance", "")] = v / 100
            elif k.endswith("ResistScalar") and isinstance(v, (int, float)) and v != 1:
                resists[k.replace("DmgResistScalar", "")] = 1 - v
        enemies.append({
            "id": eid,
            "templateId": e.get("templateId") or d.get("templateId"),
            # 解包表中敌人显示名哈希均为 0,名字暂以 templateId 兜底,待接入森空岛 Wiki「威胁」分区补全
            "name": t(d.get("name")) or t(d.get("nickname")) or e.get("templateId"),
            "dangerous": e.get("isDangerous", False),
            "superArmor": template.get("initialSuperArmor"),
            "maxResilience": template.get("maxResilience"),
            "resists": resists,
            "lvMax": {k: lv_max.get(k) for k in ("MaxHp", "Atk", "Def") if lv_max.get(k) is not None},
        })
    enemies.sort(key=lambda x: x["id"])
    dump("enemies", enemies)

    # ---- 元信息 ----
    _src = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["tablecfg"]
    meta = {
        "generatedAt": t0.isoformat(timespec="seconds"),
        "source": {"repo": _src["repo"], "branch": _src["branch"],
                   "fetchedAt": load_json(RAW_DIR / "tablecfg" / "manifest.json")["fetched_at"]},
        "i18nMisses": t.misses,
        "counts": {
            "characters": len(characters), "items": len(items),
            "recipes": len(recipes), "weapons": len(weapons), "enemies": len(enemies),
            "equips": len(equips), "suits": len(suits),
        },
    }
    dump("meta", meta)
    info(f"i18n 未命中 {t.misses} 处(哈希不在 CN 表中,多为占位 0)")

    # ---- 构建报告(人类可读,写入 reports/) ----
    manifest = load_json(RAW_DIR / "tablecfg" / "manifest.json")
    channels: dict[str, int] = {}
    for f in manifest.get("files", {}).values():
        ch = f.get("channel", "?")
        channels[ch] = channels.get(ch, 0) + 1
    icon_items = sum(1 for i in items if i.get("iconUrl"))
    report = f"""# 构建报告

- 构建时间:{t0.isoformat(timespec="seconds")}(UTC)
- 数据源:{_src["repo"]}@{_src["branch"]}(抓取于 {meta["source"]["fetchedAt"]})
- 抓取渠道分布:{json.dumps(channels, ensure_ascii=False)}
- i18n 未命中:{t.misses}

## 数据集规模

| 数据集 | 条数 |
|---|---|
| 干员 characters | {len(characters)} |
| 物品 items(含图标链接 {icon_items} 条) | {len(items)} |
| 配方 recipes | {len(recipes)} |
| 武器 weapons | {len(weapons)} |
| 敌人 enemies | {len(enemies)} |

## 产物位置

- 数据集:`data/processed/*.json`(网页展示由 `site/` 消费)
- 本报告:`reports/build-report.md`
"""
    report_dest = REPORTS_DIR / "build-report.md"
    report_dest.write_text(report, encoding="utf-8")
    info(f"  -> {report_dest.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
