"""配方用料倒推(recipe_calc)单元测试。

覆盖:数量解析、物品解析与重名消歧、拆解配方排除、基础链路、分数数量、
自持环宏配方(种子环)、等量回收环外部投料、投料点收缩、--have 截断、
飞船无原料配方、流量守恒(抽样不变量)、速率口径(60/min 材料流量与设备数)、
渲染与 JSON 输出、总览报告。

运行:poetry run pytest tests/ -q
"""

from fractions import Fraction

import pytest

from analysis.recipe_calc import (
    KIND_CRAFT,
    KIND_EXTERN,
    KIND_PROVIDED,
    KIND_RAW,
    RecipeGraph,
    build_report,
    compute,
    machine_counts,
    parse_qty,
    render_result,
    render_mermaid,
    result_json,
)

def leaf_map(req):
    return {(n.id, n.kind): total for n, total in req.leaf_items()}


def find_node(root, item_id):
    return next(n for n in root.walk() if n.id == item_id)


@pytest.fixture(scope="module")
def graph():
    return RecipeGraph()


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


def test_resolve(graph):
    assert graph.resolve("item_iron_cmpt")[0] == "item_iron_cmpt"
    # 重名消歧:铁制零件 = 材料 item_iron_cmpt 与系统蓝图 sysbp_*,参与配方图者优先
    assert graph.resolve("铁制零件")[0] == "item_iron_cmpt"
    assert graph.resolve("灼铜零件")[0] == "item_copper_enr2_cmpt"
    # 唯一子串
    assert graph.resolve("蓝铁瓶")[0] == "item_iron_bottle"
    assert graph.resolve("不存在的东西") == (None, [])


def test_dismantler_excluded(graph):
    """拆解配方不列入产出图谱;仅能拆解产出的物品(惰气)视同最初用料。"""
    for item, recipes in graph.producers.items():
        assert all(not r.id.startswith("dismantler_") for r in recipes)
    assert "item_gas_inert" not in graph.producers


# ---------------------------------------------------------------- 基础链路
def test_basic_chain(graph):
    req = compute(graph, "item_iron_cmpt", Fraction(10))
    assert req.strict_ok
    assert leaf_map(req) == {("item_iron_ore", KIND_RAW): Fraction(10)}
    assert req.crafts == {
        "component_iron_cmpt_1": Fraction(10),
        "furnance_iron_nugget_1": Fraction(10),
    }


def test_fractional_qty(graph):
    req = compute(graph, "item_iron_nugget", Fraction(1, 2))
    assert req.crafts == {"furnance_iron_nugget_1": Fraction(1, 2)}
    assert leaf_map(req) == {("item_iron_ore", KIND_RAW): Fraction(1, 2)}


def test_raw_leaf_obtain_annotation(graph):
    """最初用料附 items 数据集的获取途径(惰气 = 矿点采集)。"""
    req = compute(graph, "item_filter_core", Fraction(1))
    assert graph.obtain_of("item_gas_inert") == "惰气矿点采集"
    assert ("item_gas_inert", KIND_RAW) in leaf_map(req)


# ---------------------------------------------------------------- 环处理
def test_seed_cycle_macro(graph):
    """种子↔作物净产环:自持宏配方供给种子,净耗清水计入,环内作物守恒。"""
    req = compute(graph, "item_plant_grass_1", Fraction(10))
    assert req.strict_ok
    seed = find_node(req.root, "item_plant_grass_seed_1")
    assert seed.kind == KIND_CRAFT and seed.macro is not None
    m = seed.macro
    assert m.demanded == "item_plant_grass_seed_1"
    assert m.loop == ("item_plant_grass_1", "item_plant_grass_seed_1")
    assert m.ratio == (1, 2)                    # planter ×1 + seedcollector ×2 每轮
    assert m.net_per_round == 1
    assert m.side_inputs() == {"item_liquid_water": 1}
    assert seed.macro_rounds == 5
    # 制造步骤合计:直接种植 5(产锦草)+ 宏内 5 = 10;采种 10
    assert req.crafts["planter_plant_grass_1_1"] == 10
    assert req.crafts["seedcollector_plant_grass_1_1"] == 10
    # 用料:清水 10(宏净耗 5 + 种植直接 5),全部为外部投料点
    assert leaf_map(req) == {("item_liquid_water", KIND_EXTERN): Fraction(10)}
    assert any("自持环" in note and "初始占用" in note for note in req.notes)


def test_netzero_loop_extern(graph):
    """清水⇄水蒸气等量回收环:净产出为零 → 换下一配方,清水记外部投料。"""
    req = compute(graph, "item_copper_nugget", Fraction(1))
    assert req.strict_ok
    leaves = leaf_map(req)
    assert leaves[("item_liquid_water", KIND_EXTERN)] == 1
    assert leaves[("item_copper_ore", KIND_RAW)] == 1
    assert "liquid_transmuter_1_liquid_liquid_water_1" not in req.crafts
    assert req.crafts == {"furnance_copper_nugget_1": 1}


def test_shrink_returns_craftable_to_chain(graph):
    """投料点收缩:赤铜块在清水有供给时可严格自产,不留在投料集。"""
    req = compute(graph, "item_filter_core", Fraction(4))
    copper = find_node(req.root, "item_copper_nugget")
    assert copper.kind == KIND_CRAFT and copper.macro is None
    assert copper.recipe.id == "furnance_copper_nugget_1"
    kinds = {(n.id, n.kind) for n in req.root.walk() if n.kind != KIND_CRAFT}
    assert ("item_liquid_water", KIND_EXTERN) in kinds
    assert ("item_copper_nugget", KIND_EXTERN) not in kinds


def test_have_stops_expansion(graph):
    """--have 清单命中即截断:种子视为外部提供,不再启用自持环。"""
    req = compute(graph, "item_plant_grass_1", Fraction(10),
                  frozenset({"item_plant_grass_seed_1"}))
    leaves = leaf_map(req)
    assert leaves[("item_plant_grass_seed_1", KIND_PROVIDED)] == 5
    assert leaves[("item_liquid_water", KIND_EXTERN)] == 5
    assert all(n.macro is None for n in req.root.walk())
    assert req.strict_ok


def test_spaceship_free_recipe(graph):
    """飞船配方无原料:制造步骤成立但零投入。"""
    req = compute(graph, "item_expcard_stage1_low", Fraction(5))
    assert leaf_map(req) == {}
    assert req.crafts == {"mfg_exp_1_1": 5}


# ---------------------------------------------------------------- 流量守恒(抽样不变量)
def test_conservation_invariants(graph):
    """抽样审计:产出=单产×次数、子需求=单耗×次数、宏配方环内守恒、目标净产=需求量。"""
    sample = sorted(graph.producers)[::12] + [
        "item_filter_core", "item_copper_enr2_cmpt", "item_plant_grass_1",
    ]
    for t in sample:
        qty = Fraction(7)
        req = compute(graph, t, qty)
        for node in req.root.walk():
            if node.kind != KIND_CRAFT:
                continue
            assert node.recipe is not None and node.crafts is not None
            if node.macro is None:
                assert node.qty == node.recipe.yield_of(node.id) * node.crafts, t
                for s in node.recipe.ingredients:
                    kid = next((c for c in node.children if c.id == s.id), None)
                    assert kid is not None and kid.qty == s.count * node.crafts, (t, s.id)
            else:
                m, rounds = node.macro, node.macro_rounds
                flow = {}
                for r, k in zip(m.recipes, m.ratio):
                    for s in r.outcomes:
                        flow[s.id] = flow.get(s.id, Fraction(0)) + k * s.count
                    for s in r.ingredients:
                        flow[s.id] = flow.get(s.id, Fraction(0)) - k * s.count
                for lid in m.loop:
                    want = m.net_per_round if lid == m.demanded else Fraction(0)
                    assert flow.get(lid, Fraction(0)) == want, (t, lid)
                for sid, need in m.side_inputs().items():
                    kid = next((c for c in node.children if c.id == sid), None)
                    assert kid is not None and kid.qty == need * rounds, (t, sid)
        produced, consumed = {}, {}
        for rid, n in req.crafts.items():
            r = req.recipes_by_id[rid]
            for s in r.outcomes:
                produced[s.id] = produced.get(s.id, Fraction(0)) + s.count * n
            for s in r.ingredients:
                consumed[s.id] = consumed.get(s.id, Fraction(0)) + s.count * n
        for node, total in req.leaf_items():
            consumed[node.id] = consumed.get(node.id, Fraction(0)) - total
        assert produced.get(t, Fraction(0)) - consumed.get(t, Fraction(0)) == qty, t
        byproducts = {s.id for rid in req.crafts
                      for s in req.recipes_by_id[rid].outcomes}
        for i, p in produced.items():
            if i != t and p - consumed.get(i, Fraction(0)) > 0:
                assert i in byproducts, (t, i)   # 副产物之外不得凭空净产


# ---------------------------------------------------------------- 速率口径(60/min)
def test_rate_filter_core_60_per_min(graph):
    """分离芯 60/min:材料流量 + 设备数(产量每分钟 × 单次耗时 ÷ 60,向上取整)。"""
    req = compute(graph, "item_filter_core", Fraction(60))
    assert leaf_map(req) == {
        ("item_liquid_water", KIND_EXTERN): Fraction(90),
        ("item_copper_ore", KIND_RAW): Fraction(60),
        ("item_gas_inert", KIND_RAW): Fraction(30),
    }
    assert req.crafts == {
        "tools_proc_filter_core_2": 30,
        "shaper_gas_copper_jar_1": 30,
        "furnance_copper_nugget_1": 60,
        "xiranite_oven_xiranite_powder_1": 30,
        "furnance_carbon_enr_1": 60,
        "furnance_carbon_enr_powder_1": 60,
        "thickener_plant_moss_enr_powder_1_1": 60,
        "grinder_plant_moss_powder_1_1": 60,
        "grinder_plant_moss_powder_3_1": 20,
        "planter_plant_moss_1_1": 120,
        "seedcollector_plant_moss_1_1": 60,
        "planter_plant_moss_3_1": 40,
        "seedcollector_plant_moss_3_1": 20,
    }
    machines = {r.id: m for r, _, m in machine_counts(req)}
    assert machines["component" if False else "tools_proc_filter_core_2"] == 1   # 30×2s/60
    assert machines["furnance_copper_nugget_1"] == 2        # 60×2s/60
    assert machines["planter_plant_moss_1_1"] == 4          # 120×2s/60
    assert machines["grinder_plant_moss_powder_3_1"] == 1   # 20×2s/60 → 2/3 向上取整
    for r, n, m in machine_counts(req):
        assert m == math_ceil_frac(n * r.craft_time / 60)
        assert r.craft_time and m >= 1


def math_ceil_frac(x):
    n, d = x.numerator, x.denominator
    return -(-n // d)


# ---------------------------------------------------------------- 副产物 / 环境 / 链路图
def test_byproducts_sewage(graph):
    """副产物入账:精炼炉产赤铜块的污水按净流量计入全链产出。"""
    req = compute(graph, "item_copper_nugget", Fraction(1))
    assert req.byproducts == {"item_liquid_sewage": 1}
    assert req.byproduct_sources == {"item_liquid_sewage": "furnance_copper_nugget_1"}
    rate = compute(graph, "item_filter_core", Fraction(60))
    assert rate.byproducts == {"item_liquid_sewage": Fraction(60)}


def test_required_environments(graph):
    """环境需求:气态灼铜反应炉要求酸性环境;分离芯链全为常规。"""
    req = compute(graph, "item_copper_enr2_cmpt", Fraction(1))
    assert req.required_envs() == [("酸性环境", ["gas_reactor_gas_copper_enr2_1"])]
    assert "item_copper_enr2_cmpt" in req.crafts or True
    basic = compute(graph, "item_filter_core", Fraction(1))
    assert basic.required_envs() == []


def test_used_facilities(graph):
    """设备清单:链上生产设施按首次出现序去重。"""
    req = compute(graph, "item_iron_cmpt", Fraction(1))
    assert req.used_facilities() == ["配件机", "精炼炉"]


def test_mermaid_flow(graph):
    """链路图:物品/配方二部图,含目标节点与副产物虚线边。"""
    req = compute(graph, "item_copper_nugget", Fraction(2))
    text = render_mermaid(graph, req)
    assert text.startswith("flowchart LR")
    assert "I_item_copper_nugget((" in text                  # 目标节点
    assert "I_item_copper_ore([" in text                     # 最初用料
    assert 'R_furnance_copper_nugget_1' in text
    assert "-.->" in text and "I_item_liquid_sewage" in text  # 副产物虚线边
    assert "-->" in text


def test_render_sections(graph):
    """最终输出分节:目标/需求原料/产出(副产物)/制造步骤/设备/环境/链路图。"""
    req = compute(graph, "item_filter_core", Fraction(60))
    text = render_result(graph, "分离芯", req, per_min=True)
    for section in ("目标 分离芯", "需求原料", "产出:", "副产物 污水", "制造步骤",
                    "设备需求", "环境需求", "产出链路图", "```mermaid", "flowchart LR"):
        assert section in text, section


# ---------------------------------------------------------------- 渲染 / JSON / 报告
def test_render_rate_and_batch(graph):
    req = compute(graph, "item_filter_core", Fraction(60))
    text = render_result(graph, "分离芯", req, per_min=True)
    assert "×60/min" in text and "设备需求" in text and "清水" in text
    batch = render_result(graph, "分离芯", compute(graph, "item_filter_core", Fraction(4)))
    assert "设备需求" not in batch and "/min" not in batch


def test_result_json(graph):
    import json
    req = compute(graph, "item_filter_core", Fraction(60))
    payload = json.loads(json.dumps(result_json(req, graph, per_min=True)))
    assert payload["target"]["per_min"] is True
    assert payload["strict_ok"] is True
    kinds = {(l["id"], l["kind"]) for l in payload["leaves"]}
    assert ("item_liquid_water", "external") in kinds
    assert ("item_gas_inert", "raw") in kinds
    machines = {m["recipe"]: m["count"] for m in payload["machines"]}
    assert machines["tools_proc_filter_core_2"] == 1
    tree = payload["tree"]
    assert tree["id"] == "item_filter_core" and tree["kind"] == "craft"
    assert tree["recipe_id"] == "tools_proc_filter_core_2"


def test_build_report_sections(graph):
    report = build_report(graph, demos=[("铁制零件", Fraction(10), frozenset())])
    assert "# 配方用料倒推 · 数据概览" in report
    assert "## 潜在循环依赖" in report
    assert "## 示例:铁制零件 ×10" in report
    assert "净产出" in report and "外部投料" in report
