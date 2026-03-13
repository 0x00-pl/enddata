"""配方求解器包:每个求解器实现一个模块,经 SOLVERS 注册后由 CLI --solver 选择。

接口约定(RecipeSolver.solve(request: SolveRequest),SolveRequest 字段
    以物品 id 为键、数量为值):
    targets     目标产物 → 需求量(支持多个目标,聚合为一份需求);
    available   持有原料 → 数量:命中即停止向下展开(数量当前版本仅透传对账,
                清单内物品视为充足;CLI --have 等价于 数量不限的持有清单);
    preferred   优先使用配方:物品 → 配方 id(优先尝试,失败仍回退其他配方);
    byproducts  结果是否计入副产物输出与额外输入(环境维持/设备维持气体);
                False 时只保留目标主链需求。
返回 Requirement(targets=目标→需求量;crafts/leaves/byproducts 等为
平面解合计,leaves 按物品 → 数量;materials() 提供按物品聚合的净需求)。
"""

from analysis.solvers.base import RecipeSolver, SolveRequest

SOLVERS: dict[str, type[RecipeSolver]] = {}


def register(name: str):
    """类装饰器:以 name 将求解器实现注册进 SOLVERS。"""

    def deco(cls: type[RecipeSolver]) -> type[RecipeSolver]:
        SOLVERS[name] = cls
        return cls

    return deco


import analysis.solvers.z3 as _z3  # noqa: E402,F401  (导入即注册 z3,需 z3-solver 包)
