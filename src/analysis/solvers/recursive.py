"""递归展开求解器(默认实现)。

严格展开 → 外部投料点迭代增长/收缩 → 宽松兜底;支持多目标输入(逐目标
求解后聚合一份需求)、优先使用配方(先试首选、失败回退其他)与副产物
开关(False 时结果不含环境/设备维持等额外输入与副产物净产出)。
"""

import math
from fractions import Fraction

from analysis.recipe_calc import (
    KIND_EXTERN,
    KIND_RAW,
    Requirement,
    _ExpandCtx,
    _collect,
    _expand,
)
from analysis.solvers import RecipeSolver, register

MAX_EXTERN_ROUNDS = 32   # 外部投料点自动求解的最大迭代轮数(每轮至少新增一个物品)


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

    def solve(self, targets, *, available=None, preferred=None,
              per_min=False, byproducts=True) -> Requirement:
        targets = dict(targets)
        avail_keys = frozenset(dict(available or {}))
        pref = dict(preferred or {})
        auto: set[str] = set()          # 外部投料点(跨目标共享,发现一次全局复用)
        reqs = [self._solve_one(tid, Fraction(qty), avail_keys, pref,
                                auto, per_min, byproducts)
                for tid, qty in targets.items()]
        return reqs[0] if len(reqs) == 1 else _merge(reqs, self.graph, byproducts)

    def _solve_one(self, target: str, qty: Fraction,
                   avail_keys: frozenset[str], pref: dict[str, str],
                   auto: set[str], per_min: bool, byproducts: bool) -> Requirement:
        """单目标求解:增长 → 收缩 → 定稿(三阶段详见类 docstring)。"""
        root = None
        for _ in range(MAX_EXTERN_ROUNDS):
            closures: set[tuple[str, str]] = set()
            ctx = _ExpandCtx(self.graph, avail_keys, frozenset(auto), pref, True, closures)
            root = _expand(ctx, target, qty, ())
            if root is not None:
                break
            new = {a if (a != target and a not in pref) else x
                   for a, x in closures} - auto - {target} - set(pref)
            if not new:
                root = None
                break
            auto |= new
        if root is None:  # 增长耗尽仍失败:宽松兜底(环叶记外部投料)
            lenient_ctx = _ExpandCtx(self.graph, avail_keys, frozenset(auto), pref, False, set())
            root = _expand(lenient_ctx, target, qty, ())
            assert root is not None  # 宽松模式必然终止(环叶兜底)
            return _collect([root], strict_ok=False, ctx=lenient_ctx,
                            per_min=per_min, byproducts=byproducts)

        while True:  # 收缩:单个投料点可严格自产 ⇒ 移出后整体仍可行(可替换性)
            for a in sorted(auto):
                if self.graph.is_gatherable(a):
                    continue  # 采集类资源(清水等)保持外部投料,不翻成内部合成链
                shrink_ctx = _ExpandCtx(self.graph, avail_keys, frozenset(auto - {a}),
                                        pref, True, set())
                if _expand(shrink_ctx, a, Fraction(1), ()) is not None:
                    auto.discard(a)
                    break
            else:
                break
        root = _expand(_ExpandCtx(self.graph, avail_keys, frozenset(auto), pref, True, set()),
                       target, qty, ())
        assert root is not None  # 收缩只做可替换的单点移除,整体可行性保持
        return _collect([root], strict_ok=True, ctx=ctx, per_min=per_min, byproducts=byproducts)


def _merge(reqs, graph, byproducts: bool) -> Requirement:
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
