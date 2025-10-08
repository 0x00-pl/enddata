"""EndData 统一命令行入口:数据采集(clone/fetch)、数据分析(build)、版本监控(version)。"""

from __future__ import annotations

import argparse

from collection import build_all, clone_sources, fetch_tablecfg
from tools import fffdan_version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enddata",
        description="EndData · 明日方舟:终末地 战斗与生产数据采集/分析工具集",
    )
    sub = parser.add_subparsers(dest="command", metavar="{clone,fetch,build,version}", required=True)

    clone_sources.configure_parser(
        sub.add_parser("clone", help="克隆/更新本地数据源仓库到 sources/")
    )
    fetch_tablecfg.configure_parser(
        sub.add_parser("fetch", help="抓取 TableCfg 原始数值表到 data/raw/")
    )
    sub.add_parser("build", help="运行全部采集产物,生成数据集与构建报告")
    fffdan_version.configure_parser(
        sub.add_parser("version", help="宏山档案局构建号监控")
    )
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "clone":
        clone_sources.run(args)
    elif args.command == "fetch":
        fetch_tablecfg.run(args)
    elif args.command == "build":
        build_all.main()
    elif args.command == "version":
        fffdan_version.run(args)
