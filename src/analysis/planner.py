"""产线规划器:给定目标产物与数量,倒推所需原材料、制造步骤与耗时。

基于 data/recipes.json(含 craftTimeSec/facility,来自 endfield-calc 精校数据)
与 data/items.json(名称)计算。约定:
    - 有产出配方的物品按配方展开(多配方时优先 machine,其次 manual/spaceship;
      可用 --station 指定)
    - 无产出配方的物品计为原材料
    - 制造批次 = ceil(需求量 ÷ 单次产量),整数向上取整
    - 耗时为该设施串行总耗时(游戏内多设施并行,实际更短)

用法:
    poetry run enddata analysis plan <物品ID或名称> [数量]
    poetry run enddata analysis plan component_copper_cmpt 10
"""

from __future__ import annotations

import json
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"

STATION_PRIORITY = ("machine", "manual", "spaceship")
STATION_CN = {"manual": "手工", "machine": "工厂", "spaceship": "飞船"}
MAX_DEPTH = 24


def _load(name: str):
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def build_item_graph(recipes: list[dict]) -> dict[str, list[dict]]:
    """产物物品 → 可产出它的配方列表(按站点优先级排序)。"""
    graph: dict[str, list[dict]] = {}
    for r in recipes:
        for out in r.get("outcomes") or []:
            for opt in out.get("options") or []:
                graph.setdefault(opt["id"], []).append(r)
    for item, prods in graph.items():
        prods.sort(key=lambda r: STATION_PRIORITY.index(r["station"])
                   if r["station"] in STATION_PRIORITY else 99)
    return graph


def _pick_recipe(prods: list[dict], prefer: str | None) -> dict | None:
    if prefer:
        for r in prods:
            if r["station"] == prefer:
                return r
    return prods[0] if prods else None


def plan(item_id: str, qty: float, recipes: list[dict], prefer: str | None = None) -> dict:
    graph = build_item_graph(recipes)
    steps: dict[str, dict] = {}
    raw: dict[str, float] = {}
    unresolved: list[str] = []

    def resolve(item: str, quantity: float, depth: int) -> None:
        if depth > MAX_DEPTH:
            unresolved.append(item)
            return
        prods = graph.get(item) or []
        recipe = _pick_recipe(prods, prefer)
        if recipe is None:
            raw[item] = raw.get(item, 0.0) + quantity
            return
        out = recipe.get("outcomes") or []
        out_options = (out[0].get("options") or [{}]) if out else [{}]
        target = next((o for o in (out[0].get("options") or []) if o.get("id") == item),
                      out_options[0])
        per_craft = target.get("count", 1) or 1
        craft_count = math.ceil(quantity / per_craft)
        step = steps.setdefault(item, {
            "item": item, "station": recipe["station"],
            "recipeId": recipe["id"], "crafts": 0, "craftTimeSec": recipe.get("craftTimeSec"),
            "totalTimeSec": 0.0,
        })
        step["crafts"] += craft_count
        step["totalTimeSec"] += craft_count * (recipe.get("craftTimeSec") or 0)
        for ing in recipe.get("ingredients") or []:
            opt = (ing.get("options") or [{}])[0]
            resolve(opt["id"], opt.get("count", 1) * craft_count, depth + 1)

    resolve(item_id, qty, 0)
    return {
        "target": {"id": item_id, "qty": qty},
        "steps": sorted(steps.values(), key=lambda x: -x["crafts"]),
        "rawMaterials": sorted(raw.items(), key=lambda x: -x[1]),
        "totalTimeSec": sum(s["totalTimeSec"] for s in steps.values()),
        "unresolved": sorted(set(unresolved)),
    }


def _fmt_time(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s2 = divmod(rem, 60)
    return (f"{h}小时" if h else "") + (f"{m}分" if m else "") + f"{s2}秒"


def run(item: str, qty: float = 1, station: str | None = None, save: bool = True) -> dict:
    items = _load("items")
    recipes = _load("recipes")
    by_id = {i["id"]: i for i in items}
    # 支持按名称定位
    target_id = item if item in by_id else next(
        (i["id"] for i in items if i.get("name") == item), None)
    if not target_id:
        raise SystemExit(f"未找到物品: {item}(请使用物品 ID 或精确名称)")

    result = plan(target_id, qty, recipes, prefer=station)
    name_of = lambda iid: (by_id.get(iid) or {}).get("name") or iid  # noqa: E731

    print(f"目标: {name_of(target_id)} × {qty:g}")
    print(f"\n[制造步骤] {len(result['steps'])} 个环节,串行总耗时 ≈ {_fmt_time(result['totalTimeSec'])}")
    for s in result["steps"]:
        time_s = (f", 单次 {s['craftTimeSec']}s,小计 {_fmt_time(s['totalTimeSec'])}"
                  if s["craftTimeSec"] else "")
        print(f"  {STATION_CN.get(s['station'], s['station'])} {name_of(s['item'])} ×{s['crafts']}"
              f"(配方 {s['recipeId']}{time_s})")
    print(f"\n[原材料] {len(result['rawMaterials'])} 种")
    for iid, q in result["rawMaterials"]:
        print(f"  {name_of(iid)} ×{q:g}")
    if result["unresolved"]:
        print(f"[!] 展开深度超限: {result['unresolved']}")

    payload = dict(result)
    payload["targetName"] = name_of(target_id)
    if save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        dest = REPORTS_DIR / f"plan_{target_id}_{qty:g}.json"
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已保存: {dest.relative_to(PROJECT_ROOT)}")
    return payload


def main(argv=None) -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item", help="目标物品 ID 或名称")
    parser.add_argument("qty", nargs="?", default=1, type=float, help="目标数量(默认 1)")
    parser.add_argument("--station", choices=STATION_PRIORITY, default=None,
                        help="优先制造站点")
    args = parser.parse_args(argv)
    run(args.item, args.qty, args.station)


if __name__ == "__main__":
    main()
