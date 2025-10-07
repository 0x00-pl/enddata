# 数据模型:原始表 → 数据集

## 流水线

```
GitHub 源仓库 (rmxlinux/EndfieldData@main,跟随当前游戏版本)
        │  collection/fetch_tablecfg.py(本地git → 缓存 → jsdelivr → raw → COS → API)
        ▼
data/raw/tablecfg/<repo>/<branch>/*.json     ← 原始快照 + manifest.json(抓取时间)
        │  collection/build_all.py(按产物模块初步处理:i18n 反查、表间 join、attrType 枚举翻译)
        ▼
data/processed/{meta,characters,weapons,items,recipes,enemies}.json   ← 生成的报告,由 site/ 消费
reports/build-report.md                                               ← 人类可读构建报告
```

## 文本引用规则

数值表中一切文本都是 `{"id": <64位哈希>, "text": null}` 形式,
用 `I18nTextTable_CN.json` 以 `str(id)` 为键反查中文。哈希为 `0` 表示无文本。
(rmxlinux 的 i18n 表就在 TableCfg/ 目录内;XiaBei-cy 旧镜像在独立 i18n/ 目录。)

## 属性枚举(重要)

新版解包把 `attrType` 从字符串改成了整数。`src/collection/common.py` 内置
`INT_ATTR_MAP`(0=Level,1=MaxHp,2=Atk,3=Def,9=暴击率,10=暴击伤害,
39-42=力/敏/智/意志,4-7/48/55=各系受伤倍率),依据 `TableCfg/AttributeMetaTable.json`
的 iconName 反查并经数值交叉验证。旧镜像的字符串 attrType 原样透传,两版兼容。

## 输出数据集结构

### characters.json — 干员(战斗)
```json
{
  "id": "chr_0005_chen", "name": "陈", "enName": "Chen",
  "profession": "GUARD", "professionName": "近卫",
  "rarity": 6, "weaponType": "Sword", "cv": "...", "maxLevel": 60,
  "lv1":   { "MaxHp": 500, "Atk": 30, "Def": 0, "Str": 10.8, "Agi": 20.6, "Wisd": 8.9, "Will": 9.7 },
  "lvMax": { "...": "同上结构,最终突破满级面板" }
}
```

### items.json — 物品(生产)
`{id, name, type, typeName, rarity, showingType, desc, icon}`;无名条目 `name` 为 null。
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

### weapons.json — 武器
`{id, name, rarity, weaponType, maxLevel}`

### equips.json — 装备与套装(战斗/养成)
```json
{
  "equips": [ { "id": "item_equip_t0_parts_tundra01_body_01", "name": "简易护甲",
                "part": "body", "suit": null, "rarity": 1, "minWearLv": 1,
                "icon": "…vfs…/itemicon/….png",
                "baseAttr": null,
                "attrs": [ { "type": "Str", "value": 15.0 }, { "type": "MaxHp", "value": 46.3 } ] } ],
  "suits":  [ { "id": "suit_agi01", "name": "巡行信使", "logo": "icon_pack_tundra_suit_agi01",
                "members": 9,
                "effects": [ { "count": 3, "skill": "passive_equipsuit_agi_01", "lv": 1 } ] } ]
}
```
`part` 自装备 id 解析(body/hand/edc),`name`/`rarity`/`icon` 经 itemId join ItemTable;
套装效果仅登记件数与被动技能 ID,技能描述文本待接入技能表。

### enemies.json — 敌人(战斗)
```json
{
  "id": "eny_0007_mimicw", "templateId": "eny_0007_mimicw", "name": "eny_0007_mimicw",
  "dangerous": false, "superArmor": 20, "maxResilience": 65,
  "resists": { "cryst": 0.0, "fire": 0.0, "natural": 0.3, "physical": 0.0, "pulse": 0.0 },
  "lvMax": { "MaxHp": 552167, "Atk": 9877, "Def": 1200 }
}
```
注意:`name` 当前以 templateId 兜底(解包表中显示名哈希为 0,见 docs/sources.md 缺口 2);
新版 `resists` 为具名抗性(physical/fire/pulse/cryst/natural,值为**减伤比例**,0=无抗性),
旧镜像的 `*ResistScalar`(受伤倍率)已在构建时统一换算为减伤比例。

### meta.json — 构建信息
`{generatedAt, source{repo,branch,fetchedAt}, i18nMisses, counts{...}}`

## 已抓取、待加工的表

| 表 | 后续用途 |
|---|---|
| `SkillPatchTable` | 技能数值 blackboard → 干员 DPS 计算 |
| `CharBreakTable` / `CharLevelUpTable` | 养成材料/金币曲线 |
| `BuffTable`、`GeneralAbilityTable` | 增益机制建模 |
| `EnemyTagTable`、`DisplayEnemyTypeTable` | 敌人分类标签 |
| `FactoryBuildingTable`、`FactoryPowerStationTable` 等 Factory* 30+ 张 | 产线规划器(电力/物流/机器模式) |
