# 构建报告

- 构建时间:2026-09-16T10:30:05+00:00(UTC)
- 数据源:rmxlinux/EndfieldData@main
- 默认翻译语言:CN
- i18n 未命中:0

## 数据集规模

| 数据集 | 条数 |
|---|---|
| 干员 characters | 33 |
| 物品 items(含图标 id 2808 条) | 2829 |
| 配方 recipes | 427 |
| 武器 weapons | 79 |
| 装备 equips / 套装 suits | 258 / 24 |
| 敌人 enemies | 381 |

## 产物位置

- 数据集:`data/<产物>/` 目录(每条一个 `<id>.json` + 轻量索引 `index.json`;
  图标只存裸 id,经 `node web/build.mjs` 构建为 dist/ 零外链站点后展示)
- 本报告:`reports/build-report.md`
