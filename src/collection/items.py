"""采集+初步处理(多数据源综合):物品数据集 → data/items/ 目录。

目录按物品类型的 EN slug 分层(如 currency、engraved_medal),条目 typeName
跟随默认语言(--lang);index.json 为按类型分组的 id 清单(纯清单,无内容)。
图标只存 iconId 裸 id,站点 URL 由 JS 构建(node web/build.mjs)注入。

数据来源与贡献:
    - rmxlinux/EndfieldData@TableCfg(本地 git):身份、类型、稀有度、描述、图标
      (ItemTable × ItemTypeTable × I18nTextTable_CN/EN,typeName 用默认语言,
      typeSlug 用 EN)
    - rmxlinux@TableCfg 配方关联统计(直读原始表,不经 recipes 数据集):
      FactoryManualCraftTable / FactoryMachineCraftTable / SpaceshipManufactureFormulaTable
      → usedInRecipes(作原料)/ producedBy(作产物),按站点 manual/machine/spaceship 计数
    - 获取途径:ItemTable.obtainWayIds → SystemJumpTable(游戏内跳转表)desc 经 i18n 反查
    - 交易/价值:FactoryItemTable.value → factoryValue;据点收购(SettlementBasicDataTable
      settlementTradeItemMap,按 据点×等级×物品)→ settlementTrades,同报价合并据点去重;
      活动叠加援助券(ActivityLimitedFormulaSettlementTable tradeList)→ activityCoupons,
      保留 活动→券额→适用据点 耦合
"""

from __future__ import annotations

from tools.tables import I18n, dump_dir, i18n_table, load_tables, slugify

PRODUCT = "items"

REQUIRED_TABLES = [
    "ItemTable", "ItemTypeTable", "I18nTextTable_CN", "I18nTextTable_EN",
    "FactoryManualCraftTable", "FactoryMachineCraftTable",
    "SpaceshipManufactureFormulaTable", "SystemJumpTable",
    "FactoryItemTable", "SettlementBasicDataTable", "ActivityLimitedFormulaSettlementTable",
]

STATIONS = ("manual", "machine", "spaceship")


def _side_item_ids(entries: list[dict]) -> set[str]:
    """配方一侧条目 → 涉及的物品 ID 集合(条目形如 {id, count})。

    机器配方的 group 是同槽原料(游戏内同时消耗,非可替代项),组员逐一计入:
    每个组员都算参与这一条配方。同一条配方内同一物品只计一次(按配方计数)。
    """
    ids: set[str] = set()
    for e in entries or []:
        if "group" in e:
            ids.update(o.get("id") for o in e["group"])
        else:
            ids.add(e.get("id"))
    ids.discard(None)
    return ids


def collect_recipe_stats(raw: dict) -> tuple[dict, dict]:
    """统计物品的配方关联(直读三张配方原始表)。

    返回 (used, produced):{item_id: {station: 配方数}}。
        - used:    物品作为原料(ingredients)出现的配方数
        - produced:物品作为产物(outcomes / outcomeItemId)出现的配方数
    飞船制造表(SpaceshipManufactureFormulaTable)只登记产物,无原料侧。
    """
    used = {s: {} for s in STATIONS}
    produced = {s: {} for s in STATIONS}

    def add(side: str, station: str, ids: set[str]) -> None:
        target = used if side == "ingredients" else produced
        per = target[station]
        for iid in ids:
            per[iid] = per.get(iid, 0) + 1

    for r in raw["FactoryManualCraftTable"].values():
        add("ingredients", "manual", _side_item_ids(r.get("ingredients")))
        add("outcomes", "manual", _side_item_ids(r.get("outcomes")))
    for r in raw["FactoryMachineCraftTable"].values():
        add("ingredients", "machine", _side_item_ids(r.get("ingredients")))
        add("outcomes", "machine", _side_item_ids(r.get("outcomes")))
    for r in raw["SpaceshipManufactureFormulaTable"].values():
        oid = r.get("outcomeItemId")
        if oid:
            add("outcomes", "spaceship", {oid})
    return used, produced


def _stat_view(per_item: dict, iid: str) -> dict | None:
    """单物品站点计数 → {"total": n, "manual": n, "machine": n, "spaceship": n};无关联返回 None。"""
    if iid not in per_item["manual"] and iid not in per_item["machine"] and iid not in per_item["spaceship"]:
        return None
    m, mc, sp = (per_item[s].get(iid, 0) for s in STATIONS)
    return {"total": m + mc + sp, "manual": m, "machine": mc, "spaceship": sp}


def collect_trade_prices(raw: dict) -> tuple[dict, dict, dict]:
    """统计物品的交易/价值(直读原始表,不经其他数据集)。

    返回 (factory_value, trades, coupons):
        - factory_value: {item_id: FactoryItemTable.value}(生产/回收基准价值)
        - trades: {item_id: [{"settlements": [...], "money": 调度券, "stmExp": 据点经验}]}
          SettlementBasicDataTable 按 据点×等级×物品 收购,同(调度券,经验)报价合并据点去重
        - coupons: {item_id: {活动id: {"moneyCount": 援助成果券, "settlements": [...]}}}
          ActivityLimitedFormulaSettlementTable 活动期叠加券;同一活动同一物品券额
          取登记值(当前各据点一致),保留 活动→券额→适用据点 耦合
    """
    factory_value = {iid: f.get("value") for iid, f in raw["FactoryItemTable"].items()
                     if f.get("value") is not None}
    trade: dict[str, dict[tuple, set[str]]] = {}
    for stm, v in raw["SettlementBasicDataTable"].items():
        for lv in (v.get("settlementLevelMap") or {}).values():
            for iid, e in (lv.get("settlementTradeItemMap") or {}).items():
                trade.setdefault(iid, {}).setdefault(
                    (e.get("rewardMoneyCount"), e.get("stmExp")), set()).add(stm)
    trades = {iid: [{"settlements": sorted(stms), "money": money, "stmExp": exp}
                    for (money, exp), stms in sorted(offers.items())]
              for iid, offers in trade.items()}
    coupons: dict[str, dict[str, dict]] = {}
    for aid, av in raw["ActivityLimitedFormulaSettlementTable"].items():
        for stm, sv in (av.get("settlementList") or {}).items():
            for iid, e in (sv.get("tradeList") or {}).items():
                c = coupons.setdefault(iid, {}).setdefault(
                    aid, {"moneyCount": e.get("moneyCount"), "settlements": []})
                if stm not in c["settlements"]:
                    c["settlements"].append(stm)
    for by_act in coupons.values():
        for entry in by_act.values():
            entry["settlements"].sort()
    return factory_value, trades, coupons


def build(raw: dict, t: I18n) -> list[dict]:
    type_names = {v.get("itemType"): t(v.get("name")) for v in raw["ItemTypeTable"].values()}
    # EN 名称仅用于目录 slug(目录名对文件系统/URL 友好),不替代中文 typeName
    t_en = I18n(raw["I18nTextTable_EN"])
    type_slugs = {v.get("itemType"): slugify(t_en(v.get("name")), f"type_{v.get('itemType')}")
                  for v in raw["ItemTypeTable"].values()}
    used, produced = collect_recipe_stats(raw)
    factory_value, trades, coupons = collect_trade_prices(raw)
    # 获取途径:obtainWayIds → SystemJumpTable desc(游戏内"获取途径"文案即取此处)
    obtain_desc = {oid: t(cfg.get("desc")) for oid, cfg in raw["SystemJumpTable"].items()}

    items = []
    for iid, it in raw["ItemTable"].items():
        # 多个跳转条目文案可能相同(不同跳转目标),保序去重
        obtain_ways = list(dict.fromkeys(
            obtain_desc[o] for o in it.get("obtainWayIds") or [] if obtain_desc.get(o)))
        items.append({
            "id": iid,
            "name": t(it.get("name")),
            "type": it.get("type"),
            "typeSlug": type_slugs.get(it.get("type")),
            "typeName": type_names.get(it.get("type")),
            "rarity": it.get("rarity"),
            "showingType": it.get("showingType"),
            "desc": t(it.get("desc")),
            "icon": it.get("iconId"),
            "obtainWays": obtain_ways or None,
            "factoryValue": factory_value.get(iid),
            "settlementTrades": trades.get(iid) or None,
            "activityCoupons": coupons.get(iid) or None,
            "usedInRecipes": _stat_view(used, iid),
            "producedBy": _stat_view(produced, iid),
        })
    items.sort(key=lambda x: (str(x["showingType"] or ""), -(x["rarity"] or 0), x["id"]))
    return items


def write(payload: list[dict]) -> None:
    """每件物品一个独立文件,按类型 EN slug 子目录存放(typeSlug 字段 = 子目录名)。

    index.json 只是清单:按 typeSlug 分组的物品 id 列表;描述/获取途径/配方关联
    等一切内容都在子文件里,不在索引中重复。
    """
    def finalize(_rows: list, entries: list[dict]) -> dict:
        grouped: dict[str, list] = {}
        for e in entries:
            grouped.setdefault(e["typeSlug"], []).append(e["id"])
        return dict(sorted(grouped.items()))

    dump_dir(PRODUCT, payload, subdir=lambda e: e["typeSlug"],
             index_map=lambda e: e["id"], index_finalize=finalize)


def main(force: bool = False) -> None:
    raw = load_tables(REQUIRED_TABLES, force=force)
    write(build(raw, I18n(raw[i18n_table()])))


if __name__ == "__main__":
    main()
