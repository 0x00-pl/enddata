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

from analysis.recipe_calc import GAS_ENV_RATE, RECYCLER_PREFIX, is_gatherable


from analysis.solvers import RecipeSolver, SolveRequest, SolveResult, register


@register("z3")
class Z3Solver(RecipeSolver):
    """Z3 (SMT/LP) 求解器:整图约束一次求解,环路与共享中间品天然可解。

    建模:
        变量      每条产出配方(不含拆解)一个 ≥0 有理数变量 = 制造次数,
                  维持设施另有 ≥0 整数台数变量(次数 ≤ 台数 × 单台容量);
        守恒      每种物品:产出 − 消耗 = 净流量;
        目标      净流量 == 需求量(多目标合并为一张约束网);
        available 持有物品只允许消耗(其产出配方强制为 0)→ 差额全部外部供给;
        可制造物品净流量 ≥ 0(必须自产,不允许外部缺口);
        最初用料(无产出配方)净流量 ≤ 0(消耗量即需求);
        byproducts=False 时追加硬约束:非目标物品净流量 == 0(不允许副产物)。
    目标函数(字典序):
        ① minimize Σ 制造次数(最少制造次数口径;替代口径如最少设备台数、
          最少外部购买可按同样框架扩展),preferred 配方成本按 1/4 计(软偏好);
        ② maximize 指定物品的加权净产出——只在成本最优的等价解中挑选盈余
          最大的,不会为多产副产物而增加制造次数;
        - preferred 暂未生效;
        - 外部供给仅限 无产出配方物品、采集资源 与 available 清单——可制造
          物品要外部获取须显式列入 available;usage_max/usage_min 约束各
          物品外部使用量(净缺口)上下限;
        - 环境维持按用到的环境计入 6/min 采集气体;设备维持(转化机气体)按
          占用台数计入(整数变量,向上取整,不满载也按整台 6/min;线性
          折算口径可经临时配方表达);
        - byproducts=False 是硬约束:依赖副产物的路线(如需冶炼产污水)会不可行
          (maximize 物品豁免该约束)。
    """

    def solve(self, request: SolveRequest) -> SolveResult:
        import z3

        # 独立 Context:隔离跨调用的求解器状态(复用全局上下文会在多次
        # Optimize 后劣化,个别查询从亚秒级劣化到分钟级)
        ctx = z3.Context()
        sat = z3.sat

        targets = {t: Fraction(q) for t, q in request.targets.items()}
        available = set(request.available)
        preferred = request.preferred
        byproducts = request.byproducts
        maximize = {m: Fraction(w) for m, w in request.maximize.items()}
        usage_max = {i: Fraction(v) for i, v in request.usage_max.items()}
        usage_min = {i: Fraction(v) for i, v in request.usage_min.items()}

        recipes = {r.id: r for r in self.recipes
                   if not r.id.startswith(RECYCLER_PREFIX)}
        opt = z3.Optimize(ctx=ctx)
        crafts = {rid: z3.Real(f"x__{rid}", ctx=ctx) for rid in recipes}
        for v in crafts.values():
            opt.add(v >= 0)

        # 全链净流量(产出 − 消耗),按物品累计 z3 算术表达式
        flow: dict[str, object] = {}
        machine_vars: list = []                       # 维持设施占用台数(整数)
        for rid, r in recipes.items():
            for s in r.produce_items:
                flow[s.id] = flow.get(s.id, 0) + crafts[rid] * s.count
            for s in r.require_items:
                flow[s.id] = flow.get(s.id, 0) - crafts[rid] * s.count
            # 设施维持:按占用台数计——占用秒数 ≤ 整数台数 × 60,气体 = 6 × 台数
            # (不满载也按整台全额;线性口径可经临时配方表达,见模块注释)
            if (gas_id := r.upkeep_gas) is not None and r.require_time:
                t = Fraction(str(r.require_time))
                m = z3.Int(f"m__{rid}", ctx=ctx)
                machine_vars.append(m)
                opt.add(m >= 0)
                opt.add(crafts[rid] * t.numerator <= m * 60 * t.denominator)
                flow[gas_id] = flow.get(gas_id, 0) - int(GAS_ENV_RATE) * m

        preferred_recipes = set(preferred.values()) if preferred else set()
        target_ids = set(targets)
        max_ids = set(maximize)
        for t, q in targets.items():
            opt.add(flow.get(t, 0) == q)
        for i, f in flow.items():
            if i in target_ids:
                continue
            if i in available:
                opt.add(f <= 0)              # available 清单:可外部供给(只耗不产)
            elif i in max_ids:
                pass                         # 最大化物品:净产出方向不受限(允许盈余)
            elif i not in self.produced or is_gatherable(i):
                opt.add(f <= 0)              # 无产出配方物品/采集资源:外部获取
            else:
                opt.add(f >= 0)              # 可制造且未列 available:必须自产
            if not byproducts and i not in max_ids:
                opt.add(f <= 0)              # 不允许副产物净剩余(硬约束;最大化物品豁免)
        # 外部使用量(净缺口)上下限:使用量 = −净流量
        for i, cap in usage_max.items():
            opt.add(flow.get(i, 0) >= -cap)
        for i, floor in usage_min.items():
            opt.add(flow.get(i, 0) <= -floor)

        # 目标函数:制造次数计价,优先使用配方按半价(软偏好;整数计价规避除法节点)
        def cost(rid: str):
            return crafts[rid] * (1 if rid in preferred_recipes else 4)

        opt.minimize(sum(cost(rid) for rid in recipes))
        if machine_vars:
            # 字典序第二目标:维持台数最少(把整数台数压到 ceil,不虚增)
            opt.minimize(sum(machine_vars))
        if maximize:
            # 字典序第二目标:成本最优的等价解中,最大化指定物品的加权净产出
            opt.maximize(sum(w * flow.get(m, 0) for m, w in maximize.items()))
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
