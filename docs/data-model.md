# 数据模型:原始表 → 数据集

## 流水线

```
sources/ 本地 git 仓库 (rmxlinux/EndfieldData,跟随当前游戏版本)
        │  enddata collection clone(fetch.update_repos 同步仓库)
        ▼
collection/<产物>.py 按需读取原始表
        │  tools/datasource.py:本地 git cat-file 直读,缺 blob 自动懒取;
        │    force 或不可用时回退 jsdelivr → raw → 一图流 COS → GitHub API
        ▼
        │  i18n 反查、表间 join、attrType 枚举翻译
        ▼
data/<产物>/          ← 生成的数据集目录(每条一个 <id>.json + 轻量索引 index.json,
        │               套装/强化全局配置在 data/equips/_global.json),经 web/build.mjs
        │               构建为 dist/(图标落地 + 注入本地 URL)后由站点消费
        ▼
data/meta.json / data/versions.json   ← 构建信息 / 游戏构建号与各仓库 HEAD
reports/build-report.md               ← 人类可读构建报告
```

## 文本引用规则

数值表中一切文本都是 `{"id": <64位哈希>, "text": null}` 形式,
用 `I18nTextTable_CN.json` 以 `str(id)` 为键反查中文。哈希为 `0` 表示无文本。
(rmxlinux 的 i18n 表就在 TableCfg/ 目录内;XiaBei-cy 旧镜像在独立 i18n/ 目录。)

## 属性枚举(重要)

新版解包把 `attrType` 从字符串改成了整数。`src/tools/tables.py` 内置
`INT_ATTR_MAP`(0=Level,1=MaxHp,2=Atk,3=Def,9=暴击率,10=暴击伤害,
39-42=力/敏/智/意志,4-7/48/55=各系受伤倍率),依据 `TableCfg/AttributeMetaTable.json`
的 iconName 反查并经数值交叉验证。旧镜像的字符串 attrType 原样透传,两版兼容。

## 输出数据集结构

### characters/ — 干员目录(战斗,多数据源综合)

目录化输出:`index.json` 为轻量列表(不含 skills/wiki/sources,列表页用);
每名干员一个完整文件 `data/characters/<charId>.json`:
```json
```json
{
  "id": "chr_0005_chen", "name": "陈千语", "enName": "Chen",
  "profession": "GUARD", "professionName": "近卫",
  "professionIcon": "…vfs…/charprofessionicon/….png",
  "icon": "…vfs…/charicon/icon_chr_0005_chen.png",
  "rarity": 6, "weaponType": "Sword", "cv": "...", "maxLevel": 60,
  "lv1":   { "MaxHp": 500, "Atk": 30, "Def": 0, "Str": 10.8, "Agi": 20.6, "Wisd": 8.9, "Will": 9.7 },
  "lvMax": { "...": "同上结构,最终突破满级面板" },
  "skillGroupMap": {
    "chr_0005_chen_NormalAttack":  { "skillGroupType": 0, "icon": "icon_attack_sword",
      "name": "…", "desc": "…",
      "conditionId1": "", "conditionIcon1": "", "conditionName1": "", "conditionDesc1": "",
      "conditionId2": "", "conditionIcon2": "", "conditionName2": "", "conditionDesc2": "",
      "conditionDescInactive1": "", "conditionDescInactive2": "",
      "conditionPostDesc1": "", "conditionPostDesc2": "",
      "skillList": [ { "skillId": "chr_0005_chen_attack1", "coolDown": 0.0,
                       "levels": [ { "level": 1, "blackboard": { "atk_scale": 0.1 } },
                                   { "level": 2, "blackboard": { "…": "…" } } ] },
                     { "skillId": "chr_0005_chen_attack2", "…": "…" } ] },
    "chr_0005_chen_NormalSkill":   { "…": "同结构" },
    "chr_0005_chen_UltimateSkill": { "…": "同结构" },
    "chr_0005_chen_ComboSkill":    { "…": "同结构" }
  },
  "wiki":  { "itemId": "12", "rarityStars": 5, "icon": "https://bbs.hycdn.cn/….png",
             "detail": { "chapters": [ { "title": "能力扩延", "widgets": [
                 { "title": "战斗技能", "tabs": [ { "name": "归穹宇", "type": "战技",
                     "imgUrl": "…gif", "desc": "对目标敌人进行上挑攻击,造成物理伤害和击飞。",
                     "text": "…" } ] },
                 { "title": "天赋阵列", "tabs": [ { "name": "", "text": "游刃干员敏捷能力提高10/15/15/20。" } ] } ] } ] } },
  "weapon":  { "id": "wpn_sword_0003", "name": "Tarr 11", "rarity": 3 },
  "recommendedWeapons": { "weaponIds1": ["…"], "weaponIds2": ["…"], "weaponIds3": [] },
  "battleTags": ["击飞", "失衡"],
  "stationTags": [ { "tag": "erudit", "desc": "博闻强记·博采众长\n百家之法…" } ],
  "potentials": [ { "level": 1, "name": "绝影",
                    "desc": "对生命值少于{hp_remain:0%}的敌人造成的伤害+{extra_dmg:0%}。",
                    "values": { "extra_dmg": 0.0, "hp_remain": 0.5 },
                    "effectId": "chr_0005_chen_talent_1_1",
                    "materials": [ { "id": "item_charpotentialup_chr_0005_chen", "count": 1 } ],
                    "skills": [] } ],
  "sources": ["rmxlinux@TableCfg", "rmxlinux@SkillPatchTable", "jei-web@森空岛Wiki干员包"]
}
```
多源说明:
- 基础与面板来自 CharacterTable(本地 git 直读);技能按 skillId 分组,
  `levels` 是逐级 blackboard 数值板;技能名称/描述取 CharGrowthTable.skillGroupMap
  (name/desc 哈希 → I18nTextTable,经 skillIdList 精确 join + 技能族前缀回退,
  富文本标签已剥离;SkillPatchTable 行内哈希恒为 0)。当前覆盖 357/360:
  yvonne 被动、wulfa 连携变体不在任何 skillGroupMap,lizhiyan 连携的 desc 哈希
  不在 i18n 转储——均为解包数据本身的缺口,待上游更新)
- `skillGroupMap` 与源表 CharGrowthTable.skillGroupMap 同构(组对象 = 源组全字段,
  i18n 引用已反查为文本):键 = `<charId>_<族>` 完整组 id,即四个主技能槽
  `NormalAttack`(普攻,skillGroupType=0)/`NormalSkill`(战技,1)/
  `UltimateSkill`(终结,2)/`ComboSkill`(连携,3);普攻的分段 attack1..5、
  重击/下落、浮空形态变体随所属主技能入组。未入组的附属技能(被动、
  个别变体)入 `unknown`(对齐 equips 无套装的约定)。
  组级 `name`/`desc` 为该族全体技能共享的官方文本(成员实测恒一致,故上提
  去重),`skillGroupType` 即槽位号;另收 `icon` 与 condition 系列字段
  (`conditionId/Icon/Name/Desc/DescInactive/PostDesc 1/2`——形态/条件状态
  的官方文本,如诀· Lizhiyan 的「智识值 ≥ 意志值」条件,多数干员为空串)。
  源表的 `skillIdList` 不再输出——其信息已由 `skillList` 的逐成员展开涵盖。
  `skillList` 与 SkillPatchTable 键一一对应(一个成员 = 一个 skillId,一对多;
  同干员内每个 skillId 只属一组,已验证),数值完全相同的形态变体保持独立
  条目,忠实源数据。名称/描述覆盖 357/360:yvonne 被动、wulfa
  连携变体不在任何 skillGroupMap,lizhiyan 连携的 desc 哈希不在 i18n
  转储,均为解包数据本身的缺口
- 技能文本的富文本标签(`<@ba.key>`、`<#ba.xx>`、`</>` 等)原样保留,
  前端经 `rich()` 转义后转换为 `span.rt` 渲染
- `talentNodeMap` 按节点类型分组(键 = nodeType 字符串,节点内不再重复该字段,
  i18n 引用已递归反查为文本、富文本保留):`"1"`=突破、`"2"`=装备破解、
  `"3"`=天赋(`attributeNodeInfo`:`title`/`desc`/`attributeModifiers` 属性加成/
  `favorability` 好感门槛)、`"4"`=被动技能(`passiveSkillNodeInfo`:`name`/`desc`/
  `values`/`iconId`/`talentEffectId`——desc 经 talentEffectId 从 PotentialTalentEffectTable
  反查,131/131 全覆盖;`values` 收录该 effect dataList 全部数值,desc 占位符
  245/245 可由 values 替换)、`"5"`=工厂技能
  (`factorySkillNodeInfo`);各节点含 `nodeId` 与 `requiredItem` 解锁消耗
- `charTypeId` 伤害属性枚举(Physical/Fire/Electric…);`mainAttrType`/`subAttrType`
  主/副属性枚举,与天赋 `attributeModifiers.attrType` 同体系
- `charBreakCostMap` 与源表同构(节点 nodeId → 节点):charBreak20/40/60/70 +
  equipBreakT2/3/4,每节点含 `breakStage`、`name`/`desc`(i18n 反查)、
  `equipTierLimit`(该阶段装备穿戴档位)、`requiredItem` 突破/破解材料
- `skillLevelUp` 技能升级消耗:每行 `{level, skillGroupId, goldCost, itemBundle}`,
  按 skillGroupId 对应 skillGroupMap 各族,即各族 Lv2→12 的龙门币与材料路线
- `cv` 四语言 CV 名:CharacterTable.cvName 的 i18n 句柄已各按其语言表反查
  (Chi→CN、Eng→EN、Jap→JP、Kor→KR,原生写法,与 --lang 默认语言无关),空文本为 null
- `wiki` 来自 jei-web 森空岛 Wiki 干员包(名称 join;管理员按 charId 后缀 m/f 特判),
  部分新干员 Wiki 尚未覆盖时为 null
- `potentials` 潜能/天赋:CharacterPotentialTable(解锁链+材料)×
  PotentialTalentEffectTable(效果描述 165/165 全可读,富文本标签已剥离;
  `{键:0%}` 占位符对应 blackboard/属性键,由游戏运行时填充)
- `icon`/`professionIcon` 只存裸 id(`icon_<charId>` / 职业图标 id),
  站点构建期经 icon_git 源本地化注入 URL
- `potentials.values` 与技能 `castCost`/`buffs` 来自 rmxlinux 的
  `Json/BuffData`、`Json/SkillData`(表现层定义),并合并 PotentialTalentEffectTable
  `dataList` 的全部数值(attachBuff/attachSkill 黑板、attrModifier 经属性枚举转
  属性名、skillBbModifier/skillParamModifier):描述中的 `{键:0%}` 占位符
  191/204 按同名键精确命中 `values`,其余 13 处数值也在 `values` 中
  (游戏按位置对应,键名与占位符不一致,如「冷却-3秒」存为 `param2: -3.0`);
  `castCost` 为技能真实消耗(如终结技 8 点)
- `weapon`/`recommendedWeapons` 来自 defaultWeaponId 与 CharWpnRecommendTable(join 武器表名称)
- `stationTags` 派驻标签描述来自 CharacterTagDesTable(基建加成全文,i18n 已反查)
- `breakStages` 不在干员文件内:来自全局表 CharBreakStageTable(实测 33 名干员完全一致),
  独立写入 `data/characters/_global.json` 的 `{"breakStages": [...]}`
- `wiki.detail` 来自森空岛 Wiki 文档解析(章节→组件→tab→嵌套文档块递归取文本):
  按章节输出 干员资料表格(代号/性别/生日/种族)、战斗技能卡(名称/类型/描述/正文)、
  天赋阵列正文。⚠️ 天赋无独立名称字段(游戏内为图标),名称含于正文首词

### items/ — 物品(生产)
目录化输出:每件物品一个完整文件 `data/items/<typeSlug>/<itemId>.json`——子目录为
物品类型的 EN slug(`ItemTable.type` → `ItemTypeTable.name` 经 `I18nTextTable_EN`
反查后转小写下划线,如 `currency`/`engraved_medal`,共 77 个;`typeSlug` 字段与
目录同名)。`index.json` 只是按 typeSlug 分组的 id 清单,内容不做重复。
条目字段:`{id, name, type, typeSlug, typeName, rarity, showingType, showingName,
showingIcon, desc, icon, iconUrl, obtainWays, factoryValue, settlementTrades,
activityCoupons, usedInRecipes, producedBy}`;`typeName` 为 `I18nTextTable`
按默认翻译语言(--lang)反查;无名条目 `name` 为 null,`iconUrl` 为 vfs 图标直链。注意新版
`showingType`/`type` 可能是整数枚举(旧镜像为字符串),前端只做展示不做枚举解释。
- `obtainWays`:`ItemTable.obtainWayIds` → `SystemJumpTable` 的 `desc` 经 i18n 反查的获取途径文案数组(保序去重),无登记时为 null
- `decoDesc`:`ItemTable.decoDesc` 展示描述(潜能明信片/干员留影等收藏品的陈列文案,干员 wiki 侧同名文本据此剔除),无登记时为 null
- `factoryValue`:`FactoryItemTable.value` 生产/回收基准价值,无登记时为 null
- `showingName`/`showingIcon`:`showingType` 经 `ItemShowingTypeTable` 反查的展示分类名与
  枚举图标(矿物/植物/产物/可用道具/护手/护甲/配件/采集材料/培养素材/生产工具/随身装置);
  注意物品用的是这张表,与配方展示分类 `FactoryCraftShowingTypeTable` 是两套体系;
  `showingType` 为 0 或未登记(如部分活动材料)时两者为 null
- `settlementTrades`:据点收购价(`SettlementBasicDataTable.settlementTradeItemMap`,
  按 据点×等级×物品),同(调度券,据点经验)报价合并据点去重,形如
  `[{"settlements": ["stm_hongs_1", …], "money": 200, "stmExp": 200}]`;不被收购时为 null
- `activityCoupons`:限时配方活动的叠加援助券(`ActivityLimitedFormulaSettlementTable`
  tradeList),形如 `{"activity_limited_formula_2": {"moneyCount": 20, "settlements": […]}}`,
  保留 活动→券额→适用据点 耦合;无活动券时为 null
- 用途细节字段(每物品零到多个,无关联不出现;实现见 `collect_item_details`):
  - `apRecover` 理智药剂回复量;`exp` 经验卡 `{gain, type}`;`gift` 赠礼好感
    `{favor, tags, preferTag, popular}`;`fuel` 燃料 `{energy, power}`;
    `batteryEnergy` 电池容量;`seed` 种子生长 `{growTotalProgress}`;`fertilize` 施肥 `{type, time}`
  - `fluid` 气液装灌映射,`kind=liquid|gas|fullBottle|fullJar|emptyBottle|emptyJar`
    (Gas/Liquid/Full·EmptyBottle·GasJar 六表,官方瓶罐对应关系,含容量与另一侧物品清单)
  - `useEffect` 使用效果(UseItemTable):`{duration, effectType, persistent, useDesc, actions}`,
    actions 内 buff 黑板按 `{key: value}` 摊平并保留 `buffId`/`skillId`
  - `battleEquip` 战斗装备物品实战参数(EquipItemTable,与随身装置两表物品不相交):
    `{castTime, chargeCount, cooldown, recoverTime, levelUpChargeCount, cond, desc, extraDesc}`
  - `device` 随身装置(ItemPortableDeviceTable):`{type, isMainDevice, lv, nextLvItemId}`
  - `chest` 宝箱/自选包(UsableItemChestTable):`rewardIdList` 经 `RewardTable` 展开为
    `{items, probItems}` 物品清单,附 `random` 随机池与 `selectedCount`
  - `weekraid` 周本收藏品:转换目标(`convertItemId`/`convertGoldId`/`convertGoldNum`)与所属区域
  - `gemDomain` 宝石所属地块;`gemBox` 定制箱(所引宝石的词条池随箱收录——宝石本体
    `item_gem_*` 不在 ItemTable,无独立条目)
  - `gachaPools` 抽卡票券适用卡池;`money` 货币清规则;`moneyExchanges` 货币兑换率(挂源货币)
- `usedInRecipes`/`producedBy`:物品作为原料/产物出现的配方数(直读三张 Factory 表统计,形如 `{"total": n, "manual": n, "machine": n, "spaceship": n}`);机器配方 group 为同槽原料(同时消耗),逐组员计入;无关联时为 null
注意新版 `showingType`/`type` 可能是整数枚举(旧镜像为字符串),前端只做展示不做枚举解释。

### recipes/ — 生产配方(按站点分 子目录)
每条配方一个完整文件 `data/recipes/<station>/<recipeId>.json`(manual/machine/spaceship);
`index.json` 只是**清单**:按站点分组的配方 id 列表(`{"manual": [...], "machine": [...],
"spaceship": [...]}`),告知"有哪些配方、在哪个子目录";名称/分类/原料/产物/耗时等
一切内容都在对应子文件里,索引中不做任何重复。
分类字段仅随条目输出、不做目录层级:
- 手工/飞船:`showingType` → `showingName` 中文名(精制食药/应急食药/随身装置/种植调配/
  素材转化/干员经验素材/武器经验素材,来自 `FactoryCraftShowingTypeTable`);
  手工另有 `craftFilterType`(0=普通手工,素材转化按 1/2/3 细分)与 `name` 配方名(102/102 可反查)
- 机器:无 showingType,以生产设施为分类(`machineId` → `machineName`,来自
  `FactoryBuildingTable`,灌装机/拆解机/精炼炉等 18 种),并带 `formulaGroupId`/
  `formulaDesc` 配方组(317/317 可反查)

```json
{
  "id": "handwork_bottled_flower1spc_1", "station": "manual",
  "name": "小瓶荞复锭剂",
  "showingType": 19, "showingName": "精制食药", "craftFilterType": 0,
  "rarity": 4, "domainId": "domain_1", "sortId": 21,
  "ingredients": [ { "group": [ { "id": "item_plant_moss_spc_powder_1", "name": "荞愈药粉", "count": 5 } ] },
                   { "group": [ { "id": "item_glass_bottle", "name": "紫晶质瓶", "count": 5 } ] } ],
  "outcomes": [ ... ]
}
```
机器配方条目另有 `machineId`/`machineName`/`formulaGroupId`/`formulaDesc`(如
`filling_bottled_copper_acid` → 灌装机 / 沉积酸(灌装))。机器配方的 `group` 是**同槽
原料**(游戏内同时消耗,如灌装=空瓶+溶液,非可替代项);手工配方 group 长度恒为 1;
飞船制造表只登记产物,`ingredients` 为空数组。
**机器运行消耗** `machineConsume`:来自 `FactoryTransmuterTable`(按 `machineId`
join,源表字段原样透传 + `consumeItemName` i18n 反查;仅转化机配方命中,24/317,
其余机器不输出该字段)——转化机运行时持续烧稀晶质:transmuter_1 烧液化息壤
(`item_liquid_xiranite`)、transmuter_2 烧息壤气(`item_gas_xiranite`),`consumeRate`
为满负载下每台每分钟消耗数(1 单位 = 60/rate 秒工时,随负载比例计耗,
endfield-calc 已实测验证);`consumeRateUpperLimit`(30,超供钳制)与
`consumeBindings`(2)为源表数值,原样保留不计入原料 `ingredients`。
**源表字段全量保留**:采集侧只替换加工形态(i18n 反查后的名称、解析后的原料/产物、
合并进 `outcomes` 的 `outcomeItemId`/`perCapacity`),其余字段原样透传,上游新增字段
不需要改采集代码即自动进入数据集。各站透传字段:
- 机器:`gasEnv` 所需气体环境(0=无要求,1=稳定,2=湿润,3=酸性,4=息壤,取值见
  `FactoryEnvDisplayTable.GenEnv`;当前数据仅 0/1/3)、`buffers`(产出物计数缓冲,如
  活动 pair 配方)、`progressRound`/`totalProgress`(多轮进度配方:2/10/20 轮,总进度
  12000~120000,如组件类 10 轮×单轮 6000)、`signal`(恒 0)
- 手工:`itemId` 制成物物品 ID、`defaultUnlock`(当前全 false)
- 飞船:`level` 舱室等级(1~3)、`roomAttrType` 舱室属性类型、`totalProgress`
  (容量总进度,如 92000)
机器源表没有 rarity 列,条目不再输出恒 null 的 `rarity`(手工/飞船照常)。
`craftTimeSec`(制造耗时,秒)与 `facility`(生产设施 ID)来自 JamboChen/endfield-calc
(本地克隆,其常量展开后与 TableCfg 同一套小写 ID,按配方 ID join);
仅机器配方命中(317/317),手工/飞船及 calc 数据缺失时为 null。
产率/分钟 = 产物数量 × 60 ÷ craftTimeSec。

### settlements/ — 据点
条目少,平铺输出:每据点一个完整文件 `data/settlements/<settlementId>.json`,
`index.json` 为 id 清单。来源 `SettlementBasicDataTable`(6 据点:`stm_hongs_*` 与
`stm_tundra_*` 各 3,分属 domain_2/domain_1;ID 前缀非游戏名,游戏名见条目 `name`,
如天王坪援建点/心脏修缮站/盈天台建设站/难民暂居处/基建前站/重建指挥部)。
条目字段:`{id, name, domainId, domainLevelId, facRegionIndex, color, wantTags, levels}`;
`name` 为据点名 i18n 反查。
- `wantTags`:驻留加成标签(`SettlementTagTable`,按 `wantTagIdGroup` 保序),形如
  `{id, name, desc, charTags, expRate, moneyRate, produceSpeedRate}`——驻留干员命中
  `charTags` 时对应收益 +%。
- `levels`:按等级(1..N)登记,每级含 `bandwidth`(带宽)/`battleBuildingLimit`(战斗
  建筑上限)/`travelPoleLimit`/`moneyMax`+`moneyPeriod`(资金上限与恢复周期)/
  `levelUpExp`/`isFinalMaxLevel`/`recoItemId`+`recoItemName`(推荐产物)/`desc`。
- `levels[].trades`:该等级收购列表,`{itemId, name, money(调度券), stmExp(据点经验)}`;
  活动关联物品带 `activityId`,活动期叠加援助券 `coupon`/`couponActivityId`
  (来自 `ActivityLimitedFormulaSettlementTable`)。物品侧视图见 items 的
  `settlementTrades`/`activityCoupons`(同一份源表,按物品聚合)。

### weapons/ — 武器(多数据源综合)
目录化输出:`index.json` 为轻量列表(不含潜能/天赋/升级/突破详情,列表页用);
每把武器一个完整文件 `data/weapons/<weaponId>.json`:
```json
{
  "id": "wpn_claym_0003", "name": "Industry 0.1",
  "desc": "武器背景故事(weaponDesc,i18n 反查,79/79 可读)",
  "rarity": 4, "weaponType": 3, "maxLevel": 90,
  "potentialSkill": { "skillId": "sk_wpn_claym_0003", "name": "压制·应急强化",
    "desc": "装备者的战技命中敌人时,获得攻击力+12.0%,持续20秒。同名效果无法叠加。",
    "levels": [ { "level": 1, "blackboard": { "atk_up": 0.12, "duration": 20.0 } } ] },
  "talent": { "templateId": "wpn_potential_456star",
    "levels": [ { "talentLv": 1, "skillLevelExtraBounds": [ { "skill": "…", "lowerBound": 0, "upperBound": 0 } ] } ] },
  "upgrade": { "templateId": "weapon_upgrade_curve_4star_1",
               "baseAtkLv1": 34, "baseAtkMax": 341, "totalExp": 2524080, "totalGold": 341390 },
  "breakthrough": { "templateId": "weapon_breakthrough_456star_D_1",
    "stages": [ { "stage": 0, "level": 1, "gold": 0,
                  "materials": [ { "id": "…", "count": 0 } ],
                  "skillLevelBounds": [ { "skill": "…", "lowerBound": 1, "upperBound": 4 } ] } ] },
  "potentialUpItems": null,
  "sources": ["rmxlinux@TableCfg", "rmxlinux@SkillPatchTable"]
}
```
多源说明:
- `potentialSkill` 来自 SkillPatchTable(键=weaponPotentialSkill):79/79 名称/描述哈希
  全部可 i18n 反查;富文本标签已剥离,`{key:fmt}` 占位符按各等级 blackboard 回填
- `talent` 来自 WeaponTalentTemplateTable(talentLv 1..5 对各技能位等级加成区间,
  `skill` 按 weaponSkillList 下标对齐);`upgrade` 为升级曲线摘要(1 级/满级攻击、
  累计经验与龙门币);`breakthrough` 为突破档位(消耗与技能等级区间)
- `potentialUpItems` 非空表示潜能可用道具提升;当前 79 把武器四类模板键全部命中

### equips/ — 装备与套装(战斗/养成)
目录化输出:每件装备一个完整文件 `data/equips/<suit>/<equipId>.json`——按所属套装
分子目录(suit 字段与子目录同名,无套装的入 `unknown`,共 25 个);`index.json` 只是
按 suit 分组的 id 清单;套装被动与强化规则为全局配置,整体在 `data/equips/_global.json`
(`{"suits": [...], "enhance": {...}}`)。单件装备字段:
```json
{ "id": "item_equip_t2_suit_agi01_body_01", "name": "巡行信使夹克",
  "part": "body", "suit": "suit_agi01", "rarity": 3, "minWearLv": 1,
  "icon": "item_equip_t2_suit_agi01_body_01(裸 id,站点构建时注入 /icons/sprites URL)",
  "baseAttr": null,
  "attrs": [ { "type": "Str", "value": 15.0 }, { "type": "MaxHp", "value": 46.3 } ],
  "formula": { "formulaId": "…", "level": "T2", "packId": "…", "packName": "…",
               "unlock": null,
               "craftOptions": [ { "chainId": 1005, "discount": 1.0, "isDefault": true,
                                   "gold": null, "materials": [ … ] } ] },
  "enhancePity": null }
```
`part` 自装备 id 解析(body/hand/edc),`name`/`rarity`/`icon` 经 itemId join ItemTable;
`formula` 按 outcomeEquipId 反查(ReverseTable 索引),`level` 为合成档位,`craftOptions`
为该档位可选加工链(调度券 gold + 材料 materials,图纸条目含工艺名与解锁主线);
`enhancePity` 为词条引用的强化保底规则 id,定义在 `enhance.guaranteeRules`
(强化消耗为全局配置)。套装效果按件数分档,描述经 SkillPatchTable 反查
(24/24 可解析,富文本已剥离,`{键:fmt}`/`{1-键:fmt}` 占位符按 blackboard 回填),
即 `suits[].effects[].desc`。

### enemies/ — 敌人(战斗)
目录化输出:每个敌人一个完整文件 `data/enemies/<typeSlug>/<enemyId>.json`——typeSlug
为分类枚举的 EN slug(`DisplayEnemyTypeTable` 经 `I18nTextTable_EN` 反查:
common/elite/boss/advanced/alpha,缺展示信息的入 `unknown`,共 6 个;typeSlug 字段
与目录同名);`index.json` 只是按类型分组的 id 清单。条目 `name`/`typeName` 跟随
默认翻译语言(--lang),`cnName` 字段已取消:
```json
{
  "id": "eny_0007_mimicw", "templateId": "eny_0007_mimicw", "typeSlug": "advanced",
  "name": "潜地虬兽", "typeName": "进阶敌人",
  "dangerous": false, "superArmor": 20, "maxResilience": 65,
  "resists": { "cryst": 0.0, "fire": 0.0, "natural": 0.3, "physical": 0.0, "pulse": 0.0 },
  "lvMax": { "MaxHp": 552167, "Atk": 9877, "Def": 1200 }
}
```
> **enemies**(381 条,`data/enemies/`):EnemyTable 全量敌人,经 `templateId` 关联
> EnemyTemplateDisplayInfoTable 获得显示名(默认语言)/昵称/档案描述(覆盖率 374/381)、
> `displayType` 分类(普通/精英/领袖/进阶/头目)、出没区域(DistributionInfoTable)与特殊能力
> (EnemyAbilityDescTable);经当前语言显示名精确 join 森空岛 Wiki「威胁」分区
> (CN 构建 56/56 命中,276/381 覆盖;其他语言 Wiki 包无对应译名,相关字段为空)。

注意:显示名缺失时以 templateId 兜底(解包表中显示名哈希为 0,见 docs/sources.md 缺口 2);
新版 `resists` 为具名抗性(physical/fire/pulse/cryst/natural,值为**减伤比例**,0=无抗性),
旧镜像的 `*ResistScalar`(受伤倍率)已在构建时统一换算为减伤比例。

### meta.json — 构建信息
`{generatedAt, source{repo,branch}, lang, i18nMisses, counts{...}}`;counts 含 equips/suits;
`lang` 为本次构建的默认翻译语言(入口 `--lang` 指定,默认 CN,各语言覆盖见 I18nTextTable_<LANG>)。

## 按需读取、待加工的表

| 表 | 后续用途 |
|---|---|
| `SkillPatchTable` | 技能数值 blackboard → 干员 DPS 计算 |
| `CharBreakTable` / `CharLevelUpTable` | 养成材料/金币曲线 |
| `BuffTable`、`GeneralAbilityTable` | 增益机制建模 |
| `EnemyTagTable`、`DisplayEnemyTypeTable` | 敌人分类标签 |
| `FactoryBuildingTable`、`FactoryPowerStationTable` 等 Factory* 30+ 张 | 产线规划器(电力/物流/机器模式) |
