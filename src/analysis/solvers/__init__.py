"""配方求解器包:每个求解器实现一个模块,经 SOLVERS 注册后由 CLI --solver 选择。

接口约定(RecipeSolver.solve(request: SolveRequest),SolveRequest 字段
    以物品 id 为键、数量为值):
    targets     目标产物 → 需求量(支持多个目标,聚合为一份需求);
    available   持有原料 → 数量:命中即停止向下展开(数量当前版本仅透传对账,
                清单内物品视为充足;CLI --have 等价于 数量不限的持有清单);
    preferred   优先使用配方:物品 → 配方 id(优先尝试,失败仍回退其他配方);
    byproducts  结果是否计入副产物输出与额外输入(环境维持/设备维持气体);
                False 时只保留目标主链需求;
    maximize    最大化净产出:物品 → 权重(字典序第二目标——成本最优的
                等价解中,最大化这些物品的加权净盈余);
    usage_max   外部使用量上限:物品 → 量(外部使用量 = 净缺口);
    usage_min   外部使用量下限:物品 → 量。
    外部供给范围 = 无产出配方物品 ∪ 采集资源 ∪ available 清单;可制造物品
    要外部获取须显式列入 available。
返回 SolveResult(平面解:crafts=配方 id → 制造次数、strict_ok 可行性);
叶子/副产物/环境等展示合计不由求解器给出,由 recipe_calc 的 FlowGraph
按制造次数推导。
"""

from analysis.solvers.base import RecipeSolver, SolveRequest, SolveResult

__all__ = ["SOLVERS", "RecipeSolver", "SolveRequest", "SolveResult", "register"]

SOLVERS: dict[str, type[RecipeSolver]] = {}


def register(name: str):
    """类装饰器:以 name 将求解器实现注册进 SOLVERS。"""

    def deco(cls: type[RecipeSolver]) -> type[RecipeSolver]:
        SOLVERS[name] = cls
        return cls

    return deco


import analysis.solvers.z3 as _z3  # noqa: E402,F401  (导入即注册 z3,需 z3-solver 包)
