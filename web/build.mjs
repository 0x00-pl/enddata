#!/usr/bin/env node
/**
 * EndData 站点构建:把 data/ 数据集与 web/ 静态源码编译成零外链的 dist/。
 *
 * 图标本地化:数据集只存图标裸 id(采集管线不再生成 URL),本脚本按
 * config/sources.json → sources.icon_git 的映射,从本地 git 图标源
 * (555me/EndfieldAssets,经 `enddata collection clone` 的 partial+sparse 克隆)
 * 复制引用到的图标到 dist/icons/sprites/,并为数据集注入 /icons/sprites/... URL。
 *
 * 用法:在仓库根目录执行 npm run build(即 node web/build.mjs)
 * 依赖:仅 Node 标准库(≥18),无需 npm install。
 */

import { execFileSync } from "node:child_process";
import { copyFileSync, cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const WEB = join(ROOT, "web");
const DATA = join(ROOT, "data");
const DIST = join(ROOT, "dist");
const MD_DOCS = ["docs/sources.md", "reports/build-report.md"];

const config = JSON.parse(readFileSync(join(ROOT, "config", "sources.json"), "utf8"));
const iconCfg = config.sources.icon_git;
const repoDir = join(ROOT, config.git?.repos_dir ?? "sources", iconCfg.repo.replaceAll("/", "__"));
const spritesRoot = join(repoDir, iconCfg.sprites_root);
const urlPrefix = iconCfg.url_prefix;
const maps = iconCfg.maps;

// 缺失图标的占位图(两个源都 404 时注入它的 URL,页面不留裸 404)
const PLACEHOLDER_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="icon missing"><rect width="64" height="64" rx="10" fill="#eceff3"/><rect x="4" y="4" width="56" height="56" rx="7" fill="none" stroke="#c8ced6" stroke-width="2" stroke-dasharray="5 4"/><text x="32" y="43" font-family="sans-serif" font-size="30" fill="#9aa3af" text-anchor="middle">?</text></svg>\n`;

function info(msg) {
  console.log(`[build] ${msg}`);
}

function die(msg) {
  console.error(`[build] 错误:${msg}`);
  process.exit(1);
}

function git(repoArgs, args) {
  return execFileSync("git", ["-C", repoDir, ...args], { encoding: "utf8" }).trim();
}

/** 递归收集 dir 下所有 .json 文件路径。 */
function jsonFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...jsonFiles(p));
    else if (name.endsWith(".json")) out.push(p);
  }
  return out;
}

/** 深度遍历 JSON 树,对拥有非空字符串 id 字段的对象执行 inject(obj)。 */
function walk(node, idField, inject) {
  if (Array.isArray(node)) {
    for (const e of node) walk(e, idField, inject);
  } else if (node && typeof node === "object") {
    const id = node[idField];
    if (typeof id === "string" && id) inject(node, id);
    for (const [k, v] of Object.entries(node)) {
      if (k === "skillGroupMap") continue; // 组对象的 icon 等字段不是干员/物品图标引用
      walk(v, idField, inject);
    }
  }
}

// ---- 前置检查 ------------------------------------------------------------
if (!existsSync(DATA)) die(`缺少 ${relative(ROOT, DATA)},先运行 poetry run enddata collection all`);
if (!existsSync(join(repoDir, ".git"))) {
  die(`图标源仓库未克隆(${relative(ROOT, repoDir)}),先运行 poetry run enddata collection clone`);
}

// ---- 生成 dist:清空重建 --------------------------------------------------
rmSync(DIST, { recursive: true, force: true });
mkdirSync(DIST, { recursive: true });

cpSync(join(WEB, "index.html"), join(DIST, "index.html"));
cpSync(join(WEB, "assets"), join(DIST, "assets"), { recursive: true });
for (const md of MD_DOCS) {
  const src = join(ROOT, md);
  if (!existsSync(src)) {
    info(`警告:缺少 ${md}(index.html 的链接将 404),先运行 enddata collection all 生成报告`);
    continue;
  }
  cpSync(src, join(DIST, md));
}
cpSync(DATA, join(DIST, "data"), { recursive: true });

// 占位图与图标输出目录
const iconsOut = join(DIST, iconCfg.icons_out); // dist/icons/sprites
const placeholderUrl = `${urlPrefix.replace(/\/sprites$/, "")}/placeholder.svg`;
mkdirSync(iconsOut, { recursive: true });
writeFileSync(join(dirname(iconsOut), "placeholder.svg"), PLACEHOLDER_SVG, "utf8");

// ---- 图标落地与 URL 注入 ---------------------------------------------------
const copied = new Set(); // "dir/stem" → 避免重复复制
const stats = {};

for (const [product, fields] of Object.entries(maps)) {
  const productDir = join(DIST, "data", product);
  if (!existsSync(productDir)) die(`dist/data/${product} 不存在,先重新采集该产物`);

  const per = { injected: new Set(), missing: new Set() };
  for (const file of jsonFiles(productDir)) {
    const before = readFileSync(file, "utf8");
    const tree = JSON.parse(before);

    for (const { url: urlField, id: idField, dir } of fields) {
      walk(tree, idField, (obj, stem) => {
        if (stem.includes("/") || stem.includes("..")) return; // 非法 id(URL 形态的值),不处理
        const key = `${dir}/${stem}`;
        const src = join(spritesRoot, dir, `${stem}.png`);
        if (!existsSync(src)) {
          // 缺失(vfs 与 git 源都无此资源):注入占位图,不留裸 404;清单中标注
          obj[urlField] = placeholderUrl;
          per.missing.add(stem);
          return;
        }
        if (!copied.has(key)) {
          const dest = join(iconsOut, dir, `${stem}.png`);
          mkdirSync(dirname(dest), { recursive: true });
          copyFileSync(src, dest);
          copied.add(key);
        }
        obj[urlField] = `${urlPrefix}/${dir}/${stem}.png`;
        per.injected.add(stem);
      });
    }

    const after = JSON.stringify(tree, null, 2);
    if (after !== before) writeFileSync(file, `${after}\n`, "utf8");
  }

  stats[product] = {
    injected: per.injected.size,
    missing: per.missing.size,
    missingIds: [...per.missing].sort(),
  };
  info(`${product}: 注入 ${per.injected.size},缺失 ${per.missing.size}`);
}

// ---- 构建清单 ---------------------------------------------------------------
const head = git(repoDir, ["log", "-1", "--format=%H %cs"]).split(" ");
const manifest = {
  generatedAt: new Date().toISOString(),
  source: {
    repo: iconCfg.repo,
    branch: iconCfg.branch ?? git(repoDir, ["symbolic-ref", "--short", "HEAD"]),
    head: head[0],
    headDate: head[1],
  },
  iconsCopied: copied.size,
  stats,
};
writeFileSync(join(DIST, "data", "_icons.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");

const missingAll = Object.values(stats).reduce((n, s) => n + s.missing, 0);
info(`完成:dist/ 共 ${copied.size} 个图标,缺失 ${missingAll}(清单见 dist/data/_icons.json)`);
if (missingAll > 0) {
  info(`缺失样例:${Object.values(stats).flatMap((s) => s.missingIds).slice(0, 5).join(", ")} ...`);
}
