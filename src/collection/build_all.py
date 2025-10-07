"""统一采集入口:运行全部产物脚本,生成 data/processed/*.json、meta.json 与 reports/build-report.md。

用法:
    poetry run enddata-build
    python3 -m collection.build_all
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from collection import characters, enemies, equips, items, recipes, weapons
from collection.common import (
    I18n,
    PROCESSED_DIR,
    REPORTS_DIR,
    dump,
    load_raw_tables,
    load_vfs_config,
)
from collection.enddata_http import PROJECT_ROOT, RAW_DIR, info, load_json

PRODUCT_MODULES = (characters, items, recipes, weapons, equips, enemies)


def main() -> None:
    t0 = datetime.now(timezone.utc)
    load_vfs_config()
    raw = load_raw_tables()
    info(f"加载原始表: {len(raw)} 张")
    t = I18n(raw["I18nTextTable_CN"])

    payloads: dict[str, object] = {}
    for mod in PRODUCT_MODULES:
        payloads[mod.PRODUCT] = mod.build(raw, t)
        dump(mod.PRODUCT, payloads[mod.PRODUCT])

    equips_payload = payloads["equips"]
    meta = {
        "generatedAt": t0.isoformat(timespec="seconds"),
        "source": _source_info(),
        "i18nMisses": t.misses,
        "counts": {
            "characters": len(payloads["characters"]),
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
    return {"repo": cfg["repo"], "branch": cfg["branch"],
            "fetchedAt": load_json(RAW_DIR / "tablecfg" / "manifest.json")["fetched_at"]}


def _write_report(t0: datetime, meta: dict, payloads: dict, misses: int) -> None:
    manifest = load_json(RAW_DIR / "tablecfg" / "manifest.json")
    channels: dict[str, int] = {}
    for f in manifest.get("files", {}).values():
        ch = f.get("channel", "?")
        channels[ch] = channels.get(ch, 0) + 1
    items = payloads["items"]
    icon_items = sum(1 for i in items if i.get("iconUrl"))
    c = meta["counts"]
    report = f"""# 构建报告

- 构建时间:{t0.isoformat(timespec="seconds")}(UTC)
- 数据源:{meta["source"]["repo"]}@{meta["source"]["branch"]}(抓取于 {meta["source"]["fetchedAt"]})
- 抓取渠道分布:{json.dumps(channels, ensure_ascii=False)}
- i18n 未命中:{misses}

## 数据集规模

| 数据集 | 条数 |
|---|---|
| 干员 characters | {c["characters"]} |
| 物品 items(含图标链接 {icon_items} 条) | {c["items"]} |
| 配方 recipes | {c["recipes"]} |
| 武器 weapons | {c["weapons"]} |
| 装备 equips / 套装 suits | {c["equips"]} / {c["suits"]} |
| 敌人 enemies | {c["enemies"]} |

## 产物位置

- 数据集:`data/processed/*.json`(网页展示由 `site/` 消费)
- 本报告:`reports/build-report.md`
"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = REPORTS_DIR / "build-report.md"
    dest.write_text(report, encoding="utf-8")
    info(f"  -> {dest.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
