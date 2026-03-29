"""统一采集入口:运行全部产物脚本,生成 data/ 各数据集目录、meta.json 与 reports/build-report.md。

用法:
    poetry run enddata collection all
    python3 -m collection.build_all
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from collection import characters, enemies, equips, items, recipes, settlements, weapons
from tools import tables, versions
from tools.datasource import PROJECT_ROOT, info, load_json
from tools.tables import (
    REPORTS_DIR,
    I18n,
    dump,
    i18n_table,
    load_tables,
)

PRODUCT_MODULES = (characters, items, recipes, weapons, equips, enemies, settlements)


def run(force: bool = False) -> None:
    t0 = datetime.now(timezone.utc)
    versions.record_repo_heads()  # 只读本地 git
    if tables.online():
        versions.refresh_game_build()  # 联网探测官方构建号;离线沿用 data/versions.json 旧值

    payloads: dict[str, Any] = {}
    t: I18n | None = None
    for mod in PRODUCT_MODULES:
        raw = load_tables(mod.REQUIRED_TABLES, force=force)  # 直读本地 git 仓库
        t = I18n(raw[i18n_table()])
        payloads[mod.PRODUCT] = mod.build(raw, t)
        mod.write(payloads[mod.PRODUCT])  # 各产物统一目录化(每条一个文件 + index.json)

    if t is None:  # PRODUCT_MODULES 非空,正常不可达;防御性兜底
        raise RuntimeError("PRODUCT_MODULES 为空,i18n 未初始化")
    equips_payload = payloads["equips"]
    meta = {
        "generatedAt": t0.isoformat(timespec="seconds"),
        "source": _source_info(),
        "lang": tables.DEFAULT_LANG,
        "i18nMisses": t.misses,
        "counts": {
            "characters": len(payloads["characters"]["characters"]),
            "items": len(payloads["items"]),
            "recipes": len(payloads["recipes"]),
            "weapons": len(payloads["weapons"]),
            "enemies": len(payloads["enemies"]),
            "equips": len(equips_payload["equips"]),
            "suits": len(equips_payload["suits"]),
        },
    }
    dump("meta", meta)
    info(f"i18n 未命中 {t.misses} 处(哈希不在 CN 表中,多为占位 0)")
    _write_report(t0, meta, payloads, t.misses)


def _source_info() -> dict:
    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["tablecfg"]
    return {"repo": cfg["repo"], "branch": cfg["branch"]}


def _write_report(t0: datetime, meta: dict, payloads: dict, misses: int) -> None:
    items = payloads["items"]
    icon_items = sum(1 for i in items if i.get("icon"))
    c = meta["counts"]
    report = f"""# 构建报告

- 构建时间:{t0.isoformat(timespec="seconds")}(UTC)
- 数据源:{meta["source"]["repo"]}@{meta["source"]["branch"]}
- 默认翻译语言:{tables.DEFAULT_LANG}
- i18n 未命中:{misses}

## 数据集规模

| 数据集 | 条数 |
|---|---|
| 干员 characters | {c["characters"]} |
| 物品 items(含图标 id {icon_items} 条) | {c["items"]} |
| 配方 recipes | {c["recipes"]} |
| 武器 weapons | {c["weapons"]} |
| 装备 equips / 套装 suits | {c["equips"]} / {c["suits"]} |
| 敌人 enemies | {c["enemies"]} |

## 产物位置

- 数据集:`data/<产物>/` 目录(每条一个 `<id>.json` + 轻量索引 `index.json`;
  图标只存裸 id,经 `node web/build.mjs` 构建为 dist/ 零外链站点后展示)
- 本报告:`reports/build-report.md`
"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = REPORTS_DIR / "build-report.md"
    dest.write_text(report, encoding="utf-8")
    info(f"  -> {dest.relative_to(PROJECT_ROOT)}")


def main(argv=None) -> None:
    run()


if __name__ == "__main__":
    main()
