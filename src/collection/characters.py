"""采集+初步处理(多数据源综合):干员数据集 → data/characters/ 目录。

输出:每名干员一个 chr_<charId>.json + 轻量索引 index.json;技能按官方分组
输出 skillGroupMap(键 = <charId>_<族>,skillList 与 SkillPatchTable 键一一
对应,附属入 unknown);突破阶段(CharBreakStageTable,全局共享、
与具体干员无关)独立写入 _global.json。

数据来源与贡献:
    - rmxlinux/EndfieldData@TableCfg(本地 git):身份、职业、稀有度、
      1 级/满级面板(CharacterTable×CharProfessionTable×CharBreakTable)
    - rmxlinux@TableCfg/SkillPatchTable:每个干员的技能数值
      (名称/描述经 i18n 反查、冷却、费用、blackboard 数值板)
    - AndreaFrederica/jei-web(本地 git,森空岛 Wiki 干员包):Wiki 条目 ID、
      站外图标、稀有度交叉验证(名称 join,管理员按 charId 后缀特判)
    - 游戏内图标路径(CharacterTable.charId / CharProfessionTable.iconId):
      只存裸 id(icon / professionIcon),站点构建期由 icon_git 源本地化注入 URL
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from difflib import SequenceMatcher

from tools.tables import (
    ATTRACTIONS_OF_INTEREST,
    DATA_DIR,
    I18n,
    dump_dir,
    i18n_table,
    flat_attrs,
    load_tables,
)
from tools.datasource import repo_dir

PRODUCT = "characters"

REQUIRED_TABLES = [
    "CharacterTable", "CharProfessionTable", "CharBreakTable",
    "SkillPatchTable", "I18nTextTable_CN", "CharGrowthTable",
    "I18nTextTable_EN", "I18nTextTable_JP", "I18nTextTable_KR",
    "CharacterPotentialTable", "PotentialTalentEffectTable",
    "WeaponBasicTable", "CharWpnRecommendTable",
    "CharBattleTagTable", "CharacterTagTable", "CharacterTagDesTable",
    "CharBreakStageTable", "CharBreakNodeTable",
]

WIKI_REPO = "AndreaFrederica/jei-web"
WIKI_PACK_DIR = "public/packs/aef-skland/items/终末地百科/干员"


def _pack_file(repo: str, pack_dir: str, name: str) -> bytes | None:
    """优先直读工作区已检出的文件;partial 克隆缺失时回退 git cat-file。"""
    f = repo_dir(repo) / pack_dir / name
    if f.is_file():
        return f.read_bytes()
    return _git_bytes(repo, "cat-file", "blob", f"HEAD:{pack_dir}/{name}")


def _git_bytes(repo: str, *args, timeout: int = 300) -> bytes | None:
    d = repo_dir(repo)
    r = subprocess.run(["git", "-C", str(d), *args],
                       capture_output=True, timeout=timeout)
    return r.stdout if r.returncode == 0 else None


def load_wiki_operators() -> dict[str, dict]:
    """从 jei-web 森空岛 Wiki 干员包提取 name → {itemId, rarityStars, icon, detail}。

    文件路径含中文,git 命令用 -z 避免路径转义;懒取 blob 失败时重试。
    """
    out = {}
    listing = _git_bytes(WIKI_REPO, "ls-tree", "-z", "--name-only", f"HEAD:{WIKI_PACK_DIR}")
    if not listing:
        return out
    files = [f for f in listing.decode("utf-8").split("\0") if f.endswith(".json")]
    for f in files:
        for attempt in range(3):
            raw = _pack_file(WIKI_REPO, WIKI_PACK_DIR, f)
            if not raw:
                time.sleep(2 * (attempt + 1))
                continue
            try:
                d = json.loads(raw)
                extra = ((d.get("wiki") or {}).get("data") or {}).get("item", {}).get("extraInfo") or {}
                out[d.get("name", "?")] = {
                    "itemId": (d.get("wiki") or {}).get("data", {}).get("item", {}).get("itemId"),
                    "rarityStars": (d.get("rarity") or {}).get("stars"),
                    "icon": d.get("icon"),
                    "illustration": extra.get("illustration"),
                    "detail": extract_wiki_detail(d),
                }
                break
            except Exception:  # noqa: BLE001 - 损坏条目跳过
                time.sleep(2 * (attempt + 1))
    return out


def _walk_text(block_map: dict, block_id: str, out: list, depth: int = 0) -> None:
    """递归收集一个(组)块的全部文本(inlineElements 顺序拼接)。

    嵌套文档块(如技能卡的描述/正文)自带独立 blockMap,子块优先查它。
    """
    b = block_map.get(block_id)
    if not b or depth > 16:
        return
    txt = b.get("text") or (b.get("data") or {}).get("text") or {}
    for ie in txt.get("inlineElements") or []:
        t = (ie.get("text") or {}).get("text")
        if t:
            out.append(t)
    child_map = b.get("blockMap") or block_map
    for child in b.get("blockIds") or []:
        _walk_text(child_map, child, out, depth + 1)


def extract_wiki_detail(wiki_json: dict) -> dict:
    """解析森空岛 Wiki 文档:按章节输出组件内容(资料表格/技能与天赋卡片)。"""
    doc = ((wiki_json.get("wiki") or {}).get("data") or {}).get("item", {}).get("document") or {}
    bm = doc.get("documentMap") or {}
    wcm = doc.get("widgetCommonMap") or {}

    def widget_info(widget_id: str) -> dict | None:
        w = wcm.get(widget_id)
        if not w:
            return None
        titles = {t.get("tabId"): t.get("title", "") for t in w.get("tabList") or []}
        tabs = []
        for tab_id, tab in (w.get("tabDataMap") or {}).items():
            out: list[str] = []
            _walk_text(bm, tab.get("content"), out)
            desc_out: list[str] = []
            intro = tab.get("intro") or {}
            desc_ref = intro.get("description")
            if isinstance(desc_ref, str):
                _walk_text(bm, desc_ref, desc_out)
            tabs.append({
                "name": intro.get("name") or titles.get(tab_id, ""),
                "type": intro.get("type"),
                "imgUrl": intro.get("imgUrl"),
                "desc": "".join(desc_out),
                "text": "".join(out),
            })
        table = [{"label": r.get("label"), "value": r.get("value")}
                 for r in w.get("tableList") or []]
        return {"table": table, "tabs": tabs}

    chapters_out = []
    for ch in doc.get("chapterGroup") or []:
        widgets = []
        for w in ch.get("widgets") or []:
            info = widget_info(w.get("id"))
            if info:
                widgets.append({"title": w.get("title"), **info})
        chapters_out.append({"title": ch.get("title"), "widgets": widgets})
    return {"chapters": chapters_out}


def _repo_json(repo: str, relpath: str) -> dict | None:
    """直读本地克隆工作树中的 JSON 文件(完整克隆已物化),缺失返回 None。"""
    f = repo_dir(repo) / relpath
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _blackboard_values(buff_json: dict | None) -> dict:
    """BuffData 的 blackboard → {key: value}(潜能描述占位符的真实数值)。"""
    if not buff_json:
        return {}
    return {x.get("key"): x.get("valueDouble", x.get("value"))
            for x in buff_json.get("blackboard") or []}


def _char_id_of(skill_id: str) -> str:
    """技能 ID 前三段即干员 ID(如 chr_0005_chen_xxx → chr_0005_chen)。"""
    return "_".join(skill_id.split("_")[:3])


def _skill_group_index(raw: dict, t: I18n) -> dict:
    """CharGrowthTable.skillGroupMap 解析 → 每个技能的官方分类与文本。

    SkillPatchTable 的 skillName/description 哈希对全部干员均为 0,
    技能名称/描述的官方文本实际挂在 CharGrowthTable.skillGroupMap
    (name/desc → I18nTextTable)。每组的 skillGroupType 即主技能槽位:
        0=普攻(NormalAttack) 1=战技(NormalSkill)
        2=终结(UltimateSkill) 3=连携(ComboSkill)
    组的 skillIdList 覆盖该槽位下全部分段/形态变体(attack1..5、
    power_attack、floating 系等)。返回三部分:
        groups — 组完整解析(gid → 全部源字段:i18n 引用已反查为文本、
                 富文本标签原样保留、skillIdList 原样),供 skillGroupMap 输出;
        exact  — skillIdList 逐 id 精确 join;
        family — 少数 skill 行与 idList 对不上(如 typhoea 终结技的
                 `_skillfloating` 变体 id),退化为 (干员, 技能族) 匹配
                 (族名 = 组键去掉干员前缀,归一化大小写与下划线比较)。
    注意:idList 仅接受本干员前缀的 skillId——chr_9000_endmin(NPC 占位)
    的组引用的是 endminm/endminf 的技能 id,必须排除(源表里唯一的多对多
    即此情形;同一干员内仍是一对多)。
    """
    exact: dict[str, dict] = {}
    family: dict[tuple[str, str], dict] = {}
    groups: dict[str, dict] = {}
    for growth in (raw.get("CharGrowthTable") or {}).values():
        cid = growth.get("charId")
        for gid, group in (growth.get("skillGroupMap") or {}).items():
            resolved = {k: (t(v) or "" if isinstance(v, dict) else v)
                        for k, v in group.items() if k != "skillIdList"}
            groups[gid] = resolved
            family_name = gid[len(cid) + 1:] if cid and gid.startswith(cid + "_") else gid
            for sid in group.get("skillIdList") or []:
                if cid and sid.startswith(cid + "_"):
                    exact[sid] = resolved
            if cid and family_name != gid:
                family[(cid, family_name.replace("_", "").lower())] = resolved
    return {"exact": exact, "family": family, "groups": groups}


def _official_skill_entry(group_index: dict, sid: str, cid: str) -> dict | None:
    entry = group_index["exact"].get(sid)
    if entry is None and sid.startswith(cid + "_"):
        rest = sid[len(cid) + 1:].replace("_", "").lower()
        entry = group_index["family"].get((cid, rest))
    return entry


def _resolve_i18n_deep(v, t: I18n):
    """递归解析数据内的 i18n 引用({id, text} 形状 → 文本,富文本标签保留),
    其余结构原样透传(如 requiredItem 的 {count, id} 不受影响)。"""
    if isinstance(v, list):
        return [_resolve_i18n_deep(x, t) for x in v]
    if isinstance(v, dict):
        if v and set(v.keys()) <= {"id", "text"}:
            return t(v) or ""
        return {k: _resolve_i18n_deep(x, t) for k, x in v.items()}
    return v


def collect_skills(raw: dict, t: I18n, group_index: dict) -> dict[str, list[dict]]:
    """SkillPatchTable 按(干员, 技能)分组,等级补丁聚合为 levels 列表。

    技能分类与名称/描述:官方取 CharGrowthTable.skillGroupMap(见
    _skill_group_index,富文本标签原样保留),SkillPatchTable 行内的哈希
    恒为 0;Wiki 回填(见 _enriched_skills)只补官方仍缺的名称/描述。
    有效数值信息是 blackboard 数值板与冷却/费用。
    """
    grouped: dict[tuple[str, str], dict] = {}
    for sid, entry in raw["SkillPatchTable"].items():
        cid = _char_id_of(sid)
        for patch in entry.get("SkillPatchDataBundle") or []:
            key = (cid, sid)
            off = _official_skill_entry(group_index, sid, cid) or {}
            sk = grouped.setdefault(key, {
                "skillId": sid,
                "name": off.get("name") or t(patch.get("skillName")),
                "desc": off.get("desc") or t(patch.get("description")),
                "skillGroupId": off.get("skillGroupId"),
                "skillGroupType": off.get("skillGroupType"),
                "coolDown": patch.get("coolDown"),
                "costType": patch.get("costType"),
                "costValue": patch.get("costValue"),
                "iconId": patch.get("iconId"),
                "levels": [],
            })
            sk["levels"].append({
                "level": patch.get("level"),
                "blackboard": {b.get("key"): b.get("value")
                               for b in patch.get("blackboard") or []},
            })
    by_char: dict[str, list[dict]] = {}
    for (cid, _sid), sk in grouped.items():
        sk["levels"].sort(key=lambda x: (x["level"] is None, x["level"]))
        by_char.setdefault(cid, []).append(sk)
    return by_char


def build(raw: dict, t: I18n, wiki_ops: dict[str, dict] | None = None) -> list[dict]:
    wiki_ops = wiki_ops or load_wiki_operators()
    professions = {v["profession"]: (t(v.get("name")), v.get("iconId"))
                   for v in raw["CharProfessionTable"].values()}
    max_level = max(int(v.get("maxLevel", 0)) for v in raw["CharBreakTable"].values())
    group_index = _skill_group_index(raw, t)
    skills_by_char = collect_skills(raw, t, group_index)
    # CV 名各按其语言表反查(中/英/日/韩原生写法),与 --lang 默认语言无关
    cv_resolvers = {k: I18n(raw[n]) for k, n in (
        ("ChiCVName", "I18nTextTable_CN"), ("EngCVName", "I18nTextTable_EN"),
        ("JapCVName", "I18nTextTable_JP"), ("KorCVName", "I18nTextTable_KR")) if n in raw}

    characters = []
    # 突破阶段(各技能等级上限):全局表,与具体干员无关(实测 33 名干员完全一致),
    # 独立写入 _global.json,不随干员文件重复
    break_stages = [{"stage": b.get("breakStage"), "maxLevel": b.get("maxCharLevel"),
                     "skillLevels": {"normalAttack": b.get("normalAttackSkillLevel"),
                                     "normal": b.get("normalSkillLevel"),
                                     "combo": b.get("comboSkillLevel"),
                                     "ultimate": b.get("ultimateSkillLevel")}}
                    for b in (raw["CharBreakStageTable"] or {}).values()]
    # 天赋节点(CharGrowthTable.talentNodeMap,与数据源同构):nodeType
    # 1=突破 2=装备破解 3=天赋(属性加成/好感度) 4=被动技能 5=工厂技能,
    # 节点内 i18n 引用已递归反查为文本(富文本标签保留)
    growth_map = {g["charId"]: g for g in (raw.get("CharGrowthTable") or {}).values()}
    talent_map = {cid: _resolve_i18n_deep(g["talentNodeMap"], t)
                  for cid, g in growth_map.items() if g.get("talentNodeMap")}
    for cid, c in raw["CharacterTable"].items():
        lv1, lv_max = {}, {}
        for seg in c.get("attributes", []):
            attrs = flat_attrs((seg.get("Attribute") or {}).get("attrs"))
            if attrs.get("Level") == 1 and not lv1:
                lv1 = attrs
            lv_max = attrs or lv_max
        _prof_name, _prof_icon = professions.get(c.get("profession"), (None, None))

        # Wiki 关联:显示名精确 join;管理员按 charId 后缀(m/f)特判
        c_name = t(c.get("name")) or cid
        w = wiki_ops.get(c_name)
        if cid.endswith("endminm"):
            w = wiki_ops.get("管理员 (男)", w)
        elif cid.endswith("endminf"):
            w = wiki_ops.get("管理员 (女)", w)

        # 技能名称/描述回填:Wiki「战斗技能」页签按类型对应技能族
        skill_family_names: dict[str, tuple[str, str | None]] = {}
        if w and w.get("detail"):
            for ch_detail in w["detail"]["chapters"]:
                for wd in ch_detail.get("widgets") or []:
                    if wd.get("title") == "战斗技能":
                        for tab in wd.get("tabs") or []:
                            if tab.get("type"):
                                skill_family_names[tab["type"]] = (tab.get("name"), tab.get("desc"))

        def _enriched_skills(skills: list[dict]) -> list[dict]:
            def family_of(skill_id: str) -> str | None:
                if "normal_skill" in skill_id:
                    return "战技"
                if "combo_skill" in skill_id:
                    return "连携技"
                if "ultimate_skill" in skill_id:
                    return "终结技"
                if any(k in skill_id for k in ("attack", "power_attack", "dash_attack", "plunging_attack")):
                    return "普通攻击"
                return None
            out = []
            for sk in sorted(skills, key=lambda x: x["skillId"]):
                sk = dict(sk)
                family = family_of(sk["skillId"])
                if family and family in skill_family_names and not sk.get("name"):
                    nm, ds = skill_family_names[family]
                    if nm:
                        sk["name"] = nm
                    if ds and not sk.get("desc"):
                        sk["desc"] = ds
                out.append(sk)
            return out

        # 潜能/天赋:CharacterPotentialTable(解锁链)× PotentialTalentEffectTable(效果)
        pot_entry = raw["CharacterPotentialTable"].get(cid)
        potentials = []
        for b in (pot_entry or {}).get("potentialUnlockBundle") or []:
            effect_id = b.get("potentialEffectId")
            effect = raw["PotentialTalentEffectTable"].get(effect_id, {})
            desc = re.sub(r"<[^>]+>", "", t(effect.get("desc")) or "")
            materials = [{"id": i, "count": c2}
                         for i, c2 in zip(b.get("itemIds") or [], b.get("itemCnts") or [])]
            skills_hit = sorted({(d.get("attachSkill") or {}).get("skillId")
                                 for d in effect.get("dataList") or []
                                 if (d.get("attachSkill") or {}).get("skillId")})
            buff_json = _repo_json("rmxlinux/EndfieldData",
                                   f"Json/BuffData/buff_{cid}_potential_{b.get('level')}.json")
            potentials.append({
                "level": b.get("level"),
                "name": t(b.get("name")),
                "desc": desc or None,
                "values": _blackboard_values(buff_json) or None,
                "effectId": effect_id,
                "materials": materials,
                "skills": skills_hit,
            })

        # 专武与推荐武器
        dwid = c.get("defaultWeaponId")
        dw = raw["WeaponBasicTable"].get(dwid) if dwid else None
        weapon = ({"id": dwid, "name": t(dw.get("engName")) or dwid,
                   "rarity": dw.get("rarity")} if dw else None)
        rec = raw["CharWpnRecommendTable"].get(cid, {})
        recommended = {tier: [t(raw["WeaponBasicTable"].get(w, {}).get("engName")) or w
                              for w in rec.get(tier) or []]
                       for tier in ("weaponIds1", "weaponIds2", "weaponIds3")}

        # 战斗标签与派驻(基建)标签描述
        battle_tags = raw["CharBattleTagTable"]
        battle_tag_names = [t(battle_tags.get(x)) for x in c.get("charBattleTagIds") or []]
        tag_des = raw["CharacterTagDesTable"].get(cid, {}).get("tagDesc") or {}
        station_tags = []
        for tag_id, td in tag_des.items():
            desc = re.sub(r"<[^>]+>", "", t(td.get("desc")) or "")
            station_tags.append({"tag": tag_id.replace("tag_expert_", "").replace("tag_hobby_", ""),
                                 "desc": desc or None})

        # 表现层数据:SkillData 的施法消耗与关联 Buff(本地 Json/SkillData)
        for sk in skills_by_char.get(cid, []):
            sd = _repo_json("rmxlinux/EndfieldData", f"Json/SkillData/{sk['skillId']}.json")
            if sd:
                cost = ((sd.get("castData") or {}).get("costData") or {}).get("costValue")
                if cost:
                    sk["castCost"] = cost
                if sd.get("buffs"):
                    sk["buffs"] = sd.get("buffs")

        raw_cv = c.get("cvName") or {}
        cv_view = {k: cv_resolvers[k](raw_cv[k]) or None
                   for k in ("ChiCVName", "EngCVName", "JapCVName", "KorCVName")
                   if raw_cv.get(k)} or None
        characters.append({
            "id": cid,
            "name": c_name,
            "enName": c.get("engName"),
            "profession": c.get("profession"),
            "professionName": _prof_name,
            "professionIcon": _prof_icon,
            "icon": f"icon_{cid}",
            "rarity": c.get("rarity"),
            "weaponType": c.get("weaponType"),
            "cv": cv_view,
            "maxLevel": max_level,
            "lv1": {k: lv1.get(k) for k in ATTRACTIONS_OF_INTEREST},
            "lvMax": {k: lv_max.get(k) for k in ATTRACTIONS_OF_INTEREST},
            "skills": _enriched_skills(skills_by_char.get(cid, [])),
            "potentials": potentials,
            "weapon": weapon,
            "recommendedWeapons": recommended,
            "battleTags": [n for n in battle_tag_names if n],
            "stationTags": station_tags,
            "talentNodeMap": talent_map.get(cid) or None,
            "charTypeId": growth_map.get(cid, {}).get("charTypeId"),
            "mainAttrType": growth_map.get(cid, {}).get("mainAttrType"),
            "subAttrType": growth_map.get(cid, {}).get("subAttrType"),
            "charBreakCostMap": _resolve_i18n_deep(growth_map.get(cid, {}).get("charBreakCostMap"), t) or None,
            "skillLevelUp": _resolve_i18n_deep(growth_map.get(cid, {}).get("skillLevelUp"), t) or None,
            "wiki": ({"itemId": w["itemId"], "rarityStars": w["rarityStars"],
                      "icon": w["icon"], "illustration": w.get("illustration"),
                      "detail": w.get("detail")} if w else None),
            "sources": ["rmxlinux@TableCfg", "rmxlinux@SkillPatchTable",
                        "rmxlinux@养成/武器/标签相关表"]
                       + (["jei-web@森空岛Wiki干员包"] if w else []),
        })
    characters.sort(key=lambda x: (-(x["rarity"] or 0), x["id"]))

    # 技能按官方分组输出:skillGroupMap = {组 id: 完整解析后的源组字段
    # (condition*/icon/name/desc/skillGroupId/skillGroupType/skillIdList,
    # i18n 引用已反查为文本、富文本保留)+ skillList(按 SkillPatchTable 键
    # 逐一展开的成员,一个成员 = 一个 skillId,含数值相同的形态变体,
    # 忠实源数据不合并)。未入组的附属技能(被动、个别变体)入 "unknown"
    # (对齐 equips 无套装的约定;无源组字段,仅成员 + 回填的 name/desc)。
    for c in characters:
        raw_map: dict[str, list[dict]] = {}
        for sk in c.pop("skills") or []:
            gid = sk.pop("skillGroupId", None) or "unknown"
            sk.pop("skillGroupType", None)
            raw_map.setdefault(gid, []).append(sk)

        skill_group_map: dict[str, dict] = {}
        for gid, members in raw_map.items():
            src = group_index["groups"].get(gid) or {}
            name, desc = src.get("name"), src.get("desc")
            uniform_text = all(m.get("name") == name and m.get("desc") == desc
                               for m in members)
            skill_list = []
            for m in members:
                mem = {"skillId": m["skillId"]}
                if not uniform_text:
                    mem.update({k: m.get(k) for k in ("name", "desc") if m.get(k) is not None})
                mem.update({k: m.get(k) for k in
                            ("iconId", "coolDown", "costType", "costValue", "castCost", "buffs", "levels")
                            if m.get(k) is not None})
                skill_list.append(mem)
            grp = dict(src)
            grp["skillList"] = skill_list
            if "name" not in grp and name is not None:
                grp["name"] = name  # unknown 组:无源字段,回填首个成员文本
            if "desc" not in grp and desc is not None:
                grp["desc"] = desc
            skill_group_map[gid] = grp

        # 排序:主技能槽 0普攻/1战技/2终结/3连携 在前,其余(unknown)垫底
        order_key = lambda item: (item[1].get("skillGroupType") is None,
                                  item[1].get("skillGroupType") if item[1].get("skillGroupType") is not None else 99,
                                  item[0])
        c["skillGroupMap"] = dict(sorted(skill_group_map.items(), key=order_key))

    return {"characters": characters, "breakStages": break_stages}


def write(payload: dict) -> None:
    """每名干员一个独立文件 + 轻量索引 index.json(列表页用,不含技能详情)。

    突破阶段(CharBreakStageTable,全局共享、与干员无关)独立写入 _global.json,
    不在干员文件与索引中重复。
    """
    dump_dir(PRODUCT, payload["characters"],
             exclude_index=("skills", "skillGroupMap", "potentials", "talentNodeMap",
                            "charBreakCostMap", "skillLevelUp", "wiki", "sources"))
    dest = DATA_DIR / PRODUCT / "_global.json"
    dest.write_text(json.dumps({"breakStages": payload["breakStages"]},
                               ensure_ascii=False, indent=2), encoding="utf-8")


def main(force: bool = False) -> None:
    raw = load_tables(REQUIRED_TABLES, force=force)
    wiki_ops = load_wiki_operators()
    write(build(raw, I18n(raw[i18n_table()]), wiki_ops))


if __name__ == "__main__":
    main()
