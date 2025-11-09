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
data/{meta,characters,weapons,items,recipes,equips,enemies}.json   ← 生成的数据集,由 site/ 消费
data/versions.json                                                 ← 游戏构建号与各仓库 HEAD
reports/build-report.md                                            ← 人类可读构建报告
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
  "skills": [ { "skillId": "chr_0005_chen_attack1", "name": null, "desc": null,
                "coolDown": 0.0, "costType": 0, "costValue": 0.0, "castCost": 8,
                "buffs": ["buff_chr_0005_chen_…"],
                "levels": [ { "level": 1, "blackboard": { "atk_scale": 0.1 } },
                            { "level": 2, "blackboard": { "…": "…" } } ] } ],
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
  "breakStages": [ { "stage": 0, "maxLevel": 20,
                     "skillLevels": { "normalAttack": 1, "normal": 1,
                                      "combo": 1, "ultimate": 1 } } ],
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
  `levels` 是逐级 blackboard 数值板(干员技能名称/描述哈希在解包表中多为 0,待补)
- `wiki` 来自 jei-web 森空岛 Wiki 干员包(名称 join;管理员按 charId 后缀 m/f 特判),
  部分新干员 Wiki 尚未覆盖时为 null
- `potentials` 潜能/天赋:CharacterPotentialTable(解锁链+材料)×
  PotentialTalentEffectTable(效果描述 165/165 全可读,富文本标签已剥离;
  `{键:0%}` 占位符对应 blackboard/属性键,由游戏运行时填充)
- `icon`/`professionIcon` 为宏山档案局 vfs 直链
- `potentials.values` 与技能 `castCost`/`buffs` 来自 rmxlinux 的
  `Json/BuffData`、`Json/SkillData`(表现层定义):potentials 描述中的
  `{键:0%}` 占位符数值即 `values` 的键值;`castCost` 为技能真实消耗
  (如终结技 8 点)
- `weapon`/`recommendedWeapons` 来自 defaultWeaponId 与 CharWpnRecommendTable(join 武器表名称)
- `stationTags` 派驻标签描述来自 CharacterTagDesTable(基建加成全文,i18n 已反查)
- `breakStages` 为突破阶段的各技能等级上限(CharBreakStageTable)
- `wiki.detail` 来自森空岛 Wiki 文档解析(章节→组件→tab→嵌套文档块递归取文本):
  按章节输出 干员资料表格(代号/性别/生日/种族)、战斗技能卡(名称/类型/描述/正文)、
  天赋阵列正文。⚠️ 天赋无独立名称字段(游戏内为图标),名称含于正文首词

### items.json — 物品(生产)
`{id, name, type, typeName, rarity, showingType, desc, icon, iconUrl, obtainWays, usedInRecipes, producedBy}`;无名条目 `name` 为 null,`iconUrl` 为 vfs 图标直链。注意新版 `showingType`/`type` 可能是整数枚举(旧镜像为字符串),前端只做展示不做枚举解释。
- `obtainWays`:`ItemTable.obtainWayIds` → `SystemJumpTable` 的 `desc` 经 i18n 反查的获取途径文案数组(保序去重),无登记时为 null
- `usedInRecipes`/`producedBy`:物品作为原料/产物出现的配方数(直读三张 Factory 表统计,形如 `{"total": n, "manual": n, "machine": n, "spaceship": n}`);机器配方 group 可替代组按"任选其一"逐组员计入;无关联时为 null
注意新版 `showingType`/`type` 可能是整数枚举(旧镜像为字符串),前端只做展示不做枚举解释。

### recipes.json — 生产配方
```json
{
  "id": "thickener_originium_enr_powder_1",
  "station": "manual | machine | spaceship",
  "machineId": "thickener_1",
  "rarity": null,
  "ingredients": [ { "count": 2, "options": [ { "id": "item_originium_powder", "name": "源石粉末", "count": 2 },
                                                { "id": "item_plant_moss_powder_3", "name": "砂叶粉末", "count": 1 } ] } ],
  "outcomes": [ ... ]
}
```
机器配方的 `options` 是**可替代原料组**(任选其一);手工配方 options 长度恒为 1;
飞船制造表只登记产物,`ingredients` 为空数组。
`craftTimeSec`(制造耗时,秒)与 `facility`(生产设施 ID)来自 JamboChen/endfield-calc
(本地克隆,其常量展开后与 TableCfg 同一套小写 ID,按配方 ID join);
仅机器配方命中(317/317),手工/飞船及 calc 数据缺失时为 null。
产率/分钟 = 产物数量 × 60 ÷ craftTimeSec。

### weapons.json — 武器(多数据源综合)
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

### equips.json — 装备与套装(战斗/养成)
```json
{
  "equips": [ { "id": "item_equip_t0_parts_tundra01_body_01", "name": "简易护甲",
                "part": "body", "suit": null, "rarity": 1, "minWearLv": 1,
                "icon": "…vfs…/itemicon/….png", "baseAttr": null,
                "attrs": [ { "type": "Str", "value": 15.0 }, { "type": "MaxHp", "value": 46.3 } ],
                "formula": { "formulaId": "item_formu_t0_parts_tundra01_body_01", "level": "T0.5",
                             "packId": "pack_parts_tundra01_t0", "packName": "简易独立装备组",
                             "unlock": null,
                             "craftOptions": [ { "chainId": 1005, "discount": 1.0, "isDefault": true,
                                 "gold": null,
                                 "materials": [ { "id": "item_crystal_shell", "name": "晶体外壳", "count": 10 } ] } ] },
                "enhancePity": null } ],
  "suits":  [ { "id": "suit_agi01", "name": "巡行信使", "logo": "icon_pack_tundra_suit_agi01",
                "members": 9,
                "effects": [ { "count": 3, "skill": "passive_equipsuit_agi_01", "lv": 1 } ] } ]
}
```
`part` 自装备 id 解析(body/hand/edc),`name`/`rarity`/`icon` 经 itemId join ItemTable;
`formula` 按 outcomeEquipId 反查(ReverseTable 索引),`level` 为合成档位,`craftOptions`
为该档位可选加工链(调度券 gold + 材料 materials,图纸条目含工艺名与解锁主线);
`enhancePity` 为词条引用的强化保底规则 id,定义在顶层 `enhance.guaranteeRules`
(强化消耗为全局配置)。套装效果仅登记件数与被动技能 ID,技能描述文本待接入技能表。

### enemies.json — 敌人(战斗)
```json
{
  "id": "eny_0007_mimicw", "templateId": "eny_0007_mimicw", "name": "eny_0007_mimicw",
  "dangerous": false, "superArmor": 20, "maxResilience": 65,
  "resists": { "cryst": 0.0, "fire": 0.0, "natural": 0.3, "physical": 0.0, "pulse": 0.0 },
  "lvMax": { "MaxHp": 552167, "Atk": 9877, "Def": 1200 }
}
```
> **enemies**(381 条,`data/enemies.json`):EnemyTable 全量敌人,经 `templateId` 关联
> EnemyTemplateDisplayInfoTable 获得中文名/昵称/档案描述(覆盖率 374/381)、`displayType`
> 分类(普通/精英/领袖/进阶/头目)、出没区域(DistributionInfoTable)与特殊能力
> (EnemyAbilityDescTable);经中文名精确 join 森空岛 Wiki「威胁」分区(56/56 命中,
> 276/381 覆盖)补充条目图标与 Wiki itemId。

注意:`name` 当前以 templateId 兜底(解包表中显示名哈希为 0,见 docs/sources.md 缺口 2);
新版 `resists` 为具名抗性(physical/fire/pulse/cryst/natural,值为**减伤比例**,0=无抗性),
旧镜像的 `*ResistScalar`(受伤倍率)已在构建时统一换算为减伤比例。

### meta.json — 构建信息
`{generatedAt, source{repo,branch}, i18nMisses, counts{...}}`;counts 含 equips/suits。

## 按需读取、待加工的表

| 表 | 后续用途 |
|---|---|
| `SkillPatchTable` | 技能数值 blackboard → 干员 DPS 计算 |
| `CharBreakTable` / `CharLevelUpTable` | 养成材料/金币曲线 |
| `BuffTable`、`GeneralAbilityTable` | 增益机制建模 |
| `EnemyTagTable`、`DisplayEnemyTypeTable` | 敌人分类标签 |
| `FactoryBuildingTable`、`FactoryPowerStationTable` 等 Factory* 30+ 张 | 产线规划器(电力/物流/机器模式) |
