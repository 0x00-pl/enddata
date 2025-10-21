"""版本报告:输出项目版本与各数据源的版本信息。

内容:
    - 项目版本(pyproject.toml / 包元数据)
    - 数据源 git 仓库:分支、HEAD 短哈希、最近提交日期与说明
    - 官方构建号(宏山档案局 /version,可 --record 记录基线对比)
    - 本地数据快照与数据集构建时间
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from tools.enddata_http import PROJECT_ROOT, RAW_DIR, git_env, http_get, info, load_json, repo_dir

RECORD = RAW_DIR / "fffdan_version.txt"


def project_version() -> str:
    try:
        from importlib.metadata import version
        return version("enddata")
    except Exception:  # noqa: BLE001 - 未安装时回退读 pyproject.toml
        text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version = "(.*?)"', text, re.M)
        return m.group(1) if m else "?"


def git_repo_info(entry: dict) -> dict:
    d = repo_dir(entry["repo"])
    info = {"repo": entry["repo"], "branch": entry.get("branch") or "?",
            "sha": "-", "date": "-", "subject": "-", "status": "缺失"}
    if not d.is_dir():
        return info
    if info["branch"] == "?":
        r = subprocess.run(["git", "-C", str(d), "symbolic-ref", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10, env=git_env())
        if r.returncode == 0:
            info["branch"] = r.stdout.strip()
    r = subprocess.run(
        ["git", "-C", str(d), "log", "-1", "--format=%h|%cs|%s"],
        capture_output=True, text=True, timeout=30, env=git_env(),
    )
    if r.returncode == 0:
        sha, date, subject = r.stdout.strip().split("|", 2)
        info.update({"sha": sha, "date": date, "subject": subject, "status": "ok"})
    return info


def fffdan_build(record: bool = False) -> None:
    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["fffdan_vfs"]
    current = None
    for host in cfg["hosts"]:
        try:
            current = http_get(host + cfg["version_endpoint"], timeout=10).decode().strip()
            print(f"  当前构建: {current}  ({host})")
            break
        except Exception as e:  # noqa: BLE001 - 逐主机故障转移
            print(f"  [--] {host}: {type(e).__name__}")
    if current is None:
        print("  所有主机均不可达,跳过官方构建号")
        return

    if RECORD.exists():
        last = RECORD.read_text(encoding="utf-8").strip()
        if last != current:
            print(f"  ⚠️ 版本变化: {last} -> {current}(建议重新抓取 TableCfg)")
        else:
            print(f"  与上次记录一致")
    else:
        print("  尚无本地版本记录")

    if record:
        RECORD.parent.mkdir(parents=True, exist_ok=True)
        RECORD.write_text(current, encoding="utf-8")
        print(f"  已记录到 {RECORD.relative_to(PROJECT_ROOT)}")


def _local_snapshot_line() -> str:
    from tools.common import raw_tables_dir

    d = raw_tables_dir()
    tables = len(list(d.glob("*.json")))
    if not tables:
        return "原始快照: 无(尚未抓取)"
    return f"原始快照: {tables} 张表 (data/raw/tablecfg)"


def _local_build_line() -> str:
    meta_path = PROJECT_ROOT / "data" / "processed" / "meta.json"
    if not meta_path.exists():
        return "数据集构建: 无(尚未运行 enddata build)"
    m = json.loads(meta_path.read_text(encoding="utf-8"))
    c = m.get("counts", {})
    return ("数据集构建: {}(干员 {} / 物品 {} / 配方 {} / 武器 {} / 装备 {} / 敌人 {})"
            .format(m.get("generatedAt", "?"), c.get("characters"), c.get("items"),
                    c.get("recipes"), c.get("weapons"), c.get("equips"), c.get("enemies")))


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--record", action="store_true", help="把当前官方构建号写入本地记录")


def run(args) -> None:
    print(f"EndData v{project_version()}\n")

    print("[数据源仓库] sources/")
    git_cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["git"]
    for entry in git_cfg["clone"]:
        i = git_repo_info(entry)
        print(f"  {i['repo']:<45} {i['branch']:<8} {i['sha']:<9} {i['date']}  {i['subject'][:40]}")
    for r in git_cfg.get("retired", []):
        print(f"  [退役] {r['repo']}")
    print()

    print("[官方构建号] 宏山档案局 /version")
    fffdan_build(record=args.record)
    print()

    print("[本地数据]")
    print(f"  {_local_snapshot_line()}")
    print(f"  {_local_build_line()}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    configure_parser(parser)
    run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
