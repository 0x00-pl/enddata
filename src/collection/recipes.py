"""采集+初步处理:生产配方数据集 → data/recipes.json。

来源表:FactoryManualCraftTable × FactoryMachineCraftTable × SpaceshipManufactureFormulaTable
        × ItemTable(原料/产物命名) × I18nTextTable_CN
        × JamboChen/endfield-calc(本地 git:制造耗时 craftingTime 与生产设施 facilityId;
          其 recipes.ts 里的 RecipeId/ItemId/FacilityId 常量展开后与 rmxlinux TableCfg
          是同一套小写游戏 ID,可直接按配方 ID join)
产物:按站点(manual/machine/spaceship)合并的配方;机器配方的可替代原料组保留为 options;
      calc 命中的条目补充 craftTimeSec(制造耗时,秒)与 facility(生产设施 ID),未命中留空。
"""

from __future__ import annotations

import re

from tools.datasource import info, read_from_git
from tools.tables import I18n, dump, load_tables

PRODUCT = "recipes"

REQUIRED_TABLES = ["FactoryManualCraftTable", "FactoryMachineCraftTable",
                                 "SpaceshipManufactureFormulaTable", "ItemTable", "I18nTextTable_CN"]

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

    def resolve_side(entries: list[dict]) -> list[dict]:
        """原料/产物条目 → [{count, options:[{id,name}]}];机器配方的 group 是可替代原料组。"""
        out = []
        for e in entries or []:
            if "group" in e:
                options = [{"id": o["id"], "name": item_name.get(o["id"]) or o["id"], "count": o.get("count", 1)}
                           for o in e["group"]]
            else:
                options = [{"id": e["id"], "name": item_name.get(e["id"]) or e["id"], "count": e.get("count", 1)}]
            out.append({"count": options[0]["count"], "options": options})
        return out

    recipes = []
    for rid, r in raw["FactoryManualCraftTable"].items():
        recipes.append({
            "id": rid, "station": "manual",
            "rarity": r.get("rarity"), "domainId": r.get("domainId"),
            "ingredients": resolve_side(r.get("ingredients")),
            "outcomes": resolve_side(r.get("outcomes")),
        })
    for rid, r in raw["FactoryMachineCraftTable"].items():
        recipes.append({
            "id": rid, "station": "machine", "machineId": r.get("machineId"),
            "rarity": r.get("rarity"),
            "ingredients": resolve_side(r.get("ingredients")),
            "outcomes": resolve_side(r.get("outcomes")),
        })
    for rid, r in raw["SpaceshipManufactureFormulaTable"].items():
        recipes.append({
            "id": rid, "station": "spaceship",
            "rarity": r.get("rarity"),
            "ingredients": [],
            "outcomes": resolve_side([{"id": r["outcomeItemId"], "count": r.get("perCapacity", 1)}]),
        })

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


def main(force: bool = False) -> None:
    raw = load_tables(REQUIRED_TABLES, force=force)
    calc = load_calc_recipes()
    dump(PRODUCT, build(raw, I18n(raw["I18nTextTable_CN"]), calc))


if __name__ == "__main__":
    main()
