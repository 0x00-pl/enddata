#!/usr/bin/env python3
"""抓取终末地 TableCfg 核心数值表到 data/raw/tablecfg/。

用法:
    python3 src/collection/fetch_tablecfg.py              # 抓取 config/sources.json 中的 core_tables
    python3 src/collection/fetch_tablecfg.py ItemTable EnemyTable   # 只抓指定表
    python3 src/collection/fetch_tablecfg.py --force      # 忽略本地缓存强制重新抓取
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from enddata_http import RAW_DIR, PROJECT_ROOT, fetch_to_cache, gh_api, http_get, info, load_json, resolve_branch

MANIFEST = RAW_DIR / "tablecfg" / "manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tables", nargs="*", help="要抓取的表名(不含 .json),缺省取 core_tables 全部")
    parser.add_argument("--force", action="store_true", help="忽略本地缓存")
    args = parser.parse_args()

    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["tablecfg"]
    repo = cfg["repo"]
    branch = resolve_branch(repo, cfg.get("branch"))
    wanted = args.tables or cfg["core_tables"]
    table_dir = cfg.get("table_dir", "TableCfg")
    i18n_dir = cfg.get("i18n_dir", table_dir)
    # 不同镜像的 i18n 位置不同(rmxlinux 在 TableCfg/ 内,XiaBei-cy 在 i18n/ 目录),
    # 依次尝试候选目录,取第一个命中
    candidates = []
    for d in (table_dir, i18n_dir):
        if d and d not in candidates:
            candidates.append(d)
    info(f"数据源: {repo}@{branch}  待抓取 {len(wanted)} 个文件")

    results = {"repo": repo, "branch": branch, "fetched_at": None, "files": {}}
    ok = 0
    cos_base = None
    try:
        cos_base = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["yituliu_cos"]["table_base"]
    except (KeyError, FileNotFoundError, json.JSONDecodeError):
        pass
    for name in wanted:
        try:
            last_err = None
            dest = channel = None
            for d in candidates:
                try:
                    dest, channel = fetch_to_cache("tablecfg", repo, branch, f"{d}/{name}.json", force=args.force)
                    last_err = None
                    break
                except Exception as e:  # noqa: BLE001 - 目录候选失败则继续
                    last_err = e
            if dest is None and cos_base:
                # 兜底:一图流 COS 直取(无需 git,见 docs/sources.md)
                data = http_get(f"{cos_base}/{name}.json")
                dest = RAW_DIR / "tablecfg" / repo.replace("/", "__") / branch / f"{name}.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                channel = "yituliu-cos"
            if dest is None:
                raise last_err
            results["files"][name] = {
                "path": str(dest.relative_to(PROJECT_ROOT)),
                "channel": channel,
                "size_kb": round(dest.stat().st_size / 1024),
            }
            ok += 1
        except Exception as e:  # noqa: BLE001 - 单表失败不中断整批
            info(f"  [FAIL] {name}: {e}")
            results["files"][name] = {"error": str(e)}
        time.sleep(0.3)  # 温和一些,避免触发限流

    results["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    info(f"完成 {ok}/{len(wanted)},清单已写入 {MANIFEST.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
