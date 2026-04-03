# AGENTS.md — 项目记忆(会话自动加载)

EndData · 明日方舟:终末地 数据站。采集(Python 标准库)→ JS 构建生成零外链站点。
详细文档在 `docs/`(sources 数据源调研 / data-model 字段结构与数据约定 /
data-lineage 血缘统计 / id-map id 映射),本文件只记约定与坑。

## 常用命令(全部在仓库根执行)

```bash
poetry run enddata collection clone/all   # 数据源同步 / 全量采集
npm run build                             # 即 node web/build.mjs → dist/
python3 -m http.server 8321 --bind 127.0.0.1 --directory dist
```

- 采集重跑后必须重跑 `npm run build`(数据集只存裸 id,URL 由构建期注入)。
- 唯一根目录是 project-root;JS 项目根也是它(package.json 在根,零 npm 依赖)。
- `data/`、`dist/`、`sources/` 均已 gitignore;`.zcode/` 不要提交。

## 代码检查与提交钩子

- Python 统一 `poetry run ruff check src tests`(风格/lint)+ `poetry run mypy`
  (静态类型);配置在 pyproject.toml,渐进式基线(mypy 非 strict,不查无注解函数体)。
- 提交含 .py 改动时 `.githooks/pre-commit` 自动跑两项检查并拦截失败;
  钩子经 `git config core.hooksPath .githooks` 启用(新克隆记得执行)。
- 逐点豁免:`# noqa: <code> - 原因`(ruff)/ `# type: ignore[<code>]`(mypy),
  必须写原因;全局豁免(中文全角标点 RUF001-003、git 子进程 S603/S607 等)在
  pyproject `[tool.ruff.lint] ignore`,新增全局豁免需谨慎。
- 修改 .py 后提交前自查:ruff 必须全绿,mypy 不得新增错误,pytest 通过。

## 数据约定速记(细节见 docs/data-model.md)

- **技能**:`skillGroupMap` 与源表 CharGrowthTable.skillGroupMap 同构,键为完整
  组 id;未入组技能统一入 `unknown` 键;跨干员共享的全局配置入 `_global.json`。
- **富文本**:i18n 文本一律保留 `<@ba.xx>`/`</>` 标签原样,不在采集侧剥离;
  前端 `rich()` 先整体转义再渲染。
- **占位符**:`{key:fmt}` 数值按位置/键查 blackboard/values(来源映射与缺数
  约定见 docs/data-model.md「描述占位符数值来源与缺数约定」);缺数一律维持
  占位符原文,不回填误导值。
- **管理员**:`chr_9000_endmin` 是系统数据实体,潜能/天赋效果行都在它名下
  (重定向映射见 characters.py `_TALENT_EFFECT_REDIRECT`,详见 docs/data-model.md)。
- **分析产物 JSON key 一律英文**:中文名经顶层 resourceLabels/dimensionLabels
  映射,不拿中文词当 key(约定见 docs/data-model.md「分析产物的 key 约定」)。

## 图标(离线源)

- 图标 git 源 `555me/EndfieldAssets`(与 fffdan vfs 同构,17G 完整克隆在 sources/),
  32 个双源 404 的图标构建期注入 `/icons/placeholder.svg`。
- `web/build.mjs` 的 walk 会跳过 `skillGroupMap` 子树——组对象的 `icon` 字段
  不是干员/物品图标引用,勿移除该跳过逻辑。

## id 关联映射(idmap)

- 查找/核对 id 对应关系(引用是否存在、定义在哪、被谁引用)优先用 idmap,
  不要手工拼字符串猜测:`enddata idmap build` 重建 `data/id_map/`,
  `enddata idmap relate <file#path>` 返回同组定位符列表;程序化用法见
  `tools/id_links.py`(ids.jsonl 逐行 id → defs/refs)与 docs/id-map.md。
  扫描黑名单 SCAN_BLACKLIST 排除 i18n 与关卡侧资源目录,优先于范围与 --dir。

## 提交

conventional commits 中文描述(`feat(scope): …`),按主题拆分;并行开发中的
他人 WIP 不要混提。
