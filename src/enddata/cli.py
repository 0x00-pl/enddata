"""EndData 统一命令行入口:数据采集(collection)、版本监控(version)。

用法示例:
    enddata collection clone                   # 克隆/更新数据源仓库到 sources/
    enddata collection all                     # 依赖全部 collection:自动补抓原始表并产出所有数据集
    enddata collection items                   # 只生成 items 数据集(缺表自动补抓)
    enddata collection characters --force      # 强制重抓该产物依赖的原始表
    enddata version --record
"""

from __future__ import annotations

import argparse

from collection import build_all, fetch
from collection import characters, enemies, equips, items, recipes, weapons
from tools import fffdan_version

PRODUCT_MODULES = {
    "characters": characters,
    "items": items,
    "recipes": recipes,
    "weapons": weapons,
    "equips": equips,
    "enemies": enemies,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enddata",
        description="EndData · 明日方舟:终末地 战斗与生产数据采集/分析工具集",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="{collection,version}")

    coll = sub.add_parser(
        "collection",
        help="数据采集:数据源仓库同步与各产物数据集(产物隐式依赖原始表抓取)",
    )
    coll_sub = coll.add_subparsers(
        dest="target",
        required=True,
        metavar="{clone,all,characters,items,recipes,weapons,equips,enemies}",
    )

    fetch.configure_clone_parser(
        coll_sub.add_parser("clone", help="克隆/更新数据源仓库到 sources/")
    )
    all_p = coll_sub.add_parser("all", help="全部产物数据集 + meta + 构建报告")
    all_p.add_argument("--force", action="store_true", help="重新抓取全部依赖的原始表")
    for name, mod in PRODUCT_MODULES.items():
        pp = coll_sub.add_parser(name, help=f"生成 {name}.json(缺原始表时自动补抓)")
        pp.add_argument("--force", action="store_true", help="强制重抓该产物依赖的原始表")

    version_p = sub.add_parser("version", help="宏山档案局构建号监控")
    fffdan_version.configure_parser(version_p)
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "version":
        fffdan_version.run(args)
        return

    # collection 域
    if args.target == "clone":
        fetch.update_repos(no_update=args.no_update, only=args.only or None)
    elif args.target == "all":
        build_all.run(force=args.force)
    else:  # 单产物
        mod = PRODUCT_MODULES[args.target]
        fetch.ensure_tables(mod.REQUIRED_TABLES, force=args.force)
        mod.main()
