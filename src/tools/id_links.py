"""sources/rmxlinux__EndfieldData 的 id 关联映射:扫描、LCS 规则归纳与查询。

定位符规范(详见 docs/id-map.md):描述 id 值所在位置。文件名即 id 的实体文件
(Json/SkillData、Json/BuffData)定位符就是文件路径;表内出现为 `文件#段序列`,
除末段外每段是结构(对象成员的键名,值为数组的键带 [] 后缀、不下标),末段恒为
id 本身 —— 键出现(行键/map 键,小写 snake)与值出现(Id/IdList 等键下的取值,
或 >2³² 的数值哈希)统一表达。

规则生成(enddata idmap build,循环 LCS 反统一):
1. 按字典序遍历 id;其全部定位符(defs+refs)逐一做覆盖检查,已被某条规则匹配
   的位置跳过;全部已覆盖则不产生新规则(归属首条命中规则)。
2. 存在未覆盖位置 → 用该 id 的全部定位符推导新规则:循环求全组最长公共子串,
   长度 ≥2 就把每次出现替换为新变量 {v1}、{v2}…,直到 ≤1;规则 =
   {"patterns": [各定位符泛化后的模板串(去重)]},列表内任一模式匹配即视为
   该规则覆盖。
3. 只有单条路径的 id 不成规则(pid=0);模式至少含 1 个 ≥4 字符字面量才参与
   覆盖判定(防退化规则吃掉全部位置)。
4. 覆盖判定按规则加入顺序先到先得;候选过滤用"模式最长字面量的 8 字符窗口 →
   规则号"倒排索引(在线选当前最稀有窗口),必要条件预筛后正则 fullmatch 验证。

查询(enddata idmap relate <file#path>):直接返回全部匹配的规则组,命中几条
返回几条,无一对多报错。

产物:data/id_map/{patterns.json, ids.jsonl, files.json, meta.json}
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from tools.datasource import PROJECT_ROOT, info, local_head, repo_dir

REPO = "rmxlinux__EndfieldData"
OUT_DIR = PROJECT_ROOT / "data" / "id_map"
ALGORITHM = "lcs-v1"

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

# 覆盖判定参数:模式至少含 1 个 ≥4 字符字面量才参与;候选索引 gram 窗口 8 字符
_MIN_COVER_LITERAL = 4
_GRAM = 8
# relate 单条规则最多展示的模式数
_DISPLAY_CAP = 50

_VAR_RE = re.compile(r"\{v\d+\}")
_VAR_CORE_RE = re.compile(r"v\d+")


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


# ---------------------------------------------------------------- LCS 规则归纳


def _common_of_len(anchor: str, rest: list[str], length: int) -> str | None:
    """anchor 的全部 length 窗口中,第一个在 rest 全部串里出现的;无则 None。

    含 '{'/'}' 的窗口与变量核心(v数字)跳过 —— 变量记号本身不允许再被提取成
    公共子串(否则死循环替换)。
    """
    seen: set[str] = set()
    for i in range(len(anchor) - length + 1):
        sub = anchor[i:i + length]
        if sub in seen or "{" in sub or "}" in sub or _VAR_CORE_RE.fullmatch(sub):
            continue
        seen.add(sub)
        if all(sub in s for s in rest):
            return sub
    return None


def _lcs_all(temps: list[str]) -> str:
    """全组最长公共子串(二分长度;anchor 取最短串)。"""
    if len(temps) == 1:
        return temps[0]
    order = sorted(range(len(temps)), key=lambda i: len(temps[i]))
    anchor = temps[order[0]]
    rest = [temps[i] for i in order[1:]]
    lo, hi, best = 1, len(anchor), ""
    while lo <= hi:
        mid = (lo + hi) // 2
        s = _common_of_len(anchor, rest, mid)
        if s is not None:
            best, lo = s, mid + 1
        else:
            hi = mid - 1
    return best


def _renumber_vars(pat: str) -> str:
    """模式内变量按首次出现顺序重排为 {v1}…{vN}(消去 LCS 轮次带来的跳号)。"""
    mapping: dict[str, str] = {}
    out: list[str] = []
    idx = 0
    for m in _VAR_RE.finditer(pat):
        out.append(pat[idx:m.start()])
        v = m.group(0)
        if v not in mapping:
            mapping[v] = "{v%d}" % (len(mapping) + 1)
        out.append(mapping[v])
        idx = m.end()
    out.append(pat[idx:])
    return "".join(out)


def _generalize(locs: list[str]) -> tuple[list[str], list[str]]:
    """循环把全组最长公共子串(≥2)替换为 {vN}。

    返回 (patterns, examples):各定位符泛化后的模板(变量名按模式内出现顺序
    规格化,patterns 按模式串排序),examples 与之一一对应(泛化前真实定位符,
    去重时取首个来源)。
    """
    temps = list(locs)
    n = 0
    while n < 64:  # 保险丝:每轮消耗一个公共子串,正常远达不到
        s = _lcs_all(temps)
        if len(s) <= 1:
            break
        n += 1
        v = "{v%d}" % n
        temps = [t.replace(s, v) for t in temps]
    pats: list[tuple[str, str]] = []
    seen: set[str] = set()
    for t, loc in zip(temps, locs):
        t = _renumber_vars(t)
        if t not in seen:
            seen.add(t)
            pats.append((t, loc))
    pats.sort(key=lambda pair: pair[0])  # patterns 数组顺序规格化
    return [p for p, _ in pats], [e for _, e in pats]


def _pattern_literals(pat: str) -> list[str]:
    return _VAR_RE.split(pat)


def _match_lits(parts: list[str], s: str) -> bool:
    """有序字面量匹配(首尾锚定):等价于把 {vN} 当作可空间隙,纯 C find 实现。

    不校验同名变量绑定同值 —— 换取数量级的速度;代价只是覆盖判定在极端情形
    略宽松(多认领的位置本就跳过建新规则)。
    """
    first, last = parts[0], parts[-1]
    if not s.startswith(first):
        return False
    if len(parts) == 1:
        return len(s) == len(first)
    if not s.endswith(last):
        return False
    pos = len(first)
    end = len(s) - len(last)
    for lit in parts[1:-1]:
        i = s.find(lit, pos)
        if i < 0 or i + len(lit) > end:
            return False
        pos = i + len(lit)
    return True


def _eligible(patterns: list[str]) -> list[str]:
    """参与覆盖判定的模式:至少含 1 个 ≥_MIN_COVER_LITERAL 字符的字面量段。"""
    out = []
    for p in patterns:
        if max(map(len, _pattern_literals(p))) >= _MIN_COVER_LITERAL:
            out.append(p)
    return out


def _pick_gram(lit: str, counter: Counter) -> str:
    """字面量的候选窗口里选当前最稀有的(在线均衡倒排索引的 posting 长度)。"""
    size = min(_GRAM, len(lit))
    windows = [lit[i:i + size] for i in range(len(lit) - size + 1)] or [lit]
    return min(windows, key=lambda w: (counter[w], w))


class _RuleIndex:
    """增量规则表:规则列表 + 覆盖判定用的字面量段与 gram 倒排索引。"""

    def __init__(self) -> None:
        self.rules: list[dict] = []
        self._lits: list[list[list[str]]] = []
        self._grams: dict[str, list[int]] = {}
        self._gram_count: Counter = Counter()

    def add(self, pats: list[str], examples: list[str] | None = None) -> int:
        rid = len(self.rules)
        self.rules.append({"patterns": pats, "example": examples or []})
        elig = _eligible(pats)
        self._lits.append([_pattern_literals(p) for p in elig])
        # 每个参与判定的模式各建一个 gram:模式 P 匹配 loc ⇒ P 的最长字面量
        # (及其 gram)必在 loc 中,必要条件成立;候选再有序字面量验证。
        for p in elig:
            lit = max(_pattern_literals(p), key=len)
            gram = _pick_gram(lit, self._gram_count)
            self._grams.setdefault(gram, []).append(rid)
            size = min(_GRAM, len(lit))
            self._gram_count.update(
                {lit[i:i + size] for i in range(len(lit) - size + 1)} or {lit})
        return rid

    def cover(self, loc: str) -> int | None:
        """返回首条匹配 loc 的规则号(按规则加入顺序);无则 None。"""
        seen: set[int] = set()
        cands: list[int] = []
        for length in range(_MIN_COVER_LITERAL, _GRAM + 1):
            for i in range(len(loc) - length + 1):
                for rid in self._grams.get(loc[i:i + length], ()):
                    if rid not in seen:
                        seen.add(rid)
                        cands.append(rid)
        for rid in sorted(cands):  # 先到先得:按规则加入顺序判定
            for parts in self._lits[rid]:
                if _match_lits(parts, loc):
                    return rid
        return None


def derive_rules(groups: dict):
    """关联组 → (rules, gid→rid)。

    rules 元素为 {"patterns": [...]},数组下标即 rid;单条路径的 id 记 rid=0。
    """
    index = _RuleIndex()
    gid_rid: dict[str, int] = {}
    n_single = 0
    for gid in sorted(groups):
        d, r = groups[gid]
        locs = sorted((*d, *r))
        if len(locs) == 1:  # 单条路径不成规则
            gid_rid[gid] = 0
            n_single += 1
            continue
        first_cover = 0
        triggered = False
        for loc in locs:
            rid = index.cover(loc)
            if rid is not None:
                if first_cover == 0:
                    first_cover = rid
            else:
                triggered = True
                break
        if triggered:
            pats, examples = _generalize(locs)
            gid_rid[gid] = index.add(pats, examples)
        else:
            gid_rid[gid] = first_cover
    meta = {"rules": len(index.rules), "singlePathIds": n_single}
    return index.rules, gid_rid, meta


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
    info("归纳匹配规则(循环 LCS 反统一)…")
    rules, gid_rid, rmeta = derive_rules(groups)
    info(f"  规则 {rmeta['rules']} 条 · 单路径 id {rmeta['singlePathIds']}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_file: dict[str, dict] = defaultdict(lambda: {"defs": [], "refs": []})
    with open(OUT_DIR / "ids.jsonl", "w", encoding="utf-8") as fh:
        for gid in sorted(groups):
            d, r = groups[gid]
            for loc in d:
                by_file[loc.partition("#")[0]]["defs"].append(gid)
            for loc in r:
                by_file[loc.partition("#")[0]]["refs"].append(gid)
            fh.write(json.dumps({"id": gid, "pid": gid_rid.get(gid, 0),
                                 "defs": sorted(d), "refs": sorted(r)},
                                ensure_ascii=False, sort_keys=True) + "\n")
    _write_json(OUT_DIR / "patterns.json", {"rules": rules})
    _write_json(OUT_DIR / "files.json",
                {k: {**v, "defs": sorted(v["defs"]), "refs": sorted(v["refs"])}
                 for k, v in sorted(by_file.items())})
    meta = {
        "generated": t0.isoformat(timespec="seconds"),
        "repo": REPO,
        "head": local_head(REPO),
        "algorithm": ALGORITHM,
        "scope": scope,
        "i18nBaseLang": I18N_BASE_LANG,
        "extraRefKeys": sorted(EXTRA_REF_KEYS),
        "includeNumericHash": include_numeric,
        "counts": {"files": smeta["files"], "ids": len(groups),
                   "defs": n_defs, "refs": n_refs,
                   "rules": rmeta["rules"],
                   "singlePathIds": rmeta["singlePathIds"]},
        "errors": smeta["errors"][:50],
    }
    _write_json(OUT_DIR / "meta.json", meta)
    info(f"产物已写入 {OUT_DIR}(patterns.json / ids.jsonl / files.json / meta.json)")
    return meta


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 查询


def relate(locator: str) -> int:
    """按定位符查规则:直接返回全部匹配的规则组,命中几条返回几条。"""
    locator = locator.strip()
    data = json.loads((OUT_DIR / "patterns.json").read_text(encoding="utf-8"))
    index = _RuleIndex()
    for r in data["rules"]:
        index.add(r["patterns"], r.get("example"))
    hits = []
    seen: set[int] = set()
    for length in range(_MIN_COVER_LITERAL, _GRAM + 1):
        for i in range(len(locator) - length + 1):
            for rid in index._grams.get(locator[i:i + length], ()):
                if rid not in seen:
                    seen.add(rid)
                    if any(_match_lits(parts, locator) for parts in index._lits[rid]):
                        hits.append(rid)
    hits.sort()
    if not hits:
        print(f"无匹配规则: {locator}")
        return 1
    print(f"匹配 {len(hits)} 条规则:")
    for rid in hits:
        rule = index.rules[rid]
        pats = rule["patterns"]
        examples = rule.get("example") or []
        print(f"[R{rid}] {len(pats)} 条模式:")
        for i, p in enumerate(pats[:_DISPLAY_CAP]):
            ex = f"   例: {examples[i]}" if i < len(examples) else ""
            print(f"  {p}{ex}")
        if len(pats) > _DISPLAY_CAP:
            print(f"  …(其余 {len(pats) - _DISPLAY_CAP} 条省略)")
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
    rl = sub.add_parser("relate", help="按定位符 file#path 查规则,返回全部匹配的规则组")
    rl.add_argument("locator", help="形如 TableCfg/ItemTable.json#item_gold 或文件路径")


def run(args) -> None:
    if args.idmap_cmd == "build":
        build(args.dir, args.all_json, args.no_numeric)
    else:
        code = 0
        try:
            code = relate(args.locator)
            sys.stdout.flush()  # 管道下游提前关闭(如 | head)时在此暴露 EPIPE
        except BrokenPipeError:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(code)
