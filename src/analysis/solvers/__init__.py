"""配方求解器包:每个求解器实现一个模块,经 SOLVERS 注册后由 CLI --solver 选择。

接口约定(RecipeSolver.solve(request: SolveRequest),SolveRequest 字段
    以物品 id 为键、数量为值):
    targets     目标产物 → 需求量(支持多个目标,聚合为一份需求);
    available   持有/可外部供给清单(无数量,不限量):命中即可外部获取、
                只耗不产(CLI --have 等价);
    preferred   优先使用配方:物品 → 配方 id(优先尝试,失败仍回退其他配方);
    byproducts  结果是否计入副产物输出与额外输入(环境维持/设备维持气体);
                False 时只保留目标主链需求;
返回 SolveResult(平面解:crafts=配方 id → 制造次数、strict_ok 可行性);
叶子/副产物/环境等展示合计不由求解器给出,由 recipe_calc 的 FlowGraph
按制造次数推导。
"""

from analysis.solvers.base import RecipeSolver, SolveRequest, SolveResult

SOLVERS: dict[str, type[RecipeSolver]] = {}


def register(name: str):
    """类装饰器:以 name 将求解器实现注册进 SOLVERS。"""

    def deco(cls: type[RecipeSolver]) -> type[RecipeSolver]:
        SOLVERS[name] = cls
        return cls

    return deco


import analysis.solvers.z3 as _z3  # noqa: E402,F401  (导入即注册 z3,需 z3-solver 包)
