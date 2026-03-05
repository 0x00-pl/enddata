"""RecipeSolver 抽象基类:solve 的输入/输出契约(所有集合以物品 id 为键)。"""

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
