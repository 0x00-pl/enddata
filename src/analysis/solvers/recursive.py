"""递归展开求解器(默认实现)。

严格展开 → 外部投料点迭代增长/收缩 → 宽松兜底;支持多目标输入(逐目标
求解后聚合一份需求)、优先使用配方(先试首选、失败回退其他)与副产物
开关(False 时结果不含环境/设备维持等额外输入与副产物净产出)。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from analysis.recipe_calc import (
    Recipe,
    RecipeGraph,
    ReqNode,
    Requirement,
    fmt_qty,
)
from analysis.solvers import RecipeSolver, register
from analysis.solvers.common import ExpandContext, collect_result, expand_node

MAX_EXTERN_ROUNDS = 32   # 外部投料点自动求解的最大迭代轮数(每轮至少新增一个物品)


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


@register("recursive")
class RecursiveSolver(RecipeSolver):
    """递归展开求解器(默认):严格展开 → 外部投料点迭代增长/收缩 → 宽松兜底。

    ① 增长:严格展开,被环堵死时收集「净产出判定失败的闭环点」(A, X),
       把环上祖先 A(A 为目标本身时取 X)记为外部投料点后重试 —— 这些物品
       (清水、种子一类)本就来自地图/初始存量,无法从最初用料纯合成;
    ② 收缩:对外部投料点逐个检验「给定其余投料点,它能否严格自产」,
       能则移出(如赤铜块在清水有供给时可用矿石+清水合成),收敛到局部
       最小投料集 —— 单点可替换保证整体仍严格可行。采集类资源
       (obtainWays 非空,如 清水=水泵采集)不参与收缩:保持外部投料,
       不被提纯回收一类内部合成链顶替;优先配方同样不翻成外部投料;
    ③ 增长耗尽仍失败才退回宽松模式(环叶兜底)。
    """

    def solve(self, targets: Mapping[str, Fraction], *,
              available: Mapping[str, Fraction] | None = None,
              preferred: Mapping[str, str] | None = None,
              per_min: bool = False,
              byproducts: bool = True) -> Requirement:
        """逐目标求解并聚合(单目标直接返回;多目标净流量线性可加)。"""
        targets = dict(targets)
        available_keys = frozenset(dict(available or {}))
        preferred_map = dict(preferred or {})
        extern_points: set[str] = set()   # 外部投料点(跨目标共享,发现一次全局复用)
        reqs = [self._solve_one(tid, Fraction(qty), available_keys, preferred_map,
                                extern_points, per_min, byproducts)
                for tid, qty in targets.items()]
        return reqs[0] if len(reqs) == 1 else _merge_requirements(reqs, self.graph, byproducts)

    def _solve_one(self, target: str, qty: Fraction,
                   available: frozenset[str], preferred: dict[str, str],
                   extern_points: set[str], per_min: bool,
                   byproducts: bool) -> Requirement:
        """单目标求解:增长 → 收缩 → 定稿(三阶段详见类 docstring)。"""
        root = None
        for _ in range(MAX_EXTERN_ROUNDS):
            closures: set[tuple[str, str]] = set()
            ctx = ExpandContext(self.graph, available, frozenset(extern_points),
                                preferred, True, closures)
            root = expand_node(ctx, target, qty, ())
            if root is not None:
                break
            new = {a if (a != target and a not in preferred) else x
                   for a, x in closures} - extern_points - {target} - set(preferred)
            if not new:
                root = None
                break
            extern_points |= new
        if root is None:  # 增长耗尽仍失败:宽松兜底(环叶记外部投料)
            lenient_ctx = ExpandContext(self.graph, available, frozenset(extern_points),
                                        preferred, False, set())
            root = expand_node(lenient_ctx, target, qty, ())
            assert root is not None  # 宽松模式必然终止(环叶兜底)
            return collect_result([root], strict_ok=False, ctx=lenient_ctx,
                                  per_min=per_min, byproducts=byproducts)

        while True:  # 收缩:单个投料点可严格自产 ⇒ 移出后整体仍可行(可替换性)
            for a in sorted(extern_points):
                if self.graph.is_gatherable(a):
                    continue  # 采集类资源(清水等)保持外部投料,不翻成内部合成链
                shrink_ctx = ExpandContext(self.graph, available,
                                           frozenset(extern_points - {a}), preferred, True, set())
                if expand_node(shrink_ctx, a, Fraction(1), ()) is not None:
                    extern_points.discard(a)
                    break
            else:
                break
        root = expand_node(ExpandContext(self.graph, available,
                                         frozenset(extern_points), preferred, True, set()),
                           target, qty, ())
        assert root is not None  # 收缩只做可替换的单点移除,整体可行性保持
        return collect_result([root], strict_ok=True, ctx=ctx, per_min=per_min,
                              byproducts=byproducts)


def _merge_requirements(reqs: list[Requirement], graph: RecipeGraph,
                        byproducts: bool) -> Requirement:
    """多目标聚合:合并各目标需求(净流量线性可加,重复投入自动抵扣)。"""
    crafts: dict[str, Fraction] = {}
    leaves: dict[tuple[str, str], Fraction] = {}
    notes: list[str] = []
    for r in reqs:
        for rid, n in r.crafts.items():
            crafts[rid] = crafts.get(rid, Fraction(0)) + n
        for k, v in r.leaves.items():
            leaves[k] = leaves.get(k, Fraction(0)) + v
        notes.extend(r.notes)
    flows: dict[str, Fraction] = {}
    for rid, n in crafts.items():
        rec = graph.recipes_by_id[rid]
        for s in rec.outcomes:
            flows[s.id] = flows.get(s.id, Fraction(0)) + n * s.count
        for s in rec.ingredients:
            flows[s.id] = flows.get(s.id, Fraction(0)) - n * s.count
    target_ids = {r.root.id for r in reqs}
    byproducts_out = {i: f for i, f in flows.items()
                      if f > 0 and i not in target_ids and byproducts}
    sources: dict[str, str] = {}
    for i in byproducts_out:
        sources[i] = next(rid for rid, n in crafts.items()
                          if any(s.id == i for s in graph.recipes_by_id[rid].outcomes))
    return Requirement(roots=[r.root for r in reqs], strict_ok=True, leaves=leaves,
                       crafts=crafts, recipes_by_id=graph.recipes_by_id,
                       notes=notes, byproducts=byproducts_out,
                       byproduct_sources=sources)
