# 终末地数据源调研(2026-09-15)

目标:为 EndData(战斗 + 生产数据站)确定可靠、可持续更新的数据来源。
以下所有结论均经过实际抓取/结构验证,标 ★ 的为已接入 `config/sources.json` 的源。

## 一、游戏解包数值表(TableCfg)—— 主数据源 ★

游戏的全部数值都在 `TableCfg/*.json`(当前 725 张表),文本全部是 `{id: 哈希}` 引用,
需要 `TableCfg/I18nTextTable_CN.json`(147,603 条)反查中文。

| 仓库 | 状态 | 内容 | 结论 |
|---|---|---|---|
| ★ [rmxlinux/EndfieldData](https://github.com/rmxlinux/EndfieldData)(18★) | main,2026-09-08 更新,持续活跃 | **完整数据包:TableCfg 725 表(含 16 语言 i18n)+ LuaScripts + 关卡/地图/NavMesh(共 9.8 万文件,1.5GB)** | **当前采用**。跟随当前游戏版本(1.5.x,33 干员);i18n 在 TableCfg/ 目录内 |
| ~~luosky/EndfieldDataRmxLinux~~ | 2026-03-12 | rmxlinux 旧备份:TableCfg 586 表 + LuaScripts(无 i18n) | **退役**(严格子集,2026-09-15 审查) |
| ~~XiaBei-cy/EndfieldData~~ | 2026-01 | 开服版 TableCfg 561 表 + 15 语言 i18n | **退役**(内容 ⊂ rmxlinux,2026-09-15 审查) |
| ~~[Hengle/EndFieldData-Archive](https://github.com/Hengle/EndFieldData-Archive)~~ | 2025-05-25 | 0.5.5→0.5.28 分版本快照 | **退役**(测试服时代,无当前信息) |
| ~~lsy-404/EndfieldGameData~~ | 2025-01 停更 | 测试服 TableCfg 91 表 | **退役**(子集,2026-09-15 审查) |
| ~~UPON-2021/EndFieldData~~ | 2025-01 停更 | 测试服 TableCfg 360 表 + LuaScripts | **退役**(子集,Lua 已在 rmxlinux,2026-09-15 审查) |
| [4n3u/EndfieldResourceData](https://github.com/4n3u/EndfieldResourceData)(7★) | 活跃 | 各版本资源 manifest(1.0.14 → 1.5.3) | **版本更新监控**用 |
| [BiologyHazard/endfield-archive-library](https://github.com/BiologyHazard/endfield-archive-library) | 每日活跃 | 官方公告/卡池(up-recruit)等 API 响应存档 | 活动与卡池资讯数据,非数值表 |

**版本跟进方式**:所有 git 数据源已统一克隆到本地 `sources/`(`src/collection/fetch.py`
维护,`enddata collection clone` 即更新到远端最新);读取渠道优先级为 **本地 git 仓库 →
jsdelivr → raw → 一图流 COS(备源)→ GitHub API blob**,本地命中时零网络。partial 仓库
(blob:none)的 blob 首次读取会经仓库配置里的代理懒取,之后即本地缓存。

### 已验证的关键表(战斗)

| 表 | 规模 | 内容 |
|---|---|---|
| `CharacterTable` | 33 干员 | 职业、稀有度、武器类型、**按突破阶段分段的等级成长曲线**(生命/攻/防/力/敏/智/意志/暴击/范围…,新版 attrType 为整数枚举) |
| `CharProfessionTable` | 6 | 职业枚举(近卫/重装/辅助/突击…)与图标 |
| `SkillPatchTable` | 509 技能 | 技能 blackboard 数值(atk_scale、冷却、费用类型)——DPS 计算的核心,待加工 |
| `BuffTable` | — | 战斗增益/减益 |
| `WeaponBasicTable` | 79 | 武器稀有度、类型、满级、天赋/潜能引用 |
| `EnemyTable` | 381 | 敌人实例:属性模板引用、修饰器、出生 Buff、精英标记 |
| `EnemyAttributeTemplateTable` | 136 模板 | 敌人**等级曲线**(生命/攻/防)、五系抗性(fire/pulse/cryst/natural/ether,0-100 百分数)、霸体与韧性条 |
| `CharBreakTable` / `CharLevelUpTable` | 5 / 90 | 突破阶段上限与升级消耗 |

### 已验证的关键表(生产)

| 表 | 规模 | 内容 |
|---|---|---|
| `FactoryManualCraftTable` | 102 | 手工制作(烹饪):ingredients/outcomes、稀有度、解锁 |
| `FactoryMachineCraftTable` | 317 | 工厂机器配方:**支持可替代原料组(group)**、机器绑定、进度 |
| `FactoryMachineCrafterTable` | 27+ | 机器模式(如 liquid) |
| `FactoryBuildingTable` / `FactoryItemTable` | — | 工厂建筑与产线物品 |
| `SpaceshipManufactureFormulaTable` | 8 | 飞船制造公式 |
| `ItemTable` + `ItemTypeTable` | 2829 / 101 | 全物品:类型、稀有度、堆叠、获取途径引用、图标 ID |

## 二、社区加工数据 —— 补充源

| 来源 | 内容 | 用途 |
|---|---|---|
| ★ [宏山档案局 end.fffdan.com](https://end.fffdan.com) | 终末地档案站;后端为四主机镜像农场,提供**按路径直取的游戏资源 vfs 接口**与 `/version` 构建号 | **图标资源源**(干员头像/职业/属性/物品图标,WebP);版本更新监控 |
| ★ [天师工具箱 end-tools.fffdan.com](https://end-tools.fffdan.com) | Blazor WASM 工具箱(Database/Gameplay/Web 三模块,.NET 单文件打包):数据浏览(`/data/tables`、`/data/operators/{charId}`)、战斗模拟器(`/simulator/upgrade`)、配方查询、**vfs 资源浏览器**(`/vfsexplorer`) | 无自有数据 API:其 TableCfg 与图标均从 endfield-assets 的 vfs 加载(Database.wasm 二进制字符串证实);其代码是 vfs 路径模式的权威参考 |
| ★ [AndreaFrederica/jei-web](https://github.com/AndreaFrederica/jei-web)(26★) | `public/packs/aef-skland/recipes.json`(**8.5MB 配方图**)+ 森空岛 Wiki 全量物品包(物品 191/装备 165/武器 62/**威胁 56**/干员 24/设备 65…) | 生产配方交叉验证;**敌人中文名**在「威胁」分区;物品图标备用源 |
| ★ [JamboChen/endfield-calc](https://github.com/JamboChen/endfield-calc)(117★) | **320 条手工精校配方**(`{inputs, outputs, facilityId, craftingTime}`)+ `power.ts` 电力、`facilities.ts` 设施、LP 产线求解器 | 产线规划器的参考实现与耗时数据源 |
| [NagiYume/AKEDatabase](https://github.com/NagiYume/AKEDatabase)(36★) | 在线查询工具,自带多语言数据(akedata.wiki) | 对照 |

### fffdan 工具家族资源接口(已实测验证,已接入)

`end.fffdan.com`(档案局)与 `end-tools.fffdan.com`(工具箱)共用同一后端,另有 `blog.fffdan.com`。

- **主机故障转移**(前端按序重试):`endfield-assets.fffdan.com` → `cn/cn2/cn3.endfield.fffdan.com`;
  该 CDN 间歇性抖动,请求需带重试
- **版本端点**:`GET /version` → 游戏构建号(如 `initial_10024360-6_main_10024360-6`,镜像自官方版本信息;注意该站为粉丝项目,非官方),
  构建号基线由 collection 域命令自动写入 data/versions.json,`enddata version` 读取对比
- **资源直取**:`GET /vfs/Bundle/file/assets/beyond/dynamicassets/gameplay/ui/sprites/<路径>`(WebP)。
  下表路径与 git 图标源(`icon_git`)的 `sprites_root` 内子目录/文件名**一一对应**,可在两个渠道间无损切换。

| 资源 | 路径模板 | 对应字段 | 验证 |
|---|---|---|---|
| 干员头像 | `charicon/icon_{charId}.png` | CharacterTable.charId | ✓ |
| 干员圆头像 | `charroundicon/icon_round_{charId}.png` | CharacterTable.charId | ✓(自工具箱代码发现) |
| 职业图标 | `charprofessionicon/{iconId}.png` | CharProfessionTable.iconId | ✓ |
| 属性图标 | `attributeicon/{iconName}.png` | AttributeMetaTable.iconName | ✓ |
| 物品图标 | `itemicon/{iconId}.png` | ItemTable.iconId | ✓ |
| 工厂建筑面板图 | `factory/buildingpanelicon/{icon}.png` | FactoryBuildingTable(精确字段待确认) | 路径来自工具箱代码,文件名未中 |
| 元素/天赋树/背包图标 | `elementicon`、`talenttreeicon`、`inventory` | 待确认 | 同上 |

  采集管线已不再生成 vfs 直链:数据集只存图标裸 id,站点构建(`node web/build.mjs`)按
  `icon_git` 映射从 git 镜像本地化并注入 URL(见下节「游戏图标 git 离线源」)。路径模板保留于
  `config/sources.json` 的 `fffdan_vfs.paths`,作 vfs 资源定位的程序化参考
  (以 `paths_verified`/`paths_unverified` 区分验证状态)。
  档案局自身的 `/endfield-update-diff/*` 版本差分接口当前 404(前端仍在调用,恢复后可提供逐表变更清单);
  两站拉取的原始表与我们一致(CharacterTable/SkillPatchTable/ItemTable…),可作数据旁证。

### 游戏图标 git 离线源(已实测验证,已接入 ★)

[555me/EndfieldAssets](https://github.com/555me/EndfieldAssets)(6.4GB)= 游戏 `assets/beyond`
解包树的 git 转储,与 fffdan vfs **同一套目录结构**(`assets/beyond/dynamicassets/gameplay/ui/sprites/`
下 125 个图标子目录,charicon/itemicon/attributeicon/factory/talenttreeicon 等全部在位)。
按构建号跟版(提交信息即构建号,约 1~3 周一更;2026-09-16 实测 HEAD 为构建 9764758,2026-09-02,
比 rmxlinux 表数据(2026-09-08)落后 6 天,图标资源与数值表版本天然接近)。

- **接入方式**:完整克隆(`--depth 1` 单分支,2026-09-16 起;盘上实测 ~17G = 工作区 ~7G /
  28737 文件 + .git,其中 9 个图标目录约 74MB——itemicon 1740 / charicon 61 / charroundicon 95 /
  charprofessionicon 26 / attributeicon / elementicon / talenttreeicon / inventory / factory,
  其余为 guide 引导图、副本/关卡图、loading 立绘等解包资源,可一并离线取用)。
  代理链路扛不住单连接 ~4GB(57% 处断流),实际按「blob:none 骨架(原生 http.proxy,约 1MB)
  → GitHub API recursive tree 取精确体积 → ≤400MB 逐批 sparse-checkout(单批失败只重试
  当前批)→ 去 sparse 与 partial 滤镜」分批物化(脚本在 sources/ 本地,不入库)。
  由 `enddata collection clone` 统一维护,HEAD 自动入 data/versions.json。
  如需压缩本地占用,可改回 partial+sparse(blob:none + sparse-checkout --no-cone 只取
  图标目录,本地约 146MB 含 .git)
- **消费方式**:数据集只存裸 id → `node web/build.mjs` 按映射复制引用到的图标到
  `dist/icons/sprites/` 并注入 `/icons/sprites/...` 本地 URL(映射与覆盖率注记见
  `config/sources.json` 的 `icon_git`;构建清单产出 `dist/data/_icons.json`)
- **覆盖率实测(构建 9764758)**:items 数据集 1431 个 iconId 命中 1400、equips 252 全命中、
  charicon 32/33;缺的 32 个(itemicon 31 + `icon_chr_9000_endmin`,多为周本奖励等新内容)在
  fffdan vfs **同样 404** —— 游戏本无此资源,构建时注入 `/icons/placeholder.svg` 占位图
  (不产生 404 请求),并在 `_icons.json` 的 `missingIds` 逐项标注
- **备选(不采用)**:`eldritchtools/endfield-assets`(24MB,按英文显示名组织如
  `Advanced_Cognitive_Carrier.png`,items 仅 170 张、干员 31 张,与 iconId 无法映射,仅作装饰素材);
  `JamboChen/endfield-calc` 内置约 200 张生产物品图(EN slug 名);敌人图片与 wiki 图
  (bbs.hycdn.cn,共约 500 张)无 git 源,保持在线直链,待后续寻找 git 静态资源后并入同一构建步骤

已克隆核对(endfield-calc):其配方含 `craftingTime`(秒)字段,而我们的 TableCfg
`FactoryMachineCraftTable` 对应字段是 `totalProgress=12000 / progressRound=2`,两者换算
关系未定;产线规划若需精确耗时,优先从 calc 的精校数据取,或以实测校准 `totalProgress`。

### 一图流(yituliu)数据镜像(已实测验证,应急备源 ★)

- **TableCfg HTTP 直取**:`https://cos.yituliu.cn/endfield/endfielddata/TableCfg/<表名>.json`
  (无需 git;已验证可用)
- ⚠️ **实测为开服版快照**(25 角色,落后 rmxlinux 8 个角色,与 XiaBei 同世代,2026-09-15 逐项对比):
  仅作 git 源全部失效时的应急备源,不作跟版源
- 开源生态:前端 [Arknights-yituliu/ef-frontend-v1](https://github.com/Arknights-yituliu/ef-frontend-v1)
  (已退役,端点已文档化;后端 `endfield-yituliu-backend`、资产仓库可按需克隆)
- 子站:`factory.ef.yituliu.cn`(量化计算器)、`ef.yituliu.cn/resources/essence-recognizer`(基质识别器)

### 工具站与 Wiki(参考生态,暂不采集)

| 站点 | 类型 | 备注 |
|---|---|---|
| [endfieldtools.dev](https://endfieldtools.dev) | 英文数据库+工具 | Next.js SSR,API 未公开文档化 |
| [caffuchin0/zmdgraph](https://caffuchin0.github.io/zmdgraph) | 养成规划计算器 | 已退役(2026-09-15 审查,可重克隆);数据内嵌于 `js/data.js`(养成数值交叉验证) |
| [mikunyaaa/endfield-calculator](https://mikunyaaa.github.io/endfield-calculator) | 产线分流计算器 | 已退役(仓库内无数据,运行时远程加载) |
| [maaend.com](https://maaend.com) | 自动化助手 | MaaEnd 智能自动化,数据无关 |
| [end.canmoe.com](https://end.canmoe.com) | CEP 规划器 | 原终末地基质规划器(Next.js) |
| [dige.aunly.cn](https://dige.aunly.cn) | 工厂设计器 | D.I.G.E. 能源生产/存储系统设计 |
| [www.end-axis.com/timeline](https://www.end-axis.com/timeline) | 排轴工具 | 活动时间线 |
| [www.gamekee.com/zmd](https://www.gamekee.com/zmd) | 攻略 Wiki | GameKee |
| [warfarin.wiki/cn/operators](https://warfarin.wiki/cn/operators) | 干员 Wiki | SSR 内嵌数据,无公开 JSON 端点 |
| end.wiki | Wiki | DNS 解析失败(2026-09-15),不可达 |

以上登记于 `config/sources.json` 的 `tools_and_wikis`,后续需要工具逻辑参考或补数据时按图索骥。

## 三、官方 API —— 玩家侧数据(暂不自动采集)

来自 [AixLnyt/skport-api-docs](https://github.com/AixLnyt/skport-api-docs)(非官方文档,已克隆核对:含完整 OAuth 流程、`cred`/`salt` 签名算法与六域名划分):

| 域名 | 用途 |
|---|---|
| `as.gryphline.com` | 账号认证、OAuth |
| `ef-webview.gryphline.com` | 抽卡记录、卡池 metadata(URL token,免签名) |
| `zonai.skport.com` | 全部游戏资料 API(需 `cred` + HMAC V2 签名) |
| `static.skport.com` | 静态资源(图片 CDN) |

- **Skport API** 端点:`GET /web/v1/wiki/item/catalog`(官方物品库全量)、`GET /web/v1/wiki/char-pool` / `weapon-pool`(卡池)、`GET /api/v1/game/endfield/card/detail`(玩家完整游戏卡)
- **抽卡记录**:`https://ef-webview.gryphline.com` 的 `/api/content`、`/api/record/char`、`/api/record/weapon`
- ~~[daydreamer-json/ak-endfield-api-archive](https://github.com/daydreamer-json/ak-endfield-api-archive)~~(55★,每日自动存档):**退役**(版本监控已由 fffdan /version 覆盖;资源 manifest 用 4n3u 替代),已克隆核对过其内置 API 客户端 SDK。

玩家个人数据(练度/抽卡)需要用户自己的凭据,涉及账号安全,后续做成"用户自选导入"功能,不做服务端集中采集。

## 四、明确不使用的源

- 各类作弊/修改器仓库(Endfield-Ultra-Vision、Endfield-Hack 等)——与数据站无关且违反游戏条款。
- 盗版客户端解包资源分发。

## 五、已知缺口与下一步

1. ~~数据新鲜度~~ 已解决:rmxlinux/EndfieldData HEAD 即当前版本(2026-09,725 表 + i18n,33 干员),
   已切换为主数据源。后续跟进其 main 分支更新即可。
2. **敌人中文名缺失**:新旧解包表中敌人显示名哈希均为 0(381 个敌人全以 templateId 兜底),
   从 jei-web「威胁」分区或 Skport wiki 目录补全。
3. **技能/Buff 数值**:`SkillPatchTable`(新版 6.5MB)已抓取未加工,是战斗计算(DPS 模拟)的下一块拼图;
   注意新版技能数值可能同样使用整数枚举。
4. ~~物品图标~~ 已解决并升级为离线:git 图标源 555me/EndfieldAssets 已接入,
   站点构建期本地化,dist/ 站点零外链(见「游戏图标 git 离线源」节);
   敌人图片(bbs.hycdn.cn,无 git 源)与 32 个双方皆 404 的图标仍待补。
5. **生产系统深度数据**:电力、物流带、流派加成表已可从 rmxlinux 抓取,尚未加工;
   机器配方的 `totalProgress/progressRound` 与实际秒数的换算待实测(endfield-calc 用手工维护的 craftingTime)。
6. **战斗属性枚举**:新版 `attrType` 为整数(AttributeMetaTable 可反查图标名),
   `src/tools/tables.py` 已内置核心 15 项映射,扩展数值系统时需同步补全。

## 六、本机网络备忘(采集脚本环境)

- 本机 git 全局配置含 `url.git@github.com:.insteadOf=https://github.com/`,会把 https 改写成 SSH 导致克隆失败;
  脚本化克隆需 `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null` 绕过(`datasource.git_env` 已内置)。
- GitHub 直连不稳定,代理为 `http://10.1.20.20:7890`(/etc/proxychains4.conf 同源):
  - git 用 `-c http.proxy=...`(libcurl 原生代理)最稳;proxychains4 的 LD_PRELOAD 层会让 git 长连接卡死。
  - 文件下载走 `cdn.jsdelivr.net/gh/<repo>@<branch>/<path>`(20MB 内),大文件用 GitHub API blob 兜底。
  - 克隆大仓库务必加 `--depth 1` 与低速熔断(`http.lowSpeedLimit/lowSpeedTime`,注意它们是 git 配置而非环境变量)。
- **数据源本地化**:git 形态的源统一克隆在 `sources/`(已 gitignore),由 `src/collection/fetch.py`
  维护(`enddata collection clone`)。rmxlinux/jei-web 已完整本地化(2026-09-16,proxychains 实测 11MB/s);
  今后新仓库默认 partial 克隆(`--filter=blob:none --no-checkout`)按需懒取即可。
  ⚠️ 非 sparse 的 partial 仓库更新后**不要** `reset --hard`(会触发全量 blob 懒取),用 `git update-ref`
  移动分支引用;配置了 `sparse` 的仓库 reset --hard 只物化 sparse 范围内的
  blob,可安全使用(fetch 后直接 `reset --hard FETCH_HEAD`)。
- **速度实测(2026-09-16)**:`proxychains4 -q git clone` + `GIT_CONFIG_GLOBAL=/dev/null`(绕过 insteadOf)
  为最优路径——jei-web 114MB/10s、rmxlinux 1.5GB 约 12 分钟完整克隆成功;远快于 git 原生
  `http.proxy`(170KB/s 且长传输易断流)。
