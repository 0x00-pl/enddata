"""采集+初步处理(多数据源综合):武器数据集 → data/weapons/ 目录。

数据来源与贡献(rmxlinux/EndfieldData@TableCfg,本地 git 直读):
    - WeaponBasicTable:身份、名称/武器描述(i18n 反查)、稀有度、类型、
      满级、潜能提升道具(potentialUpItemList)
    - SkillPatchTable:潜能技能(weaponPotentialSkill,sk_wpn_*)分级补丁——
      名称/描述经 i18n 反查(武器技能哈希全部非 0,711/711 可解析)、
      blackboard 数值板按 level 列表、描述 {key:fmt} 占位符按各等级数值回填
    - WeaponTalentTemplateTable:天赋等级(talentLv)→ 各技能位等级加成区间
      (技能位下标与 weaponSkillList 对齐,实测 395/395 命中潜能技能位)
    - WeaponUpgradeTemplateTable / WeaponUpgradeTemplateSumTable:
      升级曲线摘要(1 级/满级基础攻击力、满级累计经验与龙门币)
    - WeaponBreakThroughTemplateTable:突破阶段(所需等级、龙门币、材料、
      各技能位等级区间)
"""

from __future__ import annotations

import re

from tools.tables import I18n, dump_dir, load_tables

PRODUCT = "weapons"

REQUIRED_TABLES = [
    "WeaponBasicTable", "I18nTextTable_CN",
    "SkillPatchTable",
    "WeaponTalentTemplateTable",
    "WeaponUpgradeTemplateTable", "WeaponUpgradeTemplateSumTable",
    "WeaponBreakThroughTemplateTable",
]

# 技能描述富文本标签(<@ba.vup>…</> 等)与数值占位符({atk_up:0.0%};
# 少量为键乘积 {spell_dmg_up2*max_stack:0.0%} 或键带尾随空格 {dmg_up :0.0%})
_TAG_RE = re.compile(r"<[^>]+>")
_PLACEHOLDER_RE = re.compile(r"\{\s*([A-Za-z_]\w*(?:\s*\*\s*[A-Za-z_]\w*)*)\s*(?::\s*([^}]+))?\}")


def _fmt_value(value: float, spec: str | None) -> str:
    """按占位符格式说明渲染数值:'0.0%'/'0%'→百分比,'0'/'0.0'/'0.00'→定点小数。"""
    if spec and spec.endswith("%"):
        num = spec[:-1]
        decimals = len(num.split(".")[-1]) if "." in num else 0
        return f"{value * 100:.{decimals}f}%"
    decimals = len(spec.split(".")[-1]) if spec and "." in spec else 0
    return f"{value:.{decimals}f}"


def _fill_desc(text: str | None, blackboard: dict) -> str | None:
    """剥离富文本标签,并用对应等级的 blackboard 回填 {key:fmt} 占位符。

    支持键乘积({a*b:0.0%});键查不到(含表内 'cd ' 带尾随空格的脏数据)
    时保留原样,如实呈现。
    """
    if not text:
        return None

    def lookup(key: str):
        v = blackboard.get(key, blackboard.get(key.strip()))
        return v if isinstance(v, (int, float)) else None

    def sub(m: re.Match) -> str:
        factors = [lookup(k) for k in m.group(1).split("*")]
        if any(v is None for v in factors):
            return m.group(0)
        v = 1.0
        for x in factors:
            v *= x
        return _fmt_value(v, m.group(2))

    return _PLACEHOLDER_RE.sub(sub, _TAG_RE.sub("", text)).strip()


def _blackboard(patch: dict) -> dict:
    return {b.get("key"): b.get("value") for b in patch.get("blackboard") or []}


def _bounds_with_skills(bounds: list[dict], skills: list) -> list[dict]:
    """技能位等级区间按下标对齐 weaponSkillList(列表外/未用的技能位留 null)。"""
    return [{"skill": skills[i] if i < len(skills) else None,
             "lowerBound": b.get("lowerBound"), "upperBound": b.get("upperBound")}
            for i, b in enumerate(bounds or [])]


def collect_potential_skill(raw: dict, t: I18n, weapon: dict) -> dict | None:
    """weaponPotentialSkill → SkillPatchTable 分级补丁(9 级/把)。

    名称/描述经 i18n 反查,哈希为 0 时如实留 null;blackboard 按 level 列表;
    各等级模板文本一致(当前 79/79)时只保留 1 级描述,变化等级单独给出。
    """
    sid = weapon.get("weaponPotentialSkill")
    patches = (raw["SkillPatchTable"].get(sid) or {}).get("SkillPatchDataBundle") or []
    if not patches:
        return None
    patches = sorted(patches, key=lambda p: (p.get("level") is None, p.get("level")))
    base_desc = t(patches[0].get("description"))
    levels = []
    for p in patches:
        bb = _blackboard(p)
        lv: dict = {"level": p.get("level"), "blackboard": bb}
        desc = t(p.get("description"))
        if desc and desc != base_desc:
            lv["desc"] = _fill_desc(desc, bb)
        levels.append(lv)
    return {
        "skillId": sid,
        "name": t(patches[0].get("skillName")),
        "desc": _fill_desc(base_desc, _blackboard(patches[0])),
        "levels": levels,
    }


def collect_talent(raw: dict, weapon: dict) -> dict | None:
    """talentTemplateId → WeaponTalentTemplateTable:talentLv 1..5 的技能位加成区间。"""
    tpl = (raw["WeaponTalentTemplateTable"].get(weapon.get("talentTemplateId")) or {}).get("list") or []
    if not tpl:
        return None
    skills = weapon.get("weaponSkillList") or []
    levels = [{"talentLv": item.get("talentLv"),
               "skillLevelExtraBounds": _bounds_with_skills(item.get("skillLevelExtraBounds"), skills)}
              for item in sorted(tpl, key=lambda x: (x.get("talentLv") is None, x.get("talentLv")))]
    return {"templateId": weapon.get("talentTemplateId"), "levels": levels}


def collect_upgrade(raw: dict, weapon: dict) -> dict | None:
    """levelTemplateId → 升级曲线摘要(1 级/满级攻击力、满级累计经验与龙门币)。"""
    tid = weapon.get("levelTemplateId")
    curve = (raw["WeaponUpgradeTemplateTable"].get(tid) or {}).get("list") or []
    if not curve:
        return None
    last_sum = ((raw["WeaponUpgradeTemplateSumTable"].get(tid) or {}).get("list") or [{}])[-1]
    return {
        "templateId": tid,
        "baseAtkLv1": curve[0].get("baseAtk"),
        "baseAtkMax": curve[-1].get("baseAtk"),
        "totalExp": last_sum.get("lvUpExpSum"),
        "totalGold": last_sum.get("lvUpGoldSum"),
    }


def collect_breakthrough(raw: dict, weapon: dict) -> dict | None:
    """breakthroughTemplateId → 突破阶段(stage 0 为初始态)。

    stage=breakthroughShowLv,level=breakthroughLv(达到该武器等级可突破),
    gold=breakthroughGold,materials=breakItemList,skillLevelBounds 原样保留
    并按 weaponSkillList 下标标注技能 id。
    """
    tpl = (raw["WeaponBreakThroughTemplateTable"].get(weapon.get("breakthroughTemplateId")) or {}).get("list") or []
    if not tpl:
        return None
    skills = weapon.get("weaponSkillList") or []
    stages = []
    for s in sorted(tpl, key=lambda x: (x.get("breakthroughShowLv") is None, x.get("breakthroughShowLv"))):
        stages.append({
            "stage": s.get("breakthroughShowLv"),
            "level": s.get("breakthroughLv"),
            "gold": s.get("breakthroughGold"),
            "materials": [{"id": m.get("id"), "count": m.get("count")}
                          for m in s.get("breakItemList") or []],
            "skillLevelBounds": _bounds_with_skills(s.get("skillLevelBounds"), skills),
        })
    return {"templateId": weapon.get("breakthroughTemplateId"), "stages": stages}


def build(raw: dict, t: I18n) -> list[dict]:
    weapons = []
    for wid, w in raw["WeaponBasicTable"].items():
        potential = collect_potential_skill(raw, t, w)
        weapons.append({
            "id": wid,
            "name": t(w.get("engName")) or wid,
            "desc": t(w.get("weaponDesc")),
            "rarity": w.get("rarity"),
            "weaponType": w.get("weaponType"),
            "maxLevel": w.get("maxLv"),
            "potentialSkill": potential,
            "talent": collect_talent(raw, w),
            "upgrade": collect_upgrade(raw, w),
            "breakthrough": collect_breakthrough(raw, w),
            "potentialUpItems": w.get("potentialUpItemList") or None,
            "sources": ["rmxlinux@TableCfg"]
                       + (["rmxlinux@SkillPatchTable"] if potential else []),
        })
    weapons.sort(key=lambda x: (-(x["rarity"] or 0), x["id"]))
    return weapons


def write(payload: list[dict]) -> None:
    """每把武器一个独立文件 + 轻量索引 index.json(列表页用,不含潜能/天赋/升级/突破详情)。"""
    dump_dir(PRODUCT, payload,
             exclude_index=("potentialSkill", "talent", "upgrade", "breakthrough", "sources"))


def main(force: bool = False) -> None:
    raw = load_tables(REQUIRED_TABLES, force=force)
    write(build(raw, I18n(raw["I18nTextTable_CN"])))


if __name__ == "__main__":
    main()
