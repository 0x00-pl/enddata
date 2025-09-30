# EndData · 明日方舟:终末地 数据站

收集《明日方舟:终末地》的**战斗**与**生产**数据,加工成报告并以网页展示。
项目按三大功能组织:**数据采集(collection)→ 数据分析(analysis)→ 数据展示(site)**。

零框架、零构建:Python 标准库采集 + 原生 HTML/CSS/JS 展示。

## 当前状态(v0)

已跑通端到端流水线,当前数据集(来源 rmxlinux@main,2026-09-08):

| 数据集 | 条数 | 来源表 |
|---|---|---|
| 干员(含 1 级/满级面板+头像直链) | 33 | CharacterTable × CharProfessionTable × CharBreakTable |
| 物品(含图标直链) | 2829 | ItemTable × ItemTypeTable × I18nTextTable_CN |
| 生产配方(手工/工厂/飞船) | 427 | FactoryManualCraftTable + FactoryMachineCraftTable + SpaceshipManufactureFormulaTable |
| 武器 | 79 | WeaponBasicTable |
| 敌人(属性/抗性/韧性/霸体) | 381 | EnemyTable × EnemyAttributeTemplateTable |

数据源调研结论见 **[docs/sources.md](docs/sources.md)**,字段结构见 **[docs/data-model.md](docs/data-model.md)**,
来源血缘关系与统计见 **[docs/data-lineage.md](docs/data-lineage.md)**(原则:同一数据优先追溯 git 项目,无 git 才用网页渠道)。

## 快速开始

项目由 Poetry 管理(运行时零第三方依赖),首次使用先 `poetry install`:

```bash
# ① 数据采集:把所有 git 数据源克隆到本地 sources/,抓取优先读本地
poetry run enddata-clone                 # 重跑即更新到远端最新
poetry run enddata-fetch                 # 抓取原始数值表(本地命中则零网络)

# ② 数据分析:加工为数据集与构建报告
poetry run enddata-build                 # 输出 data/processed/*.json + reports/build-report.md

# ③ 数据展示:本地预览(从仓库根目录起服务)
python3 -m http.server 8321 --bind 127.0.0.1
# 打开 http://127.0.0.1:8321/site/
```

等价的辅助命令:`poetry run enddata-version`(宏山档案局构建号监控)。
不使用 Poetry 也可以直接以脚本方式运行:`python3 src/collection/clone_sources.py`、
`python3 src/collection/fetch_tablecfg.py`、`python3 src/analysis/build_dataset.py`(Python 3.10+ 标准库)。

## 目录结构

```
enddata/
├── pyproject.toml          # Poetry 项目定义与命令行入口
├── poetry.lock
├── config/
│   └── sources.json        # 数据源注册表(git 仓库清单/核心表/官方 API 端点/资源路径模板)
├── docs/                   # 项目文档
│   ├── sources.md          # 数据源调研报告
│   ├── data-model.md       # 原始表 → 数据集的流水线与字段说明
│   └── data-lineage.md     # 来源血缘关系、追溯规则与统计
├── src/                    # 功能代码
│   ├── collection/         #   ① 数据采集
│   │   ├── enddata_http.py     # 抓取公共库:本地git → 缓存 → jsdelivr → raw → COS → API
│   │   ├── clone_sources.py    # 数据源仓库克隆/更新到 sources/
│   │   └── fetch_tablecfg.py   # TableCfg 数值表抓取到 data/raw/
│   ├── analysis/           #   ② 数据分析
│   │   └── build_dataset.py    # i18n 反查 + 表间 join → 数据集与构建报告
│   └── tools/              #   其他工具
│       └── fffdan_version.py   # 宏山档案局 /version 构建号监控
├── sources/                # 数据源(13 个本地 git 克隆,gitignore,约 380MB)
├── data/
│   ├── raw/                # 采集好的数据(原始快照 + manifest 抓取清单)
│   ├── processed/          # 生成的数据集(构建产物,gitignore)
│   └── ...                 # 版本记录等
├── reports/                # 生成的报告(build-report.md 等,入库)
└── site/                   # ③ 报告的网页展示
    ├── index.html          #   总览/干员/武器/物品/配方/敌人 六个分页
    └── assets/             #   style.css / app.js(读取 /data/processed/)
```

## 数据来源与致谢

- [rmxlinux/EndfieldData](https://github.com/rmxlinux/EndfieldData) — **主数据源**:跟随当前版本的完整 TableCfg(725 表 + i18n)
- [XiaBei-cy/EndfieldData](https://github.com/XiaBei-cy/EndfieldData) — 正式服开服版 TableCfg(历史对照)
- [AndreaFrederica/jei-web](https://github.com/AndreaFrederica/jei-web) — 森空岛 Wiki 物品/配方包(规划接入)
- [AixLnyt/skport-api-docs](https://github.com/AixLnyt/skport-api-docs) — 官方 API 文档(玩家数据,规划接入)
- [JamboChen/endfield-calc](https://github.com/JamboChen/endfield-calc) — 产线规划参考实现
- [宏山档案局 end.fffdan.com](https://end.fffdan.com) / [天师工具箱 end-tools.fffdan.com](https://end-tools.fffdan.com) — 图标资源 vfs 与版本监控

完整清单、血缘关系与取舍理由见 [docs/sources.md](docs/sources.md) 与 [docs/data-lineage.md](docs/data-lineage.md)。

## 许可与声明

代码随项目分发;游戏内数据(数值表、文本、图标)版权归上海鹰角网络所有,
本项目仅供学习研究,请勿用于商业用途。
