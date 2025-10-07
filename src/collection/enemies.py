"""采集+初步处理:敌人数据集 → data/processed/enemies.json。

来源表:EnemyTable × EnemyDisplayInfoTable × EnemyAttributeTemplateTable × I18nTextTable_CN
产物:精英标记、初始霸体、韧性、五系抗性(统一为减伤比例)、满级生命/攻击/防御。
"""

from __future__ import annotations

from collection.common import I18n, attr_map, dump, load_raw_tables

PRODUCT = "enemies"


def build(raw: dict, t: I18n) -> list[dict]:
    display = raw["EnemyDisplayInfoTable"]
    enemies = []
    for eid, e in raw["EnemyTable"].items():
        d = display.get(eid, {})
        template = raw["EnemyAttributeTemplateTable"].get(e.get("attrTemplateId"), {})
        curve = template.get("levelDependentAttributes") or []
        lv_max = attr_map(curve[-1:]) if curve else {}
        # 抗性:新版是具名百分数字段(0-100),旧版是 *ResistScalar(受伤倍率);
        # 统一归一化为「减伤比例」0-1 输出
        resists = {}
        for k, v in template.items():
            if k.endswith("Resistance") and isinstance(v, (int, float)) and v:
                resists[k.replace("Resistance", "")] = v / 100
            elif k.endswith("ResistScalar") and isinstance(v, (int, float)) and v != 1:
                resists[k.replace("DmgResistScalar", "")] = 1 - v
        enemies.append({
            "id": eid,
            "templateId": e.get("templateId") or d.get("templateId"),
            # 解包表中敌人显示名哈希均为 0,名字暂以 templateId 兜底,待接入森空岛 Wiki「威胁」分区补全
            "name": t(d.get("name")) or t(d.get("nickname")) or e.get("templateId"),
            "dangerous": e.get("isDangerous", False),
            "superArmor": template.get("initialSuperArmor"),
            "maxResilience": template.get("maxResilience"),
            "resists": resists,
            "lvMax": {k: lv_max.get(k) for k in ("MaxHp", "Atk", "Def") if lv_max.get(k) is not None},
        })
    enemies.sort(key=lambda x: x["id"])
    return enemies


def main() -> None:
    raw = load_raw_tables()
    dump(PRODUCT, build(raw, I18n(raw["I18nTextTable_CN"])))


if __name__ == "__main__":
    main()
