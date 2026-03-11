# 配方用料倒推 · 数据概览

- 配方 427 条(manual 102、machine 317、spaceship 8);其中拆解/回收配方(dismantler_)75 条
- 涉及物品:产出 295 种,原料 222 种;无配方最初用料 45 种,可制造 177 种
- 口径:同组/同槽原料同时消耗(AND);副产物不做回收抵扣;配方择路 = 主产物 → machine>manual>spaceship → 耗时短 → id;拆解(dismantler_)配方不列为产出途径
- 环处理:z3 整图线性约束,每种物品一条净流量守恒等式,环与共享中间品天然可解;采集类资源(obtainWays 非空)允许外部供给

## 潜在循环依赖(产出图谱,11 组)

以下物品组在图谱上互达成环;z3 求解器以净流量守恒直接解出环内配比(如种子⇄作物自持、清水⇄水蒸气回收),环上采集类资源(清水等)按外部投料计,亦可用 --have 指定持有:

- 分离芯 → 壤晶废液 → 息壤 → 息壤气 → 惰性壤晶废液 → 气态赤铜 → 气态赫铜 → 水蒸气 → 污水 → 沉积酸 → 液化息壤 → 清水 → 碳块 → 碳粉末 → 稳定碳块 → 致密碳粉末 → 芽针 → 芽针种子 → 芽针粉末 → 赤铜块 → 赤铜溶液 → 赤铜粉末 → 赤铜耐压罐 → 赫铜块 → 赫铜溶液 → 酸气 → 锦草 → 锦草种子 → 锦草粉末 → 分离芯
- 液化重息壤 → 重息壤 → 重息壤气 → 液化重息壤
- 实验息壤铜气 → 实验息壤铜锭 → 实验息壤铜气
- 晶体外壳 → 晶体外壳粉末 → 晶体外壳
- 柑实 → 柑实种子 → 柑实
- 气态灼铜 → 灼铜块 → 气态灼铜
- 砂叶 → 砂叶种子 → 砂叶
- 紫晶粉末 → 紫晶纤维 → 紫晶粉末
- 荞花 → 荞花种子 → 荞花
- 蓝铁块 → 蓝铁粉末 → 蓝铁块
- 酮化树种 → 酮化灌木 → 酮化树种

## 示例:铁制零件 ×10

```
目标 铁制零件 ×10
铁制零件 ×10
   └─ 蓝铁矿 ×10

需求原料(精确用量 → 实备数量),1 项:
  [最初用料] 蓝铁矿          ×10         → 备料 10(蓝铁矿矿点采集)
产出:目标 铁制零件 ×10
制造步骤:
  component_iron_cmpt_1 ×10 次  蓝铁块×1 → 铁制零件×1
  furnance_iron_nugget_1 ×10 次  蓝铁矿×1 → 蓝铁块×1
使用设备:配件机、精炼炉
环境需求:无特殊气体环境(全部常规)
产出链路图(mermaid):
```mermaid
flowchart LR
  I_item_iron_cmpt(("铁制零件<br/>目标 ×10"))
  I_item_iron_ore(["蓝铁矿 ×10"])
  R_component_iron_cmpt_1["配件机<br/>component_iron_cmpt_1"]
  R_furnance_iron_nugget_1["精炼炉<br/>furnance_iron_nugget_1"]
  I_item_iron_ore -->|"×10"| R_furnance_iron_nugget_1
  R_component_iron_cmpt_1 -->|"×10"| I_item_iron_cmpt
  R_furnance_iron_nugget_1 -->|"×10"| R_component_iron_cmpt_1
```
z3 求解:最少制造次数口径(优先配方成本 1/4);设施维持按运行时长线性计入流量
```

## 示例:分离芯 ×4

```
目标 分离芯 ×4
分离芯 ×4
   ├─ 赤铜矿 ×4
   ├─ 惰气 ×2
   ├─ 息壤气 ×2 + 2/5
   └─ 清水 ×4

需求原料(精确用量 → 实备数量),4 项:
  [最初用料] 赤铜矿          ×4          → 备料 4(赤铜矿矿点采集)
  [外部投料] 清水           ×4          → 备料 4
  [外部投料] 息壤气          ×2 + 2/5    → 备料 3
  [最初用料] 惰气           ×2          → 备料 2(惰气矿点采集)
产出:目标 分离芯 ×4;副产物 污水 ×4(← furnance_copper_nugget_1)
制造步骤:
  furnance_copper_nugget_1 ×4 次  赤铜矿×1 + 清水×1 → 赤铜块×1 + 污水×1
  liquid_transmuter_2_solid_xiranite_powder_1 ×2 次  息壤气×1 → 息壤×1
  shaper_gas_copper_jar_1 ×2 次  赤铜块×2 + 惰气×1 → 赤铜耐压罐×1
  tools_proc_filter_core_2 ×2 次  赤铜耐压罐×1 + 息壤×1 → 分离芯×2
使用设备:精炼炉、固气转化机、塑形机、封装机
环境需求:无特殊气体环境(全部常规)
产出链路图(mermaid):
```mermaid
flowchart LR
  I_item_copper_ore(["赤铜矿 ×4"])
  I_item_filter_core(("分离芯<br/>目标 ×4"))
  I_item_gas_inert(["惰气 ×2"])
  I_item_gas_xiranite[["息壤气 ×2 + 2/5"]]
  I_item_liquid_sewage["污水"]
  I_item_liquid_water[["清水 ×4"]]
  R_furnance_copper_nugget_1["精炼炉<br/>furnance_copper_nugget_1"]
  R_liquid_transmuter_2_solid_xiranite_powder_1["固气转化机<br/>liquid_transmuter_2_solid_xiranite_powder_1"]
  R_shaper_gas_copper_jar_1["塑形机<br/>shaper_gas_copper_jar_1"]
  R_tools_proc_filter_core_2["封装机<br/>tools_proc_filter_core_2"]
  I_item_copper_ore -->|"×4"| R_furnance_copper_nugget_1
  I_item_gas_inert -->|"×2"| R_shaper_gas_copper_jar_1
  I_item_gas_xiranite -->|"×2"| R_liquid_transmuter_2_solid_xiranite_powder_1
  I_item_liquid_water -->|"×4"| R_furnance_copper_nugget_1
  R_furnance_copper_nugget_1 -->|"×4"| I_item_liquid_sewage
  R_furnance_copper_nugget_1 -->|"×4"| R_shaper_gas_copper_jar_1
  R_liquid_transmuter_2_solid_xiranite_powder_1 -->|"×2"| R_tools_proc_filter_core_2
  R_shaper_gas_copper_jar_1 -->|"×2"| R_tools_proc_filter_core_2
  R_tools_proc_filter_core_2 -->|"×4"| I_item_filter_core
  I_item_gas_xiranite -->|"维持 ×2/5"| R_liquid_transmuter_2_solid_xiranite_powder_1
```
z3 求解:最少制造次数口径(优先配方成本 1/4);设施维持按运行时长线性计入流量
```

## 示例:锦草 ×10

```
目标 锦草 ×10
锦草 ×10
   └─ 清水 ×10

需求原料(精确用量 → 实备数量),1 项:
  [外部投料] 清水           ×10         → 备料 10
产出:目标 锦草 ×10
制造步骤:
  planter_plant_grass_1_1 ×10 次  锦草种子×1 + 清水×1 → 锦草×2
  seedcollector_plant_grass_1_1 ×10 次  锦草×1 → 锦草种子×1
使用设备:种植机、采种机
环境需求:无特殊气体环境(全部常规)
产出链路图(mermaid):
```mermaid
flowchart LR
  I_item_liquid_water[["清水 ×10"]]
  I_item_plant_grass_1(("锦草<br/>目标 ×10"))
  R_planter_plant_grass_1_1["种植机<br/>planter_plant_grass_1_1"]
  R_seedcollector_plant_grass_1_1["采种机<br/>seedcollector_plant_grass_1_1"]
  I_item_liquid_water -->|"×10"| R_planter_plant_grass_1_1
  I_item_plant_grass_1 -->|"×10"| R_seedcollector_plant_grass_1_1
  R_planter_plant_grass_1_1 -->|"×20"| I_item_plant_grass_1
  R_seedcollector_plant_grass_1_1 -->|"×10"| R_planter_plant_grass_1_1
```
z3 求解:最少制造次数口径(优先配方成本 1/4);设施维持按运行时长线性计入流量
```

## 示例:柑实罐头 ×5

```
目标 柑实罐头 ×5
柑实罐头 ×5
   ├─ 柑实 ×12 + 1/2
   └─ 紫晶矿 ×50

需求原料(精确用量 → 实备数量),2 项:
  [最初用料] 紫晶矿          ×50         → 备料 50(紫晶矿矿点采集)
  [外部投料] 柑实           ×12 + 1/2   → 备料 13
产出:目标 柑实罐头 ×5
制造步骤:
  furnance_quartz_glass_1 ×50 次  紫晶矿×1 → 紫晶纤维×1
  grinder_plant_moss_powder_2_1 ×12 + 1/2 次  柑实×1 → 柑实粉末×2
  handwork_bottled_food_1 ×5 次  柑实粉末×5 + 紫晶质瓶×5 → 柑实罐头×1
  shaper_glass_bottle_1 ×25 次  紫晶纤维×2 → 紫晶质瓶×1
使用设备:manual、精炼炉、粉碎机、塑形机
环境需求:无特殊气体环境(全部常规)
产出链路图(mermaid):
```mermaid
flowchart LR
  I_item_bottled_food_1(("柑实罐头<br/>目标 ×5"))
  I_item_plant_moss_2[["柑实 ×12 + 1/2"]]
  I_item_quartz_sand(["紫晶矿 ×50"])
  R_furnance_quartz_glass_1["精炼炉<br/>furnance_quartz_glass_1"]
  R_grinder_plant_moss_powder_2_1["粉碎机<br/>grinder_plant_moss_powder_2_1"]
  R_handwork_bottled_food_1["柑实罐头<br/>handwork_bottled_food_1"]
  R_shaper_glass_bottle_1["塑形机<br/>shaper_glass_bottle_1"]
  I_item_plant_moss_2 -->|"×12 + 1/2"| R_grinder_plant_moss_powder_2_1
  I_item_quartz_sand -->|"×50"| R_furnance_quartz_glass_1
  R_furnance_quartz_glass_1 -->|"×50"| R_shaper_glass_bottle_1
  R_grinder_plant_moss_powder_2_1 -->|"×25"| R_handwork_bottled_food_1
  R_handwork_bottled_food_1 -->|"×5"| I_item_bottled_food_1
  R_shaper_glass_bottle_1 -->|"×25"| R_handwork_bottled_food_1
```
z3 求解:最少制造次数口径(优先配方成本 1/4);设施维持按运行时长线性计入流量
```
