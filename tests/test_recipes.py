"""配方采集(recipes.build)全字段保留单元测试。

覆盖:加工字段形态替换(i18n 反查、原料产物解析、设施中文名、产物合并、机器运行
消耗 machineConsume)、源表其余字段原样透传(gasEnv/buffers/itemId/level 等)、
上游新增字段自动进入数据集、机器配方不再输出源表中不存在的 rarity。

运行:poetry run pytest tests/ -q
"""

from collection.recipes import build
from tools.tables import I18n

I18N = {"123": "手工甲", "456": "沉积酸(灌装)"}

RAW = {
    "I18nTextTable_CN": I18N,
    "ItemTable": {
        "item_a": {"name": {"text": "甲"}},
        "item_b": {"name": {"text": "乙"}},
    },
    "FactoryCraftShowingTypeTable": {"1": {"name": {"text": "素材转化"}}},
    "FactoryBuildingTable": {"m_1": {"name": {"text": "灌装机"}},
                             "m_tr": {"name": {"text": "液气转化机"}}},
    "FactoryTransmuterTable": {
        "m_tr": {"consumeBindings": 2, "consumeItem": "item_b",
                 "consumeRate": 6, "consumeRateUpperLimit": 30, "id": "m_tr"},
    },
    "FactoryManualCraftTable": {
        "hand_1": {
            "craftFilterType": 0, "defaultUnlock": False, "domainId": "domain_1",
            "id": "hand_1",
            "ingredients": [{"count": 1, "id": "item_a"}],
            "itemId": "item_b",
            "name": {"id": 123},
            "outcomes": [{"count": 1, "id": "item_b"}],
            "rarity": 2, "showingType": 1, "sortId": 1,
            "brandNewField": {"v": 1},          # 上游新增字段
        },
    },
    "FactoryMachineCraftTable": {
        "mach_1": {
            "buffers": {"item_a": 0}, "formulaDesc": {"id": 456}, "formulaGroupId": "g1",
            "gasEnv": 1, "id": "mach_1",
            "ingredients": [{"group": [{"count": 1, "id": "item_a"},
                                       {"count": 2, "id": "item_b"}]}],
            "machineId": "m_1", "outcomes": [{"count": 1, "id": "item_b"}],
            "progressRound": 10, "signal": 0, "sortId": 1, "totalProgress": 60000,
        },
        "mach_2": {                              # 无 gasEnv → 默认 0(无要求)
            "formulaDesc": None, "formulaGroupId": "g1", "id": "mach_2",
            "ingredients": [], "machineId": "m_1", "outcomes": [],
            "progressRound": 1, "signal": 0, "sortId": 2, "totalProgress": 100,
        },
        "mach_3": {                              # 机器在 TransmuterTable → 带 machineConsume
            "formulaDesc": None, "formulaGroupId": "g2", "id": "mach_3",
            "ingredients": [], "machineId": "m_tr", "outcomes": [],
            "progressRound": 2, "signal": 0, "sortId": 3, "totalProgress": 12000,
        },
    },
    "SpaceshipManufactureFormulaTable": {
        "ship_1": {"id": "ship_1", "level": 2, "outcomeItemId": "item_b", "perCapacity": 3,
                   "rarity": 1, "roomAttrType": 16, "showingType": 1, "sortId": 1,
                   "totalProgress": 92000},
    },
}


def build_all():
    return {r["id"]: r for r in build(RAW, I18n(RAW["I18nTextTable_CN"]), calc={})}


def test_manual_fields():
    r = build_all()["hand_1"]
    assert r["station"] == "manual"
    assert r["name"] == "手工甲"                       # i18n 反查后的文本,非原始引用
    assert isinstance(r["name"], str)
    assert r["showingName"] == "素材转化"
    assert r["ingredients"] == [{"group": [{"id": "item_a", "name": "甲", "count": 1}]}]
    assert r["outcomes"] == [{"group": [{"id": "item_b", "name": "乙", "count": 1}]}]
    for k in ("craftFilterType", "defaultUnlock", "domainId", "rarity", "sortId"):
        assert r[k] == RAW["FactoryManualCraftTable"]["hand_1"][k]


def test_manual_new_upstream_field_passthrough():
    assert build_all()["hand_1"]["brandNewField"] == {"v": 1}


def test_machine_fields():
    r = build_all()["mach_1"]
    assert r["station"] == "machine"
    assert r["machineName"] == "灌装机"
    assert r["formulaDesc"] == "沉积酸(灌装)"          # i18n 反查,原始 {id} 引用不残留
    assert r["gasEnv"] == 1
    assert r["ingredients"] == [{"group": [
        {"id": "item_a", "name": "甲", "count": 1},
        {"id": "item_b", "name": "乙", "count": 2},
    ]}]
    for k in ("buffers", "formulaGroupId", "machineId", "progressRound",
              "signal", "sortId", "totalProgress"):
        assert r[k] == RAW["FactoryMachineCraftTable"]["mach_1"][k]
    assert "rarity" not in r                           # 机器源表无 rarity,不输出恒 null 的幽灵字段


def test_machine_gas_env_default():
    assert build_all()["mach_2"]["gasEnv"] == 0


def test_machine_consume_hit_and_miss():
    # machineId 命中 FactoryTransmuterTable:源表字段原样 + 消耗物中文名反查
    assert build_all()["mach_3"]["machineConsume"] == {
        "consumeItem": "item_b", "consumeItemName": "乙",
        "consumeRate": 6, "consumeRateUpperLimit": 30, "consumeBindings": 2,
    }
    # 未命中的机器配方不输出恒 null 的 machineConsume
    assert "machineConsume" not in build_all()["mach_1"]


def test_spaceship_fields():
    r = build_all()["ship_1"]
    assert r["station"] == "spaceship"
    assert r["ingredients"] == []
    assert r["outcomes"] == [{"group": [{"id": "item_b", "name": "乙", "count": 3}]}]
    for k in ("level", "rarity", "roomAttrType", "sortId", "totalProgress"):
        assert r[k] == RAW["SpaceshipManufactureFormulaTable"]["ship_1"][k]
