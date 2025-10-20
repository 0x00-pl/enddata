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
| 装备(含词条/套装) | 258 + 24 套装 | EquipTable × EquipSuitTable × ItemTable |
| 敌人(属性/抗性/韧性/霸体) | 381 | EnemyTable × EnemyAttributeTemplateTable |

数据源调研结论见 **[docs/sources.md](docs/sources.md)**,字段结构见 **[docs/data-model.md](docs/data-model.md)**,
来源血缘关系与统计见 **[docs/data-lineage.md](docs/data-lineage.md)**(原则:同一数据优先追溯 git 项目,无 git 才用网页渠道)。

## 快速开始

项目由 Poetry 管理(运行时零第三方依赖),首次使用先 `poetry install`:

统一 CLI(子命令见 `poetry run enddata --help`):

```bash
# 数据采集:原始表抓取 + 各产物数据集(产物隐式依赖 fetch,缺原始表自动补抓)
poetry run enddata collection clone                      # 更新 sources/ 下数据源仓库
poetry run enddata collection characters --force         # 强制重抓干员依赖的原始表
poetry run enddata collection items                      # 只生成 items 数据集(缺原始表自动补抓)
poetry run enddata collection all                        # 依赖全部 collection,产出所有数据集与报告

# 数据展示:本地预览(从仓库根目录起服务)
python3 -m http.server 8321 --bind 127.0.0.1
# 打开 http://127.0.0.1:8321/site/

# 辅助:宏山档案局构建号监控
poetry run enddata version --record
```

导入采用规范的包内绝对导入(`from tools.enddata_http import ...`),不做任何 sys.path 修改,
因此请在 Poetry 虚拟环境内运行(`poetry run`/`poetry shell`,需先 `poetry install`)。

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
│   ├── collection/         #   ① 数据采集:原始数据的收集 + 初步处理(按产物一个模块)
│   │   ├── fetch.py            # 数据源仓库同步(sources/)+ 原始表抓取到 data/raw/
│   │   ├── characters.py items.py recipes.py weapons.py equips.py enemies.py
│   │   └── build_all.py        # 统一入口:全部产物 + meta + 构建报告
│   └── analysis/           #   ② 进阶分析(概率/DPS/产线规划等,见其 README)
│       └── README.md
├── tools/                  # 工具库:抓取公共库 + 共享初步处理工具 + 版本监控
│   ├── enddata_http.py     #   抓取公共库:本地git → 缓存 → jsdelivr → raw → COS → API
│   ├── common.py           #   i18n 反查/属性枚举/vfs 链接等共享工具
│   └── fffdan_version.py   #   宏山档案局 /version 构建号监控
├── sources/                # 数据源(6 个本地 git 克隆,gitignore,约 299MB,经血统审查裁剪)
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
