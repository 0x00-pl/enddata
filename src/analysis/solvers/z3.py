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

from fractions import Fraction

from analysis.recipe_calc import RECYCLER_PREFIX, is_gatherable


from analysis.solvers import RecipeSolver, SolveRequest, SolveResult, register


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
        - byproducts=False 是硬约束:依赖副产物的路线(如需冶炼产污水)会不可行
          (maximize 物品豁免该约束)。
    """

    def solve(self, request: SolveRequest) -> SolveResult:
        from z3 import Optimize, Real, sat

        targets = {t: Fraction(q) for t, q in request.targets.items()}
        available = set(request.available)
        preferred = request.preferred
        byproducts = request.byproducts

        recipes = {r.id: r for r in self.recipes
                   if not r.id.startswith(RECYCLER_PREFIX)}
        opt = Optimize()
        crafts = {rid: Real(f"x__{rid}") for rid in recipes}
        for v in crafts.values():
            opt.add(v >= 0)

        # 全链净流量(产出 − 消耗),按物品累计 z3 算术表达式
        flow: dict[str, object] = {}
        for rid, r in recipes.items():
            for s in r.produce_items:
                flow[s.id] = flow.get(s.id, 0) + crafts[rid] * s.count
            for s in r.require_items:
                flow[s.id] = flow.get(s.id, 0) - crafts[rid] * s.count
            # 设施维持:机器运行期间持续通入息壤系气体,按运行时长线性计入
            upkeep = r.require_upkeep
            if upkeep is not None:
                gas_id, per_craft = upkeep
                flow[gas_id] = flow.get(gas_id, 0) - crafts[rid] * per_craft

        preferred_recipes = set(preferred.values()) if preferred else set()
        target_ids = set(targets)
        for t, q in targets.items():
            opt.add(flow.get(t, 0) == q)
        for i, f in flow.items():
            if i in target_ids:
                continue
            if i in available:
                opt.add(f <= 0)              # available 清单:可外部供给(只耗不产)
            elif i not in self.produced or is_gatherable(i):
                opt.add(f <= 0)              # 无产出配方物品/采集资源:外部获取
            else:
                opt.add(f >= 0)              # 可制造且未列 available:必须自产
            if not byproducts:
                opt.add(f <= 0)              # 不允许副产物净剩余(硬约束;最大化物品豁免)

        # 目标函数:制造次数计价,优先使用配方按半价(软偏好;整数计价规避除法节点)
        def cost(rid: str):
            return crafts[rid] * (1 if rid in preferred_recipes else 4)

        opt.minimize(sum(cost(rid) for rid in recipes))
        if opt.check() != sat:
            return SolveResult(crafts={}, strict_ok=False)

        model = opt.model()
        solved: dict[str, Fraction] = {}
        for rid, v in crafts.items():
            val = model.eval(v, model_completion=True)
            frac = Fraction(val.numerator_as_long(), val.denominator_as_long())
            if frac > 0:
                solved[rid] = frac
        return SolveResult(crafts=solved, strict_ok=True)
