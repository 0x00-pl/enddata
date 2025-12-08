"""sources/rmxlinux__EndfieldData 的 id 关联映射:扫描、分组、模式归纳与查询。

核心概念(详见 docs/id-map.md):
- 定位符:描述 id 所在位置。文件名即 id 的实体文件(Json/SkillData、Json/BuffData)
  定位符就是文件路径;表内出现为 `文件#段序列`,除末段外每段是结构(对象成员的
  键名,值为数组的键带 [] 后缀、不下标),**末段恒为 id 本身** —— 键出现(id 是
  行键或 skillGroupMap/charBreakCostMap 等 map 键)与值出现(id 是 Id/IdList 等
  键下的取值,或 >2³² 的数值哈希)统一表达。
- 关联组:同一个 id 字符串的全部定位符,按 defs(键出现/文件名出现)/refs(值出现)
  分集;键出现与值出现可以互为印证(如 skillGroupMap 键与组内 skillGroupId 字段)。
- 模式:同构关联组(定位符槽位集合相同或为其超集)的跨实例对齐模板,带 {var};
  取值向量相同的变量跨槽共享同名,取值集合高度重合的变量归并(例外记入
  varExceptions,如 chr_9000_endmin 引用 endminm 前缀技能)。
- 查询语义:lookup 按 id 值直查关联组(总能回答);relate 按定位符走模式,
  变量绑定不全(查询方向一对多)直接报错,渲染结果经实例组验证后才输出。

产物:data/id_map/{ids.jsonl, patterns.json, files.json, meta.json, index.db}
(index.db 为 ids.jsonl 的 sqlite 派生索引,可随时删除重建)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from tools.datasource import PROJECT_ROOT, info, local_head, repo_dir

REPO = "rmxlinux__EndfieldData"
OUT_DIR = PROJECT_ROOT / "data" / "id_map"

# 默认扫描范围:项目消费的数值表 + 技能/Buff 实体目录。其余 Json(关卡/NPC/口型等)
# 与数据站无关且量大(LipSync 7.4 万文件),--dir 追加、--all-json 全量。
DEFAULT_SCOPE = ["TableCfg", "Json/SkillData", "Json/BuffData"]
# i18n 各语言表是同一批文本哈希键的重复定义(项目以 CN 为基准),只扫 CN,
# 否则 13 张表 × 14.7 万行纯重复定义会把数值 id 组淹没。
_I18N_RE = re.compile(r"^I18nTextTable_([A-Z]{2})\.json$")
I18N_BASE_LANG = "CN"

# 不带 Id 字样但实测承载 id 引用的键(试点扫描逐键核对过取值形态)。
# 取值仍需通过 ID_SHAPE 校验,防止同名键在别处装普通字符串。
EXTRA_REF_KEYS = frozenset({
    "bornBuffs",        # EnemyTable 出生 Buff → Json/BuffData
    "equips", "equipList", "perfectEquips",  # 预设/卡池表里的装备条目
    "fullBottleItems",  # LiquidTable 瓶装物品 → ItemTable
    "actorList",        # RemoteCommonTable 的 chr_/npc_ 引用
    "ids",              # WorldGameMechanicsDisplayInfoTable 敌人引用
    "list",             # FactoryLevelRegionTable 的 region 引用
    "valueStringList",  # FacSTTNodeTable 的 item 引用
})

ID_SHAPE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
NUM_SHAPE = re.compile(r"^\d+$")
# 数值引用只认 64 位哈希(即 i18n 文本 id),过滤 0/1/开关位等小整数
HASH_MIN = 1 << 32

# 定位符分词时的段分隔标记(仅内部使用,渲染时还原为 '.' '/')
_SEP_SEG = "\x01"


# ---------------------------------------------------------------- 扫描与分组


def _lang_of(name: str) -> str | None:
    m = _I18N_RE.match(name.rsplit("/", 1)[-1])
    return m.group(1) if m else None


def _resolve_scope(root: Path, extra_dirs: list[str], all_json: bool) -> list[str]:
    if all_json:
        scope = ["TableCfg", "Json", "ExtendData"]
    else:
        scope = list(DEFAULT_SCOPE)
    for d in extra_dirs:
        if d not in scope:
            scope.append(d)
    if all_json:
        return scope
    out = []
    for s in scope:
        lang = _lang_of(s)
        if lang and lang != I18N_BASE_LANG and (root / s).is_file():
            info(f"警告: i18n 只扫基准语言 {I18N_BASE_LANG},跳过 {s}")
            continue
        out.append(s)
    return out


def _iter_scope_files(root: Path, scope: list[str]):
    for entry in scope:
        p = root / entry
        if p.is_dir():
            for r, dirs, fs in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d != ".git")
                for f in sorted(fs):
                    # i18n 只收基准语言表(其余 13 语言是同键重复定义)
                    if f.endswith(".json") and _lang_of(f) in (None, I18N_BASE_LANG):
                        yield Path(r) / f
        elif p.is_file():
            yield p
        else:
            info(f"警告: 扫描范围不存在,跳过 {entry}")


def _walk(obj, segs: list[str], rel: str, groups: dict, include_numeric: bool) -> None:
    """segs 为从文件根到当前节点的结构段;叶节点的归属键 = segs[-1]。

    定位符 = 段序列 '.' 连接,末段恒为 id 本身:对象成员追加键名;值为数组的
    键追加 '[]' 后缀(数组位置无关,不下标);id 形态的键本身就是一次「键出现」
    (行键、skillGroupMap/charBreakCostMap 等 map 键),以该键结尾记为定义。
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            # 键出现:id 形态的键(小写 snake;混合大小写的 map 键如 chr_x_ComboSkill
            # 不收集,其内容自带 *Id 字段)。数值键与数值引用同阈值,滤掉 "1"/"2" 层级键。
            if ID_SHAPE.match(k) or (include_numeric and NUM_SHAPE.fullmatch(k)
                                     and abs(int(k)) > HASH_MIN):
                groups[k][0].add(f"{rel}#{'.'.join((*segs, k))}")
            _walk(v, segs + [k + ('[]' if isinstance(v, list) else '')],
                  rel, groups, include_numeric)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, segs, rel, groups, include_numeric)
    else:
        if not segs:
            return
        key = segs[-1]
        base = key[:-2] if key.endswith('[]') else key
        idish = _idish_key(base)
        if not idish and base not in EXTRA_REF_KEYS:
            return
        val = None
        if isinstance(obj, str) and obj:
            # 补充键的取值必须像 id(小写 snake),Id 键的取值不设限
            if idish or ID_SHAPE.match(obj):
                val = obj
        elif (include_numeric and isinstance(obj, int) and not isinstance(obj, bool)
              and abs(obj) > HASH_MIN):
            val = str(obj)
        if val is None:
            return
        groups[val][1].add(f"{rel}#{'.'.join((*segs, val))}")


def _idish_key(k: str) -> bool:
    return k == "id" or "Id" in k or k.endswith("_id") or k.endswith("_ids")


def scan(root: Path, scope: list[str], include_numeric: bool = True):
    """扫描范围内全部 JSON,返回 (groups, meta)。

    groups: id -> (定义定位符集, 引用定位符集);定位符形如
    'TableCfg/X.json#行键.字段.id值' 或 'Json/SkillData/xxx.json'(文件名即 id)。
    """
    groups: dict[str, tuple[set, set]] = defaultdict(lambda: (set(), set()))
    errors: list[str] = []
    nfiles = 0
    for path in _iter_scope_files(root, scope):
        rel = path.relative_to(root).as_posix()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # 单文件损坏不中断全量
            errors.append(f"{rel}: {e}")
            continue
        nfiles += 1
        # 文件名即 id 的单实体文件(技能/Buff 等;表名是驼峰无下划线,天然不匹配)
        if ID_SHAPE.match(path.stem):
            groups[path.stem][0].add(rel)
        if isinstance(data, (dict, list)):
            _walk(data, [], rel, groups, include_numeric)
    return groups, {"files": nfiles, "errors": errors}


# ---------------------------------------------------------------- 模式归纳
#
# 定位符分词:文件名按 '_' 分词,路径各段按 '_' 分词;跨实例逐位置对齐后,
# 常量位置保留字面量;可变位置中相邻且完全共变(同变同不变)的合并为一个变量;
# 样本取值向量相同的变量跨槽共享同名({chr} 可同时出现在表路径与技能 id 前缀)。


def _parse_locator(loc: str) -> tuple[str, str, list[str]]:
    f, _, p = loc.partition("#")
    d, _, name = f.rpartition("/")
    stem = name[:-5] if name.endswith(".json") else name
    return d, stem, p.split(".") if p else []


def _split_tokens(loc: str) -> tuple[list[str], list[list[str]]]:
    """定位符 → (文件名 token 流, [各路径段 token 流])。空 token(空键/空段)剔除。"""
    d, stem, segs = _parse_locator(loc)
    return ([t for t in [d, *stem.split("_")] if t],
            [[t for t in s.split("_") if t] for s in segs])


def _align(streams: list[list[str]], qbase: int) -> tuple[list, dict[int, dict]]:
    """同槽多实例的 token 流 → (模板 parts, 变量表)。

    part 为字面量 str 或 {"q": 变量号, "n": 占 token 数};相邻且完全共变
    (同变同不变)的位置合并为一个变量,以合并后的完整取值作为变量身份。
    """
    n = len(streams[0])
    kinds: list = []
    for col in zip(*streams):
        vals = list(col)
        kinds.append(vals[0] if len(set(vals)) == 1 else tuple(vals))
    parts: list = []
    varinfo: dict[int, dict] = {}
    i = 0
    while i < n:
        if isinstance(kinds[i], str):
            parts.append(kinds[i])
            i += 1
            continue
        j = i
        while j + 1 < n and isinstance(kinds[j + 1], tuple) and _traj(kinds[i]) == _traj(kinds[j + 1]):
            j += 1
        span = ["_".join(s[i:j + 1]) for s in streams]
        if len(set(span)) == 1:  # 各位置各自变化但合并后恒定 → 视为字面量
            parts.append(span[0])
        else:
            q = qbase + len(varinfo)
            parts.append({"q": q, "n": j - i + 1})
            varinfo[q] = tuple(span)
        i = j + 1
    return parts, varinfo


def _traj(vals: tuple) -> tuple:
    first: dict = {}
    return tuple(first.setdefault(v, len(first)) for v in vals)


def _slot_template(locs: list[str], qbase: int) -> tuple[dict, dict[int, tuple]]:
    """同槽多实例定位符 → (槽模板 {file, segs}, 变量号→样本取值向量)。

    文件名 token 流的首元素是目录字面量,与其余 token 一起参与对齐。
    """
    splits = [_split_tokens(x) for x in locs]
    fparts, fvars = _align([s[0] for s in splits], qbase)
    segs, svars = [], {}
    qnext = qbase + len(fvars)
    for j in range(len(splits[0][1])):
        sp, sv = _align([s[1][j] for s in splits], qnext)
        segs.append(sp)
        svars.update(sv)
        qnext += len(sv)
    return {"file": fparts, "segs": segs}, {**fvars, **svars}


def _rewrite_q(parts: list, remap: dict[int, int]) -> None:
    for p in parts:
        if isinstance(p, dict):
            p["q"] = remap[p["q"]]


def _merge_identities(patterns: list[dict]) -> None:
    """跨槽归并取值高度重合的变量(chr_0027_tangtang 在表路径前缀与技能 id 前缀
    是同一实体;chr_9000_endmin 的 skillGroupMap 引用 endminm 技能这类例外,
    会让两侧取值集合不完全一致 —— 重合率 ≥0.9 仍归并为同一变量,差集记入
    varExceptions 文档化,该例外的实例在 relate 匹配时自然落入不匹配)。"""
    for pat in patterns:
        vi = pat.get("varinfo")
        if not vi:
            continue
        parent = {q: q for q in vi}

        def find(q):
            while parent[q] != q:
                parent[q] = parent[parent[q]]
                q = parent[q]
            return q

        qs = sorted(vi)
        sets = {q: set(vi[q]["span"]) for q in qs}
        for i, a in enumerate(qs):
            for b in qs[i + 1:]:
                A, B = sets[a], sets[b]
                if min(len(A), len(B)) >= 5 and len(A & B) / len(A | B) >= 0.9:
                    parent[find(b)] = find(a)
        comp: dict[int, list[int]] = defaultdict(list)
        for q in qs:
            comp[find(q)].append(q)
        if len(comp) == len(qs):
            continue
        remap = {q: find(q) for q in qs}
        for slot in pat["slots"]:
            for seg in [slot["file"], *slot["segs"]]:
                _rewrite_q(seg, remap)
        newvi: dict[int, dict] = {}
        for root, members in comp.items():
            allvals = [v for q in members for v in vi[q]["span"]]
            common = set.intersection(*(sets[q] for q in members))
            exc = sorted(set().union(*(sets[q] for q in members)) - common)
            newvi[root] = {"span": tuple(allvals),
                           "examples": list(dict.fromkeys(allvals))[:3],
                           "exceptions": exc[:6]}
        pat["varinfo"] = newvi
        if any(v["exceptions"] for v in newvi.values()):
            pat["varExceptions"] = {q: v["exceptions"] for q, v in newvi.items()
                                    if v["exceptions"]}


def _name_vars(patterns: list[dict]) -> None:
    """给全部模式的变量定名并就地改写 parts:{"q":号} → {"v":名,"n":token 数}。

    命名:数字开头的跨度用其前邻字面量(chr_0027_tangtang → {chr}),纯数字
    无前邻用 num,其余用示例值首个字母段;不同变量撞名加序号。
    """
    for pat in patterns:
        if not pat.get("slots"):
            continue
        varinfo = pat.pop("varinfo")
        prevs: dict[int, list[str]] = defaultdict(list)

        def collect(parts: list) -> None:
            for idx, p in enumerate(parts):
                if isinstance(p, dict) and idx and isinstance(parts[idx - 1], str):
                    prevs[p["q"]].append(parts[idx - 1])

        for slot in pat["slots"]:
            collect(slot["file"])
            for seg in slot["segs"]:
                collect(seg)
        names: dict[int, str] = {}
        used: set[str] = set()
        for q in sorted(varinfo):
            ex0 = varinfo[q]["examples"][0] or "id"
            if ex0[0].isdigit():
                cand = prevs.get(q) or []
                base = max(set(cand), key=cand.count) if cand else "num"
            else:
                alpha = [t for t in re.findall(r"[A-Za-z_]+", ex0) if t.strip("_")]
                base = alpha[0].strip("_") if alpha else "id"
            name, k = base, 2
            while name in used:
                name, k = f"{base}{k}", k + 1
            used.add(name)
            names[q] = name

        def rename(parts: list) -> None:
            for idx, p in enumerate(parts):
                if isinstance(p, dict):
                    parts[idx] = {"v": names[p["q"]], "n": p["n"]}

        for slot in pat["slots"]:
            rename(slot["file"])
            for seg in slot["segs"]:
                rename(seg)
        pat["vars"] = {names[q]: varinfo[q]["examples"] for q in sorted(varinfo)}


def _parts_to_text(parts: list, bind: dict[str, str] | None, missing: set) -> list[str]:
    out = []
    for p in parts:
        if isinstance(p, str):
            out.append(p)
        elif bind is not None and p["v"] in bind:
            out.append(bind[p["v"]])
        else:
            missing.add(p["v"])
            out.append("{" + p["v"] + "}")
    return out


def render_slot(slot: dict, bind: dict[str, str] | None) -> tuple[str, set[str]]:
    """槽模板 → 定位符文本;bind 为 None 时变量保持 {名},返回未绑定变量名集合。"""
    missing: set[str] = set()
    stem = "_".join(_parts_to_text(slot["file"][1:], bind, missing))
    f = slot["file"][0] + "/" + stem + ".json"
    if not slot["segs"]:
        return f, missing
    segs = ["_".join(_parts_to_text(sp, bind, missing)) for sp in slot["segs"]]
    return f + "#" + ".".join(segs), missing


def _derive_slots(per_slot: dict) -> tuple[list[dict], dict[int, dict]]:
    """同模式各槽的实例定位符 → (槽模板列表, 变量表)。"""
    slots: list[dict] = []
    ident: dict[tuple, int] = {}  # 样本取值向量 → 规范变量号(跨槽共享)
    varinfo: dict[int, dict] = {}
    for key in sorted(per_slot):
        t, vinfo = _slot_template(per_slot[key], len(ident))
        remap = {}
        for q, span in vinfo.items():
            cq = ident.setdefault(span, len(ident))
            remap[q] = cq
            if cq not in varinfo:
                varinfo[cq] = {"span": span,
                               "examples": list(dict.fromkeys(span))[:3]}
        for seg in [t["file"], *t["segs"]]:
            _rewrite_q(seg, remap)
        slots.append(t)
    return slots, varinfo


def derive_patterns(groups: dict):
    """关联组 → (模式目录, 组id→模式id)。单例组(仅一处出现)统一挂 P0。

    组先按槽位集合精确分桶;槽位集合全库唯一的组退而匹配"槽位是其子集的
    最大模式"(同一模式加额外引用不影响核心关联的成立)。槽模板在归组完成后
    用该模式的全部实例重新推导(精确桶往往只有少数样本,子集实例同样参与
    对齐才能让变量归并见到足够多的取值)。
    """
    buckets: dict[frozenset, list[str]] = defaultdict(list)
    for gid, (defs, refs) in groups.items():
        locs = (*defs, *refs)
        if len(locs) > 1:
            buckets[frozenset(_coarse(x) for x in locs)].append(gid)
    single = sum(1 for d, r in groups.values() if len(d) + len(r) == 1)
    patterns = [{"pid": 0, "slots": [], "vars": {}, "instances": single,
                 "sampleIds": [], "note": "单例组:仅一处出现,无跨实例模式"}]
    gid_pid: dict[str, int] = {}
    exact_sets: list[tuple[frozenset, int]] = []  # (槽集合, 模式号)
    slot_index: dict[tuple, list[int]] = defaultdict(list)
    for gids in buckets.values():
        gids.sort()
        if len(gids) == 1:
            continue  # 槽位唯一的组,待模式壳建好后做子集匹配
        slots_key = frozenset(_coarse(x) for x in
                              (*groups[gids[0]][0], *groups[gids[0]][1]))
        pid = len(patterns)
        for key in slots_key:
            slot_index[key].append(pid)
        exact_sets.append((slots_key, pid))
        for gid in gids:
            gid_pid[gid] = pid
        patterns.append({"pid": pid, "slots": [], "varinfo": {}, "vars": {},
                         "instances": len(gids), "sampleIds": gids[:3]})
    # 槽位集合唯一的组 → 子集匹配(覆盖槽最多、实例最多者优先)
    for gids in buckets.values():
        if len(gids) != 1:
            continue
        gid = gids[0]
        d, r = groups[gid]
        gset = frozenset(_coarse(x) for x in (*d, *r))
        cands = {p for s in gset for p in slot_index.get(s, ())}
        best = [pid for pid in cands if exact_sets[pid - 1][0] <= gset]
        if best:
            pid = min(best, key=lambda p: (-len(exact_sets[p - 1][0]),
                                           -patterns[p]["instances"], p))
            gid_pid[gid] = pid
            patterns[pid]["instances"] += 1
        else:
            patterns[0]["instances"] += 1
            gid_pid[gid] = 0
    # 用各模式全部实例重推槽模板
    by_pid: dict[int, list[str]] = defaultdict(list)
    for gid, pid in gid_pid.items():
        if pid:
            by_pid[pid].append(gid)
    for pat in patterns[1:]:
        gids = sorted(by_pid[pat["pid"]])[:200]
        per_slot: dict[tuple, list[str]] = defaultdict(list)
        # 同组同槽可能有多条同形定位符(深层动作树里路径恰好同构),只取一条,
        # 保证各槽样本与实例一一对应。
        for gid in gids:
            d, r = groups[gid]
            seen: set[tuple] = set()
            for loc in (*d, *r):
                c = _coarse(loc)
                if c not in seen:
                    seen.add(c)
                    per_slot.setdefault(c, []).append(loc)
        pat["slots"], pat["varinfo"] = _derive_slots(per_slot)
        pat["sampleIds"] = gids[:3]
    _merge_identities(patterns)
    _name_vars(patterns)
    return patterns, gid_pid


def _coarse(loc: str) -> tuple:
    ftoks, segs = _split_tokens(loc)
    return (ftoks[0], len(ftoks) - 1, tuple(len(s) for s in segs))


# ---------------------------------------------------------------- 产物输出


def build(extra_dirs: list[str] | None = None, all_json: bool = False,
          no_numeric: bool = False) -> dict:
    root = repo_dir(REPO)
    if not root.exists():
        info(f"错误: 本地数据源缺失,先执行 enddata collection clone({root})")
        raise SystemExit(1)
    scope = _resolve_scope(root, extra_dirs or [], all_json)
    include_numeric = not no_numeric
    t0 = datetime.now(timezone.utc)
    info(f"扫描 {root}({', '.join(scope)}) …")
    groups, smeta = scan(root, scope, include_numeric)
    n_defs = sum(len(d) for d, _ in groups.values())
    n_refs = sum(len(r) for _, r in groups.values())
    info(f"  文件 {smeta['files']} · id {len(groups)} · 定义 {n_defs} · 引用 {n_refs}")
    info("归纳关联模式 …")
    patterns, gid_pid = derive_patterns(groups)
    info(f"  模式 {len(patterns) - 1} 个(另单例组 {patterns[0]['instances']})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_file: dict[str, dict] = defaultdict(lambda: {"defs": [], "refs": []})
    with open(OUT_DIR / "ids.jsonl", "w", encoding="utf-8") as fh:
        for gid in sorted(groups):
            d, r = groups[gid]
            for loc in d:
                by_file[loc.partition("#")[0]]["defs"].append(gid)
            for loc in r:
                by_file[loc.partition("#")[0]]["refs"].append(gid)
            fh.write(json.dumps({"id": gid, "pid": gid_pid.get(gid, 0),
                                 "defs": sorted(d), "refs": sorted(r)},
                                ensure_ascii=False, sort_keys=True) + "\n")
    _write_json(OUT_DIR / "patterns.json", {
        "patterns": patterns,
        "note": "slots 为定位符模板(file + segs);{var} 在同一模式内取相同值,"
                "vars 为变量示例;pid 0 为单例组聚合。",
    })
    _write_json(OUT_DIR / "files.json",
                {k: {**v, "defs": sorted(v["defs"]), "refs": sorted(v["refs"])}
                 for k, v in sorted(by_file.items())})
    _build_db()
    meta = {
        "generated": t0.isoformat(timespec="seconds"),
        "repo": REPO,
        "head": local_head(REPO),
        "scope": scope,
        "i18nBaseLang": I18N_BASE_LANG,
        "extraRefKeys": sorted(EXTRA_REF_KEYS),
        "includeNumericHash": include_numeric,
        "counts": {"files": smeta["files"], "ids": len(groups),
                   "defs": n_defs, "refs": n_refs,
                   "patterns": len(patterns) - 1,
                   "singletonGroups": patterns[0]["instances"]},
        "errors": smeta["errors"][:50],
    }
    _write_json(OUT_DIR / "meta.json", meta)
    info(f"产物已写入 {OUT_DIR}(ids.jsonl / patterns.json / files.json / meta.json / index.db)")
    return meta


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _build_db() -> None:
    """ids.jsonl → sqlite 主键索引,支撑 lookup/search 免全量加载。"""
    db = sqlite3.connect(OUT_DIR / "index.db")
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("DROP TABLE IF EXISTS ids")
    db.execute("CREATE TABLE ids(id TEXT PRIMARY KEY, pid INT, defs TEXT, refs TEXT) WITHOUT ROWID")
    with open(OUT_DIR / "ids.jsonl", encoding="utf-8") as fh:
        db.executemany("INSERT INTO ids VALUES(?,?,?,?)",
                       ((r["id"], r["pid"], json.dumps(r["defs"], ensure_ascii=False),
                         json.dumps(r["refs"], ensure_ascii=False))
                        for r in map(json.loads, fh)))
    db.commit()
    db.close()


# ---------------------------------------------------------------- 查询


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_patterns() -> list[dict]:
    return _load_json(OUT_DIR / "patterns.json")["patterns"]


def _db() -> sqlite3.Connection:
    if not (OUT_DIR / "index.db").exists():
        info("错误: 缺少 data/id_map/index.db,先执行 enddata idmap build")
        raise SystemExit(1)
    return sqlite3.connect(f"file:{OUT_DIR / 'index.db'}?mode=ro", uri=True)


def lookup(id_value: str) -> int:
    id_value = id_value.strip()
    row = _db().execute("SELECT pid, defs, refs FROM ids WHERE id=?", (id_value,)).fetchone()
    if row is None:
        print(f"未找到 id: {id_value}(可先 enddata idmap search <子串> 模糊定位)")
        return 1
    defs, refs = json.loads(row[1]), json.loads(row[2])
    label = "单例组" if row[0] == 0 else f"模式 P{row[0]}"
    print(f"{id_value}  ({label} · 定义 {len(defs)} · 引用 {len(refs)})")
    for loc in defs:
        print(f"  定义  {loc}")
    for loc in refs:
        print(f"  引用  {loc}")
    pat = next((p for p in _load_patterns() if p["pid"] == row[0]), None)
    if pat and pat["slots"]:
        print("  模板  " + "  ↔  ".join(render_slot(s, None)[0] for s in pat["slots"]))
    return 0


def _match_parts(parts: list, toks: list[str], bind: dict[str, str]) -> bool:
    need = sum(p["n"] if isinstance(p, dict) else 1 for p in parts)
    if need != len(toks):
        return False
    i = 0
    for p in parts:
        k = p["n"] if isinstance(p, dict) else 1
        val = "_".join(toks[i:i + k])
        i += k
        if isinstance(p, str):
            if p != val:
                return False
        elif p["v"] not in bind:
            bind[p["v"]] = val
        elif bind[p["v"]] != val:  # 同槽内同名变量必须取同一值
            return False
    return True


def _match_slot(slot: dict, loc: str) -> dict[str, str] | None:
    """定位符是否吻合槽模板;吻合返回变量绑定,否则 None。"""
    bind: dict[str, str] = {}
    ftoks, ssegs = _split_tokens(loc)
    if not _match_parts(slot["file"], ftoks, bind):
        return None
    if len(slot["segs"]) != len(ssegs):
        return None
    for spart, s in zip(slot["segs"], ssegs):
        if not _match_parts(spart, s, bind):
            return None
    return bind


def _locator_id(locator: str) -> str | None:
    """从定位符提取关联组 id:引用取值段、表行取行键、单实体文件取文件名。"""
    if "#" in locator:
        rest = locator.rpartition("#")[2]
        return rest.rsplit(".", 1)[-1] if rest else None
    stem = locator.rsplit("/", 1)[-1]
    return stem[:-5] if stem.endswith(".json") else stem


def relate(locator: str) -> int:
    """按定位符走关联模式,找同组条目。

    语义:命中槽模板 → 绑定变量 → 渲染同模式其余槽。绑定不全的变量先尝试用
    关联组 id 本身补齐(模式各槽共享同一 id 值)并经实例组验证;仍无法确定者
    属查询方向一对多(如 I18nTextTable 行 → 引用表行),聚合报错、不强行映射。
    渲染结果一律对照该 id 的实例组验证,只报告实际存在的定位符。
    """
    locator = locator.strip()
    matches: dict[int, tuple] = {}
    for pat in _load_patterns():
        for slot in pat["slots"]:
            b = _match_slot(slot, locator)
            if b is not None:
                matches.setdefault(pat["pid"], (pat, b, slot))
    if not matches:
        print(f"定位符不匹配任何关联模式: {locator}")
        return 1
    idv = _locator_id(locator)
    group: set[str] | None = None
    if idv:
        row = _db().execute("SELECT defs, refs FROM ids WHERE id=?", (idv,)).fetchone()
        if row:
            group = set(json.loads(row[0])) | set(json.loads(row[1]))
        else:
            print(f"错误: 定位符末段 id {idv} 不在索引中(64 位以下的小整数不作为 id 收集),"
                  f"无法验证任何映射")
            return 1
    answered, failed, uniq = 0, [], {}
    for pid in sorted(matches):
        pat, bind, hit = matches[pid]
        outs, miss, missed = [], set(), 0
        for slot in pat["slots"]:
            if slot is hit:
                continue
            text, m = render_slot(slot, bind)
            if not m:
                if group is None or text in group:
                    outs.append(text)
                else:
                    missed += 1
                continue
            if idv:  # 未绑定变量试填关联组 id,经实例组验证后才采信
                guess, _ = render_slot(slot, {**bind, **{v: idv for v in m}})
                if guess in (group or ()):
                    outs.append(guess)
                    continue
            miss |= m
        if outs:  # 不同模式常收敛到同一组关联,按结果去重后合并展示
            ent = uniq.setdefault(tuple(outs), {"pids": [], "missed": 0})
            ent["pids"].append(pid)
            ent["missed"] = max(ent["missed"], missed)
        elif not miss:
            print(f"[P{pid}] 模式成立,但该 id 实例无其余关联槽位")
        if miss:
            failed.append((pid, sorted(miss)))
    for key, ent in uniq.items():
        pids = ent["pids"]
        label = f"P{pids[0]}" if len(pids) == 1 else f"P{pids[0]} 等 {len(pids)} 个模式"
        print(f"[{label}] {len(key)} 处关联:")
        for t in key:
            print(f"  {t}")
        if ent["missed"]:
            print(f"  (另有至多 {ent['missed']} 个模式槽位在该 id 实例上未观察到,已剔除)")
    answered = len(uniq)
    if failed:
        ex = "; ".join(f"P{p} 缺 {','.join('{' + v + '}' for v in vs)}"
                       for p, vs in failed[:3])
        more = f" 等共 {len(failed)} 个" if len(failed) > 3 else ""
        print(f"无法映射{more}(变量绑定不全,查询方向一对多):{ex}")
    if answered == 0:
        print("提示: 可改用 enddata idmap lookup <id> 按 id 值直查关联组。")
    return 0 if answered else 1


def search(substr: str, file: str | None = None, limit: int = 50) -> int:
    like = "%" + substr.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
    rows = _db().execute(
        "SELECT id, pid, defs, refs FROM ids WHERE id LIKE ? ESCAPE '\\' ORDER BY id",
        (like,)).fetchall()
    if file:
        rows = [r for r in rows
                if any(x.startswith(file) for x in json.loads(r[2]) + json.loads(r[3]))]
    extra = f"(显示前 {limit})" if len(rows) > limit else ""
    print(f"匹配 {len(rows)} 个 id{extra}")
    for r in rows[:limit]:
        d, rfs = json.loads(r[2]), json.loads(r[3])
        print(f"{r[0]}  (P{r[1]} · 定义 {len(d)} · 引用 {len(rfs)})")
    return 0


def stats() -> int:
    meta = _load_json(OUT_DIR / "meta.json")
    if not meta.get("counts"):
        print("错误: data/id_map/meta.json 缺失或为空,先执行 enddata idmap build")
        return 1
    c = meta["counts"]
    print(f"数据源  {meta['repo']} @ {str(meta['head'])[:12]}")
    print(f"范围    {', '.join(meta['scope'])}"
          + ("" if meta["includeNumericHash"] else "(不含数值哈希)"))
    print(f"生成    {meta['generated']}")
    print(f"规模    文件 {c['files']} · id {c['ids']} · 定义 {c['defs']} · 引用 {c['refs']}")
    print(f"模式    {c['patterns']} 个 · 单例组 {c['singletonGroups']}")
    top = sorted((p for p in _load_patterns() if p["pid"]),
                 key=lambda p: -p["instances"])[:10]
    print("实例最多的模式:")
    for p in top:
        slots = "  ↔  ".join(render_slot(s, None)[0] for s in p["slots"])
        print(f"  P{p['pid']} ×{p['instances']}  {slots}")
    return 0


# ---------------------------------------------------------------- CLI


def configure_parser(sub) -> None:
    """挂载到 enddata idmap 的子命令(cli.py 持有顶层 parser)。"""
    b = sub.add_parser("build", help="扫描数据源,重建 data/id_map/ 全部产物")
    b.add_argument("--dir", action="append", default=[],
                   help="附加扫描目录/文件(相对数据源根,可多次)")
    b.add_argument("--all-json", action="store_true",
                   help="扫描全仓 JSON(含关卡/NPC 等大目录,慢且产物大)")
    b.add_argument("--no-numeric", action="store_true",
                   help="跳过 64 位数值哈希引用(i18n 文本 id)")
    lk = sub.add_parser("lookup", help="按 id 值直查关联组(定义 + 引用)")
    lk.add_argument("id")
    rl = sub.add_parser("relate", help="按定位符 file#path 走关联模式;变量绑定不全时报错")
    rl.add_argument("locator", help="形如 TableCfg/ItemTable.json#item_gold 或文件路径")
    se = sub.add_parser("search", help="按子串模糊搜 id")
    se.add_argument("substr")
    se.add_argument("--file", help="只保留在该文件路径下出现的 id")
    se.add_argument("--limit", type=int, default=50)
    sub.add_parser("stats", help="产物规模与实例最多的模式")


def run(args) -> None:
    if args.idmap_cmd == "build":
        build(args.dir, args.all_json, args.no_numeric)
    else:
        raise SystemExit({"lookup": lambda: lookup(args.id),
                          "relate": lambda: relate(args.locator),
                          "search": lambda: search(args.substr, args.file, args.limit),
                          "stats": stats}[args.idmap_cmd]())
