# id 关联映射(enddata idmap)

回答一个问题:**"这个 id 还在哪些文件、哪些字段出现?"** —— 无论它是被定义
还是被引用。扫描 `sources/rmxlinux__EndfieldData`,按 id 字符串把全部出现位置
聚成**关联组**,再把同构的关联组归纳成带 `{var}` 的**关联模式**,一并存入
`data/id_map/`(gitignore 的派生产物,随时可重建)。

## 定位符规范(描述 id 值所在位置的 path 生成方法)

```
locator := filepath                        # 文件名出现:id 即单实体文件名
         | filepath '#' step ('.' step)*   # 表内出现
step    := 键名 | 键名'[]' | id
```

生成规则(JSON 树 → 定位符):

- 从根维护段序列;对象成员追加其键名;**值是数组的键追加 `[]` 后缀**(数组位置
  无关,不记下标);
- **末段恒为 id 本身**,两种出现:
  - **值出现**:id 是 Id/IdList 类键(键名 `id`、含 `Id`、`_id(s)` 结尾)下的取值
    —— 标量直接取,数组逐元素;数值只收 |v| > 2³² 的 64 位哈希(即 i18n 文本 id);
  - **键出现**:id 本身是对象键 —— 表行键(I18nTextTable 的文本哈希)、
    `skillGroupMap`/`charBreakCostMap` 等 map 键。键形态要求小写 snake
    (`chr_0027_tangtang` ✓,`wiki_type_equip` ✓);混合大小写的 map 键
    (`chr_x_ComboSkill`、`charBreak20`)不收集 —— 它们的内容里必带镜像
    `*Id` 字段,作为路径结构段保留;数值键同 2³² 阈值,滤掉 "1"/"2" 层级键。
- **文件名出现**:`Json/SkillData`、`Json/BuffData` 等单实体文件,文件名即 id,
  定位符就是文件路径。
- 不带 Id 字样但实测承载 id 引用的键白名单 `EXTRA_REF_KEYS`(逐键核实):
  `bornBuffs`(敌人出生 Buff)、`equips/equipList/perfectEquips`(预设/卡池装备)、
  `fullBottleItems`、`actorList`、`ids`、`list`、`valueStringList`;取值还须通过
  小写 snake 校验。

示例(同一 id 的五种真实定位符):

```
Json/SkillData/chr_0027_tangtang_combo_skill.json                     # 文件名出现
TableCfg/CharGrowthTable.json#chr_0027_tangtang                       # 行键出现
TableCfg/CharGrowthTable.json#chr_0027_tangtang.skillGroupMap.chr_0027_tangtang_ComboSkill.skillIdList[].chr_0027_tangtang_combo_skill   # 值出现(数组)
Json/SkillData/chr_0027_tangtang_combo_skill.json#skillId.chr_0027_tangtang_combo_skill                                                   # 值出现(标量)
TableCfg/StrIdNumTable.json#skill_id.dic.chr_0027_tangtang_combo_skill                                                                    # 键出现(map 键)
```

除末段外每段描述结构,末段即 id —— 因此定位符既给出 id 的准确位置(可回 JSON
逐步走到底),又自描述(末段可 grep)。

## 产物(`enddata idmap build`,约 30 秒)

| 文件 | 内容 |
|---|---|
| `ids.jsonl` | 全部关联组:每行 `{id, pid, defs[], refs[]}`,定位符按字典序 |
| `index.db` | ids.jsonl 的 sqlite 主键索引(lookup/search 用,派生物,可删) |
| `patterns.json` | 关联模式目录:槽位模板 + 变量示例/例外 + 实例数 |
| `files.json` | 反查:每个文件定义/引用了哪些 id |
| `meta.json` | 数据源 HEAD、扫描范围、计数、解析失败清单 |

## 收集范围与规模(2026-09,rmxlinux@ef902ef)

默认扫描 `TableCfg + Json/SkillData + Json/BuffData`(项目消费面);i18n 各语言表
只扫基准语言 CN(其余 13 语言是同键重复定义,`--dir` 可强行附加)。`--all-json`
全量(含关卡/NPC/口型 7 万+文件,慢且产物大)。

当前规模:6206 文件 → **253,724 个 id**(定义 209,665 · 引用 347,945),归纳出
**1,279 个模式**,另 13.7 万单例组(仅一处出现,无模式)。

## 模式归纳

1. **分桶**:每组的定位符各算粗签名(目录, 文件名 token 数, 各段 token 数),
   签名集合相同的组同桶;
2. **子集匹配**:槽位组合全库唯一的组,回退并入"槽集合为其子集"的最大模式
   (组可带模式之外的多余定位符);
3. **逐槽对齐**:每模式取全部实例(≤200),每(组, 槽) 取一条定位符,跨实例逐
   位置对齐:常量位置留字面量;相邻可变位置按共变性(变化轨迹完全一致)合并为
   变量;变量身份 = 该跨度在各实例上的完整取值向量;
4. **跨槽归并**:取值集合 Jaccard ≥ 0.9(且 ≥5 元素)的变量并为同一变量,例外
   差集记入 `varExceptions` —— 典型即 chr_9000_endmin 的 skillGroupMap 引用
   endminm/endminf 前缀技能(CLAUDE.md「系统数据实体」节),例外实例在匹配时
   自然不命中,不污染一般规则;
5. **命名**:数字开头的跨度用前邻字面量(`chr_0027_tangtang` → `{chr}`),纯数字
   用 `num`,其余取示例值首段;模式内同名变量取同一值。

于是有(用户给的原例,现为 P461 系模式的槽):

```
TableCfg/CharGrowthTable.json#chr_{chr}.skillGroupMap.chr_{chr}_ComboSkill.skillIdList[].chr_{chr}_combo_skill
  ↔ Json/SkillData/chr_{chr}_combo_skill.json
  ↔ TableCfg/SkillPatchTable.json#chr_{chr}_combo_skill
```

## 查询(`enddata idmap {lookup,relate,search,stats}`)

```bash
poetry run enddata idmap lookup chr_0027_tangtang_combo_skill   # 按 id 直查关联组
poetry run enddata idmap search tangtang --file TableCfg        # 子串模糊搜 id
poetry run enddata idmap stats                                  # 规模与头部模式
```

`lookup` 永远能回答(组内全部定义 + 引用 + 所属模式模板)。

`relate <file#path>` 沿**模式**找同组条目,语义从严:

1. 定位符匹配某模式的某槽模板 → 得到变量绑定;
2. 渲染同模式其余槽;绑定不全的变量先试填关联组 id 本身(模式各槽共享同一 id 值),
   渲染结果一律对照该 id 的实例组**验证后才输出**;
3. 仍无法确定的变量(查询方向一对多,如从 `I18nTextTable_CN.json#{num}` 反推
   `TableCfg/{表}.json#{item}.name.id.{num}` 的 `{item}`)**直接报错,不强行映射**,
   并提示改用 `lookup <id>`;
4. 定位符末段 id 不在索引中(如 <2³² 的小整数)同样直接报错。

真实输出示例(tangtang 连携技,从成长表 `skillIdList[]` 出发):

```text
$ enddata idmap relate 'TableCfg/CharGrowthTable.json#chr_0027_tangtang.skillGroupMap.chr_0027_tangtang_ComboSkill.skillIdList[].chr_0027_tangtang_combo_skill'
[P461 等 9 个模式] 5 处关联:
  Json/SkillData/chr_0027_tangtang_combo_skill.json
  Json/SkillData/chr_0027_tangtang_combo_skill.json#skillId.chr_0027_tangtang_combo_skill
  TableCfg/StrIdNumTable.json#skill_id.dic.chr_0027_tangtang_combo_skill
  TableCfg/SkillPatchTable.json#chr_0027_tangtang_combo_skill
  TableCfg/SkillPatchTable.json#chr_0027_tangtang_combo_skill.SkillPatchDataBundle[].skillId.chr_0027_tangtang_combo_skill
  (另有至多 7 个模式槽位在该 id 实例上未观察到,已剔除)
无法映射 等共 8 个(变量绑定不全,查询方向一对多):P461 缺 {attack}; …
```

## 跟版与边界

- 数据源更新后重跑 `enddata idmap build` 即可(离线,只读本地克隆);
  meta.json 的 `head` 记录构建时数据源版本。
- 已知边界:单例组(P0)无模式可 relate;数组不记下标;JSON 空键被分词剔除;
  混合大小写 map 键不作键出现(见定位符规范);关卡/NPC 等目录默认不在范围
  (需要时 `--dir Json/NPC` 附加)。
