# 数据来源关系(血缘)与统计

更新:2026-09-16。本文回答三个问题:每类数据从哪来、优先走什么渠道、本地化程度如何。

## 一、追溯规则(渠道解析策略)

> **原则:同一数据优先追溯到 git 项目;没有 git 项目的,才允许网页/HTTP 渠道。**

实际解析顺序(`tools/datasource.py` 统一实现):

```
1. sources/ 本地 git 克隆      ← 零网络,首选(src/collection/fetch.py 维护;
                                  缺失 blob 由 git 按需懒取并落本地对象库)
2. jsdelivr / raw.githubusercontent ← 无配额 HTTP(git 项目文件的网页形态)
3. 一图流 COS(TableCfg 专用)     ← 无 git 的 HTTP 镜像,开服版应急备源
4. GitHub API blob                ← 有配额,最后兜底
```

注册表:`config/sources.json`(`git.clone` 列出全部 git 源;`sources.*` 记录各源角色与验证状态)。

## 二、血缘关系图

```mermaid
graph TD
    GAME[明日方舟:终末地 游戏本体/官方构建]

    GAME -->|"解包(datamining)"| RMX
    GAME -->|"官方服务(非git)"| SKPORT[Skport/Gryphline API<br>zonai.skport.com 等]
    GAME -->|"官方公告/卡池"| BHAZ

    subgraph GIT1[git:解包数据仓库]
        RMX[rmxlinux/EndfieldData ★主源<br>TableCfg 725表+i18n+Lua+关卡]
        ICONS[555me/EndfieldAssets ★图标源<br>assets/beyond 解包树 6.4GB<br>完整克隆 6.4GB(2026-09-16 起)]
        XIABEI[XiaBei-cy/EndfieldData 等 5 个<br>历史对照镜像/测试服快照<br>⚠️ 2026-09-15 审查退役]
    end

    subgraph GIT2[git:官方 API 派生]
        SKPORTDOC[AixLnyt/skport-api-docs<br>API 逆向文档]
        BHAZ[BiologyHazard/endfield-archive-library<br>公告/卡池存档]
    end

    subgraph GIT3[git:社区手工精校]
        CALC[JamboChen/endfield-calc<br>320条配方+耗时+电力]
    end

    subgraph NOWEB[无 git:HTTP/网页渠道]
        FFFDAN_VFS[endfield-assets.fffdan.com vfs<br>游戏资源直取:图标 WebP]
        YITULIU_COS[cos.yituliu.cn/endfield/endfielddata<br>TableCfg HTTP 镜像]
        WIKIS[Wiki/工具站网页<br>gamekee / warfarin / CEP / D.I.G.E. 等]
    end

    RMX -->|"cat-file 本地直读|懒取"| ENDDATA
    YITULIU_COS -.->|"备源(尺寸与rmxlinux有差异)"| ENDDATA
    FFFDAN_VFS -.->|"路径模式参考 + 版本监控"| ENDDATA
    ICONS -->|"图标裸 id → 构建期本地化"| SITEBUILD
    CALC -.->|"craftingTime/电力参考"| ENDDATA
    SKPORT -.->|"玩家数据(规划:用户自选导入)"| ENDDATA
    BHAZ -.->|"公告/卡池(规划)"| ENDDATA

    subgraph ENDDATA[EndData 本项目]
        FETCH[fetch.py] --> BUILD[collection/build_all.py] --> SITE[data/ 数据集目录<br>只存图标裸 id] 
        SITE --> SITEBUILD[web/build.mjs<br>复制图标 + 注入本地 URL] --> DIST[dist/ 零外链站点<br>http.server 服务目录]
    end

    GAME -.->|"同源旁证:两站消费同一份解包"| FFFDAN_SPA[宏山档案局/天师工具箱<br>消费同一 vfs 后端]
```

**防重复采集说明**:宏山档案局与天师工具箱消费的就是同一份解包 TableCfg(其二进制字符串
与 rmxlinux 仓库同构),因此本项目**只从 git 源取数值**。图标资源(数值表不含贴图)同样
优先 git 形态:555me/EndfieldAssets 与 fffdan vfs 同源同构(同一棵 assets/beyond 解包树),
已作为 ★ 图标源接入(完整克隆),由站点构建
(`node web/build.mjs`)落地为本地文件并注入 URL —— dist/ 站点零外链;
fffdan vfs 降为备源与路径模式参考。敌人图片与 wiki 图(bbs.hycdn.cn,约 500 张)
暂无 git 形态,属"无 git 才用网页"的合法情形,保持在线直链。
一图流 COS 同理:其数值表与 rmxlinux 同源同构,仅作 HTTP 备源,不作主源。

## 二·五、血统确认(2026-09-15 实测)

### 内容世代对比(CharacterTable + i18n)

| 源 | 渠道 | 角色数 | i18n 条数 | 最新角色 | 世代判定 |
|---|---|---|---|---|---|
| rmxlinux/EndfieldData | git 本地 | **33** | **147,603** | chr_0032_lizhiyan | **当前版本(唯一跟版)** |
| luosky/EndfieldDataRmxLinux | git 本地 | 26 | 96,165 | chr_0029_pograni | 2026-03 世代 |
| 一图流 COS | HTTP | 25 | — | chr_0025_ardelia | **开服版世代** |
| XiaBei-cy/EndfieldData | git 本地 | 25 | (独立 i18n 目录) | chr_0012_avywen | 开服版世代 |

共同角色字段逐项一致(稀有度/成长曲线相同;rmxlinux 每角色多 3 个新字段)。
**结论**:四源同出一脉(游戏解包),差别只是解包时点;cos 与 XiaBei 同为开服世代,
内容上是彼此的冗余而非互补;rmxlinux 是唯一持续跟版的数据源。

### 提交频率(近 90 天,2026-09-15 统计)

| 仓库 | 近90天提交 | 最近提交 | 活跃度判定 |
|---|---|---|---|
| JamboChen/endfield-calc | **16** | 2026-09-04 | 最活跃(手工精校持续进行) |
| daydreamer-json/ak-endfield-api-archive | 13 | 2026-09-05 | 活跃(近自动) |
| rmxlinux/EndfieldData | 10 | 2026-09-08 | 活跃(随游戏版本提交) |
| AndreaFrederica/jei-web | 2 | 2026-08-06 | 放缓(数据包趋稳) |

## 二·五·一、数据源审查(2026-09-15)

原则:无新增信息(内容被保留源完全覆盖、或仓库内无数据)的数据源退役;
保留血统最优/质量最高/信息独特者,并优先使用本地 git 克隆。

| 处置 | 源 | 理由 |
|---|---|---|
| ✅ 保留 | rmxlinux/EndfieldData | 唯一跟版(33 角色/725 表),血统最优 |
| ✅ 保留 | jei-web | 森空岛 Wiki 血统(与解包互补):敌人中文名、物品包 |
| ✅ 保留 | endfield-calc | 人工精校(耗时/电力),近 90 天 16 次提交最活跃 |
| ✅ 保留 | skport-api-docs | API 文档(236KB,玩家数据功能需要) |
| ❌ 退役 | luosky / XiaBei / Hengle / lsy-404 / UPON | 旧版备份或测试服子集,内容被 rmxlinux 覆盖 |
| ❌ 退役 | mikunyaaa / ef-frontend-v1 | 仓库内无数据(纯代码),端点已文档化 |
| ❌ 退役(二轮) | ak-endfield-api-archive(182MB) | 版本监控已由 fffdan /version 覆盖,manifest 可用 4n3u 替代 |
| ❌ 退役(二轮) | zmdgraph(31MB) | 养成数据为解包衍生品,交叉验证可随时重克隆 |

退役源保留在 `config/sources.json` 的 `git.retired`(含复克隆所需信息),需要时可随时恢复。

## 二·六、推荐优先数据来源(按数据类别)

> 图例:P0=当前在用主源 P1=推荐备源 P2=历史对照/参考 R=规划接入

| 数据类别 | 推荐顺序 |
|---|---|
| **数值表 TableCfg** | **P0 rmxlinux(git 本地)** → P1 一图流 COS(HTTP,开服版仅应急)→ P2 luosky/XiaBei(历史) |
| **中文 i18n** | **P0 rmxlinux**(147,603 条,唯一含最新文本) → P2 XiaBei 独立 i18n |
| **图标资源**(头像/职业/物品) | **P0 555me/EndfieldAssets**(git,完整克隆,构建期本地化)→ P1 fffdan vfs(HTTP,同构备源)→ P2 jei-web 森空岛物品包(git) |
| **生产配方结构** | **P0 rmxlinux FactoryCraftTable 家族**(427 条) |
| **配方耗时/电力** | **P0 endfield-calc**(git,最活跃,craftingTime 精校)→ P1 rmxlinux totalProgress(换算待实测) |
| **技能数值(DPS)** | **P0 rmxlinux SkillPatchTable**(509 技能,待加工);参考 endfield-calc 模拟器实现 |
| **敌人中文名** | **P0 jei-web「威胁」分区**(git);备选 Skport wiki 目录(HTTP) |
| **养成数值验证** | P2 重克隆 CaffuChin0/zmdgraph(见 git.retired);P1 本表成长曲线自洽校验 |
| **版本监控** | **P0 rmxlinux main 提交**;P1 fffdan `/version`(HTTP);P2 4n3u manifest |
| **公告/卡池** | **P0 BiologyHazard archive**(git,需要时克隆);P2 ak-archive(已退役,可恢复) |
| **客户端代码结构**(类面/字段/协议) | **P0 DeftSolutions-dev/IL2CPP-Dumper**(git,1.2.4 桩 dump;不含方法体,玩法逻辑走 IFix 热修) |
| **玩法调度逻辑**(工厂传输优先级等) | 无源:服务器权威 + IFix 补丁,两端均不在任何 git 数据源内;仅可运行时实测 |
| **玩家个人数据** | R Skport API(无 git,唯一渠道,需用户凭据) |

## 三、数据类别 × 来源 × 渠道

| 数据类别 | 主源(git) | 备源 | 渠道 | 状态 |
|---|---|---|---|---|
| **数值表 TableCfg**(战斗+生产) | rmxlinux/EndfieldData@main | 一图流 COS(HTTP);XiaBei/luosky 历史对照 | 本地 git 直读 24/24 核心表 | ✅ 在用 |
| **中文文本 i18n** | 同上(TableCfg/I18nTextTable_CN,147,603 条) | — | 本地 git | ✅ 在用 |
| **干员/物品/职业图标** | 555me/EndfieldAssets(git,完整克隆) | fffdan vfs(HTTP,同构) | 本地 git → `node web/build.mjs` 落地 dist/ 并注入 URL;敌人/wiki 图(bbs.hycdn.cn)暂为在线直链 | ✅ 在用(2026-09-16 起) |
| **生产配方**(手工/工厂/飞船) | rmxlinux(427 条,同数值表) | endfield-calc 精校 320 条(craftingTime 秒数) | 本地 git | ✅ 在用 |
| **配方制造耗时** | 无解包换算定论 | endfield-calc 手工数据(git) | 本地 git | ⏳ 待校准 |
| **技能/Buff 数值** | rmxlinux SkillPatchTable(509 技能,已抓取) | — | 本地 git | ⏳ 已取未加工 |
| **敌人中文名** | 无(解包哈希为 0) | jei-web 森空岛包「威胁」分区(git) | 本地 git | ⏳ 待接入 |
| **养成数值交叉验证** | zmdgraph(git,数据内嵌 js) | — | 本地 git | 参考 |
| **版本更新监控** | rmxlinux main 提交(git) | 宏山档案局 /version(HTTP);P2 4n3u manifest | 本地 git + HTTP | ✅ 在用(`enddata version`) |
| **公告/卡池资讯** | BiologyHazard/endfield-archive-library(git) | — | 本地 git | ⏳ 规划 |
| **客户端代码结构** | DeftSolutions-dev/IL2CPP-Dumper(1.2.4 桩 dump,git) | — | 本地 git | ✅ 在用(2026-09-19 起,结构参考) |
| **玩家个人数据**(练度/抽卡) | 无 git(Skport 官方 API) | skport-api-docs 仅为文档(git) | HTTP+签名 | ⏳ 规划(用户自选导入) |

## 四、统计(2026-09-16)

### 本地 git 仓库(`sources/`,已 gitignore)——2026-09-19 实测

| 指标 | 值 |
|---|---|
| 仓库总数 | **6**(审查前 13,累计退役 9;2026-09-19 新增 IL2CPP dump) |
| 总体积 | **约 20.5 GB**(555me 图标源 17G 为大头;rmxlinux/jei-web 已完整物化,不再走 partial 懒取) |
| 主源核心表本地可直读 | **24/24(100%,零网络)** |

| 仓库 | 体积 | 角色 |
|---|---|---|
| 555me/EndfieldAssets | 17G | **图标源**(完整克隆:工作区 ~7G / 28737 文件,其中 9 个图标目录约 74MB;大头部 guide 引导图、副本/关卡图、loading 立绘) |
| rmxlinux/EndfieldData | 3.1G | **主源**(完整物化:工作区 1.5G + 累积懒取对象) |
| JamboChen/endfield-calc | 69M | 产线精校数据(craftingTime/电力) |
| AndreaFrederica/jei-web | 114M | 森空岛 Wiki 包(敌人中文名,规划) |
| AixLnyt/skport-api-docs | 0.24M | 官方 API 文档 |
| DeftSolutions-dev/IL2CPP-Dumper | 187M | **客户端代码面**(1.2.4 桩 dump ×2 格式 + dumper 工具源码) |

### 数据集产出(`data/`,构建于 rmxlinux@main 2026-09-08)

图标一律只存裸 id,URL 由站点构建期注入(见上表「图标资源」行)。

| 数据集 | 条数 |
|---|---|
| 干员(icon = `icon_{charId}`,professionIcon = iconId) | 33 |
| 物品(icon = iconId) | 2829(2808 有图标 id) |
| 生产配方 | 427 |
| 武器 | 79 |
| 装备(icon = iconId) | 258 + 24 套装 |
| 敌人(icon 为 bbs.hycdn.cn 在线直链) | 381 |

站点构建实测(dist/,2026-09-16):落地图标 **1438** 个(items 1400 + equips 252 + characters 38,
按去重后合计 1438),缺失 32(游戏本无此资源,vfs 同样 404);dist/ 体积约 48MB。

### 渠道健康度

| 渠道 | 配额/限制 | 备注 |
|---|---|---|
| 本地 git | 无 | 首选;更新靠 `collection/fetch.py` |
| jsdelivr | 单文件 20MB | GitHub 文件的 CDN 形态 |
| 一图流 COS | 无已知限制 | 备源;尺寸与主源有差异需比对 |
| fffdan vfs | CDN 间歇抖动,需重试 | 图标专用 |
| GitHub API | 60 次/小时(匿名) | 仅 blob 兜底 |

## 五、维护约定

1. 新增数据源时先找 git 项目;确实无 git 的(如 fffdan vfs、bbs.hycdn.cn wiki 图)才允许
   HTTP,并在 `config/sources.json` 标注 `note` 说明原因。
2. 同一数据出现多个来源时,以「跟版最新 > 结构完整 > 可本地化」排序,其余降级为
   历史对照(参考现有主源/镜像分层)。
3. 更新流程:`enddata collection clone`(更新 git 源)→ `enddata collection all`
   (按需读表并产出全部数据集与报告)→ 仓库根 `npm run build`(生成零外链 dist/)
   → 提交 `reports/` 变更。采集重跑后 URL 字段还原为裸 id,必须重跑站点构建。
