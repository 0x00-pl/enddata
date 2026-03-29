"""采集+初步处理(多数据源综合):装备与套装数据集 → data/equips/ 目录。

(装备逐件一个文件、按所属套装分子目录,suit 字段 = 子目录名,无套装入 unknown;
套装与强化全局配置在 _global.json;index.json 为按 suit 分组的 id 清单)

数据来源与贡献:
    - rmxlinux@TableCfg:EquipTable × EquipSuitTable × ItemTable(命名/稀有度/图标)
      → 身份、部位、所属套装、词条(attrType 枚举翻译)、基础属性
    - rmxlinux@TableCfg/SkillPatchTable:套装被动技能描述(24/24 可 i18n 反查,
      富文本标签已剥离,{键:fmt}/{1-键:fmt} 占位符按 blackboard 回填)
    - rmxlinux@TableCfg/EquipFormulaTable(+ReverseTable 反查):合成公式
      (formulaId、合成档位 level、所属装备组 packId、解锁条件 unlock*)
    - rmxlinux@TableCfg/EquipFormulaChainTable × EquipCostMaterialTable:
      合成消耗(按档位的可选加工链:调度券 + 工艺原件;工艺名/解锁主线关卡)
    - rmxlinux@TableCfg/EquipPackTable:装备组名称
    - rmxlinux@TableCfg/EquipEnhanceCostTable × EquipEnhanceGuaranteeTimesRuleTable:
      强化消耗(全局,按领域)与强化保底规则(装备侧经词条引用规则 ID)
产物:
    - equips:部位(自 id 解析 body/hand/edc)、所属套装、词条、基础属性,
      另有 formula(合成公式/档位/装备组/解锁/可选加工链材料)、enhancePity(引用的保底规则)
    - suits:套装名称、成员数、按件数分档的被动技能(描述经 SkillPatchTable 反查并回填数值)
    - enhance:全局强化消耗与保底规则定义(逐件装备仅引用,不重复展开)
"""

from __future__ import annotations

import json

from tools.placeholders import fill_desc
from tools.tables import DATA_DIR, I18n, attr_name, dump_dir, i18n_table, load_tables

PRODUCT = "equips"

REQUIRED_TABLES = [
    "EquipTable", "EquipSuitTable", "ItemTable", "I18nTextTable_CN",
    "EquipFormulaTable", "EquipFormulaReverseTable", "EquipFormulaChainTable",
    "EquipCostMaterialTable", "EquipPackTable",
    "EquipEnhanceCostTable", "EquipEnhanceGuaranteeTimesRuleTable",
    "SkillPatchTable",
]

# 套装被动描述的富文本标签与 {键:fmt} 占位符(含裸 {键} 与 {1-键:0%} 型
# 表达式:项为数字/键,可 * 连乘)由 tools/placeholders.py 共享实现回填;
# 占位符缺数(键查不到/0 值)直接抛错,不静默留错档文案


def suit_effects(raw: dict, t: I18n, tiers: list[dict]) -> list[dict]:
    """EquipSuitTable 各件数档的被动效果,描述 join SkillPatchTable(等级恒为 1)。

    patch 按 skillLv 匹配,缺失回退首条;占位符按该等级 blackboard 回填。
    """
    out = []
    for x in tiers or []:
        sid = x.get("skillID")
        patches = (raw["SkillPatchTable"].get(sid) or {}).get("SkillPatchDataBundle") or []
        patch = next((p for p in patches if p.get("level") == x.get("skillLv")), patches[0] if patches else None)
        bb = {b.get("key"): b.get("value") for b in (patch or {}).get("blackboard") or []}
        out.append({
            "count": x.get("equipCnt"),
            "skill": sid,
            "lv": x.get("skillLv"),
            "desc": fill_desc(t((patch or {}).get("description")), bb),
        })
    return out


def cost_item(raw: dict, t: I18n, iid: str | None, count) -> dict | None:
    """材料/代币统一提炼为 {id, name, count};无 id 返回 None,名称 join ItemTable。"""
    if not iid:
        return None
    item = raw["ItemTable"].get(iid) or {}
    return {"id": iid, "name": t(item.get("name")) or iid, "count": count}


def collect_scripts(raw: dict, t: I18n) -> dict[str, dict]:
    """EquipCostMaterialTable:工艺原件(图纸)粒度的工艺名与解锁途径。

    仅 T4 系列图纸(item_equip_script_4*)有独立条目(4 张工艺表共用
    chainId 4000-4003 与 EquipFormulaChainTable 对齐);T1-T3 图纸无解锁配置。
    obtainWay 为原始资源 id(解包表中无对应名称表),如实保留。
    """
    out = {}
    for sid, s in raw["EquipCostMaterialTable"].items():
        out[sid] = {
            "craftName": t(s.get("scriptName")),
            "unlockMission": s.get("unlockScriptMission") or None,
            "obtainWays": s.get("unlockScriptObtainWay") or None,
            "recommended": s.get("isRecommended"),
        }
    return out


def collect_craft_options(raw: dict, t: I18n) -> dict[str, list[dict]]:
    """EquipFormulaChainTable:合成档位(level)→ 可选加工链列表。

    合成消耗按档位组织而非逐件:同档位装备共用一份配方;多条链表示可用
    不同图纸合成(如 T4 可走息壤/赤铜/赫铜/灼铜工艺,灼铜链 cnDiscount≈0.01
    即代币消耗 1 折)。gold 为领域代币(调度券),materials 为图纸/普通材料,
    图纸条目并入 EquipCostMaterialTable 的工艺名与解锁信息。
    """
    scripts = collect_scripts(raw, t)
    out = {}
    for level, cfg in raw["EquipFormulaChainTable"].items():
        opts = []
        for ch in cfg.get("chainList") or []:
            ids, nums = ch.get("costItemId") or [], ch.get("costItemNum") or []
            materials = []
            for iid, cnt in zip(ids, nums, strict=False):
                mat = cost_item(raw, t, iid, cnt)
                script = scripts.get(iid)
                if mat is not None and script:
                    mat.update({k: v for k, v in script.items() if v is not None})
                materials.append(mat)
            opts.append({
                "chainId": ch.get("chainId"),
                "discount": ch.get("cnDiscount"),
                "isDefault": ch.get("isDefault"),
                "gold": cost_item(raw, t, ch.get("costGoldId"), ch.get("costGoldNum")),
                "materials": materials,
            })
        out[level] = opts
    return out


def formula_of(raw: dict, t: I18n, eid: str, craft_options: dict) -> dict | None:
    """EquipFormulaTable 按 outcomeEquipId 反查单件装备的合成公式。

    equipId→formulaId 优先用 ReverseTable(游戏自带反查索引),缺失时回退
    正向扫描;craftOptions 为该装备档位的全部可选加工链(见 collect_craft_options)。
    """
    f = raw["EquipFormulaTable"].get(raw["EquipFormulaReverseTable"].get(eid) or "")
    if not f:
        f = next((v for v in raw["EquipFormulaTable"].values()
                  if v.get("outcomeEquipId") == eid), None)
    if not f:
        return None
    pack = raw["EquipPackTable"].get(f.get("packId") or "", {})
    key, utype = f.get("unlockKey"), f.get("unlockType")
    return {
        "formulaId": f.get("formulaId"),
        "level": f.get("level"),
        "packId": f.get("packId") or None,
        "packName": t(pack.get("name")),
        "unlock": ({"key": key or None, "type": utype, "value": f.get("unlockValue")}
                   if (key or utype) else None),
        "craftOptions": craft_options.get(f.get("level")) or [],
    }


def build_enhance(raw: dict, t: I18n) -> dict:
    """强化为全局系统(非逐件配置):消耗/返还按领域配置(当前仅 domain_2),
    保底次数规则全局三档;具体装备经词条的 enhanceGuaranteeTimesRuleId 引用
    (equips[].enhancePity),此处只放定义,不逐件展开。"""
    costs = []
    for did, c in raw["EquipEnhanceCostTable"].items():
        costs.append({
            "domainId": did,
            "consume": cost_item(raw, t, c.get("consumeItemId"), c.get("consumeItemCnt")),
            "returnback": cost_item(raw, t, c.get("returnbackItemId"), c.get("returnbackItemCnt")),
        })
    rules = {}
    for rid, r in raw["EquipEnhanceGuaranteeTimesRuleTable"].items():
        rules[rid] = {k: r[k] for k in ("GuaranteeTimes1", "GuaranteeTimes2", "GuaranteeTimes3")
                      if k in r}
    return {"costs": costs, "guaranteeRules": rules}


def build(raw: dict, t: I18n) -> dict:
    # partType 整数 → 部位标签(从装备 id 中的 _body_/_hand_/_edc_ 反推)
    part_by_int: dict = {}
    for eid, e in raw["EquipTable"].items():
        for tag in ("body", "hand", "edc"):
            if f"_{tag}_" in eid:
                part_by_int.setdefault(e.get("partType"), tag)

    craft_options = collect_craft_options(raw, t)
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
        # 强化保底:词条自带规则引用(baseAttr 实测不携带,仍兜底收集)
        pity = {m.get("enhanceGuaranteeTimesRuleId")
                for m in e.get("displayAttrModifiers") or []
                if m.get("enhanceGuaranteeTimesRuleId")}
        base_rule = (base or {}).get("enhanceGuaranteeTimesRuleId")
        if base_rule:
            pity.add(base_rule)
        equips.append({
            "id": eid,
            "name": t(item.get("name")) or eid,
            "part": part,
            "suit": e.get("suitID") or None,
            "rarity": item.get("rarity"),
            "minWearLv": e.get("minWearLv"),
            "icon": item.get("iconId"),
            "baseAttr": {"type": attr_name(base.get("attrType")), "value": base.get("attrValue")} if base else None,
            "attrs": mods,
            "formula": formula_of(raw, t, eid, craft_options),
            "enhancePity": sorted(pity) or None,
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
            "effects": suit_effects(raw, t, tiers),
        })
    suits.sort(key=lambda x: x["id"])
    return {"equips": equips, "suits": suits, "enhance": build_enhance(raw, t)}


def write(payload: dict) -> None:
    """每件装备一个独立文件,按所属套装子目录存放(suit 字段 = 子目录名,
    无套装的入 unknown);套装与强化规则为全局配置,整体在 _global.json。

    index.json 只是清单:按 suit 分组的装备 id 列表;formula/enhancePity 等
    一切内容都在子文件里,不在索引中重复。
    """
    def subdir(e: dict) -> str:
        return e.get("suit") or "unknown"

    def finalize(_rows: list, entries: list[dict]) -> dict:
        grouped: dict[str, list] = {}
        for e in entries:
            grouped.setdefault(subdir(e), []).append(e["id"])
        return dict(sorted(grouped.items()))

    dump_dir(PRODUCT, payload["equips"], subdir=subdir,
             index_map=lambda e: e["id"], index_finalize=finalize)
    dest = DATA_DIR / PRODUCT / "_global.json"
    dest.write_text(json.dumps({"suits": payload["suits"], "enhance": payload["enhance"]},
                               ensure_ascii=False, indent=2), encoding="utf-8")


def main(force: bool = False) -> None:
    raw = load_tables(REQUIRED_TABLES, force=force)
    write(build(raw, I18n(raw[i18n_table()])))


if __name__ == "__main__":
    main()
