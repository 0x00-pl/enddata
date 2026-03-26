"""配方用料倒推:给定最终产物与数量,沿 recipes/ 配方图回溯用料数量。

回答的问题:「要 N 个 X,需要多少最初用料(或 --have 清单里的物品)?」

模型与口径:
    配方结构   data/recipes/<station>/<id>.json;ingredients/outcomes 均为
               [{group:[{id,name,count}]}],同组与同槽原料**同时消耗**(AND,
               见 collection/recipes.py resolve_side 注:如灌装=空瓶+溶液),
               数据集中不存在"可替代"语义 → 计算前直接摊平为 [(物品, 数量)]
    用量数学   fractions.Fraction 精确计算(z3 有理数求解,结果无浮点误差);
               展示时附向上取整的实备数量
    环的处理   求解为 z3 整图线性约束(见 analysis/solvers/z3.py):每种物品
               一条净流量守恒等式(产出 − 消耗 − 设施维持 = 净流量),环与
               共享中间品天然可解(如 种子⇄作物 自持、清水⇄水蒸气 回收环),
               无需展开/回退启发;目标函数 = 最少制造次数(preferred 配方
               成本按 1/4 计的软偏好),多产出配方由目标函数统一计价
    回收配方   拆解机配方(dismantler_,满瓶→空瓶+溶液一类)是回收环而非
               生产途径,整体不列入产出图谱;某物品若仅能由拆解产出(如惰气),
               视同最初用料(外部获取)
    需求来源   ① 最初用料(raw):无产出配方的外部物品,附 items 数据集的
                 获取途径注记(如 惰气 = 惰气矿点采集);
               ② 外部投料(external):有产出配方但按口径不求自产(持有清单
                 --have、清水等采集资源、回收环物品);
               ③ 环境维持(env):链上配方要求气体环境时,气体散布机持续
                 通入对应气体 6/min(惰气→稳定、水蒸气→湿润、酸气→酸性、
                 息壤气→息壤),作为附加叶子计入需求原料;
               ④ 设备维持(upkeep):转化机运行需持续通入息壤系气体
                 (FactoryTransmuterTable:液气转化机通液化息壤、固气
                 转化机通息壤气,6/min/台、上限 30)——按占用台数计入
                 (向上取整,不满载也按整台全额);要按运行时长线性折算,
                 可另行添加临时配方表达;「溶液方案省息壤气」即源于液气
                 路线把维持气体从息壤气换成液化息壤
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
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from typing import TYPE_CHECKING

from tools.tables import DATA_DIR, REPORTS_DIR

if TYPE_CHECKING:
    from analysis.solvers import SolveResult

RECIPE_DIR = DATA_DIR / "recipes"
ITEMS_DIR = DATA_DIR / "items"
STATIONS = ("manual", "machine", "spaceship")
REPORT_PATH = REPORTS_DIR / "recipe-analysis.md"

RECYCLER_PREFIX = "dismantler_"                     # 拆解机:回收/反向配方,默认不作产出途径

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
# 口径:按占用台数计(向上取整),不满载也按整台全额计——要按运行时长线性
# 折算(按需 upkeep),可另行添加临时配方表达;「溶液方案省息壤气」即源于
# 液气路线把维持气体从息壤气换成液化息壤
MACHINE_UPKEEP = {
    "transmuter_1": "item_liquid_xiranite",   # 液气转化机:液化息壤
    "transmuter_2": "item_gas_xiranite",      # 固气转化机:息壤气
}

# 叶子类型(需求来源)
KIND_RAW = "raw"            # 采集资源(无产出配方或 obtainWays 非空)→ 最初用料
KIND_EXTERN = "external"    # 有产出配方可不求自产的外部投料(持有清单/回收环物品)
KIND_LABEL = {KIND_RAW: "最初用料", KIND_EXTERN: "外部投料"}


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
    name: str                                     # 手工配方名 / 机器 formulaDesc / 飞船 showingName
    require_items: tuple[Stack, ...]              # 每次制造的物品消耗
    produce_items: tuple[Stack, ...]              # 每次制造的产出(含副产物)
    require_time: float | None                    # 单次制造耗时(秒)
    require_machine: str | None = None            # 所需设施 ID(中文名/维持消耗据此派生)
    require_env: int = 0                          # 所需气体环境:0=无,1=稳定,2=湿润,3=酸性,4=息壤
    produce_env: int = 0                          # 产出的气体环境(散布机合成条目;普通配方恒 0)

    @property
    def machine_name(self) -> str | None:
        """所需设施中文名(_machine_names 目录;设备数折算展示用)。"""
        return _machine_names().get(self.require_machine or "")

    @property
    def env_name(self) -> str | None:
        """require_env 对应的气体环境中文名。"""
        return GAS_ENV_NAMES.get(self.require_env)

    @property
    def upkeep_gas(self) -> str | None:
        """设施维持声明:本配方设施需持续通入的气体 id(无维持设施为 None)。

        只声明"需要哪种维持";金额由消费方计算——占用台数 =
        ceil(次数 × require_time ÷ 60),每台恒 6/min、不满载也按整台
        全额计(保守口径;线性折算可经临时配方表达,见 MACHINE_UPKEEP 注)。
        """
        return MACHINE_UPKEEP.get(self.require_machine or "")

    def produce_of(self, item: str) -> int:
        """单次制造产出 item 的数量(仅统计目标物品本身,副产物另计不计抵扣)。"""
        for s in self.produce_items:
            if s.id == item:
                return s.count
        return 0

    def describe(self) -> str:
        """单行配方卡:A*n+B*m --设备(环境,维持*k/min)--> C*p+D*q。

        设备为设施中文名(手工/飞船配方无设施,以站点名兜底);括号内按需
        附气体环境与设施维持(维持气体恒 6/min/台,见 GAS_ENV_RATE)。
        """
        ins = "+".join(f"{s.name}*{s.count}" for s in self.require_items) or "(无原料)"
        outs = "+".join(f"{s.name}*{s.count}" for s in self.produce_items)
        device = (self.machine_name
                  or {"manual": "手工", "spaceship": "飞船"}.get(self.station))
        notes = []
        if self.env_name:
            notes.append(self.env_name)
        if (gas := self.upkeep_gas) is not None:
            notes.append(f"维持{_item_name(gas) or gas}*{GAS_ENV_RATE}/min")
        deco = (f"--{device}({','.join(notes)})-->" if notes
                else f"--{device}-->" if device else "-->")
        return f"{ins} {deco} {outs}"



# ---------------------------------------------------------------- 数据加载
def _flatten(side: list[dict]) -> tuple[Stack, ...]:
    """[{group:[...]}] → 摊平元组;同组同槽原料同时消耗(AND),直接拼接。"""
    out = []
    for entry in side:
        for s in entry.get("group", []):
            out.append(Stack(s["id"], s.get("name") or s["id"], int(s.get("count", 1))))
    return tuple(out)


@lru_cache(maxsize=1)
def load_recipes() -> list[Recipe]:
    """全量配方(进程共享缓存,调用方只读;子集场景自行过滤)。"""
    recipes = []
    for station in STATIONS:
        for f in sorted((RECIPE_DIR / station).glob("*.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            recipes.append(Recipe(
                id=r["id"], station=station,
                name=r.get("name") or r.get("formulaDesc") or r.get("showingName") or r["id"],
                require_items=_flatten(r.get("ingredients", [])),
                produce_items=_flatten(r.get("outcomes", [])),
                require_time=r.get("craftTimeSec"),
                require_machine=r.get("machineId"),
                require_env=int(r.get("gasEnv") or 0),
            ))
    recipes.extend(_vaporizer_recipes())
    return recipes


def _vaporizer_recipes() -> list[Recipe]:
    """气体散布机合成条目:持续通入气体 → 产出对应气体环境(produce_env 的来源)。

    散布机是设施行为而非加工配方,不在三张配方源表内(源表
    FactoryVaporizerTable 未纳入采集,口径见 GAS_ENV_PROVIDERS/GAS_ENV_RATE
    常量注释);此处建为合成条目,使「耗什么气、产什么环境」可经配方数据
    查询。require_items 数量为每分钟通入速率(连续运行,require_time=None,
    不参与求解——无物品产出,求解器不会选中)。
    """
    machine = _item_name("item_port_vaporizer_1") or "气体散布机"
    return [Recipe(
        id=f"vaporizer_1_env_{gas_id.removeprefix('item_gas_')}",
        station="machine",
        name=f"{machine}·{GAS_ENV_NAMES[env]}",
        require_items=(Stack(gas_id, _item_name(gas_id) or gas_id, int(GAS_ENV_RATE)),),
        produce_items=(),
        require_time=None,
        require_machine="vaporizer_1",
        produce_env=env,
    ) for env, (gas_id, _gas_recipe) in GAS_ENV_PROVIDERS.items()]


@lru_cache(maxsize=1)
def _item_catalog() -> tuple[dict[str, str], dict[str, str]]:
    """data/items/ 全量 id→中文名 与 id→获取途径首条(最初用料的来源注记,
    如 惰气 = 惰气矿点采集)。进程内共享缓存,只解析一次。"""
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


def _item_name(item: str) -> str | None:
    """物品中文名(items 数据集);未收录返回 None。"""
    return _item_catalog()[0].get(item)


def is_gatherable(item: str) -> bool:
    """采集类资源(obtainWays 非空,如 清水=水泵采集):视作外部可获取,
    即便存在产出配方也不强制自产。"""
    return _item_catalog()[1].get(item) is not None


@lru_cache(maxsize=1)
def _machine_names() -> dict[str, str]:
    """机器配方 JSON 的 machineId → machineName 目录(设施中文名)。

    散布机无机器配方 JSON,由 items 数据集补种(produce_env 合成条目用)。
    """
    out: dict[str, str] = {}
    for f in (RECIPE_DIR / "machine").glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r.get("machineId") and r.get("machineName"):
            out.setdefault(r["machineId"], r["machineName"])
    if "vaporizer_1" not in out:
        out["vaporizer_1"] = _item_name("item_port_vaporizer_1") or "气体散布机"
    return out


# ---------------------------------------------------------------- 配方索引(模块级)
# 原 RecipeGraph 索引类已拆平:全量数据经 lru_cache 进程单例,名称解析与
# 输入消歧均为模块函数;渲染与 CLI 直接吃 Recipe 数据与这些服务。

@lru_cache(maxsize=1)
def recipes_by_id() -> dict[str, Recipe]:
    """配方 id → Recipe 全量直查(进程共享,调用方只读)。"""
    return {r.id: r for r in load_recipes()}


@lru_cache(maxsize=1)
def produced_ids() -> frozenset[str]:
    """有产出配方(不含拆解,拆解 = 回收环)的物品 id 集合。"""
    return frozenset(s.id for r in load_recipes()
                     if not r.id.startswith(RECYCLER_PREFIX)
                     for s in r.produce_items)


@lru_cache(maxsize=1)
def _stack_names() -> dict[str, str]:
    """配方栈自带的 物品 id → 中文名(优先于 items 数据集)。"""
    return {s.id: s.name for r in load_recipes()
            for s in r.produce_items + r.require_items}


def name_of(item: str) -> str:
    """物品中文名:配方栈自带 → items 数据集 → 回退 id。"""
    return _stack_names().get(item) or _item_name(item) or item


def resolve_item(query: str) -> tuple[str | None, list[str]]:
    """查询串 → 物品 id。依次:精确 id → 精确名称 → 唯一子串(大小写不敏感)。
    多候选时确定性择优:参与配方图的物品优先,其次 id 较短、字典序较小者
    (数据集里系统蓝图/杂项与材料同名,如 铁制零件 = item_iron_cmpt 与 sysbp_*);
    未命中返回 (None, 按相关性排序的候选)。"""
    ids = set(_item_catalog()[0])
    if query in ids:
        return query, []
    by_name: dict[str, list[str]] = {}
    for iid in ids:
        by_name.setdefault(name_of(iid), []).append(iid)
    cands = by_name.get(query) or [iid for iid in ids
                                   if query.lower() in iid.lower() or query in name_of(iid)]
    if not cands:
        return None, []
    produced = produced_ids()
    used = {s.id for r in load_recipes() for s in r.require_items}
    ranked = sorted(cands, key=lambda i: (i not in produced and i not in used, len(i), i))
    return ranked[0], []


# ---------------------------------------------------------------- 倒推引擎
def compute(target: str, qty: Fraction,
            provided: frozenset[str] = frozenset(),
            pinned: dict[str, str] | None = None,
            byproducts: bool = True) -> "SolveResult":
    """单目标求解入口(全量配方):等价 Z3Solver 求解,返回平面解(配方 → 制造次数)。

    provided 为持有物品 id 集合(即 available 清单,不限量);
    pinned/byproducts 语义见 analysis.solvers.SolveRequest;限定配方子集的
    场景直接构造 Z3Solver(subset);叶子/副产物等展示合计经 FlowGraph
    按制造次数推导。
    """
    from analysis.solvers import SolveRequest
    from analysis.solvers.z3 import Z3Solver
    return Z3Solver(load_recipes()).solve(SolveRequest(
        targets={target: qty},
        available=provided,
        preferred=dict(pinned or {}), byproducts=byproducts))


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


def _fmt_qty(q: Fraction) -> str:
    """精确量:整数直书;分数保留 a b/c 形式。"""
    if q.denominator == 1:
        return str(q.numerator)
    whole, rest = divmod(q, 1)
    return f"{whole} + {rest}" if whole else f"{rest}"


def _fmt_ceil(q: Fraction) -> str:
    """向上取整后的整数字符串(备料数量:不可零碎备料)。"""
    return str(-(-q.numerator // q.denominator))


class FlowGraph:
    """平面解 → 产出链路图:构造时一次建好图结构与各类合计,渲染共用。

    构造(recipes_by_id, targets, SolveResult):
        flows     各物品净流量 = Σ 制造次数 ×(产出 − 消耗 − 设施维持);
        leaves    外部需求 (物品, 来源类型) → 数量(净缺口 + 环境维持供气);
        byproducts / byproduct_sources   副产物净产出及其首个产出配方
                  (byproducts=False 求解时硬约束已保证非目标净流量 ≤ 0,为空);
        upkeep_in (维持气体, 配方) → 通入量,独立于原料边单独记账;
        edges / items / recipes   配方↔物品二部边,经"单入单出"收缩后只剩
                  分支点与端点(目标/源/汇节点保留)。
    查询:materials() 原料聚合、machines() 设备折算、required_envs() 环境。
    渲染:outline() 平铺清单、mermaid() 链路图、summary() 控制台摘要、
        to_dict() 机器可读输出。
    """

    def __init__(self, recipes_by_id: dict[str, Recipe],
                 targets: Mapping[str, Fraction], result: "SolveResult") -> None:
        self.recipes_by_id = recipes_by_id
        self.targets = dict(targets)
        self.crafts: Mapping[str, Fraction] = result.crafts
        self.strict_ok = result.strict_ok
        self.flows = self._net_flows()
        self.leaves: dict[tuple[str, str], Fraction] = {}
        self.byproducts: dict[str, Fraction] = {}
        self.byproduct_sources: dict[str, str] = {}
        self._split_demand()
        self.upkeep_in = self._upkeep_in()
        self.edges: dict[tuple[str, str], Fraction] = {}
        self.items: set[str] = set()
        self.recipes: set[str] = set()
        self._bipartite()
        self._contract_pass_through()

    # -- 构造期推导 -----------------------------------------------------------
    def _upkeep_amount(self, rid: str) -> tuple[str, Fraction] | None:
        """(维持气体, 该配方维持通入量) = 6 × ceil(次数 × 耗时 ÷ 60)。

        不满载也按整台全额计(与求解器的整型台数约束同式)。
        """
        r = self.recipes_by_id[rid]
        if (gas := r.upkeep_gas) is None or not r.require_time:
            return None
        busy = self.crafts[rid] * Fraction(str(r.require_time)) / 60
        return gas, GAS_ENV_RATE * math.ceil(busy)

    def _net_flows(self) -> dict[str, Fraction]:
        """各物品净流量 = Σ 制造次数 ×(产出 − 消耗 − 设施维持);与求解器守恒一致。"""
        flows: dict[str, Fraction] = {}
        for rid, n in self.crafts.items():
            r = self.recipes_by_id[rid]
            for s in r.produce_items:
                flows[s.id] = flows.get(s.id, Fraction(0)) + n * s.count
            for s in r.require_items:
                flows[s.id] = flows.get(s.id, Fraction(0)) - n * s.count
            if (upkeep := self._upkeep_amount(rid)) is not None:
                gas_id, q = upkeep
                flows[gas_id] = flows.get(gas_id, Fraction(0)) - q
        return flows

    def _split_demand(self) -> None:
        """净缺口 → leaves(有产出配方 = 外部投料,否则最初用料;另按用到的
        气体环境计入散布机维持供气 6/min);净剩余 → byproducts。"""
        tids = set(self.targets)
        produced = {s.id for r in self.recipes_by_id.values()
                    if not r.id.startswith(RECYCLER_PREFIX) for s in r.produce_items}
        for i, net in self.flows.items():
            if i in tids:
                continue
            if net < 0:
                self.leaves[(i, KIND_EXTERN if i in produced else KIND_RAW)] = -net
            elif net > 0:
                self.byproducts[i] = net
        for env in {self.recipes_by_id[rid].require_env for rid in self.crafts}:
            if env in GAS_ENV_PROVIDERS:
                key = (GAS_ENV_PROVIDERS[env][0], KIND_RAW)
                self.leaves[key] = self.leaves.get(key, Fraction(0)) + GAS_ENV_RATE
        self.byproduct_sources = {
            i: next(rid for rid in self.crafts
                    if any(s.id == i for s in self.recipes_by_id[rid].produce_items))
            for i in self.byproducts}

    def _upkeep_in(self) -> dict[tuple[str, str], Fraction]:
        """维持输入边:(气体, 配方) → 通入量。独立于配方原料边(标"维持"),
        即使维持气体同时是配方原料(如固气转化机的息壤气)也分别画出。"""
        upkeep_in: dict[tuple[str, str], Fraction] = {}
        for rid, n in self.crafts.items():
            if (upkeep := self._upkeep_amount(rid)) is not None:
                gas_id, q = upkeep
                if q > 0:
                    upkeep_in[(gas_id, rid)] = upkeep_in.get((gas_id, rid), Fraction(0)) + q
        return upkeep_in

    def _bipartite(self) -> None:
        """配方↔物品二部边:原料→配方×耗量、配方→产物×产量(维持气体入点)。"""
        for rid, n in sorted(self.crafts.items()):
            r = self.recipes_by_id[rid]
            self.recipes.add(rid)
            for s in r.require_items:
                self.items.add(s.id)
                self.edges[("I_" + s.id, "R_" + rid)] = (self.edges.get(("I_" + s.id, "R_" + rid), Fraction(0))
                                                         + n * s.count)
            for s in r.produce_items:
                self.items.add(s.id)
                self.edges[("R_" + rid, "I_" + s.id)] = (self.edges.get(("R_" + rid, "I_" + s.id), Fraction(0))
                                                          + n * s.count)
        self.items.update(gas for gas, _rid in self.upkeep_in)

    def _contract_pass_through(self) -> None:
        """收缩:恰好一进一出的物品节点并入上下游配方直连边(量并入合并边)。"""
        target_ids = set(self.targets)
        changed, passes = True, 0
        while changed and passes < 50:
            changed, passes = False, passes + 1
            for i in sorted(self.items):
                if i in target_ids:
                    continue
                ins = [(s, d) for (s, d) in self.edges if d == "I_" + i and s.startswith("R_")]
                outs = [(s, d) for (s, d) in self.edges if s == "I_" + i and d.startswith("R_")]
                if len(ins) != 1 or len(outs) != 1:
                    continue
                rin, rout = ins[0][0], outs[0][1]
                through = self.edges[outs[0]]
                del self.edges[ins[0]], self.edges[outs[0]]
                self.items.discard(i)
                self.edges[(rin, rout)] = self.edges.get((rin, rout), Fraction(0)) + through
                changed = True
                break

    # -- 查询 -----------------------------------------------------------------
    def _sorted_leaves(self) -> list[tuple[tuple[str, str], Fraction]]:
        """需求原料清单:((物品, 来源类型), 数量),按数量降序。"""
        return sorted(self.leaves.items(), key=lambda kv: (-kv[1], kv[0][0]))

    def materials(self) -> dict[str, Fraction]:
        """需求原料聚合(物品 → 净外部需求量,含全部来源类型),按数量降序。"""
        out: dict[str, Fraction] = {}
        for (i, _k), v in self.leaves.items():
            out[i] = out.get(i, Fraction(0)) + v
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def machines(self) -> list[tuple[Recipe, Fraction, int]]:
        """速率口径的设备需求:各配方 → (配方, 产量/分钟, 所需设施数)。

        设施数 = ceil(产量每分钟 × 单次制造耗时秒 ÷ 60);无耗时数据(手工/飞船)
        的配方不参与,调用方自行提示。
        """
        out = []
        for rid, n in sorted(self.crafts.items()):
            r = self.recipes_by_id[rid]
            if r.require_time:
                out.append((r, n, math.ceil(n * Fraction(str(r.require_time)) / 60)))
        return out

    def required_envs(self) -> list[tuple[str, list[str]]]:
        """链上配方要求的气体环境(非零)→ [环境名, [配方…]],稳定>湿润>酸性>息壤。"""
        envs: dict[str, list[str]] = {}
        for rid in self.crafts:
            if env := self.recipes_by_id[rid].env_name:
                envs.setdefault(env, []).append(rid)
        return sorted(envs.items(), key=lambda kv: list(GAS_ENV_NAMES.values()).index(kv[0]))

    def _env_upkeep(self) -> list[tuple[str, str, Fraction]]:
        """环境维持清单:(环境名, 供气气体 id, 每分钟通入量)——散布机恒 6/min,
        一台可同时影响范围内多台设备,按环境各计一台。"""
        used = {self.recipes_by_id[rid].require_env for rid in self.crafts}
        return [(GAS_ENV_NAMES[e], GAS_ENV_PROVIDERS[e][0], GAS_ENV_RATE)
                for e in sorted(used) if e in GAS_ENV_PROVIDERS]

    def _used_facilities(self) -> list[str]:
        """链上用到的生产设施中文名(按首次出现序去重)。"""
        seen, out = set(), []
        for rid in self.crafts:
            name = self.recipes_by_id[rid].machine_name or self.recipes_by_id[rid].station
            if name not in seen:
                seen.add(name)
                out.append(name)
        return out

    # -- 渲染 -----------------------------------------------------------------
    def outline(self) -> list[str]:
        """目标与需求原料的平铺渲染(z3 平面解,无逐层展开树;多目标共用一份原料)。"""
        lines = [f"{name_of(tid)} ×{_fmt_qty(qty)}" for tid, qty in self.targets.items()]
        lines += [f"   └─ {name_of(iid)} ×{_fmt_qty(total)}"
                  for (iid, _kind), total in self._sorted_leaves()]
        return lines

    def mermaid(self) -> str:
        """产出链路图(mermaid flowchart LR):物品节点按来源取形,维持边单列。"""
        target_ids = set(self.targets)
        produced = {s.id for r in self.recipes_by_id.values()
                    if not r.id.startswith(RECYCLER_PREFIX) for s in r.produce_items}
        lines = ["flowchart LR"]
        for i in sorted(self.items):
            net = self.flows.get(i, Fraction(0))
            if i in target_ids:
                lines.append(f"  I_{i}((\"{name_of(i)}<br/>目标 ×{_fmt_qty(self.targets[i])}\"))")
            elif net < 0 and i not in produced:
                lines.append(f"  I_{i}([\"{name_of(i)} ×{_fmt_qty(-net)}\"])")
            elif net < 0:
                lines.append(f"  I_{i}[[\"{name_of(i)} ×{_fmt_qty(-net)}\"]]")
            else:
                lines.append(f"  I_{i}[\"{name_of(i)}\"]")
        for rid in sorted(self.recipes):
            r = self.recipes_by_id[rid]
            label = r.machine_name or r.name
            lines.append(f"  R_{rid}[\"{label}<br/>{rid}\"]")
        for (src, dst), qty in sorted(self.edges.items()):
            lines.append(f"  {src} -->|\"×{_fmt_qty(qty)}\"| {dst}")
        for (gas, rid), q in sorted(self.upkeep_in.items()):
            lines.append(f"  I_{gas} -->|\"维持 ×{_fmt_qty(q)}\"| R_{rid}")
        return "\n".join(lines)

    def summary(self, target_label: str, per_min: bool = False) -> str:
        """控制台摘要:目标/原料清单 + 产出(含副产物) + 制造步骤 + 设备 + 环境 + 链路图。"""
        unit = "/min" if per_min else ""
        qty_word = f"×{_fmt_qty(next(iter(self.targets.values())))}{unit}"
        lines = [f"目标 {target_label} {qty_word}"]
        lines += self.outline()
        lines.append("")
        leaves = self._sorted_leaves()
        if not leaves:
            lines.append("需求原料:无需任何原料(目标本身来自 --have 清单或飞船制造)")
        else:
            head = "需求原料(每分钟流量;精确流量 → 实备数量)" if per_min else "需求原料(精确用量 → 实备数量)"
            lines.append(f"{head},{len(leaves)} 项:")
            for (iid, kind), total in leaves:
                label = KIND_LABEL[kind]
                line = (f"  [{label}] {name_of(iid):<12} ×{_fmt_qty(total):<10} → 备料 "
                        f"{_fmt_ceil(total)}{unit}")
                if kind == KIND_RAW and (src := _item_catalog()[1].get(iid)):
                    line += f"({src})"
                lines.append(line)
        parts = [f"目标 {name_of(next(iter(self.targets)))} {qty_word}"]
        if self.byproducts:
            bp = "、".join(f"{name_of(i)} ×{_fmt_qty(n)}{unit}"
                           f"(← {self.byproduct_sources[i]})"
                           for i, n in sorted(self.byproducts.items(), key=lambda kv: -kv[1]))
            parts.append(f"副产物 {bp}")
        lines.append("产出:" + ";".join(parts))
        craft_lines = [f"  {rid} ×{_fmt_qty(n)} 次{unit}  {self.recipes_by_id[rid].describe()}"
                       for rid, n in sorted(self.crafts.items())]
        if craft_lines:
            lines.append("制造步骤" + ("(每分钟执行次数):" if per_min else ":"))
            lines += craft_lines
        facilities = self._used_facilities()
        if per_min:
            machines = self.machines()
            if machines:
                lines.append("设备需求(设施数 = 产量每分钟 × 单次耗时 ÷ 60,向上取整):")
                lines += [f"  {r.machine_name or r.station:<4} {r.id} ×{m} 台"
                          f"({_fmt_qty(n)}/min × {r.require_time:g}s)" for r, n, m in machines]
            if upkeep := self._env_upkeep():
                lines.append(f"  气体散布机 vaporizer ×{len(upkeep)} 台"
                             f"(环境维持,每种气体 {_fmt_qty(GAS_ENV_RATE)}/min)")
            no_time = [rid for rid in self.crafts if not self.recipes_by_id[rid].require_time]
            if no_time:
                lines.append("  无耗时数据不计设备:" + "、".join(no_time))
        elif facilities:
            names = facilities + (["气体散布机"] if self._env_upkeep() else [])
            lines.append("使用设备:" + "、".join(names))
        envs = self.required_envs()
        if envs:
            upkeep = {name: (gas, rate) for name, gas, rate in self._env_upkeep()}
            parts = []
            for env, rids in envs:
                base = f"{env}({', '.join(rids)})"
                if env in upkeep:
                    gas, rate = upkeep[env]
                    base += f" ← 气体散布机 通入{name_of(gas)} ×{_fmt_qty(rate)}/min"
                parts.append(base)
            lines.append("环境需求:" + ";".join(parts))
        else:
            lines.append("环境需求:无特殊气体环境(全部常规)")
        lines.append("产出链路图(mermaid):")
        lines.append("```mermaid")
        lines.append(self.mermaid())
        lines.append("```")
        if not self.strict_ok:
            lines.append("⚠ 约束不可满足:目标在当前配方图/持有清单下无法产出"
                         "(byproducts=False 时依赖副产物的路线会不可行)")
        return "\n".join(lines)

    def to_dict(self, per_min: bool = False) -> dict:
        """机器可读输出(Fraction → "num/den" 字符串 + ceil 整数)。"""

        def fr(v: Fraction) -> dict:
            return {"exact": str(v), "ceil": int(-(-v.numerator // v.denominator))}

        upkeep_by_name = {name: (gas, rate) for name, gas, rate in self._env_upkeep()}
        environments = [{"name": env, "recipes": rids,
                         **({"provider_gas": gas, "provider_rate_per_min": str(rate)}
                            if (pair := upkeep_by_name.get(env)) else {})}
                        for env, rids in self.required_envs()]
        tid, qty = next(iter(self.targets.items()))
        return {
            "target": {"id": tid, "name": name_of(tid), "qty": str(qty),
                       "per_min": per_min},
            "targets": [{"id": t, "name": name_of(t), "qty": str(q)}
                        for t, q in self.targets.items()],
            "strict_ok": self.strict_ok,
            "leaves": [{"id": iid, "name": name_of(iid), "kind": kind, **fr(total),
                        **({"obtain": src} if kind == KIND_RAW
                           and (src := _item_catalog()[1].get(iid)) else {})}
                       for (iid, kind), total in self._sorted_leaves()],
            "crafts": [{"recipe": rid, "station": self.recipes_by_id[rid].station, **fr(n)}
                       for rid, n in sorted(self.crafts.items())],
            "byproducts": [{"id": i, "name": name_of(i),
                            "source_recipe": self.byproduct_sources[i], **fr(n)}
                           for i, n in sorted(self.byproducts.items(), key=lambda kv: -kv[1])],
            "environments": environments,
            "facilities": self._used_facilities(),
            "mermaid": self.mermaid(),
            **({"machines": [{"recipe": r.id, "machine": r.machine_name,
                              "craft_time_sec": r.require_time, "count": m}
                             for r, _, m in self.machines()]
                + [{"machine": "气体散布机", "count": len(self._env_upkeep())}]
                } if per_min else {}),
        }


# ---------------------------------------------------------------- 总览报告
def build_report(demos: list[tuple[str, Fraction, frozenset[str]]]) -> str:
    """数据概览 + 口径说明 + 示例倒推(reports/recipe-analysis.md)。"""
    lines = ["# 配方用料倒推 · 数据概览", ""]
    lines.append(f"- 配方 {len(load_recipes())} 条(" +
                 "、".join(f"{s} {sum(1 for r in load_recipes() if r.station == s)}" for s in STATIONS) +
                 f");其中拆解/回收配方(dismantler_)"
                 f"{sum(1 for r in load_recipes() if r.id.startswith(RECYCLER_PREFIX))} 条")
    items_used = {s.id for r in load_recipes() for s in r.require_items}
    items_made = produced_ids()
    lines.append(f"- 涉及物品:产出 {len(items_made)} 种,原料 {len(items_used)} 种;"
                 f"无配方最初用料 {len(items_used - items_made)} 种,可制造 "
                 f"{len(items_made & items_used)} 种")
    lines.append("- 口径:同组/同槽原料同时消耗(AND);副产物不做回收抵扣;"
                 "多产出配方由 z3 目标函数统一计价(最少制造次数);"
                 "拆解(dismantler_)配方不列为产出途径")
    lines.append("- 环处理:z3 整图线性约束,每种物品一条净流量守恒等式,环与共享"
                 "中间品天然可解;采集类资源(obtainWays 非空)允许外部供给")
    lines.append("")

    for label, qty, provided in demos:
        target, cands = resolve_item(label)
        if target is None:
            continue
        res = compute(target, qty, provided)
        lines.append(f"## 示例:{name_of(target)} ×{_fmt_qty(qty)}"
                     + (f"(--have {','.join(sorted(provided))})" if provided else ""))
        lines.append("")
        lines.append("```")
        lines.append(FlowGraph(recipes_by_id(), {target: qty}, res).summary(name_of(target)))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI
def _resolve_pins(recipe_pins: list[str] | None) -> dict[str, str]:
    """--recipe 物品=配方ID 列表 → {物品 id: 配方 id},逐项校验。"""
    pinned: dict[str, str] = {}
    for token in recipe_pins or []:
        name_part, _, recipe_part = token.partition("=")
        if not recipe_part:
            sys.exit(f"--recipe 须为 物品=配方ID 形式,收到:{token!r}")
        iid, cands = resolve_item(name_part.strip())
        if iid is None:
            sys.exit(f"未识别 --recipe 中的物品:{name_part!r}"
                     + (f";候选:{'、'.join(name_of(c) for c in cands[:8])}" if cands else ""))
        rid = recipe_part.strip()
        recipe = recipes_by_id().get(rid)
        if recipe is None:
            sys.exit(f"--recipe 未找到配方:{rid!r}")
        if recipe.produce_of(iid) <= 0:
            outs = "、".join(s.name for s in recipe.produce_items)
            sys.exit(f"配方 {rid} 不产出 {name_of(iid)}(产出:{outs})")
        pinned[iid] = rid
    return pinned


def _resolve_provided(have: str) -> frozenset[str]:
    """--have 逗号分隔清单 → 物品 id 集合。"""
    ids = []
    for token in filter(None, (t.strip() for t in have.split(","))):
        iid, cands = resolve_item(token)
        if iid is None:
            sys.exit(f"未识别 --have 中的物品:{token};候选:{'、'.join(name_of(c) for c in cands[:8])}")
        ids.append(iid)
    return frozenset(ids)


def main(item: str | None = None, qty: str = "1", have: str = "",
         as_json: bool = False, recipe_pins: list[str] | None = None,
         solver: str = "z3", byproducts: bool = True) -> None:
    from analysis.solvers import SOLVERS, SolveRequest   # 惰性导入,避免与求解器实现的循环依赖
    rbi = recipes_by_id()
    solver_cls = SOLVERS.get(solver)
    if solver_cls is None:
        sys.exit(f"未知求解器:{solver!r};可选:{', '.join(SOLVERS)}")
    pinned = _resolve_pins(recipe_pins)
    provided = _resolve_provided(have)

    if item is None:  # 总览报告模式
        demos = [
            ("铁制零件", Fraction(10), frozenset()),
            ("分离芯", Fraction(4), frozenset()),
            ("锦草", Fraction(10), frozenset()),
            ("柑实罐头", Fraction(5), frozenset()),
        ]
        report = build_report(demos)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(f"配方用料倒推 · 数据概览 → {REPORT_PATH}")
        print(f"  配方 {len(load_recipes())} 条,物品 {len(produced_ids())} 种")
        return

    target, cands = resolve_item(item)
    if target is None:
        hint = "、".join(f"{name_of(c)}({c})" for c in cands[:8])
        sys.exit(f"未识别目标物品:{item!r}" + (f";候选:{hint}" if cands else ""))
    try:
        amount, per_min = parse_qty(qty)
    except ValueError as e:
        sys.exit(str(e))

    result = solver_cls(load_recipes()).solve(SolveRequest(
        targets={target: amount},
        available=provided,
        preferred=pinned, byproducts=byproducts))
    chart = FlowGraph(rbi, {target: amount}, result)
    if as_json:
        print(json.dumps(chart.to_dict(per_min), ensure_ascii=False, indent=2))
    else:
        label = name_of(target) + (f"({target})" if target != name_of(target) else "")
        print(chart.summary(label, per_min))
