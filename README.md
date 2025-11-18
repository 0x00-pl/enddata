# EndData · 明日方舟:终末地 数据站

收集《明日方舟:终末地》的**战斗**与**生产**数据,加工成报告并以网页展示。
项目按两大功能组织:**数据采集(collection)→ 数据展示(site)**。

采集零第三方依赖(Python 标准库),展示由零 npm 依赖的 Node 构建脚本
(`node web/build.mjs`)生成**零外链**的静态站点(游戏图标在构建期本地化)。

## 当前状态(v0)

已跑通端到端流水线,当前数据集(来源 rmxlinux@main,2026-09-08):

| 数据集 | 条数 | 来源表 |
|---|---|---|
| 干员(含 1 级/满级面板) | 33 | CharacterTable × CharProfessionTable × CharBreakTable |
| 物品 | 2829 | ItemTable × ItemTypeTable × I18nTextTable_CN |
| 生产配方(手工/工厂/飞船) | 427 | FactoryManualCraftTable + FactoryMachineCraftTable + SpaceshipManufactureFormulaTable |
| 武器 | 79 | WeaponBasicTable |
| 装备(含词条/套装) | 258 + 24 套装 | EquipTable × EquipSuitTable × ItemTable |
| 敌人(属性/抗性/韧性/霸体) | 381 | EnemyTable × EnemyAttributeTemplateTable |

干员/物品/装备数据集只存图标裸 id;站点构建时从 git 图标源(555me/EndfieldAssets,
fffdan vfs 同源镜像)落地为本地文件并注入 URL,dist/ 站点零外链可离线使用
(两个源都缺失的 32 个图标显示占位图,清单见 dist/data/_icons.json)。

数据源调研结论见 **[docs/sources.md](docs/sources.md)**,字段结构见 **[docs/data-model.md](docs/data-model.md)**,
来源血缘关系与统计见 **[docs/data-lineage.md](docs/data-lineage.md)**(原则:同一数据优先追溯 git 项目,无 git 才用网页渠道)。

## 快速开始

项目由 Poetry 管理(运行时零第三方依赖),首次使用先 `poetry install`:

统一 CLI(子命令见 `poetry run enddata --help`):

```bash
# 数据采集:原始表按需自动补抓 + 各产物数据集(只存图标裸 id,不生成 URL)
poetry run enddata collection clone                      # 更新 sources/ 下数据源仓库(含图标 git 源)
poetry run enddata collection fetch                      # 更新仓库 + 刷新构建号 + 预热原始表
poetry run enddata collection characters --force         # 强制重抓干员依赖的原始表
poetry run enddata collection items                      # 只生成 items 数据集(缺原始表自动补抓)
poetry run enddata collection all --lang en              # 指定默认翻译语言构建(可选 CN/TC/EN/JP/KR/FR/DE/IT/MX/BR/RU/ID/TH/VN)
poetry run enddata collection all                        # 依赖全部 collection,产出所有数据集与报告

# 站点构建:JS 工具链生成零外链的 dist/(复制静态资源 + 图标本地化 + 注入 URL)
npm run build                                          # 即 node web/build.mjs(js 项目根 = 仓库根)

# 本地预览(服务 dist/ 产物;数据集更新后需重新构建)
python3 -m http.server 8321 --bind 127.0.0.1 --directory dist
# 打开 http://127.0.0.1:8321/

# 辅助:版本报告(读取 data/versions.json,离线可用)
poetry run enddata version
```

导入采用规范的包内绝对导入(`from tools.datasource import ...`),不做任何 sys.path 修改,
因此请在 Poetry 虚拟环境内运行(`poetry run`/`poetry shell`,需先 `poetry install`)。

## 目录结构

```
enddata/
├── pyproject.toml          # Poetry 项目定义与命令行入口
├── poetry.lock
├── config/
│   └── sources.json        # 数据源注册表(git 仓库清单/产物依赖表/官方 API 端点/资源路径模板)
├── docs/                   # 项目文档
│   ├── sources.md          # 数据源调研报告
│   ├── data-model.md       # 原始表 → 数据集的流水线与字段说明
│   └── data-lineage.md     # 来源血缘关系、追溯规则与统计
├── src/                    # 功能代码
│   ├── enddata/            #   CLI 入口(poetry run enddata <子命令>)
│   │   └── cli.py              # collection {clone,fetch,all,<产物>} / version
│   ├── collection/         #   ① 数据采集:原始数据的收集 + 初步处理(按产物一个模块)
│   │   ├── fetch.py            # 数据源仓库同步(sources/)+ 原始表按需加载
│   │   ├── characters.py items.py recipes.py weapons.py equips.py enemies.py
│   │   └── build_all.py        # 统一入口:全部产物 + meta + 构建报告
│   └── tools/              #   工具库
│       ├── datasource.py       # 数据源访问:本地git → jsdelivr → raw → API 多级回退
│       ├── tables.py           # 表加载 + i18n 反查 + 属性枚举 + vfs 链接
│       └── versions.py         # data/versions.json 读写 + enddata version 报告
├── sources/                # 数据源(5 个本地 git 克隆,gitignore;含 6.4GB 图标源完整克隆,经血统审查)
├── data/                   # 生成的数据:各产物目录(每条一个 <id>.json + index.json)+ meta + versions.json(数据集 gitignore)
├── reports/                # 生成的报告(build-report.md,入库)
├── web/                    # ② 网页展示的源码(唯一手写前端源码,不含生成产物)
│   ├── index.html          #   总览/干员/武器/装备/物品/配方/敌人 七个分页
│   ├── assets/             #   style.css / app.js(读取 /data/)
│   └── build.mjs           #   站点构建脚本(零 npm 依赖):web/ 源码 + data/ → dist/
├── package.json            # JS 构建 npm 入口(js 项目根 = 仓库根):npm run build
└── dist/                   # 构建产物(gitignore,只放生成物):静态资源 + 处理后数据 + 本地图标,http.server 服务目录
```

## 数据来源与致谢

- [rmxlinux/EndfieldData](https://github.com/rmxlinux/EndfieldData) — **主数据源**:跟随当前版本的完整 TableCfg(725 表 + i18n)
- [AndreaFrederica/jei-web](https://github.com/AndreaFrederica/jei-web) — 森空岛 Wiki 物品/配方包(规划接入)
- [AixLnyt/skport-api-docs](https://github.com/AixLnyt/skport-api-docs) — 官方 API 文档(玩家数据,规划接入)
- [JamboChen/endfield-calc](https://github.com/JamboChen/endfield-calc) — 产线规划参考实现
- [555me/EndfieldAssets](https://github.com/555me/EndfieldAssets) — 游戏 `assets/beyond` 解包树的 git 镜像(图标离线源,与 fffdan vfs 同源;partial+sparse 只取图标目录)
- [宏山档案局 end.fffdan.com](https://end.fffdan.com) / [天师工具箱 end-tools.fffdan.com](https://end-tools.fffdan.com) — 图标资源 vfs 与版本监控

完整清单、血缘关系与取舍理由见 [docs/sources.md](docs/sources.md) 与 [docs/data-lineage.md](docs/data-lineage.md)。

## 许可与声明

代码随项目分发;游戏内数据(数值表、文本、图标)版权归上海鹰角网络所有,
本项目仅供学习研究,请勿用于商业用途。
