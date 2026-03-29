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
    - decoDesc:ItemTable.decoDesc 展示描述(潜能明信片/干员留影等收藏品的陈列文案)
    - 展示分类:ItemShowingTypeTable(物品专用枚举,与配方用的 FactoryCraftShowingTypeTable
      是两套体系)→ showingName/showingIcon;0 或未登记为 null
    - 交易/价值:FactoryItemTable.value → factoryValue;据点收购(SettlementBasicDataTable
      settlementTradeItemMap,按 据点×等级×物品)→ settlementTrades,同报价合并据点去重;
      活动叠加援助券(ActivityLimitedFormulaSettlementTable tradeList)→ activityCoupons,
      保留 活动→券额→适用据点 耦合
    - 用途细节:理智药剂/经验卡/赠礼/燃料/电池/种子/施肥/气液装灌/使用效果/战斗装备/
      随身装置/宝箱/周本收藏品/宝石/抽卡票券/货币 等 20+ 张表按物品 id join,
      每物品零到多个字段(实现见 collect_item_details)
"""

from __future__ import annotations

from tools.tables import I18n, dump_dir, i18n_table, load_tables, slugify

PRODUCT = "items"

REQUIRED_TABLES = [
    "ItemTable", "ItemTypeTable", "I18nTextTable_CN", "I18nTextTable_EN",
    "FactoryManualCraftTable", "FactoryMachineCraftTable",
    "SpaceshipManufactureFormulaTable", "SystemJumpTable",
    "FactoryItemTable", "SettlementBasicDataTable", "ActivityLimitedFormulaSettlementTable",
    "ItemShowingTypeTable",
    "RecoverApItemTable", "ExpItemDataMap", "GiftItemTable",
    "FactoryFuelItemTable", "FactoryBatteryItemTable", "FactorySeedItemTable", "FertilizeDataTable",
    "GasTable", "LiquidTable", "FullBottleTable", "EmptyBottleTable",
    "FullGasJarTable", "EmptyGasJarTable",
    "UseItemTable", "EquipItemTable", "ItemPortableDeviceTable",
    "UsableItemChestTable", "RewardTable",
    "WeekRaidItemTable", "WeekraidItemDomainTable",
    "GemItemDomainTable", "GemCustomizationBox", "GemItemId2TermPoolIdDataTable",
    "GachaLtTicket2PoolTable", "GachaWeaponLtTicket2PoolTable",
    "MoneyConfigTable", "MoneyExchangeTable",
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
            ids.update(oid for o in e["group"] if (oid := o.get("id")) is not None)
        else:
            eid = e.get("id")
            if eid is not None:
                ids.add(eid)
    return ids


def collect_recipe_stats(raw: dict) -> tuple[dict, dict]:
    """统计物品的配方关联(直读三张配方原始表)。

    返回 (used, produced):{item_id: {station: 配方数}}。
        - used:    物品作为原料(ingredients)出现的配方数
        - produced:物品作为产物(outcomes / outcomeItemId)出现的配方数
    飞船制造表(SpaceshipManufactureFormulaTable)只登记产物,无原料侧。
    """
    used: dict[str, dict[str, int]] = {s: {} for s in STATIONS}
    produced: dict[str, dict[str, int]] = {s: {} for s in STATIONS}

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


def collect_item_details(raw: dict, t: I18n) -> dict[str, dict]:
    """采集物品的用途/行为细节(每表按物品 id join,无关联的物品不产出字段)。

    返回 {item_id: {字段: 值}},由 build 并入条目。覆盖:
        - apRecover:理智药剂回复量(RecoverApItemTable)
        - exp:经验卡经验值 {gain, type}(ExpItemDataMap)
        - gift:干员赠礼好感 {favor, tags, preferTag, popular}(GiftItemTable)
        - fuel/batteryEnergy/seed/fertilize:燃料热值/电池容量/种子生长/施肥(Factory*)
        - fluid:气液装灌映射 kind=liquid|gas|fullBottle|fullJar|emptyBottle|emptyJar
          (GasTable × LiquidTable × Full·EmptyBottle·GasJarTable,官方瓶/罐对应关系)
        - useEffect:使用效果(UseItemTable,useActions 的 buff 黑板按 {key: value} 摊平)
        - battleEquip:战斗装备物品实战参数(EquipItemTable,与随身装置两表物品不相交)
        - device:随身装置(ItemPortableDeviceTable)
        - chest:宝箱/自选包(UsableItemChestTable,rewardIdList 经 RewardTable 展开物品清单)
        - weekraid:周本收藏品转换与所属区域(WeekRaidItemTable × WeekraidItemDomainTable)
        - gemDomain/gemBox:宝石物品地块、定制箱(含所引宝石的词条池;宝石本体
          item_gem_* 不在 ItemTable,词条池信息随定制箱收录)(Gem*)
        - gachaPools:抽卡票券适用卡池(GachaLtTicket2PoolTable × GachaWeaponLtTicket2PoolTable)
        - money/moneyExchanges:货币清规则与兑换率(MoneyConfigTable × MoneyExchangeTable)
    """
    detail: dict[str, dict] = {}

    def put(iid, key, value):
        if value is not None:
            detail.setdefault(iid, {})[key] = value

    for iid, e in raw["RecoverApItemTable"].items():
        put(iid, "apRecover", e.get("apRecoverValue"))
    for iid, e in raw["ExpItemDataMap"].items():
        put(iid, "exp", {"gain": e.get("expGain"), "type": e.get("expType")})
    for iid, e in raw["GiftItemTable"].items():
        gift = {"favor": e.get("favorablePoint"), "tags": e.get("tagList") or None,
                "preferTag": e.get("giftPreferTag") or None}
        if e.get("isPopular"):
            gift["popular"] = True
        put(iid, "gift", gift)
    for iid, e in raw["FactoryFuelItemTable"].items():
        put(iid, "fuel", {"energy": e.get("fuelEnergy"), "power": e.get("powerProvide")})
    for iid, e in raw["FactoryBatteryItemTable"].items():
        put(iid, "batteryEnergy", e.get("BatteryEnergy"))
    for iid, e in raw["FactorySeedItemTable"].items():
        put(iid, "seed", {"growTotalProgress": e.get("growTotalProgress")})
    for iid, e in raw["FertilizeDataTable"].items():
        put(iid, "fertilize", {"type": e.get("fertilizeType"), "time": e.get("fertilizeTime")})

    for iid, e in raw["LiquidTable"].items():
        put(iid, "fluid", {"kind": "liquid",
                           "emptyBottles": e.get("emptyBottleItems") or None,
                           "fullBottles": e.get("fullBottleItems") or None})
    for iid, e in raw["GasTable"].items():
        put(iid, "fluid", {"kind": "gas",
                           "emptyJars": e.get("emptyGasJarItems") or None,
                           "fullJars": e.get("fullGasJarItems") or None})
    for iid, e in raw["FullBottleTable"].items():
        put(iid, "fluid", {"kind": "fullBottle", "liquidId": e.get("liquidId"),
                           "capacity": e.get("liquidCapacity"),
                           "emptyBottleId": e.get("emptyBottleId")})
    for iid, e in raw["FullGasJarTable"].items():
        put(iid, "fluid", {"kind": "fullJar", "gasId": e.get("gasId"),
                           "capacity": e.get("gasCapacity"),
                           "emptyJarId": e.get("emptyJarId")})
    for iid, e in raw["EmptyBottleTable"].items():
        put(iid, "fluid", {"kind": "emptyBottle", "capacity": e.get("liquidCapacity"),
                           "liquids": e.get("liquidItems") or None,
                           "fullBottles": e.get("fullBottleItems") or None})
    for iid, e in raw["EmptyGasJarTable"].items():
        put(iid, "fluid", {"kind": "emptyJar", "capacity": e.get("gasCapacity"),
                           "gases": e.get("gasItems") or None,
                           "fullJars": e.get("fullGasJarItems") or None})

    def blackboard(bb: list[dict] | None) -> dict:
        return {b["key"]: b.get("valueStr") or b.get("value") for b in bb or [] if b.get("key")}

    for iid, e in raw["UseItemTable"].items():
        actions = []
        for a in e.get("useActions") or []:
            act: dict = {"useType": a.get("useType")}
            buff = a.get("buffBBData") or {}
            if buff.get("buffId"):
                act["buffId"] = buff["buffId"]
                act["blackboard"] = blackboard(buff.get("blackboard"))
            skill = a.get("skillBBData") or {}
            if skill.get("skillId"):
                act["skillId"] = skill["skillId"]
                act["skillPath"] = skill.get("skillPath") or None
            actions.append(act)
        put(iid, "useEffect", {"duration": e.get("duration"), "effectType": e.get("effectType"),
                               "persistent": e.get("isPersistentBuff") or None,
                               "useDesc": t(e.get("itemUseDesc")) or None,
                               "actions": actions or None})
    for iid, e in raw["EquipItemTable"].items():
        cond = ({"type": e.get("condType"), "params": e.get("condParams")}
                if e.get("condType") is not None else None)
        put(iid, "battleEquip", {"castTime": e.get("castTime"), "chargeCount": e.get("chargeCount"),
                                 "cooldown": e.get("cooldown"), "recoverTime": e.get("recoverTime"),
                                 "levelUpChargeCount": e.get("levelUpChargeCount") or None,
                                 "cond": cond,
                                 "desc": t(e.get("equipDesc")) or None,
                                 "extraDesc": t(e.get("equipExtraDesc")) or None})
    for iid, e in raw["ItemPortableDeviceTable"].items():
        put(iid, "device", {"type": e.get("type"), "isMainDevice": e.get("isMainDevice") or None,
                            "lv": e.get("lv"), "nextLvItemId": e.get("nextLvItemId") or None})

    reward_table = raw["RewardTable"]

    def reward_view(rid: str) -> dict | None:
        r = reward_table.get(rid)
        if not r:
            return None
        return {"items": [{"id": b.get("id"), "count": b.get("count")}
                          for b in r.get("itemBundles") or []] or None,
                "probItems": [{"id": b.get("id"), "count": b.get("count")}
                              for b in r.get("probItemBundles") or []] or None}

    for iid, e in raw["UsableItemChestTable"].items():
        rewards = [v for v in (reward_view(r) for r in e.get("rewardIdList") or []) if v]
        randoms = [{"id": i, "count": c} for i, c in zip(e.get("randomChestItemIds") or [],
                                                         e.get("randomChestItemCounts") or [], strict=False)]
        put(iid, "chest", {"type": e.get("type"), "rewards": rewards or None,
                           "random": randoms or None,
                           "selectedCount": e.get("selectedCount") or None})

    for iid, e in raw["WeekRaidItemTable"].items():
        w = {k: v for k, v in (("convertItemId", e.get("convertItemId") or None),
                               ("convertGoldId", e.get("convertGoldId") or None),
                               ("convertGoldNum", e.get("convertGoldNum") or None)) if v}
        if w:
            put(iid, "weekraid", w)
    for iid, region in raw["WeekraidItemDomainTable"].items():
        detail.setdefault(iid, {}).setdefault("weekraid", {})["region"] = region

    for iid, dom in raw["GemItemDomainTable"].items():
        put(iid, "gemDomain", dom)
    gem_term_pools: dict[str, dict | None] = {}
    for iid, e in raw["GemItemId2TermPoolIdDataTable"].items():
        pools = {f"term{i}": e.get(f"termPoolId{i}") for i in (1, 2, 3) if e.get(f"termPoolId{i}")}
        gem_term_pools[iid] = pools or None
    for iid, e in raw["GemCustomizationBox"].items():
        types = {f"term{i}": e.get(f"term{i}Type") for i in (1, 2, 3) if e.get(f"term{i}Type")}
        put(iid, "gemBox", {"gemItemId": e.get("gemItemId"),
                            "lockedTermCount": e.get("lockedTermCount"),
                            "termTypes": types or None,
                            # 宝石本体(item_gem_*)不在 ItemTable,词条池随定制箱收录
                            "termPools": gem_term_pools.get(e.get("gemItemId"))})

    for iid, e in raw["GachaLtTicket2PoolTable"].items():
        put(iid, "gachaPools", e.get("poolIdList") or None)
    for iid, e in raw["GachaWeaponLtTicket2PoolTable"].items():
        pool_ids = [d.get("gachaPoolId") for d in e.get("poolDataList") or [] if d.get("gachaPoolId")]
        put(iid, "gachaPools", pool_ids or None)

    for iid, e in raw["MoneyConfigTable"].items():
        put(iid, "money", {"clearRule": e.get("clearRule"), "clearLimit": e.get("MoneyClearLimit")})
    for e in raw["MoneyExchangeTable"].values():
        detail.setdefault(e.get("sourceMoneyId"), {}).setdefault(
            "moneyExchanges", []).append({"targetMoneyId": e.get("targetMoneyId"),
                                          "cost": e.get("sourceMoneyCost"),
                                          "minSwap": e.get("sourceMoneyMinSwap"),
                                          "get": e.get("targetMoneyGet")})
    return detail


def _int_or_none(v):
    """showingType 兼容旧镜像字符串枚举:数字串转 int,其余 None(0/未登记查不到 → null)。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build(raw: dict, t: I18n) -> list[dict]:
    type_names = {v.get("itemType"): t(v.get("name")) for v in raw["ItemTypeTable"].values()}
    # EN 名称仅用于目录 slug(目录名对文件系统/URL 友好),不替代中文 typeName
    t_en = I18n(raw["I18nTextTable_EN"])
    type_slugs = {v.get("itemType"): slugify(t_en(v.get("name")), f"type_{v.get('itemType')}")
                  for v in raw["ItemTypeTable"].values()}
    used, produced = collect_recipe_stats(raw)
    factory_value, trades, coupons = collect_trade_prices(raw)
    details = collect_item_details(raw, t)
    # 物品展示分类:showingType → (名称, 枚举图标);键 int/str 双收,兼容旧镜像字符串枚举
    showing = {}
    for k, v in raw["ItemShowingTypeTable"].items():
        showing[int(k)] = (t(v.get("name")), v.get("icon"))
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
            "showingName": showing.get(_int_or_none(it.get("showingType")), (None, None))[0],
            "showingIcon": showing.get(_int_or_none(it.get("showingType")), (None, None))[1],
            "desc": t(it.get("desc")),
            "decoDesc": t(it.get("decoDesc")) or None,
            "icon": it.get("iconId"),
            "obtainWays": obtain_ways or None,
            "factoryValue": factory_value.get(iid),
            "settlementTrades": trades.get(iid) or None,
            "activityCoupons": coupons.get(iid) or None,
            **(details.get(iid) or {}),
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
