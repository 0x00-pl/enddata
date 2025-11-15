"""EndData 统一命令行入口:数据采集(collection)、版本监控(version)。

用法示例:
    enddata collection clone                   # 克隆/更新数据源仓库到 sources/
    enddata collection all                     # 依赖全部 collection:自动补抓原始表并产出所有数据集
    enddata collection all --lang en           # 以英语为默认翻译语言构建全部数据集
    enddata collection items                   # 只生成 items 数据集(缺表自动补抓)
    enddata collection characters --force      # 强制重抓该产物依赖的原始表
    enddata version --record
"""

from __future__ import annotations

import argparse

from collection import build_all, fetch
from collection import characters, enemies, equips, items, recipes, weapons
from tools import tables, versions

PRODUCT_MODULES = {
    "characters": characters,
    "items": items,
    "recipes": recipes,
    "weapons": weapons,
    "equips": equips,
    "enemies": enemies,
}


ALL_TABLES = sorted({t for m in PRODUCT_MODULES.values() for t in m.REQUIRED_TABLES})


def _add_lang_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--lang", type=str.upper, choices=tables.LANGUAGES,
                   default=tables.DEFAULT_LANG,
                   help=f"默认翻译语言(表 I18nTextTable_<LANG>,默认 {tables.DEFAULT_LANG};"
                        f"items 目录 slug 恒为 EN)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enddata",
        description="EndData · 明日方舟:终末地 战斗与生产数据采集/分析工具集",
    )
    sub = parser.add_subparsers(dest="command", required=True,
                                metavar="{collection,version}")

    coll = sub.add_parser(
        "collection",
        help="数据采集:数据源仓库同步与各产物数据集(产物隐式依赖原始表抓取)",
    )
    coll_sub = coll.add_subparsers(
        dest="target",
        required=True,
        metavar="{fetch,clone,all,characters,items,recipes,weapons,equips,enemies}",
    )

    clone_p = coll_sub.add_parser("clone", help="克隆/更新数据源仓库到 sources/")
    fetch.configure_clone_parser(clone_p)
    fetch_p = coll_sub.add_parser(
        "fetch",
        help="更新数据源仓库 + 刷新构建号 + 预热原始表(缺省全部产物依赖表)",
    )
    fetch.configure_parser(fetch_p)
    _add_lang_arg(fetch_p)
    all_p = coll_sub.add_parser("all", help="全部产物数据集 + meta + 构建报告")
    all_p.add_argument("--force", action="store_true", help="重新抓取全部依赖的原始表")
    _add_lang_arg(all_p)
    for name, mod in PRODUCT_MODULES.items():
        pp = coll_sub.add_parser(name, help=f"生成 {name} 数据集目录(缺原始表时自动补抓)")
        pp.add_argument("--force", action="store_true", help="强制重抓该产物依赖的原始表")
        _add_lang_arg(pp)

    sub.add_parser("version", help="项目版本与数据源版本报告(读取 data/versions.json)")
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "version":
        versions.run()
        return

    # collection 域
    if args.target == "clone":
        fetch.update_repos(no_update=args.no_update, only=args.only or None)
    elif args.target == "fetch":
        tables.set_default_lang(args.lang)
        names = sorted({tables.i18n_table() if n == "I18nTextTable_CN" else n
                        for n in ALL_TABLES})
        fetch.run(args, default_names=names)
    elif args.target == "all":
        tables.set_default_lang(args.lang)
        build_all.run(force=args.force)
    else:  # 单产物
        tables.set_default_lang(args.lang)
        mod = PRODUCT_MODULES[args.target]
        mod.main(force=args.force)


if __name__ == "__main__":
    main()
