# id 关联映射(enddata idmap)

回答一个问题:**"这个 id 还在哪些文件、哪些字段出现?"** —— 无论它是被定义
还是被引用。扫描 `sources/rmxlinux__EndfieldData`,按 id 字符串把全部出现位置
聚成**关联组**,再用**循环最长公共子串(LCS)反统一**把关联组归纳成带 `{vN}`
变量的**匹配规则**,存入 `data/id_map/`(gitignore 的派生产物,随时可重建)。

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

## 产物(`enddata idmap build`,全量约 3 分钟)

| 文件 | 内容 |
|---|---|
| `patterns.json` | 匹配规则目录:`{"rules": [{"patterns": [...], "example": [...]}]}`,数组下标即规则号(rid);`example` 与 `patterns` 一一对应,是该模式泛化前的真实定位符 |
| `ids.jsonl` | 全部关联组:每行 `{id, pid, defs[], refs[]}`,pid = 命中的规则号(0 = 单路径组,不成规则) |
| `files.json` | 反查:每个文件定义/引用了哪些 id |
| `meta.json` | 数据源 HEAD、扫描范围、算法版本、计数 |

模式串 = 字面量段与 `{vN}` 变量的有序序列;一条规则的 patterns 列表里**任一**
模式能按序覆盖(首尾锚定)某定位符,即视为该规则覆盖它。

## 规则生成算法(lcs-v1)

1. **触发**:按字典序遍历 id;其**全部出现位置**(defs+refs,含行键/文件名/
   补充键)逐一做覆盖检查,已被某条规则匹配的位置跳过;
2. **规则推导**:存在未覆盖位置 → 对该 id 的全部定位符循环求**最长公共子串**,
   长度 ≥2 就把每次出现替换为新变量,直到最长公共子串 ≤1;各定位符泛化后的
   模板串(去重)即新规则的 patterns。id 特有子串通常第一轮就变成变量;
   **变量编号是规则级的**:同一公共子串在规则内所有模式里同名、绑定相同内容
   (变量可在模式内多处出现)。规格化时旧变量先改名加哨兵前缀隔离,新变量编号
   接续,最后按规则内首次出现顺序映射为 `{v1}…{vN}` —— 该机制可重入,同一规则
   多次规格化不会命名冲突、不会破坏已有变量。替换时校验公共子串的每次出现都
   不与已有变量记号重叠,防止破坏变量编号(如 '10' 命中 v10 的编号);
   **数组顺序与变量编号规格化**:patterns 按移除全部变量后的字符串排序 ——
   变量名不影响顺序;变量编号再按最终数组的出现顺序重编为 `{v1}…{vN}`,
   自上而下读恰好依次首现,同号跨模式同值;
3. **过滤**:只有单条路径的 id 不成规则(pid=0);模式至少含 1 个 ≥4 字符字面量
   才参与覆盖判定(防全变量退化规则吃掉全部位置);
4. **同构去重**:新规则的 patterns 与已有规则完全相同时不重复插入,组归属已有
   规则(如同一文本哈希被 `ap_supply_lt_n` 与 `item_ap_supply_lt_n` 两个行引用);
5. **先到先得**:覆盖判定按规则加入顺序,首个命中的规则认领该位置;id 归属
   首条命中规则(触发新规则时归属新规则)。

效果示例 —— tangtang 连携技(id `chr_0027_tangtang_combo_skill`,14 个定位符)
的规则含如下模式(完整 id 已变量化为 `{v1}`):

```
Json/S{v3}Data/{v1}{v2}
Json/S{v3}Data/{v1}{v2}#s{v3}Id.{v1}
TableCfg/CharGrowthTable{v2}#chr_0027_tangtang.s{v3}GroupMap.chr_0027_tangtang_ComboS{v3}.s{v3}IdList[].{v1}
TableCfg/StrIdNumTable{v2}#s{v3}_id.dic.{v1}
```

行为特征:字面 LCS + 先到先得会让规则按**公共片段聚簇** —— 名字片段
(`tangtang`、`skill` 等)成为字面量,同族 id 的位置被同一规则认领
(最大的规则覆盖上万个 id),规则数(5.1 万)小于多路径 id 数(11.7 万)。

## 收集范围与规模(2026-09,rmxlinux@ef902ef)

默认扫描 `TableCfg + Json/SkillData + Json/BuffData`(项目消费面);i18n 各语言表
只扫基准语言 CN(其余 13 语言是同键重复定义,`--dir` 可强行附加)。`--all-json`
全量(含关卡/NPC/口型 7 万+文件,慢且产物大)。

当前规模:6206 文件 → **253,724 个 id**(定义 209,665 · 引用 347,945)→
**49,725 条规则**;单路径组 136,667 个(rid=0)。

## 查询(`enddata idmap relate <file#path>`)

```bash
poetry run enddata idmap relate 'TableCfg/CharGrowthTable.json#chr_0027_tangtang.skillGroupMap.chr_0027_tangtang_ComboSkill.skillIdList[].chr_0027_tangtang_combo_skill'
```

直接返回**全部匹配的规则组**:每条给出规则号与其 patterns 列表;命中几条返回
几条,不做绑定完整性校验、无一对多报错。查询性能靠"模式最长字面量 gram → 规则"
倒排索引预筛候选,再按序验证(全量产物上单次查询约 2 秒)。

```text
$ enddata idmap relate '<定位符>'
匹配 18 条规则:
[R13] 2 条模式:
  {v3}Group{v2}chr_{v4}g{v1}   例: TableCfg/NpcGroupTable.json#npc_chr_0014_aurora_g01.name.id.-1072676122322635220
  {v3}{v2}{v4}spaceship_i0{v1}   例: TableCfg/NpcTable.json#npc_0014_aurora_spaceship_i001.name.id.-1072676122322635220
[R47334] 20 条模式:
  {v1}tangtang{v2}   例: TableCfg/ActivityTable.json#activity_checkin_tangtang.panelId.ActivityCharSignCommon
  …
```

每条模式附 `例:` 行 —— 该模式泛化前的真实定位符(即 patterns.json 的 example)。

规则的生成数据(哪个 id 的哪些定位符)追溯 `ids.jsonl` 中 `pid` 指向它的组。

## 跟版与边界

- 数据源更新后重跑 `enddata idmap build` 即可(离线,只读本地克隆);
  meta.json 的 `head` 记录构建时数据源版本。
- 已知边界:单路径组(rid=0)没有规则;数组不记下标;JSON 空键被分词剔除;
  混合大小写 map 键不作键出现(见定位符规范);关卡/NPC 等目录默认不在范围
  (需要时 `--dir Json/NPC` 附加);变量绑定不校验同值,覆盖判定在极端情形略宽松。
