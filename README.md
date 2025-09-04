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

数据源调研结论见 **[docs/sources.md](docs/sources.md)**,字段结构见 **[docs/data-model.md](docs/data-model.md)**。

## 快速开始

```bash
# 1. 抓取原始数值表(已有本地缓存则跳过)
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
│   └── sources.json        # 数据源注册表(仓库/分支/核心表清单/官方 API 端点)
├── docs/
│   ├── sources.md          # 数据源调研报告(核心文档)
│   └── data-model.md       # 原始表 → 数据集的流水线与字段说明
├── scripts/
│   ├── enddata_http.py     # 抓取公共库:jsdelivr → raw → GitHub API 三级回退 + 本地缓存
│   ├── fetch_tablecfg.py   # 抓取 TableCfg 数值表到 data/raw/
│   └── build_dataset.py    # i18n 反查 + 表间 join,输出 site/data/*.json
├── data/
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
