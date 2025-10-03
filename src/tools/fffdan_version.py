#!/usr/bin/env python3
"""监控宏山档案局(end.fffdan.com)镜像的官方构建版本号。

对 config/sources.json 中 fffdan_vfs 的主机依次探测 /version,
与上次记录(data/raw/fffdan_version.txt)对比,变化时提示可能出新版本数据。

用法:
    python3 src/collection/fffdan_version.py            # 查询并对比
    python3 src/collection/fffdan_version.py --record   # 查询并记录当前版本
"""

from __future__ import annotations

import argparse

from collection.enddata_http import PROJECT_ROOT, RAW_DIR, http_get, load_json

RECORD = RAW_DIR / "fffdan_version.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="把当前版本写入本地记录")
    args = parser.parse_args()

    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["fffdan_vfs"]
    current = None
    for host in cfg["hosts"]:
        try:
            current = http_get(host + cfg["version_endpoint"], timeout=10).decode().strip()
            print(f"[OK] {host}: {current}")
            break
        except Exception as e:  # noqa: BLE001 - 逐主机故障转移
            print(f"[--] {host}: {type(e).__name__}")

    if current is None:
        raise SystemExit("所有主机均不可达")

    if RECORD.exists():
        last = RECORD.read_text(encoding="utf-8").strip()
        if last != current:
            print(f"版本变化: {last} -> {current}(建议重新抓取 TableCfg)")
        else:
            print(f"与上次记录一致({last})")
    else:
        print("尚无本地版本记录")

    if args.record:
        RECORD.parent.mkdir(parents=True, exist_ok=True)
        RECORD.write_text(current, encoding="utf-8")
        print(f"已记录到 {RECORD.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
