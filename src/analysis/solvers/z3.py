"""Z3 求解器:整张配方图建线性约束一次性求解(SMT/LP,精确有理数运算)。

求解口径:
    - 环路与共享中间品天然可解,无外部投料启发式;
    - 采集类资源(无产出配方,如矿石/清水/气体)视为用量不限的外部输入;
    - 目标函数 = 制造次数计价(Σ 次数),preferred 配方成本按 1/4 计
      (软偏好:同等总代价下优先选用,显著更省的路线仍会胜出);结果为精确有理数;
    - byproducts=False 作为硬约束(非目标物品不允许净剩余);
    - 环境维持按用到的环境计入采集气体 6/min;设备维持(转化机气体)按
      运行时长线性计入流量(维持速率 × 设备占用率,速率语义下精确)。
"""

from collections.abc import Mapping
from fractions import Fraction

from analysis.recipe_calc import (
    GAS_ENV_PROVIDERS,
    GAS_ENV_RATE,
    MACHINE_UPKEEP,
    facility_upkeep,
    KIND_CRAFT,
    KIND_EXTERN,
    KIND_RAW,
    RECYCLER_PREFIX,
    ReqNode,
    Requirement,
)


from analysis.solvers import RecipeSolver, register


@register("z3")
class Z3Solver(RecipeSolver):
    """Z3 (SMT/LP) 求解器:整图约束一次求解,环路与共享中间品天然可解。

    建模:
        变量      每条产出配方(不含拆解)一个 ≥0 有理数变量 = 制造次数;
        守恒      每种物品:产出 − 消耗 = 净流量;
        目标      净流量 == 需求量(多目标合并为一张约束网);
        available 持有物品只允许消耗(其产出配方强制为 0)→ 差额全部外部供给;
        可制造物品净流量 ≥ 0(必须自产,不允许外部缺口);
        最初用料(无产出配方)净流量 ≤ 0(消耗量即需求);
        byproducts=False 时追加硬约束:非目标物品净流量 == 0(不允许副产物)。
    目标函数:
        minimize Σ 制造次数(最少制造次数口径;替代口径如最少设备台数、
        最少外部购买可按同样框架扩展)。
        - preferred 暂未生效;
        - 环境维持按用到的环境计入 6/min 采集气体;设备维持(转化机气体)按
      运行时长线性计入流量(维持速率 × 设备占用率,速率语义下精确);
        - byproducts=False 是硬约束:依赖副产物的路线(如需冶炼产污水)会不可行。
    """

    def solve(self, targets: Mapping[str, Fraction], *,
              available: Mapping[str, Fraction] | None = None,
              preferred: Mapping[str, str] | None = None,
              per_min: bool = False,
              byproducts: bool = True) -> Requirement:
        from z3 import Optimize, Real, sat

        targets = {t: Fraction(q) for t, q in targets.items()}
        available = {a: Fraction(q) for a, q in (available or {}).items()}

        recipes = {r.id: r for r in self.graph.recipes
                   if not r.id.startswith(RECYCLER_PREFIX)}
        opt = Optimize()
        crafts = {rid: Real(f"x__{rid}") for rid in recipes}
        for v in crafts.values():
            opt.add(v >= 0)

        # 全链净流量(产出 − 消耗),按物品累计 z3 算术表达式
        flow: dict[str, object] = {}
        for rid, r in recipes.items():
            for s in r.outcomes:
                flow[s.id] = flow.get(s.id, 0) + crafts[rid] * s.count
            for s in r.ingredients:
                flow[s.id] = flow.get(s.id, 0) - crafts[rid] * s.count
            # 设施维持:机器运行期间持续通入息壤系气体,按运行时长线性计入
            upkeep_gas = MACHINE_UPKEEP.get(r.machine_id or "")
            if upkeep_gas is not None:
                per_craft = facility_upkeep(Fraction(1), r.craft_time)
                flow[upkeep_gas] = flow.get(upkeep_gas, 0) - crafts[rid] * per_craft

        preferred_recipes = set(preferred.values()) if preferred else set()
        target_ids = set(targets)
        for t, q in targets.items():
            opt.add(flow.get(t, 0) == q)
        for i, f in flow.items():
            if i in target_ids:
                continue
            if i in available:
                opt.add(f <= 0)              # 持有物品:只耗不产,差额外部供给
            elif i in self.graph.producers and not self.graph.is_gatherable(i):
                opt.add(f >= 0)              # 可制造且不可采集:必须自产
            else:
                opt.add(f <= 0)              # 最初用料/采集资源:外部获取
            if not byproducts and i not in target_ids:
                opt.add(f <= 0)              # 不允许副产物净剩余(硬约束)

        # 目标函数:制造次数计价,优先使用配方按半价(软偏好;整数计价规避除法节点)
        def cost(rid: str):
            return crafts[rid] * (1 if rid in preferred_recipes else 4)

        opt.minimize(sum(cost(rid) for rid in recipes))
        if opt.check() != sat:
            roots = [ReqNode(t, self.graph.name_of(t), q, KIND_CRAFT)
                     for t, q in targets.items()]
            note = "z3:约束不可满足(byproducts=False 时含副产物的路线会不可行)"
            return Requirement(roots=roots, strict_ok=False, leaves={}, crafts={},
                               recipes_by_id=self.graph.recipes_by_id,
                               notes=[note], byproducts={}, byproduct_sources={})

        model = opt.model()
        solved: dict[str, Fraction] = {}
        for rid, v in crafts.items():
            val = model.eval(v, model_completion=True)
            frac = Fraction(val.numerator_as_long(), val.denominator_as_long())
            if frac > 0:
                solved[rid] = frac

        # 按解出的制造次数重算净流量(含设施维持消耗)→ 叶子/副产物
        leaves: dict[tuple[str, str], Fraction] = {}
        flows: dict[str, Fraction] = {}
        for rid, n in solved.items():
            r = recipes[rid]
            for s in r.outcomes:
                flows[s.id] = flows.get(s.id, Fraction(0)) + n * s.count
            for s in r.ingredients:
                flows[s.id] = flows.get(s.id, Fraction(0)) - n * s.count
            upkeep_gas = MACHINE_UPKEEP.get(r.machine_id or "")
            if upkeep_gas is not None:
                flows[upkeep_gas] = (flows.get(upkeep_gas, Fraction(0))
                                     - facility_upkeep(n, r.craft_time))
        for i, net in sorted(flows.items()):
            if i in target_ids:
                continue
            if net < 0:  # 外部消耗 → 需求原料(有产出配方=外部投料,否则最初用料)
                kind = KIND_EXTERN if i in self.graph.producers else KIND_RAW
                leaves[(i, kind)] = -net
        byproducts_out = ({i: f for i, f in flows.items()
                           if f > 0 and i not in target_ids and byproducts}
                          if byproducts else {})
        sources = {i: next(rid for rid, n in solved.items()
                           if any(s.id == i for s in recipes[rid].outcomes))
                   for i in byproducts_out}

        # 环境维持:用到的每种气体环境,散布机恒定通入采集气体 6/min
        for env in sorted({r.gas_env for rid, n in solved.items()
                           for r in [recipes[rid]] if r.gas_env}):
            if (gas := GAS_ENV_PROVIDERS.get(env)) is not None:
                gas_id = gas[0]
                leaves[(gas_id, KIND_RAW)] = (leaves.get((gas_id, KIND_RAW), Fraction(0))
                                              + GAS_ENV_RATE)

        roots = [ReqNode(t, self.graph.name_of(t), q, KIND_CRAFT)
                 for t, q in targets.items()]
        # 渲染层走树遍历(leaf_items):把流量解出的叶子挂到首个目标树下展示
        for (i, kind), qty in sorted(leaves.items()):
            roots[0].children.append(ReqNode(i, self.graph.name_of(i), qty, kind))
        return Requirement(roots=roots, strict_ok=True, leaves=leaves,
                           crafts=solved, recipes_by_id=self.graph.recipes_by_id,
                           notes=["z3 求解:最少制造次数口径(优先配方成本 1/4);"
                                  "设施维持按运行时长线性计入流量"],
                           byproducts=byproducts_out, byproduct_sources=sources)
