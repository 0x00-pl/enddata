# CLAUDE.md — 项目记忆(会话自动加载)

EndData · 明日方舟:终末地 数据站。采集(Python 标准库)→ JS 构建生成零外链站点。
详细文档在 `docs/`(sources 数据源调研 / data-model 字段结构 / data-lineage 血缘统计),本文件只记约定与坑。

## 常用命令(全部在仓库根执行)

```bash
poetry run enddata collection clone/all   # 数据源同步 / 全量采集
npm run build                             # 即 node web/build.mjs → dist/
python3 -m http.server 8321 --bind 127.0.0.1 --directory dist
```

- 采集重跑后必须重跑 `npm run build`(数据集只存裸 id,URL 由构建期注入)。
- 唯一根目录是 project-root;JS 项目根也是它(package.json 在根,零 npm 依赖)。
- `data/`、`dist/`、`sources/` 均已 gitignore;`.zcode/` 不要提交。

## 数据结构约定

- **技能**:`skillGroupMap` 与源表 CharGrowthTable.skillGroupMap 同构——键为完整组 id
  (`<charId>_<族>`),组对象 = 源组全字段(condition*/icon/name/desc/skillGroupType,
  i18n 已反查) + `skillList` 逐成员展开;成员单数 `skillId` 与 SkillPatchTable 键
  一一对应,数值相同的形态变体保持独立条目,忠实源数据不合并。
  四个主技能槽:skillGroupType 0=普攻 1=战技 2=终结 3=连携。
- **未入组 → `"unknown"`**:装备无套装、干员附属技能(被动/变体)统一入 `unknown` 键。
- **全局共享 → `_global.json`**:characters(突破阶段 breakStages)、equips(套装/强化)。
- **富文本**:i18n 文本一律保留 `<@ba.xx>`/`</>` 标签原样,不要在采集侧剥离;
  前端 `rich()` 先整体转义再转 `span.rt`(style.css 已有样式)。
- **描述占位符数值来源**:`{key:fmt}` 的值不在文本里,按位置/键查——
  技能 → 成员 `levels[].blackboard`;潜能 → `potentials[].values`;
  被动节点 → `passiveSkillNodeInfo.values`;天赋节点 → `attributeNodeInfo.attributeModifiers`。
  潜能/被动 values = BuffData 文件垫底 + PotentialTalentEffectTable.dataList
  直接覆盖(attachBuff/attachSkill 黑板 + attrModifier 经 attr_name 转属性名)
  ——BuffData 是共享模板(常为 0 或非本潜能口径),重叠键以 effect 为准;
  约 6% 占位符与 values 键名为位置对应而非同名(如「冷却-3秒」存为 `param2`),
  少数用游戏内部属性名(如 PhysicalAndSpellInflictionEnhance)而 values 存的是
  AttributeMetaTable 词条名(OriginiumArts)——采集不做别名转换,缺数交由
  placeholders.py 维持占位符原文。
  回填实现统一在 `tools/placeholders.py`(采集 weapons/equips 与分析 team_comp
  共用):fmt 模板渲染、算式键(数字/键 ± 相连、* 连乘)、values 恰有一个
  `paramN` 时回退顶替未知键名;缺数(键查不到/解析到 0)一律维持占位符原文
  ——传 missing 清单收集汇总、未传直接抛 ValueError,不回填成「+0%」一类
  误导值,分析侧在运行末尾汇总打印。
- **chr_9000_endmin 是管理员的系统数据实体**:NPC 占位条目(无技能、头像双源
  404),但潜能与天赋的**效果行都在它名下**——CharacterPotentialTable 对
  endminm/endminf 引用 chr_9000_endmin_potential_*,天赋效果行同理取 9000 行
  (characters.py `_TALENT_EFFECT_REDIRECT` 字面 id 逐条映射,不拼字符串、
  不改写节点字面 talentEffectId;endminf 的节点甚至直接引用 endminm 前缀的
  旧行;0002/0003 前缀行是旧设计残留:dataList 空壳、「封印」版文案/位置式
  占位符)。
  其 skillGroupMap 引用 endminm/endminf 的技能 id——展开时必须按干员前缀过滤
  (唯一的多对多情形)。
- **分析产物 JSON key 一律英文**:data/analysis/*.json 机器键用英文标识符
  (资源 atb/usp/poise/heal/shield,维度 firepower/poise/survival/atbCycle/
  energyCycle/diversity),中文名经顶层 resourceLabels/dimensionLabels 映射;
  文案解析的状态前缀用 `{term,prefix}` 列表,不拿中文词当 key。

## 图标(离线源)

- 图标 git 源 `555me/EndfieldAssets`(与 fffdan vfs 同构,17G 完整克隆在 sources/),
  32 个双源 404 的图标构建期注入 `/icons/placeholder.svg`。
- `web/build.mjs` 的 walk 会跳过 `skillGroupMap` 子树——组对象的 `icon` 字段
  不是干员/物品图标引用,勿移除该跳过逻辑。

## 提交

conventional commits 中文描述(`feat(scope): …`),按主题拆分;并行开发中的
他人 WIP 不要混提。
