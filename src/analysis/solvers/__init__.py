"""配方求解器包:每个求解器实现一个模块,经 SOLVERS 注册后由 CLI --solver 选择。

接口约定(RecipeSolver.solve,所有集合以物品 id 为键、数量为值):
    targets     目标产物 → 需求量(支持多个目标,聚合为一份需求);
    available   持有原料 → 数量:命中即停止向下展开(数量当前版本仅透传对账,
                清单内物品视为充足;CLI --have 等价于 数量不限的持有清单);
    preferred   优先使用配方:物品 → 配方 id(优先尝试,失败仍回退其他配方);
    byproducts  结果是否计入副产物输出与额外输入(环境维持/设备维持气体);
                False 时只保留目标主链需求。
返回 Requirement(leaves/byproducts/upkeep_supplies 等均为 物品 → 数量 映射;
materials() 提供按物品聚合的净需求)。
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from fractions import Fraction

from analysis.recipe_calc import Recipe, RecipeGraph, Requirement


class RecipeSolver(ABC):
    """配方求解器抽象基类:在配方图上对目标物品需求求解,返回 Requirement。

    构造:
        graph   配方图(缺省加载全量 data/recipes);
        recipes 限定参与求解的配方清单(构建子集图谱,用于"仅这些配方可用"场景)。
    """

    def __init__(self, graph: RecipeGraph | None = None,
                 recipes: Iterable[Recipe] | None = None) -> None:
        self.graph = RecipeGraph(recipes) if recipes is not None else (graph or RecipeGraph())

    @abstractmethod
    def solve(self, targets: Mapping[str, Fraction], *,
              available: Mapping[str, Fraction] | None = None,
              preferred: Mapping[str, str] | None = None,
              per_min: bool = False,
              byproducts: bool = True) -> Requirement:
        """求解并返回 Requirement(展开树/树木 + 各类 物品 → 数量 合计)。"""
        raise NotImplementedError


SOLVERS: dict[str, type[RecipeSolver]] = {}


def register(name: str):
    """类装饰器:以 name 将求解器实现注册进 SOLVERS。"""

    def deco(cls: type[RecipeSolver]) -> type[RecipeSolver]:
        SOLVERS[name] = cls
        return cls

    return deco


import analysis.solvers.recursive as _recursive  # noqa: E402,F401  (导入即注册 recursive)
