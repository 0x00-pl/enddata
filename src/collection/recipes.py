"""采集+初步处理:生产配方数据集 → data/recipes/ 目录(按分类分 子目录)。

来源表:FactoryManualCraftTable × FactoryMachineCraftTable × SpaceshipManufactureFormulaTable
        × ItemTable(原料/产物命名) × I18nTextTable_CN
        × FactoryCraftShowingTypeTable(展示分类中文名:精制食药/应急食药/…)
        × FactoryBuildingTable(生产设施中文名:灌装机/拆解机/…)
        × FactoryTransmuterTable(转化机运行消耗:液/气稀晶质,按 machineId join)
        × JamboChen/endfield-calc(本地 git:制造耗时 craftingTime 与生产设施 facilityId;
          其 recipes.ts 里的 RecipeId/ItemId/FacilityId 常量展开后与 rmxlinux TableCfg
          是同一套小写游戏 ID,可直接按配方 ID join)
分类:手工/飞船配方带 showingType(→ showingName 中文名),手工另有 craftFilterType
      (0=普通手工,素材转化按 1/2/3 细分)与配方名 name;机器配方无 showingType,
      以生产设施为分类(machineName),并带 formulaDesc/formulaGroupId 配方组。
全字段保留:条目先落加工/派生字段(名称反查、原料产物解析、设施中文名、转化机运行
      消耗 machineConsume),再把源表其余字段原样透传(机器 gasEnv/buffers/progressRound/
      totalProgress/signal、手工 defaultUnlock/itemId、飞船 level/roomAttrType/totalProgress
      等)——上游新增字段不需要改本模块即自动进入数据集,不会因白名单遗漏而丢字段。
目录:data/recipes/<station>/<recipeId>.json(manual/machine/spaceship),
      展示分类与设施等字段保留在条目与索引中,不做目录层级。
"""

from __future__ import annotations

import re

from tools.datasource import info, read_from_git
from tools.tables import I18n, dump_dir, i18n_table, load_tables

PRODUCT = "recipes"

REQUIRED_TABLES = ["FactoryManualCraftTable", "FactoryMachineCraftTable",
                                 "SpaceshipManufactureFormulaTable", "ItemTable", "I18nTextTable_CN",
                                 "FactoryCraftShowingTypeTable", "FactoryBuildingTable",
                                 "FactoryTransmuterTable"]

CALC_REPO = "JamboChen/endfield-calc"
CALC_CONSTANTS_TS = "src/types/constants.ts"  # RecipeId/ItemId/FacilityId 常量 → 字符串值
CALC_RECIPES_TS = "src/data/recipes.ts"


def load_calc_recipes() -> dict[str, dict]:
    """加载 endfield-calc 配方(制造耗时 + 生产设施),返回 {配方ID: {craftTimeSec, facility}}。

    第三方仓库文件缺失或解析失败时返回 {},不影响主流程(字段整体留空)。
    """
    try:
        constants_ts = read_from_git(CALC_REPO, CALC_CONSTANTS_TS)
        recipes_ts = read_from_git(CALC_REPO, CALC_RECIPES_TS)
        if not constants_ts or not recipes_ts:
            info(f"  endfield-calc 本地数据缺失(sources/{CALC_REPO.replace('/', '__')}),跳过耗时/设施补充")
            return {}
        consts = _const_map(constants_ts.decode("utf-8", errors="replace"))
        calc = _parse_calc_recipes(recipes_ts.decode("utf-8", errors="replace"), consts)
        if not calc:
            info("  endfield-calc 配方解析结果为空,跳过耗时/设施补充")
        return calc
    except Exception as e:  # noqa: BLE001 - 上游结构变化时静默降级
        info(f"  endfield-calc 解析失败({e}),跳过耗时/设施补充")
        return {}


def _const_map(constants_ts: str) -> dict[str, str]:
    """constants.ts 的各 `const X = { KEY: "value" } as const` 枚举块 → {KEY: value}。

    prettier 会把过长的字符串值折到下一行(KEY:\\n    "value"),`\\s*` 可同时兼容两种形态。
    """
    out: dict[str, str] = {}
    for block in re.findall(r"const \w+ = \{(.*?)\} as const", constants_ts, re.S):
        for m in re.finditer(r'^ {2}(\w+):\s*"([^"]+)",', block, re.M):
            out[m.group(1)] = m.group(2)
    return out


def _parse_calc_recipes(recipes_ts: str, consts: dict[str, str]) -> dict[str, dict]:
    """recipes.ts 条目 → {配方ID: {craftTimeSec, facility, inputs, outputs}}。

    条目形态固定:id: RecipeId.X / inputs|outputs: [{ itemId: ItemId.Y, amount: N }]
    / facilityId: FacilityId.Z / craftingTime: N;常量名经 constants.ts 还原为游戏 ID。
    """

    def num(text: str) -> int | float:
        v = float(text)
        return int(v) if v.is_integer() else v

    def side(body: str, tag: str) -> list[tuple[str, int | float]]:
        seg = re.search(rf"{tag}: \[(.*?)\]", body, re.S)
        if not seg:
            return []
        return [(consts.get(i, i), num(n))
                for i, n in re.findall(r"itemId: ItemId\.(\w+), amount: (\d+(?:\.\d+)?)", seg.group(1))]

    out: dict[str, dict] = {}
    chunks = re.split(r"id: RecipeId\.(\w+),", recipes_ts)
    for name, body in zip(chunks[1::2], chunks[2::2]):
        fac = re.search(r"facilityId: FacilityId\.(\w+)", body)
        ct = re.search(r"craftingTime: (\d+(?:\.\d+)?)", body)
        if not (fac and ct):
            continue
        out[consts.get(name, name)] = {
            "craftTimeSec": num(ct.group(1)),
            "facility": consts.get(fac.group(1), fac.group(1)),
            "inputs": side(body, "inputs"),
            "outputs": side(body, "outputs"),
        }
    return out


def build(raw: dict, t: I18n, calc: dict[str, dict] | None = None) -> list[dict]:
    item_name = {iid: t(it.get("name")) for iid, it in raw["ItemTable"].items() if t(it.get("name"))}
    # 展示分类中文名(手工/飞船按 showingType)与设施名(机器按 machineId)
    showing = {int(k): t(v.get("name")) for k, v in raw["FactoryCraftShowingTypeTable"].items()}
    building_name = {bid: t(b.get("name")) for bid, b in raw["FactoryBuildingTable"].items()}
    # 机器运行消耗(转化机烧稀晶质):源表字段原样 + 消耗物中文名,按 machineId join;
    # 仅命中的机器配方带 machineConsume,不输出恒 null 的幽灵字段。
    machine_consume = {}
    for mid, tr in raw.get("FactoryTransmuterTable", {}).items():
        machine_consume[mid] = {
            "consumeItem": tr.get("consumeItem"),
            "consumeItemName": item_name.get(tr.get("consumeItem")) or tr.get("consumeItem"),
            "consumeRate": tr.get("consumeRate"),
            "consumeRateUpperLimit": tr.get("consumeRateUpperLimit"),
            "consumeBindings": tr.get("consumeBindings"),
        }

    def resolve_side(entries: list[dict]) -> list[dict]:
        """原料/产物条目 → [{group:[{id,name}]}],与源表同名同构;机器配方的同组
        group 为同槽原料,游戏内同时消耗(如灌装=空瓶+溶液,非可替代项)。"""
        out = []
        for e in entries or []:
            if "group" in e:
                group = [{"id": o["id"], "name": item_name.get(o["id"]) or o["id"], "count": o.get("count", 1)}
                         for o in e["group"]]
            else:
                group = [{"id": e["id"], "name": item_name.get(e["id"]) or e["id"], "count": e.get("count", 1)}]
            out.append({"group": group})
        return out

    def merge_raw(src: dict, rec: dict, transformed: set[str]) -> dict:
        """源表未加工字段原样并入条目(transformed 里的字段已换成解析后的形态,不保留原形)。

        白名单只登记真正加工过的字段,其余(含上游新增,如机器表 gasEnv)一律透传,
        保证数据集不丢源表字段。
        """
        for k, v in src.items():
            if k not in transformed:
                rec[k] = v
        return rec

    recipes = []
    for rid, r in raw["FactoryManualCraftTable"].items():
        sh_name = showing.get(int(r["showingType"])) if r.get("showingType") is not None else None
        rec = {
            "id": rid, "station": "manual",
            "name": t(r.get("name")),
            "showingType": r.get("showingType"), "showingName": sh_name,
            "craftFilterType": r.get("craftFilterType"),
            "rarity": r.get("rarity"), "domainId": r.get("domainId"), "sortId": r.get("sortId"),
            "ingredients": resolve_side(r.get("ingredients")),
            "outcomes": resolve_side(r.get("outcomes")),
        }
        recipes.append(merge_raw(r, rec, {"name", "ingredients", "outcomes"}))
    for rid, r in raw["FactoryMachineCraftTable"].items():
        rec = {
            "id": rid, "station": "machine",
            "machineId": r.get("machineId"),
            "machineName": building_name.get(r.get("machineId")),
            "formulaGroupId": r.get("formulaGroupId"),
            "formulaDesc": t(r.get("formulaDesc")),
            "sortId": r.get("sortId"),
            "gasEnv": r.get("gasEnv", 0),   # 源表缺省补 0(无要求);有值时被 merge_raw 原值覆盖。1=稳定,2=湿润,3=酸性
            "ingredients": resolve_side(r.get("ingredients")),
            "outcomes": resolve_side(r.get("outcomes")),
        }
        consume = machine_consume.get(r.get("machineId"))
        if consume:
            rec["machineConsume"] = consume
        recipes.append(merge_raw(r, rec, {"formulaDesc", "ingredients", "outcomes"}))
    for rid, r in raw["SpaceshipManufactureFormulaTable"].items():
        sh_name = showing.get(int(r["showingType"])) if r.get("showingType") is not None else None
        rec = {
            "id": rid, "station": "spaceship",
            "showingType": r.get("showingType"), "showingName": sh_name,
            "rarity": r.get("rarity"), "sortId": r.get("sortId"),
            "ingredients": [],
            "outcomes": resolve_side([{"id": r["outcomeItemId"], "count": r.get("perCapacity", 1)}]),
        }
        recipes.append(merge_raw(r, rec, {"outcomeItemId", "perCapacity"}))

    # endfield-calc join:按配方 ID(两侧同为游戏小写 ID)补充制造耗时与生产设施;
    # calc 只有产线配方,手工/飞船配方预期不命中。数据缺失时字段整体留空,不影响主流程。
    calc = load_calc_recipes() if calc is None else calc
    hit = 0
    for r in recipes:
        c = calc.get(r["id"])
        r["craftTimeSec"] = c["craftTimeSec"] if c else None
        r["facility"] = c["facility"] if c else None
        hit += bool(c)
    if calc:
        info(f"  endfield-calc join: {hit}/{len(recipes)} 条配方补充 craftTimeSec/facility")
    return recipes


def write(payload: list[dict]) -> None:
    """每条配方一个独立文件,按站点子目录存放(manual/machine/spaceship)。

    index.json 只是清单:按站点分组的配方 id 列表(告知"有哪些配方、在哪个目录"),
    名称/分类/原料/产物等一切内容都在子文件里,不在索引中重复。
    """
    def finalize(_rows: list, entries: list[dict]) -> dict:
        grouped: dict[str, list] = {"manual": [], "machine": [], "spaceship": []}
        for e in entries:
            grouped[e["station"]].append(e["id"])
        return grouped

    dump_dir(PRODUCT, payload, subdir=lambda r: r["station"],
             index_map=lambda r: r["id"], index_finalize=finalize)


def main(force: bool = False) -> None:
    raw = load_tables(REQUIRED_TABLES, force=force)
    calc = load_calc_recipes()
    write(build(raw, I18n(raw[i18n_table()]), calc))


if __name__ == "__main__":
    main()
