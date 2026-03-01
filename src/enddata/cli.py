"""EndData 统一命令行入口:数据采集(collection)、进阶分析(analysis)、版本监控(version)、id 关联映射(idmap)。

用法示例:
    enddata collection clone                   # 克隆/更新数据源仓库到 sources/(含图标 git 源)
    enddata collection fetch                   # 联网:更新数据源仓库 + 刷新构建号 + 预热原始表
    enddata collection all                     # 全部产物数据集(默认离线直读本地 sources/)
    enddata collection all --lang en           # 以英语为默认翻译语言构建全部数据集
    enddata collection items                   # 只生成 items 数据集(离线;缺表报错)
    enddata collection items --online          # 缺原始表时允许联网补抓
    enddata collection characters --force      # 核对远端 HEAD、有更新才增量拉取,随后本地重读
    enddata analysis team                       # 配队分析:技能/天赋/潜能的需求与产出资源解析
    enddata analysis recipe 铁制零件 10         # 配方用料倒推:最终产物 → 最初用料/--have 清单(自动处理环)
    enddata idmap build                         # 扫描 rmxlinux 源,重建 data/id_map/ 关联规则产物
    enddata idmap relate <file#path>            # 按定位符返回同组定位符列表(path 列表)
    enddata version --record

站点构建(JS 工具链,非本 CLI):npm run build(js 项目根 = 仓库根)→ 零外链的 dist/
"""

from __future__ import annotations

import argparse

from analysis import gacha, recipe_calc, team_comp
from collection import build_all, fetch
from collection import characters, enemies, equips, items, recipes, settlements, weapons
from tools import id_links, tables, versions
from tools.datasource import FetchError, die

PRODUCT_MODULES = {
    "characters": characters,
    "items": items,
    "recipes": recipes,
    "weapons": weapons,
    "equips": equips,
    "enemies": enemies,
    "settlements": settlements,
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
                                metavar="{collection,analysis,version,idmap}")

    coll = sub.add_parser(
        "collection",
        help="数据采集:数据源仓库同步与各产物数据集(产物隐式依赖原始表抓取)",
    )
    coll_sub = coll.add_subparsers(
        dest="target",
        required=True,
        metavar="{fetch,clone,all,characters,items,recipes,weapons,equips,enemies,settlements}",
    )

    clone_p = coll_sub.add_parser("clone", help="克隆/更新数据源仓库到 sources/")
    fetch.configure_clone_parser(clone_p)
    fetch_p = coll_sub.add_parser(
        "fetch",
        help="更新数据源仓库 + 刷新构建号 + 预热原始表(缺省全部产物依赖表)",
    )
    fetch.configure_parser(fetch_p)
    _add_lang_arg(fetch_p)
    all_p = coll_sub.add_parser("all", help="全部产物数据集 + meta + 构建报告(默认离线)")
    all_p.add_argument("--online", action="store_true", help="缺原始表时允许联网补抓")
    all_p.add_argument("--force", action="store_true",
                       help="核对数据源远端 HEAD(一致零下载,有更新增量拉取)后本地重读;隐含 --online")
    _add_lang_arg(all_p)
    for name, mod in PRODUCT_MODULES.items():
        pp = coll_sub.add_parser(name, help=f"生成 {name} 数据集目录(离线直读本地,缺表报错)")
        pp.add_argument("--online", action="store_true", help="缺原始表时允许联网补抓")
        pp.add_argument("--force", action="store_true",
                        help="核对数据源远端 HEAD(一致零下载,有更新增量拉取)后本地重读;隐含 --online")
        _add_lang_arg(pp)

    sub.add_parser("version", help="项目版本与数据源版本报告(读取 data/versions.json)")

    ana = sub.add_parser(
        "analysis",
        help="进阶分析:基于 data/ 数据集二次计算(产物入 data/analysis/ 与 reports/)",
    )
    ana_sub = ana.add_subparsers(dest="analysis_target", required=True,
                                 metavar="{team,gacha,recipe}")
    ana_sub.add_parser(
        "team", help="配队分析:技能/天赋/潜能的需求与产出资源解析 → reports/team-analysis.md",
    )
    gacha_p = ana_sub.add_parser(
        "gacha", help="抽卡分析:寻访概率计算(卡池状态机模拟 + 解析分布对拍)→ 控制台报告",
    )
    gacha_p.add_argument(
        "version", nargs="?", default=None, metavar="VERSION",
        help="目标版本(如 1.4):限定 --plot 的统计范围与全勤对照截止,缺省为最新版本",
    )
    gacha_p.add_argument(
        "--plot", action="store_true",
        help="绘制版本全图鉴集齐概率曲线(平铺策略,零依赖 SVG)",
    )
    gacha_p.add_argument(
        "--method", choices=("both", "analytic", "simulate"), default="simulate",
        help="概率计算方式:simulate=状态机蒙特卡洛(默认,含顺路/跳过与下期券);"
             "analytic=解析卷积上界(快、保守);both=两者都画",
    )
    recipe_p = ana_sub.add_parser(
        "recipe", help="配方用料倒推:最终产物 → 最初用料/--have 清单(自动绕开循环依赖)",
    )
    recipe_p.add_argument(
        "item", nargs="?", default=None, metavar="ITEM",
        help="目标物品(id 或中文名,支持唯一子串);缺省则生成数据概览报告",
    )
    recipe_p.add_argument(
        "qty", nargs="?", default="1",
        help="目标数量(整数/分数/小数,默认 1;或速率,如 60/min)",
    )
    recipe_p.add_argument(
        "--have", default="", metavar="ITEMS",
        help="视为可直接获取的物品清单(逗号分隔 id/名称),展开到此为止"
             "(亦可用于指定循环物品的初始存量)",
    )
    recipe_p.add_argument(
        "--recipe", action="append", default=[], metavar="ITEM=RECIPE_ID",
        help="钉选某物品的产出配方(可多次),如 "
             "--recipe 息壤=xiranite_oven_xiranite_powder_2;钉选后不再尝试其他配方",
    )
    recipe_p.add_argument(
        "--solver", default="recursive",
        help=f"求解器实现(默认 recursive 递归展开;可选:"
             f"{', '.join(recipe_calc.SOLVERS)})",
    )
    recipe_p.add_argument(
        "--json", action="store_true",
        help="以 JSON 输出机器可读结果(展开树 + 用料合计 + 制造步骤)",
    )

    idm = sub.add_parser(
        "idmap",
        help="id 关联映射:扫描 rmxlinux 源建立跨表 id 关联组与模式目录(产物入 data/id_map/)",
    )
    idm_sub = idm.add_subparsers(dest="idmap_cmd", required=True,
                                 metavar="{build,relate}")
    id_links.configure_parser(idm_sub)
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "version":
        versions.run()
        return

    # analysis 域
    if args.command == "analysis":
        if args.analysis_target == "team":
            team_comp.main()
        elif args.analysis_target == "gacha":
            gacha.main(args.version, args.plot, args.method)
        elif args.analysis_target == "recipe":
            recipe_calc.main(args.item, args.qty, args.have, args.json,
                             args.recipe, args.solver)
        return

    # idmap 域
    if args.command == "idmap":
        id_links.run(args)
        return

    # collection 域
    if args.target == "clone":
        fetch.update_repos(no_update=args.no_update, only=args.only or None)
    elif args.target == "fetch":
        tables.set_default_lang(args.lang)
        tables.set_online(True)  # fetch 即联网命令:本地缺表时照常补抓
        names = sorted({tables.i18n_table() if n == "I18nTextTable_CN" else n
                        for n in ALL_TABLES})
        fetch.run(args, default_names=names)
    else:  # all / 单产物:默认离线,仅读本地 sources/
        tables.set_default_lang(args.lang)
        is_online = args.online or args.force
        tables.set_online(is_online)
        if not is_online:
            tables.warn_stale()
        try:
            if args.target == "all":
                build_all.run(force=args.force)
            else:
                PRODUCT_MODULES[args.target].main(force=args.force)
        except FetchError as e:
            die(str(e))


if __name__ == "__main__":
    main()
