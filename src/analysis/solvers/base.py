"""RecipeSolver 抽象基类:solve 的输入/输出契约(所有集合以物品 id 为键)。

求解器只依赖配方清单(Iterable[Recipe])与 recipe_calc 的数据层服务
(is_gatherable 等),不经过任何索引对象;求解所需的派生
索引(产出集合、id 直查)由基类从配方清单自行构建。
"""

from abc import ABC, abstractmethod
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction

from analysis.recipe_calc import (
    RECYCLER_PREFIX,
    Recipe,
    load_recipes,
)


@dataclass(frozen=True)
class SolveRequest:
    """solve 的打包输入:目标产物与求解开关(所有集合以物品 id 为键)。"""

    targets: Mapping[str, Fraction]                 # 目标产物 → 需求量(多目标聚合为一份需求)
    available: Collection[str] = field(default_factory=frozenset)   # 持有/可外部供给清单(只耗不产,不限量)
    preferred: Mapping[str, str] = field(default_factory=dict)      # 物品 → 优先配方 id(软偏好)
    per_min: bool = False                           # 速率口径:数量按每分钟产出计
    byproducts: bool = True                         # 结果是否计入副产物与维持流量
    maximize: Mapping[str, Fraction] = field(default_factory=dict)   # 最大化净产出:物品 → 权重


@dataclass(frozen=True)
class SolveResult:
    """solve 的原始输出:整图平面解(精确有理数)。

    crafts    配方 id → 制造次数(仅计入 > 0 的配方);
    strict_ok False = 约束不可满足(crafts 为空,目标无法满足);
    叶子/副产物/环境等展示合计不由求解器给出,由 recipe_calc 的
    FlowGraph 按制造次数推导。
    多目标求解为字典序:minimize 制造次数成本 → maximize 指定物品净产出
    (先保成本最优,再在等价最优解中最大化 maximize 物品的盈余)。
    """

    crafts: Mapping[str, Fraction]
    strict_ok: bool


class RecipeSolver(ABC):
    """配方求解器抽象基类:在配方清单上对目标物品需求求解,返回平面解。

    构造:
        recipes 参与求解的配方清单(缺省加载全量 data/recipes);
        子集场景(「仅这些配方可用」)直接传入清单。
    派生索引(构造时一次建好):
        recipes_by_id  配方 id → Recipe;
        produced       有产出配方(不含拆解)的物品 id 集合。
    """

    def __init__(self, recipes: Iterable[Recipe] | None = None) -> None:
        self.recipes = load_recipes() if recipes is None else list(recipes)
        self.recipes_by_id = {r.id: r for r in self.recipes}
        self.produced: set[str] = {s.id for r in self.recipes
                                   if not r.id.startswith(RECYCLER_PREFIX)
                                   for s in r.produce_items}

    @abstractmethod
    def solve(self, request: SolveRequest) -> SolveResult:
        """求解目标需求,返回平面解(配方 id → 制造次数 + 可行性)。"""
        raise NotImplementedError
