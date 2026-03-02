"""配方用料倒推:给定最终产物与数量,沿 recipes/ 配方图回溯用料数量。

回答的问题:「要 N 个 X,需要多少最初用料(或 --have 清单里的物品)?」

模型与口径:
    配方结构   data/recipes/<station>/<id>.json;ingredients/outcomes 均为
               [{group:[{id,name,count}]}],同组与同槽原料**同时消耗**(AND,
               见 collection/recipes.py resolve_side 注:如灌装=空瓶+溶液),
               数据集中不存在"可替代"语义 → 计算前直接摊平为 [(物品, 数量)]
    用量数学   fractions.Fraction 精确计算:所需制造次数 = 需求量 ÷ 产物单次
               产出,子需求 = 原料单耗 × 制造次数;展示时附向上取整值
    环的处理   遇环不硬断,按「环上配方表 → 净产出判定 → 宏配方反推」处理:
               ① 取环:沿当前链路收集各步所用配方 + 收口配方,构成环的配方表;
               ② 净产出判定:按「环内其他物品守恒、仅需求原料可净增」解循环
                 比例(二环闭式:前环配方执行 x_A=收口配方对前环原料的耗量,
                 收口配方执行 x_X=前环配方的产量;需求原料净产
                 = q_X·q_A − 收口耗前环·前环耗X,>0 才算净产出);
               ③ 净产出 → 环即自持宏配方:需求的原料由环净产供给,环的净耗
                 物料(如种子环的清水)继续递归展开,环上配方执行次数计入
                 制造步骤,并注记一次性初始占用(环内物品 ×1 起爆,循环内守恒);
               ④ 不净产出(如清水⇄水蒸气等量回收环、块⇄粉末互磨)→ 弃此配方,
                 试该物品的下一产出配方;全部配方均不可行时,把闭环点记为
                 **外部投料点**(清水一类本就来自地图采集/初始存量)迭代求解,
                 再逐点收缩(给定其余投料点可严格自产者移出,如赤铜块)至
                 局部最小集;彻底失败才以宽松模式兜底(环叶计外部投料)。
               环上多于两条配方(当前数据集未出现)不做宏判定,视同不净产出。
    回收配方   拆解机配方(dismantler_,满瓶→空瓶+溶液一类)是回收环而非
               生产途径,整体不列入产出图谱;某物品若仅能由拆解产出(如惰气),
               视同最初用料(外部获取)
    配方择路   同一物品多条产出配方时按序取最优:该物品是首条产物(主产物,
               非副产物)优先 → 站点 machine>manual>spaceship → 制造耗时短
               优先 → id 字典序
    终止条件   ① 无任何产出配方的物品 = 最初用料(raw,附 items 数据集的
                 获取途径注记,如 惰气 = 惰气矿点采集);
               ② 命中 --have 提供清单 = 外部提供(provided),展开到此为止;
               ③ 求解器判定的外部投料点(external)与宽松兜底环叶(cycle,
                 附依赖链);
               ④ 飞船配方无原料 = 制造步骤但零投入(free);
               ⑤ 环境维持(env):链上配方要求气体环境时,气体散布机持续
                 通入对应气体 6/min(惰气→稳定、水蒸气→湿润、酸气→酸性、
                 息壤气→息壤),作为附加叶子计入需求原料;
               ⑥ 设备维持(upkeep,仅速率口径):转化机运行需持续通入息壤系
                 气体(FactoryTransmuterTable:液气转化机通液化息壤、固气
                 转化机通息壤气,6/min/台、上限 30),按设备台数计入需求原料
                 ——「溶液方案省息壤气」即源于液气路线把维持消耗从息壤气
                 换成液化息壤
    副产物     仅统计目标产物所需,污水等副产物不做回收抵扣(那属于产线
               规划/LP 范畴,见 README 对旧 planner 的说明)

用法:
    poetry run enddata analysis recipe                        # 总览报告 → reports/recipe-analysis.md
    poetry run enddata analysis recipe 铁制零件 10            # 按中文名查询(控制台)
    poetry run enddata analysis recipe item_iron_cmpt 10      # 按 id 查询
    poetry run enddata analysis recipe 分离芯 60/min          # 速率口径:每分钟材料流量 + 设备数折算
    poetry run enddata analysis recipe 分离芯 60/min \
        --recipe 息壤=xiranite_oven_xiranite_powder_2         # 钉选配方:少耗料的碳块路线(需稳定环境)
    poetry run enddata analysis recipe 分离芯 4 --have 清水,锦草种子
    poetry run enddata analysis recipe 蓝铁块 3 --json        # 机器可读输出

测试:
    poetry run pytest tests/ -q                               # 单元测试(见 tests/test_recipe_calc.py)
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from fractions import Fraction

from tools.tables import DATA_DIR, REPORTS_DIR

RECIPE_DIR = DATA_DIR / "recipes"
ITEMS_DIR = DATA_DIR / "items"
STATIONS = ("manual", "machine", "spaceship")
REPORT_PATH = REPORTS_DIR / "recipe-analysis.md"
MAX_EXTERN_ROUNDS = 32   # 外部投料点自动求解的最大迭代轮数(每轮至少新增一个物品)

RECYCLER_PREFIX = "dismantler_"                     # 拆解机:回收/反向配方,默认不作产出途径
STATION_RANK = {"machine": 0, "manual": 1, "spaceship": 2}

# 所需气体环境(机器表 gasEnv / FactoryEnvDisplayTable):0=无要求
GAS_ENV_NAMES = {1: "稳定环境", 2: "湿润环境", 3: "酸性环境", 4: "息壤环境"}
# 环境维持供气(FactoryVaporizerTable vaporizer_1:气体散布机持续通入气体形成
# 对应气体环境,各类气体恒 6/min、上限 30;一台散布机可同时影响范围内多台设备):
# 值 = (供气气体 id, 该气体的生成配方(液气转化);None = 无生成配方,按采集)
GAS_ENV_PROVIDERS = {
    1: ("item_gas_inert", None),                                  # 惰气:矿点采集
    2: ("item_gas_water", None),                                  # 水蒸气:水泵采集
    3: ("item_gas_acid", "liquid_transmuter_1_gas_gas_acid_1"),   # 酸气:沉积酸液气转化
    4: ("item_gas_xiranite", "liquid_transmuter_1_gas_gas_xiranite_1"),
}
GAS_ENV_RATE = Fraction(6)
# 设备维持消耗(FactoryTransmuterTable):转化机运行需持续通入息壤系气体
# 6/min/台(上限 30)——液气转化机通液化息壤、固气转化机通息壤气;
# 这就是「溶液方案省息壤气」的出处:液气路线把维持消耗从息壤气换成液化息壤
MACHINE_UPKEEP = {
    "transmuter_1": "item_liquid_xiranite",   # 液气转化机:液化息壤
    "transmuter_2": "item_gas_xiranite",      # 固气转化机:息壤气
}

# 叶子类型(展开终止原因)
KIND_CRAFT = "craft"        # 经配方制造(内部节点)
KIND_RAW = "raw"            # 无产出配方 → 最初用料
KIND_PROVIDED = "provided"  # 命中 --have 清单 → 外部提供
KIND_EXTERN = "external"    # 回收环外部投料点(求解器自动判定)→ 需外部投料
KIND_CYCLE = "cycle"        # 宽松兜底:产出配方全被环堵死 → 需外部投料
KIND_LABEL = {KIND_RAW: "最初用料", KIND_PROVIDED: "外部提供(--have)",
              KIND_EXTERN: "外部投料(环)", KIND_CYCLE: "需外部投料(循环)",
              KIND_CRAFT: "制造"}


# ---------------------------------------------------------------- 数据模型
@dataclass(frozen=True)
class Stack:
    """摊平后的一条原料/产物:(物品 id, 中文名, 单次数量)。"""

    id: str
    name: str
    count: int


@dataclass(frozen=True)
class Recipe:
    id: str
    station: str
    label: str                                   # 手工配方名 / 机器 formulaDesc / 飞船 showingName
    ingredients: tuple[Stack, ...]
    outcomes: tuple[Stack, ...]
    craft_time: float | None
    machine_name: str | None = None              # 生产设施中文名(机器配方,设备数折算展示用)
    machine_id: str | None = None                # 生产设施 ID(设备维持消耗查表用)
    gas_env: int = 0                             # 所需气体环境:0=无,1=稳定,2=湿润,3=酸性,4=息壤

    @property
    def env_name(self) -> str | None:
        return GAS_ENV_NAMES.get(self.gas_env)

    def yield_of(self, item: str) -> int:
        """单次制造产出 item 的数量(仅统计目标物品本身,副产物另计不计抵扣)。"""
        for s in self.outcomes:
            if s.id == item:
                return s.count
        return 0

    def consume_of(self, item: str) -> int:
        """单次制造消耗 item 的数量(各原料槽求和,正常数据至多一槽)。"""
        return sum(s.count for s in self.ingredients if s.id == item)

    def describe(self) -> str:
        ins = " + ".join(f"{s.name}×{s.count}" for s in self.ingredients) or "(无原料)"
        outs = " + ".join(f"{s.name}×{s.count}" for s in self.outcomes)
        return f"{ins} → {outs}"


@dataclass
class CycleMacro:
    """自持环宏配方:环上配方按 ratio 循环执行,环内其他物品守恒,每轮净产 demanded。

    ratio 与 recipes 对齐(前环配方在前、收口配方在后);side_nets = 非环物品
    每轮净流量(<0 净耗,需外部供给并递归展开;>0 净产,仅作注记)。
    """

    demanded: str                                # 需求原料(环的净产物品)
    loop: tuple[str, ...]                        # 环内物品(前环物品, 需求原料)
    recipes: tuple[Recipe, ...]
    ratio: tuple[int, ...]
    net_per_round: Fraction
    side_nets: dict[str, Fraction]

    def side_inputs(self) -> dict[str, Fraction]:
        return {i: -n for i, n in self.side_nets.items() if n < 0}

    def side_outputs(self) -> dict[str, Fraction]:
        return {i: n for i, n in self.side_nets.items() if n > 0}


@dataclass
class ReqNode:
    """展开树节点:kind=craft 为内部节点(带配方与子需求),其余为叶子。"""

    id: str
    name: str
    qty: Fraction
    kind: str
    recipe: Recipe | None = None
    crafts: Fraction | None = None               # kind=craft:需制造次数
    children: list["ReqNode"] = field(default_factory=list)
    chain: tuple[str, ...] = ()                  # kind=cycle:从目标到该物品的依赖链(id)
    macro: CycleMacro | None = None              # kind=craft:由自持环净产供给
    macro_rounds: Fraction | None = None         # 宏配方循环轮数
    extra_crafts: dict[str, Fraction] = field(default_factory=dict)  # 环上其他配方的执行次数

    def walk(self) -> Iterator["ReqNode"]:
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class Requirement:
    """一次(或多目标)倒推的完整结果:各目标展开树 + 摊平合计。"""

    roots: list[ReqNode]
    strict_ok: bool                              # 严格模式是否走通(False = 结果含环叶兜底)
    leaves: dict[tuple[str, str], Fraction]      # (物品, 叶子类型) → 精确总量
    crafts: dict[str, Fraction]                  # 配方 id → 制造次数(含环上配方)
    recipes_by_id: dict[str, Recipe]
    notes: list[str] = field(default_factory=list)   # 自持环注记(初始占用等)
    byproducts: dict[str, Fraction] = field(default_factory=dict)    # 副产物净产出(非目标)
    byproduct_sources: dict[str, str] = field(default_factory=dict)  # 副产物 → 首个产出配方
    upkeep_supplies: dict[str, Fraction] = field(default_factory=dict)  # 其中供设备维持的净产出

    @property
    def root(self) -> ReqNode:
        """单目标口径的主展开树(多目标时为首个目标)。"""
        return self.roots[0]

    def materials(self) -> dict[str, Fraction]:
        """需求原料聚合(物品 → 净外部需求量,含全部叶子类型),按数量降序。"""
        out: dict[str, Fraction] = {}
        for (i, _k), v in self.leaves.items():
            out[i] = out.get(i, Fraction(0)) + v
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def leaf_items(self, *kinds: str) -> list[tuple[ReqNode, Fraction]]:
        """按叶子类型取合计(保留树中节点的中文名/依赖链),按数量降序。"""
        out: list[tuple[ReqNode, Fraction]] = []
        seen: set[tuple[str, str]] = set()
        for root in self.roots:
            for node in root.walk():
                if node.kind == KIND_CRAFT:
                    continue
                key = (node.id, node.kind)
                if key in seen or (kinds and node.kind not in kinds):
                    continue
                seen.add(key)
                out.append((node, self.leaves[key]))
        return sorted(out, key=lambda t: (-t[1], t[0].id))

    def required_envs(self) -> list[tuple[str, list[str]]]:
        """链上配方要求的气体环境(非零 gasEnv)→ [环境名, [配方…]],稳定>湿润>酸性>息壤。"""
        envs: dict[str, list[str]] = {}
        for rid in self.crafts:
            env = self.recipes_by_id[rid].env_name
            if env:
                envs.setdefault(env, []).append(rid)
        return sorted(envs.items(), key=lambda kv: list(GAS_ENV_NAMES.values()).index(kv[0]))

    def env_upkeep(self) -> list[tuple[str, str, Fraction]]:
        """环境维持清单:(环境名, 供气气体 id, 每分钟通入量)。

        气体散布机持续通入对应气体形成环境(FactoryVaporizerTable:各类气体
        恒 6/min,上限 30),一台散布机可同时影响范围内多台设备,按环境各计一台。
        """
        used = {self.recipes_by_id[rid].gas_env for rid in self.crafts}
        return [(GAS_ENV_NAMES[e], GAS_ENV_PROVIDERS[e][0], GAS_ENV_RATE)
                for e in sorted(used) if e in GAS_ENV_PROVIDERS]

    def used_facilities(self) -> list[str]:
        """链上用到的生产设施中文名(按制造步骤首次出现序去重)。"""
        seen, out = set(), []
        for rid in self.crafts:
            name = self.recipes_by_id[rid].machine_name or self.recipes_by_id[rid].station
            if name not in seen:
                seen.add(name)
                out.append(name)
        return out


# ---------------------------------------------------------------- 数据加载
def _flatten(side: list[dict]) -> tuple[Stack, ...]:
    """[{group:[...]}] → 摊平元组;同组同槽原料同时消耗(AND),直接拼接。"""
    out = []
    for entry in side:
        for s in entry.get("group", []):
            out.append(Stack(s["id"], s.get("name") or s["id"], int(s.get("count", 1))))
    return tuple(out)


def load_recipes() -> list[Recipe]:
    recipes = []
    for station in STATIONS:
        for f in sorted((RECIPE_DIR / station).glob("*.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            recipes.append(Recipe(
                id=r["id"], station=station,
                label=r.get("name") or r.get("formulaDesc") or r.get("showingName") or r["id"],
                ingredients=_flatten(r.get("ingredients", [])),
                outcomes=_flatten(r.get("outcomes", [])),
                craft_time=r.get("craftTimeSec"),
                machine_name=r.get("machineName"),
                machine_id=r.get("machineId"),
                gas_env=int(r.get("gasEnv") or 0),
            ))
    return recipes


def _load_item_names() -> tuple[dict[str, str], dict[str, str]]:
    """data/items/ 全量 id→中文名 与 id→获取途径首条(最初用料的来源注记,
    如 惰气 = 惰气矿点采集)。"""
    names: dict[str, str] = {}
    obtain: dict[str, str] = {}
    for f in ITEMS_DIR.glob("*/*.json"):
        try:
            it = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(it, dict) and it.get("name"):
            names[it["id"]] = it["name"]
            ways = it.get("obtainWays")
            if ways:
                obtain[it["id"]] = ways[0]
    return names, obtain


class RecipeGraph:
    """配方只读索引:物品 → 产出配方(确定性排序)、id↔名称解析、采集属性。"""

    def __init__(self, recipes: list[Recipe] | None = None) -> None:
        self.recipes = load_recipes() if recipes is None else list(recipes)
        self.recipes_by_id = {r.id: r for r in self.recipes}
        # 产出图谱只收非拆解配方(拆解 = 回收环,见模块 docstring)
        self.producers: dict[str, list[Recipe]] = {}
        for r in self.recipes:
            if r.id.startswith(RECYCLER_PREFIX):
                continue
            for s in r.outcomes:
                self.producers.setdefault(s.id, []).append(r)
        for item, rs in self.producers.items():
            rs.sort(key=lambda r: self._order_key(r, item))
        self._names: dict[str, str] = {s.id: s.name for r in self.recipes for s in r.outcomes + r.ingredients}
        self._used_items: set[str] = {s.id for r in self.recipes for s in r.ingredients}
        self._item_names: dict[str, str] | None = None
        self._obtain: dict[str, str] | None = None

    @staticmethod
    def _order_key(r: Recipe, item: str) -> tuple:
        """产出配方择路序:主产物 → 站点 → 耗时 → id(见模块 docstring)。"""
        return (
            0 if (r.outcomes and r.outcomes[0].id == item) else 1,
            STATION_RANK.get(r.station, 9),
            (0, r.craft_time) if r.craft_time is not None else (1, 0.0),
            r.id,
        )

    # -- 名称与解析 -----------------------------------------------------------
    def name_of(self, item: str) -> str:
        """物品中文名;配方与 items 数据集都未覆盖时回退为 id。"""
        if item in self._names:
            return self._names[item]
        return self._name_pool().get(item, item)

    def obtain_of(self, item: str) -> str | None:
        """物品获取途径首条(items 数据集 obtainWays,最初用料来源注记)。"""
        self._ensure_items_loaded()
        return self._obtain.get(item)

    def is_gatherable(self, item: str) -> bool:
        """采集类资源(obtainWays 非空,如 清水=水泵采集):收缩阶段不翻成内部合成。"""
        return self.obtain_of(item) is not None

    def resolve(self, query: str) -> tuple[str | None, list[str]]:
        """查询串 → 物品 id。依次:精确 id → 精确名称 → 唯一子串(大小写不敏感)。
        多候选时确定性择优:参与配方图的物品优先,其次 id 较短、字典序较小者
        (数据集里系统蓝图/杂项与材料同名,如 铁制零件 = item_iron_cmpt 与 sysbp_*);
        未命中返回 (None, 按相关性排序的候选)。"""
        ids = self._all_item_ids()
        if query in ids:
            return query, []
        by_name: dict[str, list[str]] = {}
        for iid in ids:
            by_name.setdefault(self.name_of(iid), []).append(iid)
        cands = by_name.get(query) or [iid for iid in ids
                                       if query.lower() in iid.lower() or query in self.name_of(iid)]
        if not cands:
            return None, []
        return self._rank(cands)[0], []

    # -- 报告辅助 -------------------------------------------------------------
    def cycle_groups(self) -> list[list[str]]:
        """产出图谱(不含拆解配方)上的极大强连通分量,即潜在循环依赖组。"""
        graph = {i: set() for i in self.producers}
        for item, rs in self.producers.items():
            for r in rs:
                for s in r.ingredients:
                    if s.id in self.producers:
                        graph[item].add(s.id)
        index, low, on_stack, stack, counter, sccs = {}, {}, set(), [], [0], []

        def strong(v: str) -> None:
            index[v] = low[v] = counter[0]
            counter[0] += 1
            stack.append(v)
            on_stack.add(v)
            for w in graph[v]:
                if w not in index:
                    strong(w)
                    low[v] = min(low[v], low[w])
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1 or v in graph[v]:
                    sccs.append(sorted(comp, key=self.name_of))

        for v in sorted(graph):
            if v not in index:
                strong(v)
        return sorted(sccs, key=lambda c: (-len(c), self.name_of(c[0])))

    # -- 内部助手 -------------------------------------------------------------
    def _name_pool(self) -> dict[str, str]:
        """items 数据集的全量 id→中文名(首次访问时加载)。"""
        if self._item_names is None:
            self._item_names, self._obtain = _load_item_names()
        return self._item_names

    def _ensure_items_loaded(self) -> None:
        self._name_pool()

    def _all_item_ids(self) -> set[str]:
        return set(self._name_pool())

    def _rank(self, cands: list[str]) -> list[str]:
        """候选排序:参与配方图(可制造或被配方消耗)优先 → id 短者优先 → 字典序。"""
        def in_graph(i: str) -> bool:
            return i in self.producers or i in self._used_items
        return sorted(cands, key=lambda i: (not in_graph(i), len(i), i))


# ---------------------------------------------------------------- 倒推引擎
@dataclass(frozen=True)
class _ExpandCtx:
    """一次递归展开的固定口径:配方图与求解入参,外加运行期收集器。

    closures 为可变收集器:展开中把回收环闭环点 (A, X) 写入,供求解器
    外部投料阶段消费;宽松模式下的写入无消费者,无副作用。
    """

    graph: RecipeGraph
    provided: frozenset[str]           # --have 清单,展开到此为止
    extern: frozenset[str]             # 求解器判定的外部投料点
    pinned: dict[str, str]             # 物品 → 钉选配方
    strict: bool                       # True=配方全堵死返回 None;False=环叶兜底
    closures: set[tuple[str, str]]


def _expand(ctx: _ExpandCtx, item: str, qty: Fraction,
            path: tuple[tuple[str, str], ...]) -> ReqNode | None:
    """展开物品需求。path = [(物品, 所用配方), …] 祖先链(用于取环上配方表)。

    原料命中祖先 → 取环上配方表做净产出判定:净产出则以自持环宏配方供给
    (净耗物料继续递归);不净产出(等量回收环)→ 记录闭环点 (A, X) 供
    外部投料求解,同时弃此配方试下一产出配方。无产出配方的物品 = 最初用料;
    命中 --have / 自动外部投料点 = 叶子。所有配方皆堵死时,strict 返回 None,
    宽松记为 cycle 叶子(需外部投料)。"""
    if item in ctx.provided:
        return ReqNode(item, ctx.graph.name_of(item), qty, KIND_PROVIDED)
    if item in ctx.extern:
        return ReqNode(item, ctx.graph.name_of(item), qty, KIND_EXTERN)
    if item in ctx.pinned:
        recipe = ctx.graph.recipes_by_id.get(ctx.pinned[item])
        producers = [recipe] if recipe and recipe.yield_of(item) > 0 else []
    else:
        producers = ctx.graph.producers.get(item, [])
    if not producers:
        return ReqNode(item, ctx.graph.name_of(item), qty, KIND_RAW)
    for recipe in producers:
        children, blocked = [], False
        for ing in recipe.ingredients:
            hit = next((k for k, (iid, _) in enumerate(path) if iid == ing.id), None)
            if hit is not None:  # 环:取环上配方表做净产出判定
                chain = path[hit:] + ((item, recipe.id),)
                macro = _cycle_macro(ctx.graph, chain)
                if macro is not None:
                    rounds = qty / macro.net_per_round
                    m_children, ok = [], True
                    for sid, need in macro.side_inputs().items():
                        child = _expand(ctx, sid, need * rounds, path + ((item, recipe.id),))
                        if child is None:
                            ok = False
                            break
                        m_children.append(child)
                    if ok:
                        return ReqNode(
                            item, ctx.graph.name_of(item), qty, KIND_CRAFT,
                            recipe=recipe, crafts=Fraction(macro.ratio[-1]) * rounds,
                            children=m_children, macro=macro, macro_rounds=rounds,
                            extra_crafts={r.id: Fraction(k) * rounds
                                          for r, k in zip(macro.recipes[:-1], macro.ratio[:-1])})
                else:
                    ctx.closures.add((ing.id, item))
                blocked = True
                break
            child = _expand(ctx, ing.id, ing.count * qty / recipe.yield_of(item),
                            path + ((item, recipe.id),))
            if child is None:
                blocked = True
                break
            children.append(child)
        if not blocked:
            return ReqNode(item, ctx.graph.name_of(item), qty, KIND_CRAFT,
                           recipe=recipe, crafts=qty / recipe.yield_of(item),
                           children=children)
    if ctx.strict:
        return None
    return ReqNode(item, ctx.graph.name_of(item), qty, KIND_CYCLE,
                   chain=tuple(i for i, _ in path) + (item,))


def _cycle_macro(graph: RecipeGraph, chain: tuple[tuple[str, str], ...]) -> CycleMacro | None:
    """环上配方表 → 自持环宏配方;不构成可解的二环/自环或需求原料不净产出时返回 None。

    chain = [(环内物品, 各自所用配方), …],首元素为被重复访及的祖先 A,
    末元素为 (需求原料 X, 收口配方 R_X)。二环守恒解:R_X 每轮耗 A 共 b,
    R_A 每轮耗 X 共 a、产 A 共 q_A → 取 x_A = b、x_X = q_A,则 A 恰好守恒,
    X 净产 = q_X·q_A − a·b(>0 才自持);自环同理(x=1,净产 = q_X − a)。
    """
    if not 1 <= len(chain) <= 2:
        return None  # 多环/缠结环:数据集未出现,视同不净产出(见模块 docstring)
    x_id, rx_id = chain[-1]
    r_x = graph.recipes_by_id[rx_id]
    q_x = r_x.yield_of(x_id)
    if len(chain) == 1:  # 自环:配方消耗自身产出
        a = r_x.consume_of(x_id)
        if q_x <= 0 or a <= 0 or q_x <= a:
            return None
        recipes, ratio, loop, net = (r_x,), (1,), (x_id,), Fraction(q_x - a)
        flows = [(r_x, 1)]
    else:
        a_id, ra_id = chain[0]
        r_a = graph.recipes_by_id[ra_id]
        q_a, a, b = r_a.yield_of(a_id), r_a.consume_of(x_id), r_x.consume_of(a_id)
        if q_x <= 0 or min(q_a, a, b) <= 0:
            return None
        net = Fraction(q_x * q_a - a * b)
        if net <= 0:
            return None
        recipes, ratio, loop = (r_a, r_x), (b, q_a), (a_id, x_id)
        flows = [(r_a, b), (r_x, q_a)]
    side: dict[str, Fraction] = {}
    for r, times in flows:
        for s in r.ingredients:
            side[s.id] = side.get(s.id, Fraction(0)) - times * s.count
        for s in r.outcomes:
            side[s.id] = side.get(s.id, Fraction(0)) + times * s.count
    side_nets = {i: n for i, n in side.items() if i not in loop and n != 0}
    return CycleMacro(demanded=x_id, loop=loop, recipes=recipes, ratio=ratio,
                      net_per_round=net, side_nets=side_nets)


def _macro_note(graph: RecipeGraph, node: ReqNode) -> str:
    """自持环注记:配方比例、净耗净产与一次性初始占用。"""
    m = node.macro
    assert m is not None and node.macro_rounds is not None
    names = [graph.name_of(i) for i in m.loop]
    parts = [f"⟳ 自持环 {graph.name_of(m.demanded)}:"
             + " + ".join(f"{r.id} ×{fmt_qty(Fraction(k) * node.macro_rounds)} 次"
                          for r, k in zip(m.recipes, m.ratio))
             + f",循环内 {'、'.join(names[:-1]) or names[0]} 守恒"
             + f",每轮净产 {graph.name_of(m.demanded)} ×{fmt_qty(m.net_per_round)}"]
    if ins := m.side_inputs():
        parts.append("净耗 " + "、".join(f"{graph.name_of(i)} ×{fmt_qty(n * node.macro_rounds)}"
                                     for i, n in sorted(ins.items())))
    if outs := m.side_outputs():
        parts.append("净产 " + "、".join(f"{graph.name_of(i)} ×{fmt_qty(n * node.macro_rounds)}"
                                      for i, n in sorted(outs.items())))
    parts.append(f"需一次性初始占用 1 个环内物品(如 {names[0]}),此后循环内守恒")
    return ";".join(parts)


def _collect(roots: list[ReqNode], strict_ok: bool, ctx: _ExpandCtx,
             per_min: bool = False, byproducts: bool = True) -> Requirement:
    """展开树(可多目标)→ 摊平合计(叶子、配方执行次数、副产物净流量、自持环注记)。

    设备维持(仅速率口径):转化机每台持续通入息壤系气体 6/min(上限 30),
    按配方的设备台数折算;维持气体作为正常需求挂入树中继续向下展开
    (到息壤/清水等给定原料为止),不可自产时按采集资源记最初用料、否则记外部投料。
    byproducts=False 时:不挂载环境/设备维持子树,结果不含副产物净产出与维持供应。
    """
    graph = ctx.graph
    # 第一遍:配方执行次数与自持环注记(设备维持按台数折算,需先于维持挂载)
    crafts: dict[str, Fraction] = {}
    notes: list[str] = []
    for root in roots:
        for node in root.walk():
            if node.kind == KIND_CRAFT:
                assert node.recipe is not None and node.crafts is not None
                crafts[node.recipe.id] = crafts.get(node.recipe.id, Fraction(0)) + node.crafts
                for rid, n in node.extra_crafts.items():
                    crafts[rid] = crafts.get(rid, Fraction(0)) + n
                if node.macro is not None:
                    notes.append(_macro_note(graph, node))
    # 挂载附加叶子:环境维持(每环境恒 6/min)与设备维持(转化机台数 × 6/min)
    for env in sorted({graph.recipes_by_id[rid].gas_env for rid in crafts} if byproducts else []):
        provider = GAS_ENV_PROVIDERS.get(env)
        if provider is None:
            continue
        gas, gas_recipe = provider
        if gas_recipe is None:
            # 无生成配方(惰气/水蒸气):按最初用料(矿点/水泵采集)
            for root in roots:
                roots[0].children.append(ReqNode(gas, graph.name_of(gas), GAS_ENV_RATE, KIND_RAW))
            continue
        # 有生成配方:单级展开 env气体 ← 液气转化 ← 前体(沉积酸等,计外部投料);
        # 不深入前体的回收环,避免把整条转化链拖进环境维持
        r = graph.recipes_by_id[gas_recipe]
        env_crafts = GAS_ENV_RATE / r.yield_of(gas)
        for root in roots:
            env_node = ReqNode(gas, graph.name_of(gas), GAS_ENV_RATE, KIND_CRAFT,
                               recipe=r, crafts=env_crafts)
            env_node.children = [
                ReqNode(s.id, s.name or graph.name_of(s.id), s.count * env_crafts, KIND_EXTERN)
                for s in r.ingredients]
            roots[0].children.append(env_node)
    upkeep_qty: dict[str, Fraction] = {}
    if per_min and byproducts:
        for rid, n in crafts.items():
            r = graph.recipes_by_id[rid]
            gas = MACHINE_UPKEEP.get(r.machine_id or "")
            if not gas or not r.craft_time:
                continue
            machines = math.ceil(Fraction(n) * r.craft_time / 60)
            if machines > 0:
                upkeep_qty[gas] = upkeep_qty.get(gas, Fraction(0)) + GAS_ENV_RATE * machines
        for gas, qty in sorted(upkeep_qty.items()):
            child = _expand(replace(ctx, extern=frozenset()), gas, qty, ())
            if child is None:
                kind = KIND_RAW if graph.is_gatherable(gas) else KIND_EXTERN
                child = ReqNode(gas, graph.name_of(gas), qty, kind)
            roots[0].children.append(child)
    # 第二遍:完整汇总(维持子树已挂载,其下游一并计入)
    leaves: dict[tuple[str, str], Fraction] = {}
    crafts = {}
    target_ids = {root.id for root in roots}
    for root in roots:
        for node in root.walk():
            if node.kind == KIND_CRAFT:
                assert node.recipe is not None and node.crafts is not None
                crafts[node.recipe.id] = crafts.get(node.recipe.id, Fraction(0)) + node.crafts
                for rid, n in node.extra_crafts.items():
                    crafts[rid] = crafts.get(rid, Fraction(0)) + n
            else:
                key = (node.id, node.kind)
                leaves[key] = leaves.get(key, Fraction(0)) + node.qty
    # 全链净流量:产出-消耗;正值且非目标 = 副产物(如精炼炉的污水)
    flows: dict[str, Fraction] = {}
    for rid, n in crafts.items():
        r = graph.recipes_by_id[rid]
        for s in r.outcomes:
            flows[s.id] = flows.get(s.id, Fraction(0)) + n * s.count
        for s in r.ingredients:
            flows[s.id] = flows.get(s.id, Fraction(0)) - n * s.count
    byproducts = {i: f for i, f in flows.items()
                  if f > 0 and i not in target_ids and byproducts}
    sources: dict[str, str] = {}
    for i in byproducts:
        sources[i] = next(rid for rid, n in crafts.items()
                          if any(s.id == i for s in graph.recipes_by_id[rid].outcomes))
    return Requirement(roots=roots, strict_ok=strict_ok, leaves=leaves,
                       crafts=crafts, recipes_by_id=graph.recipes_by_id,
                       notes=notes, byproducts=byproducts, byproduct_sources=sources,
                       upkeep_supplies={i: f for i, f in byproducts.items()
                                        if f == upkeep_qty.get(i)})




def compute(graph: RecipeGraph, target: str, qty: Fraction,
            provided: frozenset[str] = frozenset(),
            pinned: dict[str, str] | None = None,
            per_min: bool = False,
            byproducts: bool = True) -> Requirement:
    """兼容入口(单目标):等价 RecursiveSolver 求解。

    provided 为持有物品 id 集合(等价 available={id: 0} 的数量不限清单);
    pinned/_byproducts 语义见 analysis.solvers.RecipeSolver.solve。
    """
    from analysis.solvers.recursive import RecursiveSolver
    solver = RecursiveSolver(graph)
    return solver.solve({target: qty},
                        available={a: 0 for a in provided},
                        preferred=dict(pinned or {}),
                        per_min=per_min, byproducts=byproducts)


# ---------------------------------------------------------------- 展示
def parse_qty(text: str) -> tuple[Fraction, bool]:
    """"6" / "1/2" / "0.5" / "60/min"(或 "/分钟")→ (数量, 是否每分钟速率)。

    速率语义:数量按每分钟产出计,材料流量 = 每分钟需求;设备数按
    「产量/分钟 × 单次制造耗时(秒)÷ 60」向上取整折算。
    """
    t = text.strip().lower()
    per_min = False
    for suffix in ("/min", "/分钟"):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
            per_min = True
            break
    try:
        amount = Fraction(t)
    except (ValueError, ZeroDivisionError) as e:
        raise ValueError(f"数量须为整数/分数/小数或速率(如 60/min),收到:{text!r}") from e
    if amount <= 0:
        raise ValueError(f"数量须为正数,收到:{text!r}")
    return amount, per_min


def machine_counts(req: Requirement) -> list[tuple[Recipe, Fraction, int]]:
    """速率口径的设备需求:各配方 → (配方, 产量/分钟, 所需设施数)。

    设施数 = ceil(产量每分钟 × 单次制造耗时秒 ÷ 60);无耗时数据(手工/飞船)
    的配方不参与,调用方自行提示。
    """
    out = []
    for rid, n in sorted(req.crafts.items()):
        r = req.recipes_by_id[rid]
        if r.craft_time:
            out.append((r, n, math.ceil(n * r.craft_time / 60)))
    return out


def fmt_qty(q: Fraction) -> str:
    """精确量:整数直书;分数保留 a b/c 形式。"""
    if q.denominator == 1:
        return str(q.numerator)
    whole, rest = divmod(q, 1)
    return f"{whole} + {rest}" if whole else f"{rest}"


def fmt_ceil(q: Fraction) -> str:
    """向上取整后的整数字符串(备料数量:不可零碎备料)。"""
    return str(-(-q.numerator // q.denominator))


def _chain_text(graph: RecipeGraph, chain: tuple[str, ...], item: str) -> str:
    """循环依赖链中文名:A → B → A。"""
    return " → ".join(graph.name_of(i) for i in (*chain, item))


def render_tree(graph: RecipeGraph, node: ReqNode, _prefix: str = "", _is_last: bool = True) -> list[str]:
    """标准树形渲染:分支符(├─/└─)画在子行,延续符(│ /空格)传给孙辈;
    配方/循环注脚(⮡)缩进与子节点平齐,画在该节点全部子节点之后。"""
    root_line = _prefix == ""
    branch = "" if root_line else ("└─ " if _is_last else "├─ ")
    lines = [f"{_prefix}{branch}{node.name} ×{fmt_qty(node.qty)}"]
    ext = "   " if _is_last else "│  "
    for i, c in enumerate(node.children):
        lines.extend(render_tree(graph, c, _prefix + ext, i == len(node.children) - 1))
    note = None
    if node.kind == KIND_CRAFT and node.recipe is not None:
        assert node.crafts is not None
        if node.macro is not None:
            m = node.macro
            assert node.macro_rounds is not None
            note = (f"⟳ 自持环净产 ×{fmt_qty(node.qty)}:"
                    + " + ".join(f"{r.id}×{fmt_qty(Fraction(k) * node.macro_rounds)} 次"
                                 for r, k in zip(m.recipes, m.ratio)))
        else:
            note = f"配方 {node.recipe.id} ×{fmt_qty(node.crafts)} 次({node.recipe.describe()})"
            if not node.recipe.ingredients:
                note += " [飞船制造,无原料]"
    elif node.kind == KIND_CYCLE:
        note = (f"循环依赖:{_chain_text(graph, node.chain, node.id)}"
                f"(加入 --have 可展开其后继用料)")
    if note:
        lines.append(f"{_prefix}{ext}⮡ {note}")
    return lines


def render_mermaid(graph: RecipeGraph, req: Requirement) -> str:
    """产出链路图(mermaid flowchart):物品/配方二部图,原料→配方→产物,
    副产物为虚线边,自持环完整画出环上两条配方。"""
    edges: dict[tuple[str, str, bool], Fraction] = {}
    items: set[str] = set()
    recipes: set[str] = set()

    def add(src: str, dst: str, qty: Fraction, dashed: bool = False) -> None:
        key = (src, dst, dashed)
        edges[key] = edges.get(key, Fraction(0)) + qty

    for node in req.root.walk():
        if node.kind != KIND_CRAFT or node.recipe is None:
            continue
        if node.macro is not None:  # 自持环:环上配方逐条入图(含循环边)
            m = node.macro
            for r, k in zip(m.recipes, m.ratio):
                run = k * (node.macro_rounds or Fraction(1))
                recipes.add(r.id)
                for s in r.ingredients:
                    items.add(s.id)
                    add("I_" + s.id, "R_" + r.id, run * s.count)
                for s in r.outcomes:
                    items.add(s.id)
                    add("R_" + r.id, "I_" + s.id, run * s.count)
            continue
        r = node.recipe
        recipes.add(r.id)
        for s in r.ingredients:
            items.add(s.id)
            add("I_" + s.id, "R_" + r.id, s.count * node.crafts)
        items.add(node.id)
        add("R_" + r.id, "I_" + node.id, node.qty)
    for i, net in req.byproducts.items():       # 副产物:虚线边自首个产出配方
        items.add(i)
        add("R_" + req.byproduct_sources[i], "I_" + i, net, dashed=True)

    def q(x: Fraction) -> str:
        return f"×{fmt_qty(x)}"

    lines = ["flowchart LR"]
    for i in sorted(items):
        kind = next((n.kind for n in req.root.walk() if n.id == i and n.kind != KIND_CRAFT),
                    "craft")
        if i == req.root.id:
            lines.append(f"  I_{i}((\"{graph.name_of(i)}<br/>目标 ×{fmt_qty(req.root.qty)}\"))")
        elif kind != KIND_CRAFT:
            shape = ["([", "])"] if kind == KIND_RAW else ["[[", "]]"]
            lines.append(f"  I_{i}{shape[0]}\"{graph.name_of(i)}\"{shape[1]}")
        else:
            lines.append(f"  I_{i}[\"{graph.name_of(i)}\"]")
    for rid in sorted(recipes):
        r = graph.recipes_by_id[rid]
        label = r.machine_name or r.label
        lines.append(f"  R_{rid}[\"{label}<br/>{rid}\"]")
    for (src, dst, dashed), qty in sorted(edges.items()):
        arrow = "-.->" if dashed else "-->"
        lines.append(f"  {src} {arrow}|\"{q(qty)}\"| {dst}")
    return "\n".join(lines)


def render_result(graph: RecipeGraph, target_label: str, req: Requirement,
                  per_min: bool = False) -> str:
    """控制台查询结果:展开树 + 需求原料 + 产出(含副产物) + 制造步骤 + 设备 + 环境 + 链路图。"""
    unit = "/min" if per_min else ""
    qty_word = f"×{fmt_qty(req.root.qty)}{unit}"
    lines = [f"目标 {target_label} {qty_word}"]
    lines += render_tree(graph, req.root)
    lines.append("")
    leaves = req.leaf_items()
    if not leaves:
        lines.append("需求原料:无需任何原料(目标本身来自 --have 清单或飞船制造)")
    else:
        head = "需求原料(每分钟流量;精确流量 → 实备数量)" if per_min else "需求原料(精确用量 → 实备数量)"
        lines.append(f"{head},{len(leaves)} 项:")
        for node, total in leaves:
            kind = KIND_LABEL[node.kind]
            line = (f"  [{kind}] {node.name:<12} ×{fmt_qty(total):<10} → 备料 "
                    f"{fmt_ceil(total)}{unit}")
            if node.kind == KIND_CYCLE:
                line += f"   ⚠ {_chain_text(graph, node.chain, node.id)}"
            elif node.kind == KIND_RAW and (src := graph.obtain_of(node.id)):
                line += f"({src})"
            lines.append(line)
    parts = [f"目标 {graph.name_of(req.root.id)} {qty_word}"]
    if true_bp := {i: n for i, n in req.byproducts.items() if i not in req.upkeep_supplies}:
        bp = "、".join(f"{graph.name_of(i)} ×{fmt_qty(n)}{unit}"
                       f"(← {req.byproduct_sources[i]})"
                       for i, n in sorted(true_bp.items(), key=lambda kv: -kv[1]))
        parts.append(f"副产物 {bp}")
    if req.upkeep_supplies:
        sup = "、".join(f"{graph.name_of(i)} ×{fmt_qty(n)}{unit}"
                        f"(← {req.byproduct_sources[i]},供转化机通入)"
                        for i, n in sorted(req.upkeep_supplies.items(), key=lambda kv: -kv[1]))
        parts.append(f"维持供应 {sup}")
    lines.append("产出:" + ";".join(parts))
    craft_lines = [f"  {rid} ×{fmt_qty(n)} 次{unit}  {graph.recipes_by_id[rid].describe()}"
                   for rid, n in sorted(req.crafts.items())]
    if craft_lines:
        lines.append("制造步骤" + ("(每分钟执行次数):" if per_min else ":"))
        lines += craft_lines
    facilities = req.used_facilities()
    if per_min:
        machines = machine_counts(req)
        if machines:
            lines.append("设备需求(设施数 = 产量每分钟 × 单次耗时 ÷ 60,向上取整):")
            lines += [f"  {r.machine_name or r.station:<4} {r.id} ×{m} 台"
                      f"({fmt_qty(n)}/min × {r.craft_time:g}s)" for r, n, m in machines]
        if upkeep := req.env_upkeep():
            lines.append(f"  气体散布机 vaporizer ×{len(upkeep)} 台"
                         f"(环境维持,每种气体 {fmt_qty(GAS_ENV_RATE)}/min)")
        no_time = [rid for rid in req.crafts if not req.recipes_by_id[rid].craft_time]
        if no_time:
            lines.append("  无耗时数据不计设备:" + "、".join(no_time))
    elif facilities:
        names = facilities + (["气体散布机"] if req.env_upkeep() else [])
        lines.append("使用设备:" + "、".join(names))
    envs = req.required_envs()
    if envs:
        upkeep = {name: (gas, rate) for name, gas, rate in req.env_upkeep()}
        parts = []
        for env, rids in envs:
            base = f"{env}({', '.join(rids)})"
            if env in upkeep:
                gas, rate = upkeep[env]
                base += f" ← 气体散布机 通入{graph.name_of(gas)} ×{fmt_qty(rate)}/min"
            parts.append(base)
        lines.append("环境需求:" + ";".join(parts))
    else:
        lines.append("环境需求:无特殊气体环境(全部常规)")
    lines.append("产出链路图(mermaid):")
    lines.append("```mermaid")
    lines.append(render_mermaid(graph, req))
    lines.append("```")
    lines.extend(req.notes)
    if not req.strict_ok:
        lines.append("⚠ 严格推演被循环依赖堵死,上表按「循环物品=外部投料」宽松口径汇总;")
        lines.append("  如持有其中物品,加入 --have(如 --have " + ",".join(
            sorted({n.id for n in req.root.walk() if n.kind == KIND_CYCLE})) + ")可得到更精确的分解")
    return "\n".join(lines)


def result_json(req: Requirement, graph: RecipeGraph, per_min: bool = False) -> dict:
    """机器可读输出(Fraction → "num/den" 字符串 + ceil 整数)。"""

    def node_json(n: ReqNode) -> dict:
        d: dict = {"id": n.id, "name": n.name, "qty": str(n.qty),
                   "qty_ceil": int(-(-n.qty.numerator // n.qty.denominator)), "kind": n.kind}
        if n.recipe is not None:
            d["recipe_id"] = n.recipe.id
            assert n.crafts is not None
            d["crafts"] = str(n.crafts)
        if n.macro is not None:
            assert n.macro_rounds is not None
            d["macro"] = {"loop": list(n.macro.loop), "recipes": [r.id for r in n.macro.recipes],
                          "ratio": list(n.macro.ratio), "rounds": str(n.macro_rounds),
                          "net_per_round": str(n.macro.net_per_round),
                          "side_inputs": {i: str(v) for i, v in n.macro.side_inputs().items()},
                          "side_outputs": {i: str(v) for i, v in n.macro.side_outputs().items()}}
        if n.kind == KIND_CYCLE:
            d["chain"] = list(n.chain) + [n.id]
        return {**d, "children": [node_json(c) for c in n.children]}

    def fr(v: Fraction) -> dict:
        return {"exact": str(v), "ceil": int(-(-v.numerator // v.denominator))}

    upkeep_by_name = {name: (gas, rate) for name, gas, rate in req.env_upkeep()}
    environments = [{"name": env, "recipes": rids,
                     **({"provider_gas": gas, "provider_rate_per_min": str(rate)}
                        if (pair := upkeep_by_name.get(env)) else {})}
                    for env, rids in req.required_envs()]
    return {
        "target": {"id": req.root.id, "name": req.root.name, "qty": str(req.root.qty),
                   "per_min": per_min},
        "strict_ok": req.strict_ok,
        "notes": req.notes,
        "tree": node_json(req.root),
        "leaves": [{"id": n.id, "name": n.name, "kind": n.kind, **fr(total),
                    **({"chain": list(n.chain) + [n.id]} if n.kind == KIND_CYCLE else {}),
                    **({"obtain": src} if n.kind == KIND_RAW and (src := graph.obtain_of(n.id)) else {})}
                   for n, total in req.leaf_items()],
        "crafts": [{"recipe": rid, "station": req.recipes_by_id[rid].station, **fr(n)}
                   for rid, n in sorted(req.crafts.items())],
        "byproducts": [{"id": i, "name": graph.name_of(i),
                        "source_recipe": req.byproduct_sources[i], **fr(n)}
                       for i, n in sorted(req.byproducts.items(), key=lambda kv: -kv[1])],
        "environments": environments,
        "facilities": req.used_facilities(),
        "mermaid": render_mermaid(graph, req),
        **({"machines": [{"recipe": r.id, "machine": r.machine_name,
                          "craft_time_sec": r.craft_time, "count": m}
                         for r, _, m in machine_counts(req)]
            + [{"machine": "气体散布机", "count": len(req.env_upkeep())}]
            } if per_min else {}),
    }


# ---------------------------------------------------------------- 总览报告
def build_report(graph: RecipeGraph, demos: list[tuple[str, Fraction, frozenset[str]]]) -> str:
    """数据概览 + 择路口径 + 潜在循环依赖组 + 示例倒推(reports/recipe-analysis.md)。"""
    lines = ["# 配方用料倒推 · 数据概览", ""]
    lines.append(f"- 配方 {len(graph.recipes)} 条(" +
                 "、".join(f"{s} {sum(1 for r in graph.recipes if r.station == s)}" for s in STATIONS) +
                 f");其中拆解/回收配方(dismantler_)"
                 f"{sum(1 for r in graph.recipes if r.id.startswith(RECYCLER_PREFIX))} 条")
    items_used = {s.id for r in graph.recipes for s in r.ingredients}
    items_made = set(graph.producers)
    lines.append(f"- 涉及物品:产出 {len(items_made)} 种,原料 {len(items_used)} 种;"
                 f"无配方最初用料 {len(items_used - items_made)} 种,可制造 "
                 f"{len(items_made & items_used)} 种")
    lines.append("- 口径:同组/同槽原料同时消耗(AND);副产物不做回收抵扣;"
                 "配方择路 = 主产物 → machine>manual>spaceship → 耗时短 → id;"
                 "拆解(dismantler_)配方不列为产出途径")
    lines.append("- 环处理:取环上配方表,环内物品守恒下判定需求原料是否净产出 ——"
                 "净产出即自持环宏配方(净耗继续展开,注记初始占用);"
                 "不净产出(等量回收环)则换下一产出配方,全败才记外部投料")
    lines.append("")

    groups = graph.cycle_groups()
    lines.append(f"## 潜在循环依赖(产出图谱,{len(groups)} 组)")
    lines.append("")
    lines.append("以下物品组在图谱上互达成环,倒推时分两类处理:种子↔作物类为**净产环**"
                 "(自持宏配方,仅需一次性初始占用与清水等净耗);清水⇄水蒸气、块⇄粉末"
                 "类为**等量回收环**(净产出为零),环上物品由求解器择一记为外部投料"
                 "(亦可用 --have 指定持有):")
    lines.append("")
    for comp in groups:
        lines.append(f"- {' → '.join(graph.name_of(i) for i in comp)} → {graph.name_of(comp[0])}")
    lines.append("")

    for label, qty, provided in demos:
        target, cands = graph.resolve(label)
        if target is None:
            continue
        req = compute(graph, target, qty, provided)
        lines.append(f"## 示例:{graph.name_of(target)} ×{fmt_qty(qty)}"
                     + (f"(--have {','.join(sorted(provided))})" if provided else ""))
        lines.append("")
        lines.append("```")
        lines.append(render_result(graph, graph.name_of(target), req))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI
def _resolve_pins(graph: RecipeGraph,
                  recipe_pins: list[str] | None) -> dict[str, str]:
    """--recipe 物品=配方ID 列表 → {物品 id: 配方 id},逐项校验。"""
    pinned: dict[str, str] = {}
    for token in recipe_pins or []:
        name_part, _, recipe_part = token.partition("=")
        if not recipe_part:
            sys.exit(f"--recipe 须为 物品=配方ID 形式,收到:{token!r}")
        iid, cands = graph.resolve(name_part.strip())
        if iid is None:
            sys.exit(f"未识别 --recipe 中的物品:{name_part!r}"
                     + (f";候选:{'、'.join(graph.name_of(c) for c in cands[:8])}" if cands else ""))
        rid = recipe_part.strip()
        recipe = graph.recipes_by_id.get(rid)
        if recipe is None:
            sys.exit(f"--recipe 未找到配方:{rid!r}")
        if recipe.yield_of(iid) <= 0:
            outs = "、".join(s.name for s in recipe.outcomes)
            sys.exit(f"配方 {rid} 不产出 {graph.name_of(iid)}(产出:{outs})")
        pinned[iid] = rid
    return pinned


def _resolve_provided(graph: RecipeGraph, have: str) -> frozenset[str]:
    """--have 逗号分隔清单 → 物品 id 集合。"""
    ids = []
    for token in filter(None, (t.strip() for t in have.split(","))):
        iid, cands = graph.resolve(token)
        if iid is None:
            sys.exit(f"未识别 --have 中的物品:{token};候选:{'、'.join(graph.name_of(c) for c in cands[:8])}")
        ids.append(iid)
    return frozenset(ids)


def main(item: str | None = None, qty: str = "1", have: str = "",
         as_json: bool = False, recipe_pins: list[str] | None = None,
         solver: str = "recursive", byproducts: bool = True) -> None:
    from analysis.solvers import SOLVERS   # 惰性导入,避免与求解器实现的循环依赖
    graph = RecipeGraph()
    solver_cls = SOLVERS.get(solver)
    if solver_cls is None:
        sys.exit(f"未知求解器:{solver!r};可选:{', '.join(SOLVERS)}")
    pinned = _resolve_pins(graph, recipe_pins)
    provided = _resolve_provided(graph, have)

    if item is None:  # 总览报告模式
        demos = [
            ("铁制零件", Fraction(10), frozenset()),
            ("分离芯", Fraction(4), frozenset()),
            ("锦草", Fraction(10), frozenset()),
            ("柑实罐头", Fraction(5), frozenset()),
        ]
        report = build_report(graph, demos)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(f"配方用料倒推 · 数据概览 → {REPORT_PATH}")
        print(f"  配方 {len(graph.recipes)} 条,物品 {len(set(graph.producers))} 种,"
              f"潜在循环依赖 {len(graph.cycle_groups())} 组")
        return

    target, cands = graph.resolve(item)
    if target is None:
        hint = "、".join(f"{graph.name_of(c)}({c})" for c in cands[:8])
        sys.exit(f"未识别目标物品:{item!r}" + (f";候选:{hint}" if cands else ""))
    try:
        amount, per_min = parse_qty(qty)
    except ValueError as e:
        sys.exit(str(e))

    req = solver_cls(graph).solve({target: amount},
                                  available={a: 0 for a in provided},
                                  preferred=pinned, per_min=per_min,
                                  byproducts=byproducts)
    if as_json:
        print(json.dumps(result_json(req, graph, per_min), ensure_ascii=False, indent=2))
    else:
        label = graph.name_of(target) + (f"({target})" if target != graph.name_of(target) else "")
        print(render_result(graph, label, req, per_min))
