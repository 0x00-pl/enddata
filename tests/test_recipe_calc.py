"""配方求解(z3 求解器)单元测试。

覆盖:数量解析、物品解析与重名消歧、拆解配方排除、散布机 produce_env 合成条目、
基础/分数/多目标求解、环原生求解(种子自持)、优先配方折扣、持有清单、配方
子集构造、byproducts 硬约束、设施维持/环境维持流量、mermaid 链路图(流量
建点+单入单出收缩)、渲染分节、JSON 输出、总览报告、守恒抽样不变量。

求解器只返回平面解(SolveResult:crafts + strict_ok);FlowGraph 由平面解
构造产出链路图,leaves/byproducts/materials/machines 等合计与
outline/mermaid/summary/to_dict 渲染均出自它。

运行:poetry run pytest tests/ -q
"""

from fractions import Fraction

import pytest

from analysis.recipe_calc import (
    KIND_EXTERN,
    KIND_RAW,
    FlowGraph,
    compute,
    load_recipes,
    parse_qty,
    produced_ids,
    recipes_by_id,
    resolve_item,
)
from analysis.solvers import SolveRequest
from analysis.solvers.z3 import Z3Solver


def solve_chart(target, qty, **kw):
    """单目标求解便利:返回 FlowGraph(平面解 + 链路图 + 各类合计)。"""
    res = compute(target, Fraction(qty), **kw)
    return FlowGraph(recipes_by_id(), {target: Fraction(qty)}, res)


@pytest.fixture(scope="module")
def rbi():
    return recipes_by_id()


# ---------------------------------------------------------------- 数量与解析
def test_parse_qty():
    assert parse_qty("6") == (Fraction(6), False)
    assert parse_qty("1/2") == (Fraction(1, 2), False)
    assert parse_qty("0.5") == (Fraction(1, 2), False)
    assert parse_qty("60/min") == (Fraction(60), True)
    assert parse_qty("30/分钟") == (Fraction(30), True)
    for bad in ("abc", "0", "-1", "1/0", ""):
        with pytest.raises(ValueError):
            parse_qty(bad)


def test_resolve():
    assert resolve_item("item_iron_cmpt") == ("item_iron_cmpt", [])
    # 重名消歧:铁制零件 = 材料 item_iron_cmpt 与系统蓝图 sysbp_*,参与配方图者优先
    assert resolve_item("铁制零件")[0] == "item_iron_cmpt"
    assert resolve_item("灼铜零件")[0] == "item_copper_enr2_cmpt"
    assert resolve_item("蓝铁瓶")[0] == "item_iron_bottle"
    assert resolve_item("不存在的东西") == (None, [])


def test_dismantler_excluded():
    """拆解配方不计入产出集合;仅能由拆解产出的物品(如惰气)视同最初用料。"""
    produced = produced_ids()
    assert "item_gas_inert" not in produced
    non_dismantler_out = {s.id for r in load_recipes()
                          if not r.id.startswith("dismantler_") for s in r.produce_items}
    assert produced == non_dismantler_out


def test_vaporizer_produce_env():
    """散布机合成条目(produce_env 来源):通入气体 ×6/min 产出对应环境;
    无物品产出、不进产出集合,求解不会被选中。"""
    spreaders = [r for r in load_recipes() if r.produce_env]
    assert {r.produce_env: r.require_items[0].id for r in spreaders} == {
        1: "item_gas_inert", 2: "item_gas_water",
        3: "item_gas_acid", 4: "item_gas_xiranite"}
    for r in spreaders:
        assert r.produce_items == () and r.require_machine == "vaporizer_1"
        assert r.machine_name == "气体散布机"
        assert r.require_items[0].count == 6 and r.require_time is None
    res = compute("item_copper_enr2_cmpt", Fraction(6))
    assert not any(rid.startswith("vaporizer_") for rid in res.crafts)


# ---------------------------------------------------------------- 基础求解
def test_basic_chain():
    chart = solve_chart("item_iron_cmpt", 10)
    assert chart.strict_ok
    assert chart.leaves == {("item_iron_ore", KIND_RAW): Fraction(10)}
    assert chart.crafts == {
        "component_iron_cmpt_1": Fraction(10),
        "furnance_iron_nugget_1": Fraction(10),
    }


def test_fractional_qty():
    chart = solve_chart("item_iron_nugget", Fraction(1, 2))
    assert chart.crafts == {"furnance_iron_nugget_1": Fraction(1, 2)}
    assert chart.leaves == {("item_iron_ore", KIND_RAW): Fraction(1, 2)}


def test_seed_loop_native():
    """环原生求解:锦草 ×10 由 种植+采种 自持供给,种子不求外部,
    清水(水泵采集)为唯一外部投入。"""
    chart = solve_chart("item_plant_grass_1", 10)
    assert chart.strict_ok
    assert chart.crafts == {
        "planter_plant_grass_1_1": Fraction(10),
        "seedcollector_plant_grass_1_1": Fraction(10),
    }
    assert chart.leaves == {("item_liquid_water", KIND_EXTERN): Fraction(10)}
    assert chart.byproducts == {} and chart.byproduct_sources == {}


def test_available_stops_production(rbi):
    """持有清单(available):清单物品只耗不产,不再为其安排产出配方。"""
    solver = Z3Solver(load_recipes())
    targets = {"item_plant_grass_1": Fraction(10)}
    res = solver.solve(SolveRequest(targets,
                                    available={"item_plant_grass_seed_1": 0}))
    chart = FlowGraph(rbi, targets, res)
    assert chart.crafts == {"planter_plant_grass_1_1": Fraction(5)}   # 单次产 2
    assert chart.leaves == {
        ("item_plant_grass_seed_1", KIND_EXTERN): Fraction(5),
        ("item_liquid_water", KIND_EXTERN): Fraction(5),
    }


def test_gatherable_water_external(rbi):
    """清水为采集资源:即便存在回收环配方,也按外部投料计,不建回收机。"""
    chart = solve_chart("item_copper_nugget", 1)
    assert chart.crafts == {"furnance_copper_nugget_1": Fraction(1)}
    assert chart.leaves == {
        ("item_copper_ore", KIND_RAW): Fraction(1),
        ("item_liquid_water", KIND_EXTERN): Fraction(1),
    }
    assert chart.byproducts == {"item_liquid_sewage": Fraction(1)}
    assert chart.byproduct_sources == {"item_liquid_sewage": "furnance_copper_nugget_1"}


def test_spaceship_free_recipe():
    """飞船配方无原料:制造步骤成立但零投入。"""
    chart = solve_chart("item_expcard_stage1_low", 5)
    assert chart.leaves == {}
    assert chart.crafts == {"mfg_exp_1_1": Fraction(5)}


# ---------------------------------------------------------------- 优先配方与子集
def test_preferred_discount(rbi):
    """优先配方成本 1/4(软偏好):首选在折扣下胜出并浮现环境需求。"""
    default = FlowGraph(rbi, {"item_xiranite_powder": Fraction(1)},
                        compute("item_xiranite_powder", Fraction(1)))
    assert "liquid_transmuter_2_solid_xiranite_powder_1" in default.crafts
    assert default.required_envs() == []
    res = Z3Solver(load_recipes()).solve(
        SolveRequest({"item_xiranite_powder": Fraction(1)},
                     preferred={"item_xiranite_powder": "xiranite_oven_xiranite_powder_2"}))
    chart = FlowGraph(rbi, {"item_xiranite_powder": Fraction(1)}, res)
    assert "xiranite_oven_xiranite_powder_2" in chart.crafts
    assert chart.required_envs() == [("稳定环境", ["xiranite_oven_xiranite_powder_2"])]
    assert chart.leaves[("item_gas_inert", KIND_RAW)] == Fraction(6)   # 散布机维持


def test_preferred_twin_recipes():
    """完全等价的双胞胎配方(反应池 _1/_2,给定息壤/清水):折扣确定性选中首选。"""
    res = Z3Solver(load_recipes()).solve(
        SolveRequest({"item_liquid_xiranite": Fraction(2)},
                     available={"item_xiranite_powder": 0, "item_liquid_water": 0},
                     preferred={"item_liquid_xiranite": "pool_liquid_liquid_xiranite_2"}))
    assert set(res.crafts) == {"pool_liquid_liquid_xiranite_2"}


def test_solver_ctor_recipe_subset():
    """构造传入配方子集:求解被限定在子集内(息壤只能走 oven_2 + 碳块)。"""
    subset = [r for r in load_recipes()
              if r.id in ("xiranite_oven_xiranite_powder_2",
                          "furnance_carbon_material_6")]
    res = Z3Solver(subset).solve(SolveRequest({"item_xiranite_powder": Fraction(2)}))
    assert set(res.crafts) == {"xiranite_oven_xiranite_powder_2",
                               "furnance_carbon_material_6"}


# ---------------------------------------------------------------- 速率口径(60/min)
def test_rate_filter_core_60_per_min():
    """分离芯 60/min:材料流量 + 设施维持(息壤气 36 = 30 原料 + 6 维持)。"""
    chart = solve_chart("item_filter_core", 60, per_min=True)
    assert chart.leaves == {
        ("item_liquid_water", KIND_EXTERN): Fraction(60),
        ("item_gas_xiranite", KIND_EXTERN): Fraction(36),
        ("item_copper_ore", KIND_RAW): Fraction(60),
        ("item_gas_inert", KIND_RAW): Fraction(30),
    }
    assert chart.crafts == {
        "furnance_copper_nugget_1": Fraction(60),
        "liquid_transmuter_2_solid_xiranite_powder_1": Fraction(30),
        "shaper_gas_copper_jar_1": Fraction(30),
        "tools_proc_filter_core_2": Fraction(30),
    }
    assert chart.byproducts == {"item_liquid_sewage": Fraction(60)}
    machines = {r.id: m for r, _, m in chart.machines()}
    assert machines["furnance_copper_nugget_1"] == 2        # 60×2s/60
    assert machines["tools_proc_filter_core_2"] == 1        # 30×2s/60
    assert sum(machines.values()) == 5


def test_rate_filter_core_provided(rbi):
    """给定 息壤/清水:目标链只剩 冶炼+塑形+封装,给定物按外部投料计。"""
    solver = Z3Solver(load_recipes())
    targets = {"item_filter_core": Fraction(60)}
    res = solver.solve(SolveRequest(targets,
                                    available={"item_xiranite_powder": 0, "item_liquid_water": 0},
                                    per_min=True))
    chart = FlowGraph(rbi, targets, res)
    assert chart.crafts == {
        "furnance_copper_nugget_1": Fraction(60),
        "shaper_gas_copper_jar_1": Fraction(30),
        "tools_proc_filter_core_2": Fraction(30),
    }
    assert chart.leaves == {
        ("item_copper_ore", KIND_RAW): Fraction(60),
        ("item_gas_inert", KIND_RAW): Fraction(30),
        ("item_liquid_water", KIND_EXTERN): Fraction(60),
        ("item_xiranite_powder", KIND_EXTERN): Fraction(30),
    }


def test_rate_copper_enr2_6_per_min_provided(rbi):
    """灼铜零件 ×6/min,给定 息壤/清水/赤铜块:含设施维持(息壤系气体)
    与双环境需求(提纯机 _2 稳定 + 反应炉酸性)。"""
    solver = Z3Solver(load_recipes())
    targets = {"item_copper_enr2_cmpt": Fraction(6)}
    res = solver.solve(SolveRequest(targets,
                                    available={"item_xiranite_powder": 0, "item_liquid_water": 0,
                                               "item_copper_nugget": 0},
                                    per_min=True))
    chart = FlowGraph(rbi, targets, res)
    assert chart.strict_ok
    assert chart.crafts == {
        "component_copper_enr2_cmpt_1": Fraction(6),
        "gas_reactor_gas_copper_enr2_1": Fraction(30),
        "liquid_purifier_gas_copper_enr_2": Fraction(30),
        "liquid_transmuter_2_gas_gas_copper_1": Fraction(60),
        "liquid_transmuter_2_solid_copper_enr2_1": Fraction(30),
        "shaper_gas_copper_jar_1": Fraction(15),
        "tools_proc_filter_core_2": Fraction(15),
    }
    mats = chart.materials()
    assert mats["item_copper_nugget"] == Fraction(150)     # 气态 120 + 罐 30
    assert mats["item_gas_inert"] == Fraction(21)          # 罐 15 + 稳定环境 6
    assert mats["item_gas_acid"] == Fraction(6)            # 酸性环境维持
    assert mats["item_gas_xiranite"] == Fraction(48)   # 反应炉 30 + 两台固气转化机维持 18
    assert mats["item_xiranite_powder"] == Fraction(15)
    envs = dict(chart.required_envs())
    assert set(envs) == {"稳定环境", "酸性环境"}
    assert envs["稳定环境"] == ["liquid_purifier_gas_copper_enr_2"]
    assert envs["酸性环境"] == ["gas_reactor_gas_copper_enr2_1"]


# ---------------------------------------------------------------- byproducts 硬约束
def test_byproducts_flag(rbi):
    """byproducts=False 为硬约束:给定赤铜块(无冶炼)可行且零副产物;
    不给定时赤铜块只能冶炼(必产污水)→ 不可行。"""
    solver = Z3Solver(load_recipes())
    targets = {"item_copper_enr2_cmpt": Fraction(6)}
    ok = solver.solve(SolveRequest(targets,
                                   available={"item_xiranite_powder": 0, "item_liquid_water": 0,
                                              "item_copper_nugget": 0},
                                   per_min=True, byproducts=False))
    chart = FlowGraph(rbi, targets, ok)
    assert chart.strict_ok
    assert chart.byproducts == {} and chart.byproduct_sources == {}
    assert "furnance_copper_nugget_1" not in chart.crafts
    bad = solver.solve(SolveRequest(dict(targets), byproducts=False))
    assert not bad.strict_ok


# ---------------------------------------------------------------- 多目标与守恒
def test_multi_target(rbi):
    """多目标:一张约束网同时满足,原料聚合不重不漏。"""
    solver = Z3Solver(load_recipes())
    targets = {"item_filter_core": Fraction(60), "item_iron_cmpt": Fraction(10)}
    res = solver.solve(SolveRequest(targets, per_min=True))
    chart = FlowGraph(rbi, targets, res)
    assert chart.strict_ok
    mats = chart.materials()
    assert mats["item_copper_ore"] == Fraction(60)
    assert mats["item_iron_ore"] == Fraction(10)


def test_conservation_sample(rbi):
    """抽样守恒:目标净产 == 需求量;叶子 = 净缺口(含环境维持供气)。"""
    sample = sorted(i for i in produced_ids() if not i.startswith("item_port_"))[::12]
    solver = Z3Solver(load_recipes())
    for t in sample:
        res = solver.solve(SolveRequest({t: Fraction(7)}))
        assert res.strict_ok, t
        chart = FlowGraph(rbi, {t: Fraction(7)}, res)
        flows = dict(chart.flows)
        for (iid, _kind), total in chart.leaves.items():
            flows[iid] = flows.get(iid, Fraction(0)) - total
        assert flows.get(t, Fraction(0)) == Fraction(7), t


# ---------------------------------------------------------------- 求解器抽象
def test_solver_abstraction(rbi):
    """注册表:z3 为默认且唯一实现;抽象基类不可实例化;compute 等价。"""
    from analysis.solvers import SOLVERS, RecipeSolver, SolveResult
    assert set(SOLVERS) == {"z3"}
    assert issubclass(Z3Solver, RecipeSolver)
    with pytest.raises(TypeError):
        RecipeSolver()
    via_compute = compute("item_filter_core", Fraction(60))
    via_class = Z3Solver(load_recipes()).solve(
        SolveRequest({"item_filter_core": Fraction(60)}))
    assert isinstance(via_class, SolveResult)
    assert via_compute.crafts == via_class.crafts
    targets = {"item_filter_core": Fraction(60)}
    assert (FlowGraph(rbi, targets, via_compute).leaves
            == FlowGraph(rbi, targets, via_class).leaves)


# ---------------------------------------------------------------- 渲染 / 链路图 / JSON / 报告
def test_mermaid_flow(rbi):
    """链路图:流量建点 + 二部边(副产物同权实线)+ 单入单出收缩。"""
    targets = {"item_copper_nugget": Fraction(2)}
    chart = FlowGraph(rbi, targets, compute("item_copper_nugget", Fraction(2)))
    text = chart.mermaid()
    assert text.startswith("flowchart LR")
    assert "I_item_copper_nugget((" in text                  # 目标节点
    assert "I_item_copper_ore([" in text                     # 最初用料(圆角)
    assert "R_furnance_copper_nugget_1" in text
    assert "I_item_liquid_sewage" in text                    # 副产物节点(与产物同权)
    assert "I_item_copper_ore -->|" in text and "-->" in text


def test_mermaid_upkeep_edge(rbi):
    """设施维持边:固气转化机的息壤气 = 原料边 ×30 + 维持边 ×6,源节点标 36。"""
    targets = {"item_filter_core": Fraction(60)}
    chart = FlowGraph(rbi, targets,
                      compute("item_filter_core", Fraction(60), per_min=True))
    text = chart.mermaid()
    assert 'I_item_gas_xiranite[["息壤气 ×36"]]' in text
    assert '-->|"×30"| R_liquid_transmuter_2_solid_xiranite_powder_1' in text
    assert '-->|"维持 ×6"| R_liquid_transmuter_2_solid_xiranite_powder_1' in text


def test_render_rate_and_batch(rbi):
    targets = {"item_filter_core": Fraction(60)}
    chart = FlowGraph(rbi, targets,
                      compute("item_filter_core", Fraction(60), per_min=True))
    text = chart.summary("分离芯", per_min=True)
    assert "×60/min" in text and "设备需求" in text
    batch_targets = {"item_filter_core": Fraction(4)}
    batch = FlowGraph(rbi, batch_targets,
                      compute("item_filter_core", Fraction(4))).summary("分离芯")
    # 批量模式不含速率数量;describe 的维持*6/min 是设备规格,允许出现
    assert "设备需求" not in batch and "×60/min" not in batch


def test_render_sections(rbi):
    """最终输出分节:目标/需求原料/产出(副产物)/制造步骤/设备/环境/链路图。"""
    solver = Z3Solver(load_recipes())
    targets = {"item_copper_enr2_cmpt": Fraction(6)}
    res = solver.solve(SolveRequest(targets,
                                    available={"item_xiranite_powder": 0, "item_liquid_water": 0,
                                               "item_copper_nugget": 0}, per_min=True))
    text = FlowGraph(rbi, targets, res).summary("灼铜零件", per_min=True)
    for section in ("目标 灼铜零件", "需求原料", "产出:", "制造步骤",
                    "设备需求", "环境需求", "稳定环境", "酸性环境",
                    "产出链路图", "```mermaid", "flowchart LR"):
        assert section in text, section


def test_to_dict(rbi):
    import json
    solver = Z3Solver(load_recipes())
    targets = {"item_filter_core": Fraction(60)}
    res = solver.solve(SolveRequest(dict(targets), per_min=True))
    payload = json.loads(json.dumps(
        FlowGraph(rbi, targets, res).to_dict(per_min=True)))
    assert payload["target"]["per_min"] is True
    assert payload["strict_ok"] is True
    kinds = {(l["id"], l["kind"]) for l in payload["leaves"]}
    assert ("item_gas_xiranite", "external") in kinds
    assert ("item_gas_inert", "raw") in kinds
    machines = {m["recipe"]: m["count"] for m in payload["machines"] if "recipe" in m}
    assert machines["tools_proc_filter_core_2"] == 1
    assert payload["mermaid"].startswith("flowchart LR")


def test_build_report_sections():
    from analysis.recipe_calc import build_report
    report = build_report(demos=[("铁制零件", Fraction(10), frozenset())])
    assert "# 配方用料倒推 · 数据概览" in report
    assert "## 示例:铁制零件 ×10" in report
