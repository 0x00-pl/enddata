"""求解器公共引擎件:递归展开、环宏判定、结果汇总(各求解器实现复用)。

命名约定:本模块的 ExpandContext / expand_node / collect_result 是跨实现
共享的包内 API;recursive 专属的环宏机制(CycleMacro/_cycle_macro/_macro_note)
留在 recursive.py,本模块仅在调用点惰性导入以避免循环依赖。
"""

import math
from dataclasses import dataclass, replace
from fractions import Fraction

from analysis.recipe_calc import (
    GAS_ENV_PROVIDERS,
    GAS_ENV_RATE,
    KIND_CYCLE,
    KIND_CRAFT,
    KIND_EXTERN,
    KIND_PROVIDED,
    KIND_RAW,
    MACHINE_UPKEEP,
    RecipeGraph,
    ReqNode,
    Requirement,
)


@dataclass(frozen=True)
class ExpandContext:
    """一次递归展开的固定口径:配方图与求解入参,外加运行期收集器。

    available/preferred 即 RecipeSolver.solve 的同名入参;extern 为求解器
    判定的外部投料点;strict 控制配方全堵死时的行为(True 返回 None 由
    上层回退, False 就地记环叶);closures 为可变收集器,展开中把回收环
    闭环点 (A, X) 写入,供外部投料阶段消费。
    """

    graph: RecipeGraph
    available: frozenset[str]          # 持有清单(--have),展开到此为止
    extern: frozenset[str]             # 外部投料点:命中即计外部输入,不再展开
    preferred: dict[str, str]          # 优先使用配方:物品 → 配方 id
    strict: bool                       # True=配方全堵死返回 None;False=环叶兜底
    closures: set[tuple[str, str]]


def expand_node(ctx: ExpandContext, item: str, qty: Fraction,
                path: tuple[tuple[str, str], ...]) -> ReqNode | None:
    """展开单个物品的需求,返回子树节点;strict 模式被环堵死时返回 None。

    path = [(物品, 所用配方), …] 为祖先链(用于截取环上配方表)。
    命中 available / extern → 计叶子;无产出配方 → 最初用料;原料命中祖先 →
    取环上配方表做净产出判定(净产出则以自持环宏配方供给,不净产出则记
    闭环点并弃此配方);所有产出配方皆堵死时,strict 返回 None,宽松记环叶。
    """
    if item in ctx.available:
        return ReqNode(item, ctx.graph.name_of(item), qty, KIND_PROVIDED)
    if item in ctx.extern:
        return ReqNode(item, ctx.graph.name_of(item), qty, KIND_EXTERN)
    producers = ctx.graph.producers.get(item, [])
    if not producers:
        return ReqNode(item, ctx.graph.name_of(item), qty, KIND_RAW)
    # 优先配方排到最前(稳定排序,其余保持原择路序):先试首选,失败回退其他
    pref_id = ctx.preferred.get(item)
    if pref_id is not None:
        producers = sorted(producers, key=lambda r: r.id != pref_id)
    for recipe in producers:
        children, blocked = [], False
        for ing in recipe.ingredients:
            hit = next((k for k, (iid, _) in enumerate(path) if iid == ing.id), None)
            if hit is not None:  # 环:取环上配方表做净产出判定
                chain = path[hit:] + ((item, recipe.id),)
                from analysis.solvers.recursive import _cycle_macro
                macro = _cycle_macro(ctx.graph, chain)
                if macro is not None:
                    rounds = qty / macro.net_per_round
                    m_children, ok = [], True
                    for sid, need in macro.side_inputs().items():
                        child = expand_node(ctx, sid, need * rounds,
                                            path + ((item, recipe.id),))
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
            child = expand_node(ctx, ing.id, ing.count * qty / recipe.yield_of(item),
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


def collect_result(roots: list[ReqNode], strict_ok: bool, ctx: ExpandContext,
                   per_min: bool = False, byproducts: bool = True) -> Requirement:
    """展开树(可多目标)→ 摊平合计(叶子、配方执行次数、副产物净流量、自持环注记)。

    额外输入(仅速率口径且 byproducts=True 时计入):
        环境维持  气体散布机按链上要求的每种气体环境恒定通入 6/min;
        设备维持  转化机每台持续通入息壤系气体 6/min,按设备台数折算;
        两者作为附加需求挂入首个目标树继续向下展开(到息壤/清水等给定
        原料为止),不可自产时按采集资源记最初用料、否则记外部投料。
    副产物 = 全链净流量中为正且非目标的物品(如精炼炉的污水),不做回收抵扣。
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
                    from analysis.solvers.recursive import _macro_note
                    notes.append(_macro_note(graph, node))
    # 挂载附加叶子:环境维持(每环境恒 6/min)与设备维持(转化机台数 × 6/min);
    # 多目标时只挂一次(计入首个目标树),聚合总量不变
    for env in sorted({graph.recipes_by_id[rid].gas_env for rid in crafts} if byproducts else []):
        provider = GAS_ENV_PROVIDERS.get(env)
        if provider is None:
            continue
        gas, gas_recipe = provider
        if gas_recipe is None:
            # 无生成配方(惰气/水蒸气):按最初用料(矿点/水泵采集)
            roots[0].children.append(ReqNode(gas, graph.name_of(gas), GAS_ENV_RATE, KIND_RAW))
            continue
        # 有生成配方:单级展开 env气体 ← 液气转化 ← 前体(沉积酸等,计外部投料);
        # 不深入前体的回收环,避免把整条转化链拖进环境维持
        r = graph.recipes_by_id[gas_recipe]
        env_crafts = GAS_ENV_RATE / r.yield_of(gas)
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
            child = expand_node(replace(ctx, extern=frozenset()), gas, qty, ())
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
