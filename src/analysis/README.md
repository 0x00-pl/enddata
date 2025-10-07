# src/analysis · 进阶分析

基于 `data/processed/` 的数据集做**进阶分析**(区别于 `src/collection/` 的采集与初步处理):
统计数据之外的二次计算与建模,例如:

- 干员 DPS / 技能数值计算(输入 SkillPatchTable 加工结果 + 成长曲线)
- 掉落概率、养成消耗曲线拟合
- 生产产线规划(线性规划,参考 endfield-calc 的 LP 求解器)
- 材料需求倒推(Borg 图遍历 recipes.json)

## 约定

- 只读 `data/processed/*.json`,不直接读 `data/raw/`(原始数据的加工归 `src/collection/`)
- 产物写回 `data/processed/analysis/` 或 `reports/`
- 复杂分析脚本建议一个主题一个文件,并以 `analysis.<topic>` 可导入形式组织
