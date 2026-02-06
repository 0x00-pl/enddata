# src/analysis · 进阶分析

基于 `data/` 的数据集做**进阶分析**(区别于 `src/collection/` 的采集与初步处理):
统计数据之外的二次计算与建模,例如:

- 干员 DPS / 技能数值计算(输入 SkillPatchTable 加工结果 + 成长曲线)
- 掉落概率、养成消耗曲线拟合
- 生产产线规划(线性规划,参考 endfield-calc 的 LP 求解器)
- 材料需求倒推(Borg 图遍历 recipes/ 数据集)

## 约定

- 只读 `data/` 数据集目录(`data/<产物>/`,每条一个 `<id>.json` + 轻量索引 `index.json`)+
  `data/*.json`(meta/versions);原始表由 collection 直接经本地仓库读取,原始数据的加工归 `src/collection/`
- 产物写回 `data/analysis/` 或 `reports/`
- 复杂分析脚本建议一个主题一个文件,并以 `analysis.<topic>` 可导入形式组织
- 统一入口:`poetry run enddata analysis <topic>`(见 `src/enddata/cli.py`)

## 已有脚本

- **team_comp.py — 配队分析**(`enddata analysis team`):解析每名干员的技能/天赋/潜能
  (技能 = 满级 blackboard + 描述文案,天赋 = talentNodeMap 被动节点,
  潜能 = potentials[].desc;描述中 {占位符} 经 `tools/placeholders.py` 回填
  满级实际数值——采集/分析共用,数据集缺值保留原文并在运行末尾汇总),
  提炼每条描述的**需求资源**(战技技力/终结技能量/
  触发与消耗状态)与**产出资源**(技力/终结技能量/失衡值/治疗护盾/附着与异常状态)。
  产物:`reports/team-analysis.md`(报告,只保留逐干员技能资源解析一张表)。
  文案解析采用「剥离标签 → 需求/产出两张 regex 表宽松匹配 → 后处理函数精筛」:
  正则以命名组 `demand`/`produce` 捕获片段
  (`_DEMAND_PATTERNS`/`_PRODUCE_PATTERNS`),新句式加一条即可,勿在流程里加特判。

- **gacha.py — 抽卡分析**(`enddata analysis gacha`):寻访概率计算,类架构 =
  `GachaPool` 基类(`pull()` 单抽状态机:每抽更新全局状态 GachaGlobalState 的
  6★/5★保底计数与已拥有干员 owned,以及实例上的当期卡池状态 —— pulls 累计寻访
  即大保底计数、up_got、赠送十连档位)+ 五类卡池子类(限定/复刻/联合/常驻/新手,
  差异全部为类属性,概率字段名与源表 GachaCharPoolTypeTable 一致,单位 = 每百万
  分率;采集侧暂无 gacha 数据集,参数内嵌注明出处)。`POOLS` 按游戏版本给出各期
  卡池对象(配置单例,模拟前 `reset()`;安排 = GachaCharPoolTable 快照,池名经
  i18n 反查)。
  规则口径:6★ 0.8%、66 抽起每抽 +5 个百分点、80 抽必出6★(跨同类型池继承);
  6★ 命中后 **50% 当期干员 + 25% 往期两期限定干员平分 + 25% 名单内常驻平分**
  (名单 = GachaCharPoolContentTable:常驻 5 人 + 当期 + 前两期;复刻池无往期段);
  首个当期干员前本池累计第 120 抽必得**当期**干员(不跨期继承,到手即失效);
  每 10 抽必出 5★+;累计 30 次赠当期十连(基础概率、与保底互不影响、不计累计 →
  付费 = 有效抽数)、60 次赠下期十连券(券入全局状态 next_ten_tickets,下一期限定
  池开局兑换;赠送十连必须整抽,策略不可在免费段中断)。
  **抽卡策略**:`strategy(pool, g) -> bool` 以(当期卡池状态, 全局状态)决定本抽
  是否继续,`run_banner()` 按策略驱动;内置 `strategy_until_owned`(图鉴:拿齐
  即停)。
  两套实现互相对拍:① `simulate()` 驱动 `pull()` 的规则直演(固定种子),
  ② 解析分布(逐抽概率表 + 首个UP首达 DP + 赠送十连并入;全图鉴抽数 = 单池
  分布卷积)。产物:`reports/gacha-analysis.md`(版本 UP 卡池安排含同池往期提升
  + 全图鉴所需付费抽数统计:期望 ~870、P90 ~1025、上限 1320 = 11×120;联合/
  复刻池为重复获取机会不占主路径)。参考结论:单池当期干员首达期望 ~79.3 付费抽;
  按逐池顺序收集时「前两期同池提升」对全图鉴期望几乎无影响(顺路命中的往期
  干员均已拥有)。

原初版产线规划器(planner.py)因配方图环依赖处理有误已移除;
后续做产线/材料规划时建议基于线性规划重做,参考 endfield-calc 的 LP 求解器。
