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

原初版产线规划器(planner.py)因配方图环依赖处理有误已移除;
后续做产线/材料规划时建议基于线性规划重做,参考 endfield-calc 的 LP 求解器。
