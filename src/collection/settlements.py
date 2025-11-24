"""采集+初步处理:据点数据集 → data/settlements/ 目录。

来源表:SettlementBasicDataTable × SettlementTagTable(驻留加成标签)
        × ItemTable(交易物品命名) × I18nTextTable_CN
        × ActivityLimitedFormulaSettlementTable(活动期叠加援助券)
目录:data/settlements/<settlementId>.json(条目少,平铺不分层),
      index.json 为 id 清单。
条目:身份(名称/所属地块/颜色) + wantTags(驻留干员标签→收益加成) +
      levels(按等级登记的 带宽/建筑上限/资金上限与恢复周期/升级经验/推荐产物/描述,
      以及 trades 该等级收购列表:调度券 rewardMoneyCount/据点经验 stmExp,
      活动期叠加券 coupon 与券池活动 couponActivityId)。
"""

from __future__ import annotations

from tools.tables import I18n, dump_dir, i18n_table, load_tables

PRODUCT = "settlements"

REQUIRED_TABLES = ["SettlementBasicDataTable", "SettlementTagTable", "ItemTable",
                                 "I18nTextTable_CN", "ActivityLimitedFormulaSettlementTable"]


def build(raw: dict, t: I18n) -> list[dict]:
    item_name = {iid: t(it.get("name")) for iid, it in raw["ItemTable"].items() if t(it.get("name"))}
    # 活动叠加援助券:{(据点, 物品): {活动id, 券额}}
    coupon = {}
    for aid, av in raw["ActivityLimitedFormulaSettlementTable"].items():
        for stm, sv in (av.get("settlementList") or {}).items():
            for iid, e in (sv.get("tradeList") or {}).items():
                coupon[(stm, iid)] = {"activityId": aid, "moneyCount": e.get("moneyCount")}
    tag_rows = raw["SettlementTagTable"]

    out = []
    for stm, v in raw["SettlementBasicDataTable"].items():
        want_tags = []
        for tid in v.get("wantTagIdGroup") or []:
            c = tag_rows.get(tid) or {}
            want_tags.append({
                "id": tid,
                "name": t(c.get("settlementTagName")) or None,
                "desc": t(c.get("desc")) or None,
                "charTags": c.get("enhanceCharTagId") or None,
                "expRate": c.get("enhanceExpProfitRate") or None,
                "moneyRate": c.get("enhanceMoneyProfitRate") or None,
                "produceSpeedRate": c.get("enhanceMoneyProduceSpeedRate") or None,
            })
        levels = []
        level_map = v.get("settlementLevelMap") or {}
        for lv_id in sorted(level_map, key=int):
            lv = level_map[lv_id]
            trades = []
            for iid, e in (lv.get("settlementTradeItemMap") or {}).items():
                row = {"itemId": iid, "name": item_name.get(iid),
                       "money": e.get("rewardMoneyCount"), "stmExp": e.get("stmExp")}
                if e.get("activityId"):
                    row["activityId"] = e["activityId"]
                cp = coupon.get((stm, iid))
                if cp:
                    row["coupon"] = cp["moneyCount"]
                    row["couponActivityId"] = cp["activityId"]
                trades.append(row)
            trades.sort(key=lambda r: (r["money"], r["itemId"]))
            levels.append({
                "level": int(lv_id),
                "bandwidth": lv.get("bandwidth"),
                "battleBuildingLimit": lv.get("battleBuildingLimit"),
                "travelPoleLimit": lv.get("travelPoleLimit"),
                "moneyMax": lv.get("moneyMax"),
                "moneyPeriod": lv.get("moneyPeriod"),
                "levelUpExp": lv.get("levelUpExp"),
                "isFinalMaxLevel": lv.get("isFinalMaxLevel"),
                "recoItemId": lv.get("recoItemId") or None,
                "recoItemName": item_name.get(lv.get("recoItemId")),
                "desc": t(lv.get("desc")) or None,
                "trades": trades or None,
            })
        out.append({
            "id": stm,
            "name": t(v.get("settlementName")) or None,
            "domainId": v.get("domainId"),
            "domainLevelId": v.get("domainLevelId"),
            "facRegionIndex": v.get("facRegionIndex"),
            "color": v.get("settlementColor"),
            "wantTags": want_tags or None,
            "levels": levels,
        })
    out.sort(key=lambda s: s["id"])
    return out


def write(payload: list[dict]) -> None:
    """条目少,平铺:每据点一个文件 + index.json(id 清单)。"""
    dump_dir(PRODUCT, payload, index_map=lambda e: e["id"])


def main(force: bool = False) -> None:
    raw = load_tables(REQUIRED_TABLES, force=force)
    write(build(raw, I18n(raw[i18n_table()])))


if __name__ == "__main__":
    main()
