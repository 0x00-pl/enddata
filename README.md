# EndData · 明日方舟:终末地 数据站

收集《明日方舟:终末地》的**战斗**与**生产**数据,加工后以静态网页展示。
零框架、零构建:Python 标准库采集 + 原生 HTML/CSS/JS 展示。

## 当前状态(v0)

已跑通 端到端 流水线,首批数据集:

| 数据集 | 条数 | 来源表 |
|---|---|---|
| 干员(含 1 级/满级面板) | 33 | CharacterTable × CharProfessionTable × CharBreakTable |
| 物品 | 2829 | ItemTable × ItemTypeTable × I18nTextTable_CN |
| 生产配方(手工/工厂/飞船) | 427 | FactoryManualCraftTable + FactoryMachineCraftTable + SpaceshipManufactureFormulaTable |
| 武器 | 79 | WeaponBasicTable |
| 敌人(属性/抗性/韧性/霸体) | 381 | EnemyTable × EnemyAttributeTemplateTable |

数据源调研结论见 **[docs/sources.md](docs/sources.md)**,字段结构见 **[docs/data-model.md](docs/data-model.md)**,
来源血缘关系与统计见 **[docs/data-lineage.md](docs/data-lineage.md)**(原则:同一数据优先追溯 git 项目,无 git 才用网页渠道)。

## 快速开始

```bash
# 0. (推荐)把所有 git 数据源克隆到本地 data/repos/,抓取优先读本地
python3 scripts/clone_sources.py      # 重跑即更新到远端最新

# 1. 抓取原始数值表(优先读本地仓库,本地未命中才走网络)
python3 scripts/fetch_tablecfg.py

# 2. 加工为前端数据集
python3 scripts/build_dataset.py

# 3. 本地预览
python3 -m http.server 8321 --directory site
# 打开 http://127.0.0.1:8321/
```

无第三方依赖(Python 3.10+ 标准库)。

## 目录结构

```
enddata/
├── config/
│   └── sources.json        # 数据源注册表(git 仓库清单/核心表/官方 API 端点/资源路径模板)
├── docs/
│   ├── sources.md          # 数据源调研报告(核心文档)
│   └── data-model.md       # 原始表 → 数据集的流水线与字段说明
├── scripts/
│   ├── enddata_http.py     # 抓取公共库:本地git → jsdelivr → raw → API 回退 + 本地缓存
│   ├── clone_sources.py    # 数据源仓库克隆/更新到 data/repos/(partial 克隆大仓库)
│   ├── fetch_tablecfg.py   # 抓取 TableCfg 数值表到 data/raw/
│   ├── fffdan_version.py   # 宏山档案局 /version 构建号监控
│   └── build_dataset.py    # i18n 反查 + 表间 join,输出 site/data/*.json
├── data/
│   ├── repos/              # 数据源本地克隆(gitignore,约 280MB)
│   ├── raw/                # 原始快照(含 manifest.json 抓取清单)
│   └── processed/          # 预留:中间产物
└── site/                   # 静态前端
    ├── index.html
    ├── assets/             # style.css / app.js
    └── data/               # 构建产物,前端直接 fetch
```

## 数据来源与致谢

- [rmxlinux/EndfieldData](https://github.com/rmxlinux/EndfieldData) — **主数据源**:跟随当前版本的完整 TableCfg(725 表 + i18n)
- [XiaBei-cy/EndfieldData](https://github.com/XiaBei-cy/EndfieldData) — 正式服开服版 TableCfg(历史对照)
- [AndreaFrederica/jei-web](https://github.com/AndreaFrederica/jei-web) — 森空岛 Wiki 物品/配方包(规划接入)
- [AixLnyt/skport-api-docs](https://github.com/AixLnyt/skport-api-docs) — 官方 API 文档(玩家数据,规划接入)
- [JamboChen/endfield-calc](https://github.com/JamboChen/endfield-calc) — 产线规划参考实现

完整清单与取舍理由见 [docs/sources.md](docs/sources.md)。

## 许可与声明

代码随项目分发;游戏内数据(数值表、文本、图标)版权归上海鹰角网络所有,
本项目仅供学习研究,请勿用于商业用途。
