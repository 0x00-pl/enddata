"""配队分析:解析每名干员的技能/天赋/潜能,提炼每条描述的需求资源与产出资源。

只读 data/characters/ 数据集。处理来源(skillGroupMap = 官方技能分组:
0普攻/1战技/2终结技/3连携技,附属变体入 unknown):
    技能  满级描述文案 + blackboard 中的治疗/护盾形态
    天赋  talentNodeMap 被动技能节点(passiveSkillNodeInfo,同点多等级取最高等级)
    潜能  CharacterPotentialTable 描述(potentials[].desc)

资源口径(报告按需求忽略技力/终结技能量/失衡值/冷却四项,不做提取):
    治疗/护盾   blackboard 中 heal*/shield* 键(只记形态,原始数值随条目保留)
    附着/异常状态/特殊资源  描述文案解析(元素附着、燃烧/导电/重击/猎矢/启示等)

流程:① 描述提取(技能/天赋/潜能三个提取函数,预处理 = 满级 + 标签剥离 +
blackboard 治疗/护盾提取)→ ② 注册 regex(需求/产出两张表,宽松捕获 + 后处理
函数精筛)→ ③ 针对每条描述提取需求和产出 → ④ 收集汇总 → 保存结果。

输出:
    reports/team-analysis.md       人读报告(只保留逐干员技能资源解析一张表)

用法:
    poetry run enddata analysis team    # 或 analysis.team_comp.main()

模型假设:满级数值;按一次施放/一套普攻连招(含下落·冲锋变体)计;不建模攻速与
敌方抗性;治疗/护盾不折算当量。文案解析为两张 regex 表(需求/产出)的宽松捕获 +
后处理函数精筛(_DEMAND_PATTERNS/_PRODUCE_PATTERNS)。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NamedTuple

from tools.tables import DATA_DIR, REPORTS_DIR

# ---------------------------------------------------------------- 常量
CHAR_DIR = DATA_DIR / "characters"
REPORT_PATH = REPORTS_DIR / "team-analysis.md"
# chr_9000_endmin:NPC 占位(管理员合体形态,skillGroupMap 为空),不参与分析
EXCLUDED_IDS = {"chr_9000_endmin"}

SLOT_NAMES = {0: "普攻", 1: "战技", 2: "终结技", 3: "连携技", None: "附属"}

# 资源机器键(中文名经 RESOURCE_LABELS 供报告展示)
RES_HEAL, RES_SHIELD = "heal", "shield"
RESOURCE_LABELS = {"heal": "治疗", "shield": "护盾"}

# blackboard 预处理正则(只提取治疗/护盾形态;数值资源按需求忽略,不做提取)
_DISPLAY_RE = re.compile(r"^display_|_display$")
_HEAL_RE = re.compile(r"heal")
_SHIELD_RE = re.compile(r"shield")

# ---------------------------------------------------------------- 数据对象
# 干员描述一律用显式成员变量的 dataclass,不用 dict(成员名与字段契约一致)。


@dataclass
class SkillRes:
    """一条技能描述的资源解析结果(同组变体在报告中合并为一行)。"""
    skillId: str
    name: str | None
    slot: str
    desc: str | None
    trigger: list[str]       # 连携技发动条件(文案解析,破防默认条件已剔除)
    descRes: dict | None     # {demands, productions} 文案解析
    support: dict | None     # {heal/shield: 原始数值键值}
    group: str | None = None
    groupId: str | None = None


@dataclass
class ExtraEntry:
    """天赋/潜能条目(descRes 由汇总阶段解析后回填)。"""
    kind: str                # 天赋 | 潜能
    name: str
    desc: str | None
    descRes: dict | None = None


@dataclass
class Operator:
    """一名干员的资源解析结果(技能 + 天赋/潜能条目)。"""
    id: str
    name: str
    skills: list[SkillRes]
    extras: list[ExtraEntry]


# ---------------------------------------------------------------- ① 描述提取
def _strip_tags(desc: str | None) -> str | None:
    """剥离富文本标签,得到 regex 匹配与报告展示共用的纯文本。"""
    if not desc:
        return desc
    return _DESC_TAG_RE.sub(r"\1", desc)


def analyze_skill(sk: dict, slot: str, group_name: str | None, desc: str | None) -> SkillRes:
    """预处理一条技能描述:提取满级 blackboard 中的治疗/护盾形态(文案解析见 ③)。"""
    levels = sk.get("levels") or []
    bb = (levels[-1] if levels else {}).get("blackboard") or {}
    support: dict[str, dict[str, float]] = {}
    for key, value in bb.items():
        if _DISPLAY_RE.search(key):
            continue
        if _SHIELD_RE.search(key):
            support.setdefault(RES_SHIELD, {})[key] = value
        elif _HEAL_RE.search(key):
            support.setdefault(RES_HEAL, {})[key] = value
    return SkillRes(
        skillId=sk.get("skillId"),
        name=sk.get("name") or group_name,
        slot=slot,
        desc=desc,
        trigger=[],
        descRes=None,
        support=support or None,
        group=group_name,
    )


def _extract_skill_res(entry: dict) -> list[SkillRes]:
    """技能组 → SkillRes 列表(按官方槽位排序,附属组垫底;记录组名/组 ID)。"""
    groups = entry.get("skillGroupMap") or {}
    ordered = sorted(groups.items(),
                     key=lambda kv: (kv[1].get("skillGroupType") is None,
                                     kv[1].get("skillGroupType") if
                                     kv[1].get("skillGroupType") is not None else 9))
    skills: list[SkillRes] = []
    for gid, g in ordered:
        slot = SLOT_NAMES.get(g.get("skillGroupType"), "附属")
        for sk in g.get("skillList") or []:
            # 成员描述缺失时(官方分组文本统一挂在组上)回退组描述
            parsed = analyze_skill(sk, slot, g.get("name"),
                                   _strip_tags(sk.get("desc") or g.get("desc")))
            parsed.group = g.get("name")
            parsed.groupId = gid
            skills.append(parsed)
    return skills


def _extract_talents(entry: dict) -> list[ExtraEntry]:
    """talentNodeMap 的被动技能节点 → 天赋条目(正式名称+描述,同点多等级取最高等级)。"""
    best: dict[str, tuple[int, str]] = {}
    for nodes in (entry.get("talentNodeMap") or {}).values():
        for n in nodes:
            ps = n.get("passiveSkillNodeInfo") or {}
            name, desc = ps.get("name"), ps.get("desc")
            if not name or not desc:
                continue
            level = ps.get("level") or 0
            if name not in best or level > best[name][0]:
                best[name] = (level, desc)
    out: list[ExtraEntry] = []
    for name, (_level, desc) in best.items():
        out.append(ExtraEntry(kind="天赋", name=name, desc=_strip_tags(desc)))
    return out


def _extract_potentials(entry: dict) -> list[ExtraEntry]:
    """potentials[].desc → 潜能条目。"""
    out: list[ExtraEntry] = []
    for p in entry.get("potentials") or []:
        out.append(ExtraEntry(kind="潜能",
                              name=p.get("name") or f"潜能·{p.get('level')}",
                              desc=_strip_tags(p.get("desc"))))
    return out


# ---------------------------------------------------------------- ② 注册 regex
# 需求/产出两张表:每项 = (名称, regex, 后处理函数)。regex 只宽松捕获触发词后的
# 片段,捕获组统一命名(需求表 demand / 产出表 produce);词条确认、修饰前缀、
# 句式细节过滤全在后处理函数里(返回 [] 即丢弃该命中)。新的自然语言习惯句式 =
# 加一条表项,勿在流程里加特判。
# 例:「<#ba.consume>消耗</>目标的<#ba.conduct>导电</>状态」→ 剥离为
#     「消耗目标的导电状态」→ 需求短语表捕获「导电状态」→ 后处理提取词条 → 需求 导电。
_DESC_TAG_RE = re.compile(r"<[@#]ba\.[a-z_]+>(.*?)</>", re.S)
_DESC_TERMS = (
    # 元素附着与异常状态(敌人身上的"资源")
    "灼热附着", "寒冷附着", "自然附着", "电磁附着", "法术附着",
    "导电", "燃烧", "冻结", "缓速", "虚弱", "碎甲", "破防",
    "物理异常", "法术异常", "物理脆弱", "法术脆弱", "涡流",
    "重击", "连击", "猛击", "倒地", "击飞", "腐蚀",
    # 干员特殊资源与召唤物(骏卫铁誓/莱万汀熔火/庄方宜青霆剑等)
    "猎矢", "启示", "熔火", "铁誓", "青霆剑", "盾卫", "源石结晶",
    # 团队生存状态
    "庇护",
)
# 词条交替需包成非捕获组,否则嵌入更长正则时 | 会拆散模式
_T = "(?:" + "|".join(map(re.escape, sorted(_DESC_TERMS, key=len, reverse=True))) + ")"
_TERM_RE = re.compile(_T)
# 否定排除:「不消耗技力与导电」「即使未消耗……」「不再施加灼热附着」
_DESC_NEG_KW = re.compile(r"(?:不|未|无需|不能)(?:再)?(?:消耗|施加)")


# ---- 后处理函数:regex 捕获的片段 → 最终展示文案(list[str];[] = 丢弃该命中) ----
def _extract_terms(text: str) -> list[str]:
    """片段内出现的全部资源词条(保序去重)。"""
    return list(dict.fromkeys(_TERM_RE.findall(text)))


def _post_terms(text: str) -> list[str]:
    """捕获片段中的资源词条原样保留:「施加缓速和法术脆弱」→ 缓速、法术脆弱。"""
    return _extract_terms(text)


def _post_passive_consume(text: str) -> list[str]:
    """被动消耗:「(灼热附着)被消耗」→ xx被消耗。"""
    return [f"{t}被消耗" for t in _extract_terms(text)]


def _post_cond_apply(text: str) -> list[str]:
    """条件句被动施加:「每当有敌人被施加(冻结)」→ 被施加xx。"""
    return [f"被施加{t}" for t in _extract_terms(text)]


def _post_state(text: str) -> list[str]:
    """被字状态:「被冻结」「被(附着)源石结晶」→ 被xx。

    「施加」开头的片段(「被施加缓速」,陈述施加行为)交由产出表处理,此处丢弃;
    链式片段(「冻结或被附着源石结晶」)逐词取各自的前缀。
    """
    if text.startswith("施加"):
        return []
    out: list[str] = []
    rest = text
    while True:
        mm = _TERM_RE.search(rest)
        if not mm:
            break
        head = re.search(r"(?:被附着|被)$", rest[:mm.start()])
        out.append((head.group() if head else "被") + mm.group())
        rest = rest[mm.end():]
    return out


def _post_demand_phrase(text: str) -> list[str]:
    """需求短语:「消耗目标的导电状态」→ 导电。

    片段中含「被施加」时以其为界:之前的词条是需求(处于/带有的状态),
    之后是被施加动作(交由产出表)。
    """
    if "被施加" in text:
        text = text.split("被施加")[0]
    return _extract_terms(text)


def _post_all_terms(text: str) -> list[str]:
    """整句(发动条件等)内的全部资源词条。"""
    return _extract_terms(text)


class DescPattern(NamedTuple):
    """regex 表条目:名称、宽松捕获正则(含唯一命名捕获组)、后处理函数。"""

    name: str
    regex: re.Pattern
    post: Callable[[str], list[str]]


# 需求 regex 表(优先级即列表顺序;捕获组统一命名 demand)
_DEMAND_PATTERNS: list[DescPattern] = [
    # 被动消耗:「(源石结晶)被消耗/被吸收」→ xx被消耗
    DescPattern("被动消耗",
                re.compile(rf"(?P<demand>[^，。;\n]{{0,8}})被(?:消耗|吸收|转化)"),
                _post_passive_consume),
    # 被字状态:「被冻结」「被附着源石结晶」→ 被xx
    DescPattern("状态前缀",
                re.compile(rf"被(?P<demand>[^，。;\n]{{0,10}})"), _post_state),
    # 条件句被动施加:「每当有敌人被施加(冻结)后」→ 被施加xx
    DescPattern("条件被动施加",
                re.compile(
                    rf"(?:每当|当|若|如果|一旦|每次)[^。;\n]{{0,12}}?被施加(?P<demand>[^，。;\n]{{0,10}})"),
                _post_cond_apply),
    # 需求短语:「消耗/带有/处于/存在/拥有/已满/进入/命中 + 片段」→ 片段内词条
    DescPattern("需求短语",
                re.compile(
                    rf"(?:消耗|带有|处于|存在|拥有|已满|进入|命中)(?P<demand>[^，。;\n]{{0,16}})"),
                _post_demand_phrase),
    # 发动条件:整句含「可以发动」,句内词条全部视为需求
    DescPattern("发动条件",
                re.compile(r"(?=[^。;\n]*可以发动)(?P<demand>[^。;\n]*)"), _post_all_terms),
]

# 产出 regex 表(捕获组统一命名 produce)
_PRODUCE_PATTERNS: list[DescPattern] = [
    # 施加/承受/转化:「施加导电」「转化为猎矢」「敌人持续受到缓速」
    # 「(目标)被施加缓速」(陈述句)→ xx
    DescPattern("施加产出",
                re.compile(
                    rf"(?:被施加|施加|附加|附带|附着|受到|转化为)(?P<produce>[^，。;\n]{{0,16}})"),
                _post_terms),
    # 获得/生成:「获得启示」「生成青霆剑」「召唤盾卫」→ xx
    DescPattern("获得产出",
                re.compile(rf"(?:获得|生成|召唤|返还|恢复)(?P<produce>[^，。;\n]{{0,12}})"),
                _post_terms),
]


# ---------------------------------------------------------------- ③ 提取需求和产出
def _apply_patterns(patterns: list[DescPattern], sent: str,
                    blocked_spans: list[tuple[int, int]] | None = None
                    ) -> tuple[list[str], list[tuple[int, int]]]:
    """一张 regex 表对一句话的全部命中(否定排除 + span 占用 + 去重,保序)。

    blocked_spans 为上游表(需求表)已占用的区间:同一段文字只归先匹配的表,
    避免需求捕获「被施加冻结」后产出表又以裸词条重复提取「冻结」。
    返回 (词条列表, 本表占用的区间;后处理返回空结果的命中不占用)。
    """
    out: list[str] = []
    spans: list[tuple[int, int]] = list(blocked_spans or [])
    for tpl in patterns:
        group = next(iter(tpl.regex.groupindex))  # 条目内唯一的命名捕获组(demand/produce)
        for m in tpl.regex.finditer(sent):
            if any(m.start() < e and s < m.end() for s, e in spans):
                continue
            if _DESC_NEG_KW.search(sent[max(0, m.start() - 6):m.start()]):
                continue
            items = [i for i in tpl.post(m.group(group)) if i and i not in out]
            if not items:
                continue
            spans.append(m.span())
            out.extend(items)
    return out, spans


def _parse_desc(desc: str | None) -> dict | None:
    """一条描述 → {demands, productions}(两张 regex 表)。

    demands 为展示文案(含「被消耗」「被施加」等修饰),productions 为资源词条;
    技力/终结技能量/失衡等已有 blackboard 数值的资源不在词表(避免与数值重复计)。
    """
    if not desc:
        return None
    plain = _DESC_TAG_RE.sub(r"\1", desc)
    demands: list[str] = []
    productions: list[str] = []
    for sent in re.split(r"[\n。;;]", plain):
        sent_demands, spans = _apply_patterns(_DEMAND_PATTERNS, sent)
        sent_productions, _ = _apply_patterns(_PRODUCE_PATTERNS, sent, spans)
        demands += [t for t in sent_demands if t not in demands]
        productions += [t for t in sent_productions if t not in productions]
    if not demands and not productions:
        return None
    return {"demands": demands, "productions": productions}


# ---------------------------------------------------------------- ④ 收集汇总
def _attach_desc_res(skills: list[SkillRes]) -> None:
    """针对每条技能描述提取需求和产出,就地写入 descRes。

    连携技的发动条件即触发需求,上提为 trigger(展示用);破防为默认条件且属
    失衡机制(报告按需求忽略),不单独保留。上提后其余全空 → 不留空壳 descRes。
    """
    for m in skills:
        desc_res = _parse_desc(m.desc)
        if m.slot == "连携技":
            trigger = (desc_res or {}).pop("demands", None) or []
            m.trigger = [t for t in trigger if t != "破防"]
        else:
            m.trigger = []
        m.descRes = desc_res if (desc_res and (desc_res.get("demands")
                                               or desc_res.get("productions"))) else None


def _is_attack(m: SkillRes) -> bool:
    """普攻连招成员:普攻组 + 附属组里的 attack* 变体(下落/冲锋)。"""
    return m.slot == "普攻" or (m.slot == "附属" and "attack" in (m.skillId or ""))


def analyze_character(entry: dict) -> Operator:
    """一名干员:提取多种描述(①)→ 逐条解析需求/产出(③)→ 汇总(④)。"""
    skills = _extract_skill_res(entry)
    extras = _extract_talents(entry) + _extract_potentials(entry)
    _attach_desc_res(skills)
    # 天赋/潜能逐条解析需求/产出,未命中的条目丢弃
    for x in extras:
        x.descRes = _parse_desc(x.desc)
    extras = [x for x in extras if x.descRes]
    return Operator(id=entry["id"], name=entry["name"],
                    skills=skills, extras=extras)


# ---------------------------------------------------------------- 报告渲染
def _fmt_demands(m: SkillRes) -> str:
    """需求列主格:仅连携技的发动条件词条;技力/终结技能量/冷却按需求忽略不展示。"""
    if m.slot == "连携技" and m.trigger:
        return "、".join(m.trigger)
    return "—"


def _fmt_productions(support: dict | None) -> str:
    """产出列主格:仅治疗/护盾形态;技力/终结技能量/失衡值按需求忽略不展示。"""
    parts = [RESOURCE_LABELS[res] for res in (RES_HEAL, RES_SHIELD)
             if (support or {}).get(res)]
    return "、".join(parts) or "—"


def _merge_desc(rows: list[SkillRes]) -> dict | None:
    """多段技能(普攻连招/同组变体)的文案资源并集。"""
    demands: list[str] = []
    productions: list[str] = []
    for m in rows:
        for key, bucket in (("demands", demands), ("productions", productions)):
            for term in (m.descRes or {}).get(key) or []:
                if term not in bucket:
                    bucket.append(term)
    return {"demands": demands, "productions": productions} \
        if (demands or productions) else None


def _merge_support(members: list[SkillRes]) -> dict | None:
    """同组成员的治疗/护盾形态并集。"""
    support: dict[str, dict[str, float]] = {}
    for m in members:
        for res, kv in (m.support or {}).items():
            support.setdefault(res, {}).update(kv)
    return support or None


def _fmt_desc_part(desc_res: dict | None, key: str) -> str:
    """文案解析资源词列表(词条即展示文案)。无命中返回空串。"""
    return "、".join((desc_res or {}).get(key) or [])


def _cell(main: str, desc_res: dict | None, key: str) -> str:
    """需求/产出单元格 = 主格 + 文案解析资源词(「、」连接),两者皆空为 —。"""
    desc_part = _fmt_desc_part(desc_res, key)
    if not desc_part:
        return main or "—"
    if not main or main == "—":
        return desc_part
    return f"{main}、{desc_part}"


def _fmt_desc_text(desc: str | None) -> str:
    """描述列:desc 已是剥离标签的纯文本,换行合并为空格(单元格内不可换行)。"""
    return " ".join(desc.split()) if desc else ""


def _char_section(c: Operator) -> list[str]:
    """一个干员的小节;无任何资源条目(需求/产出全空)时返回空,整节不显示。

    同一技能组的成员(形态变体/等级分段)合并为一行,资源取并集;相邻完全相同的
    行(不同组同名同资源,如「闪耀焦点」两形态)也只保留一行。
    """
    lines = [f"### {c.name}"]
    rows: list[str] = []

    def add(label: str, slot: str, demand: str, prod: str, desc: str) -> None:
        if demand == "—" and prod == "—":
            return
        row = f"| {label} | {slot} | {demand} | {prod} | {desc} |"
        if not rows or rows[-1] != row:
            rows.append(row)

    chain_ids = {id(m) for m in c.skills if _is_attack(m)}
    chain_rows = [m for m in c.skills if id(m) in chain_ids]
    if chain_rows:
        chain_res = _merge_desc(chain_rows)
        label = chain_rows[0].group or "普攻"
        slot = f"普攻连招({len(chain_rows)} 段含下落/冲锋)"
        desc = max((m.desc or "" for m in chain_rows), key=len, default="")
        add(label, slot, _cell("—", chain_res, "demands"),
            _cell("—", chain_res, "productions"), _fmt_desc_text(desc))

    groups: dict[str, list[SkillRes]] = {}
    for m in c.skills:
        if id(m) in chain_ids:
            continue
        groups.setdefault(m.groupId or m.skillId, []).append(m)
    for members in groups.values():
        base = members[0]
        desc_res = _merge_desc(members)
        support = _merge_support(members)
        name = base.group or base.name or base.skillId
        desc = max((m.desc or "" for m in members), key=len, default="")
        add(name, base.slot,
            _cell(_fmt_demands(base), desc_res, "demands"),
            _cell(_fmt_productions(support), desc_res, "productions"),
            _fmt_desc_text(desc))
    for x in c.extras:
        add(x.name, x.kind,
            _cell("—", x.descRes, "demands"), _cell("—", x.descRes, "productions"),
            _fmt_desc_text(x.desc))
    if not rows:
        return []
    lines += (["", "| 技能 | 类型 | 需求 | 产出 | 描述 |", "|---|---|---|---|---|"]
              + rows + [""])
    return lines


def render_report(roster: list[Operator], meta: dict, now: str) -> str:
    """报告只保留逐干员技能资源解析;完整数值仅存于内存。"""
    game = meta.get("game") or {}
    src = meta.get("source") or {}
    lines = [
        "# 配队分析报告", "",
        f"- 生成时间:{now}(UTC);干员 {len(roster)} 名",
        f"- 数据源:{src.get('repo', 'rmxlinux/EndfieldData')}@{src.get('branch', 'main')}"
        f"(游戏 build {game.get('build', '?')});数据集:data/characters/",
        "- 处理来源:技能(满级 blackboard + 描述)、天赋(talentNodeMap 被动节点,"
        "同点多等级取最高)、潜能(潜能描述);仅解析出资源时入表", "",
        "口径:满级数值;按一次施放 / 一套普攻连招(含下落·冲锋变体)计。"
        "按需求忽略**技力、终结技能量、失衡值、冷却**四项,"
        "本表只展示触发/消耗条件、治疗/护盾与文案解析的附着·异常状态·特殊资源。"
        "需求/产出两列为描述文案解析:宽松捕获片段 + 后处理函数精筛——「消耗xx」"
        "记为 xx,「xx被消耗(被吸收)」记为 xx被消耗,「被xx(被冻结/被附着源石"
        "结晶等)」记为 被xx,「每当/当…有敌人被施加xx后」记为 被施加xx,"
        "陈述句「(目标)被施加xx」与施加/获得/生成/返还记入产出;"
        "数值资源以 blackboard 为准、不在文案中重复计。",
    ]
    sections = [_char_section(c) for c in sorted(roster, key=lambda x: x.id)]
    listed = sum(1 for s in sections if s)
    lines[-1] += f"全部 {listed} 名干员均有条目。" if listed == len(roster) else \
        f"共列出 {listed}/{len(roster)} 名干员。"
    lines.append("")
    lines += [line for s in sections for line in s]
    return "\n".join(lines)


# ---------------------------------------------------------------- 保存结果
def _load_meta() -> dict:
    """报告头部信息:versions.json(游戏 build)与 meta.json(数据集统计)按需合并。"""
    meta: dict = {}
    for name in ("meta.json", "versions.json"):
        f = DATA_DIR / name
        if f.is_file():
            try:
                meta.update(json.loads(f.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 - 头部信息缺失不影响分析
                continue
    return meta


def _save_results(report: str, roster_count: int) -> None:
    """保存结果:人读报告。"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"配队分析完成:{roster_count} 名干员\n  {REPORT_PATH}")


# ---------------------------------------------------------------- 主函数
def run() -> None:
    """主函数:提取描述 → 解析需求/产出 → 收集汇总 → 保存结果。"""
    entries = []
    for f in sorted(CHAR_DIR.glob("chr_*.json")):
        if f.stem in EXCLUDED_IDS:
            continue
        entries.append(json.loads(f.read_text(encoding="utf-8")))
    roster = [analyze_character(e) for e in entries]
    # 同名消歧(管理员男/女形态数值相同):名字后追加 id 尾段
    name_counts: dict[str, int] = {}
    for c in roster:
        name_counts[c.name] = name_counts.get(c.name, 0) + 1
    for c in roster:
        if name_counts[c.name] > 1:
            c.name = f"{c.name}({c.id.rsplit('_', 1)[-1]})"

    meta = _load_meta()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    _save_results(render_report(roster, meta, now), len(roster))


def main() -> None:
    run()


if __name__ == "__main__":
    main()
