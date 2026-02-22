/* EndData 前端:加载 dist/data 数据集并渲染各分页。无框架、无构建。
   数据布局:每个产物一个目录 data/<产物>/(每条一个 <id>.json + 轻量索引 index.json),
   列表页只读 index.json;全局共享配置在 _global.json(装备套装/强化 → equips/,
   干员突破阶段 → characters/)。 */

const main = document.getElementById("main");
const tabs = document.getElementById("tabs");

const state = {
  data: {},
  current: "overview",
  search: {},
  filters: {},
};

const FORMATTER = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });

async function loadData() {
  const folders = ["characters", "weapons"];
  const results = await Promise.allSettled([
    (await fetch("/data/meta.json")).json(),
    ...folders.map((n) => fetch(`/data/${n}/index.json`).then((r) => r.json())),
    (await fetch("/data/equips/_global.json")).json(),
    (await fetch("/data/equips/index.json")).json(),
    (await fetch("/data/recipes/index.json")).json(),
    (await fetch("/data/items/index.json")).json(),
    (await fetch("/data/enemies/index.json")).json(),
    (await fetch("/data/characters/_global.json")).json(),
  ]);
  const put = (i, key) => {
    if (results[i].status === "fulfilled") state.data[key] = results[i].value;
  };
  put(0, "meta");
  folders.forEach((n, i) => put(i + 1, n));
  put(folders.length + 1, "equipsGlobal");
  put(folders.length + 2, "equipIds");  // 装备清单:按套装分组的 id 列表
  put(folders.length + 3, "recipeIds"); // 配方清单:按站点分组的 id 列表
  put(folders.length + 4, "itemIds");   // 物品清单:按类型 slug 分组的 id 列表
  put(folders.length + 5, "enemyIds");  // 敌人清单:按类型 slug 分组的 id 列表
  put(folders.length + 6, "breakStages"); // 突破阶段:全局表(_global.json,所有干员共享)
  // id → 子目录 映射,供详情浮层定位清单式数据集的子文件
  const manifests = { equips: state.data.equipIds, items: state.data.itemIds, enemies: state.data.enemyIds };
  state.slugMap = {};
  for (const [product, manifest] of Object.entries(manifests)) {
    state.slugMap[product] = Object.fromEntries(
      Object.entries(manifest ?? {}).flatMap(([slug, ids]) => (ids ?? []).map((id) => [id, slug])));
  }
}

/* ---------- 通用渲染工具 ---------- */

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const num = (v) => (typeof v === "number" ? FORMATTER.format(Math.round(v * 10) / 10) : "—");

const rarityTag = (r) => `<span class="rarity r${r ?? 0}">${"★".repeat(Math.min(r ?? 0, 6)) || "—"}</span>`;

function toolbar(tab, placeholder, filterHtml = "") {
  return `<div class="toolbar">
    <input type="search" placeholder="${esc(placeholder)}" value="${esc(state.search[tab] ?? "")}"
           oninput="window.__search('${tab}', this.value)">
    ${filterHtml}
  </div>`;
}

window.__search = (tab, v) => {
  state.search[tab] = v;
  render();
};

function match(text, q) {
  return !q || String(text ?? "").toLowerCase().includes(q.toLowerCase());
}

/* ---------- 各分页 ---------- */

function renderOverview() {
  const m = state.data.meta;
  if (!m) return `<div class="error-state">未找到 data/meta.json —— 请先运行 poetry run enddata collection all</div>`;
  const c = m.counts;
  return `
    <div class="kpis">
      <div class="kpi"><div class="n">${c.characters}</div><div class="l">干员</div></div>
      <div class="kpi"><div class="n">${c.weapons}</div><div class="l">武器</div></div>
      <div class="kpi"><div class="n">${c.equips ?? "—"}</div><div class="l">装备</div></div>
      <div class="kpi"><div class="n">${c.items}</div><div class="l">物品</div></div>
      <div class="kpi"><div class="n">${c.recipes}</div><div class="l">生产配方</div></div>
      <div class="kpi"><div class="n">${c.enemies}</div><div class="l">敌人</div></div>
    </div>
    <p class="note">数据源:${esc(m.source.repo)}@${esc(m.source.branch)} · 构建于 ${esc(m.generatedAt)} (UTC) · 点击列表条目查看详情</p>
    <table><tbody>
      <tr><td class="dim">战斗数据</td><td>干员等级成长曲线、职业、武器类型、敌人属性模板(生命/攻击/防御、抗性、霸体)已入库;技能数值(SkillPatchTable)已抓取,待加工。</td></tr>
      <tr><td class="dim">生产数据</td><td>手工配方(大世界制作)、基建工厂产线配方(按生产设施与进料相别分组)、飞船制造已入库;电力/物流/流派加成待扩展。</td></tr>
      <tr><td class="dim">计划中</td><td>技能与 Buff 数值解析、配方产物图标。</td></tr>
    </tbody></table>`;
}

function renderCharacters() {
  const q = state.search.characters ?? "";
  const list = (state.data.characters ?? []).filter(
    (c) => match(c.name, q) || match(c.enName, q) || match(c.professionName, q)
  );
  const maxStat = 700;
  const statRow = (label, v) => `
    <div class="stat-row"><span class="dim">${label}</span>
      <span class="bar"><i style="width:${Math.min((v ?? 0) / maxStat * 100, 100)}%"></i></span>
      <span class="v">${num(v)}</span></div>`;
  return `
    ${toolbar("characters", "搜索干员名 / 职业…")}
    <div class="cards">${list.map((c) => `
      <div class="card clickable" data-detail="characters" data-id="${esc(c.id)}">
        <h3>${c.icon ? `<img class="avatar" src="${esc(c.icon)}" alt="" loading="lazy" onerror="this.remove()">` : ""}${esc(c.name)} ${rarityTag(c.rarity)}</h3>
        <div class="sub">${c.professionIcon ? `<img class="icon-sm" src="${esc(c.professionIcon)}" alt="" loading="lazy" onerror="this.remove()">` : ""}${esc(c.professionName ?? c.profession)} · 武器:${esc(c.weaponType ?? "—")}
          ${c.cv ? ` · CV:${esc(c.cv)}` : ""} · 满级 ${c.maxLevel}</div>
        ${statRow("生命", c.lvMax?.MaxHp)}${statRow("攻击", c.lvMax?.Atk)}
        ${statRow("力", c.lvMax?.Str)}${statRow("敏", c.lvMax?.Agi)}
        ${statRow("智", c.lvMax?.Wisd)}${statRow("意志", c.lvMax?.Will)}
      </div>`).join("") || '<div class="empty-state">无匹配结果</div>'}
    </div>`;
}

function renderWeapons() {
  const q = state.search.weapons ?? "";
  const list = (state.data.weapons ?? []).filter((w) => match(w.name, q) || match(w.weaponType, q));
  return `
    ${toolbar("weapons", "搜索武器名 / 类型…")}
    <table><thead><tr><th>武器</th><th>稀有度</th><th>类型</th><th>满级</th></tr></thead><tbody>
    ${list.map((w) => `<tr class="clickable" data-detail="weapons" data-id="${esc(w.id)}">
      <td>${esc(w.name)}</td><td>${rarityTag(w.rarity)}</td>
      <td>${esc(w.weaponType ?? "—")}</td><td class="num">${w.maxLevel ?? "—"}</td>
    </tr>`).join("")}
    </tbody></table>`;
}

function renderItems() {
  if (!state.data.items) {
    loadItemDetails();
    return `<div class="empty-state">正在按 data/items/index.json 清单加载物品(2829 条)…</div>`;
  }
  const q = state.search.items ?? "";
  const type = state.filters.items ?? "";
  const types = [...new Set(state.data.items.map((i) => i.typeName).filter(Boolean))].sort();
  const list = state.data.items
    .filter((i) => (!type || i.typeName === type) && (match(i.name, q) || match(i.id, q)));
  return `
    ${toolbar("items", "搜索物品名 / ID…", `
      <select onchange="window.__filter('items', this.value)">
        <option value="">全部类型</option>
        ${types.map((t) => `<option ${t === type ? "selected" : ""}>${esc(t)}</option>`).join("")}
      </select>`)}
    <p class="note">data/items/ 按物品类型 EN slug 分子目录存放(typeSlug),
      index.json 为按类型分组的 id 清单。</p>
    <table><thead><tr><th>物品</th><th>稀有度</th><th>类型</th><th>堆叠</th></tr></thead><tbody>
    ${list.slice(0, 500).map((i) => `<tr class="clickable" data-detail="items" data-sub="${esc(i.typeSlug ?? "")}" data-id="${esc(i.id)}">
      <td>${i.iconUrl ? `<img class="icon-sm" src="${esc(i.iconUrl)}" alt="" loading="lazy" onerror="this.remove()">` : ""}${esc(i.name ?? i.id)} <span class="dim">${esc(i.id)}</span></td>
      <td>${rarityTag(i.rarity)}</td><td>${esc(i.typeName ?? i.type ?? "—")}</td>
    </tr>`).join("")}
    </tbody></table>
    ${list.length > 500 ? `<p class="note">仅显示前 500 / ${list.length} 条,请用搜索缩小范围。</p>` : ""}`;
}

function recipeSide(side) {
  return side
    .flatMap((ing) => ing.group.map((o) =>
      `<span title="${esc(o.id)}">${esc(o.name)}</span>×${o.count}`))
    .join(" + ");
}

const recipeCategory = (r) => r.showingName ?? r.machineName ?? null;

/* 站点命名:游戏内工厂即玩家俗称的"基建",machine 站点按基建产线展示 */
const STATION_ORDER = ["manual", "machine", "spaceship"];
const STATION_NAME = { manual: "手工制作", machine: "基建工厂", spaceship: "飞船制造" };
const STATION_BADGE = { manual: "手工", machine: "基建", spaceship: "飞船" };

/* 机器配方组后缀 → 进料相别(同机多模式:灌装/拆解按溶液、气体等进料区分配方组) */
const PHASE_CN = { normal: "常规", liquid: "液相", gasliquid: "气液", gas: "气相",
                   liquidtrans: "液转", gastrans: "气转", solidtrans: "固转" };
const recipePhase = (r) => {
  const m = /_(normal|gasliquid|liquidtrans|gastrans|solidtrans|liquid|gas)$/.exec(r.formulaGroupId ?? "");
  return m ? PHASE_CN[m[1]] : null;
};

/* 机器配方所需气体环境(FactoryEnvDisplayTable GenEnv;0=无要求不在表中) */
const GAS_ENV_CN = { 0: "无要求", 1: "稳定", 2: "湿润", 3: "酸性" };

let recipeDetailsLoading = false;

/* 清单式数据集(recipes/items)通用:按清单批量拉取子文件,载入一次后缓存。
   任务为 thunk(延迟发起),worker 池限制真实并发,避免请求洪峰。 */
async function bulkLoadDetails(manifest, pathOf, key) {
  if (state.data[key] || state.loading?.[key]) return;
  state.loading = state.loading ?? {};
  state.loading[key] = true;
  const jobs = Object.entries(manifest ?? {}).flatMap(([sub, ids]) =>
    (ids ?? []).map((id) => async () => {
      const r = await fetch(pathOf(sub, id));
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }));
  const out = [];
  const CONCURRENCY = 8;
  let next = 0;
  async function worker() {
    while (next < jobs.length) {
      const k = next++;
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          out[k] = await jobs[k]();
          break;
        } catch {
          if (attempt) console.warn(`${key} 子文件加载失败,已跳过:`, k);
        }
      }
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  state.data[key] = out.filter(Boolean);
  state.loading[key] = false;
  render();
}

const loadRecipeDetails = () =>
  bulkLoadDetails(state.data.recipeIds, (st, id) => `/data/recipes/${st}/${id}.json`, "recipes");

const loadItemDetails = () =>
  bulkLoadDetails(state.data.itemIds, (slug, id) => `/data/items/${slug}/${id}.json`, "items");

const loadEnemyDetails = () =>
  bulkLoadDetails(state.data.enemyIds, (slug, id) => `/data/enemies/${slug}/${id}.json`, "enemies");

const loadEquipDetails = () =>
  bulkLoadDetails(state.data.equipIds, (suit, id) => `/data/equips/${suit}/${id}.json`, "equips");

function renderRecipes() {
  if (!state.data.recipes) {
    loadRecipeDetails();
    return `<div class="empty-state">正在按 data/recipes/index.json 清单加载配方…</div>`;
  }
  const q = state.search.recipes ?? "";
  const st = state.filters.recipes ?? "";
  const cat = state.filters.recipeCat ?? "";
  const catKey = (r) => recipeCategory(r) ?? "未分类";
  const byStation = state.data.recipes.filter((r) => !st || r.station === st);
  const catCount = {};
  byStation.forEach((r) => { const k = catKey(r); catCount[k] = (catCount[k] ?? 0) + 1; });
  const cats = Object.keys(catCount).sort((a, b) => {
    const ta = Math.min(...byStation.filter((r) => catKey(r) === a).map((r) => r.showingType ?? 0));
    const tb = Math.min(...byStation.filter((r) => catKey(r) === b).map((r) => r.showingType ?? 0));
    return ta - tb || catCount[b] - catCount[a];
  });
  const catEff = cats.includes(cat) ? cat : "";
  const hit = (r) => match(r.name, q) || match(r.formulaDesc, q)
    || match(r.outcomes.map((o) => o.group[0].name).join(), q)
    || match(r.ingredients.flatMap((i) => i.group.map((g) => g.name)).join(), q);
  const list = byStation.filter((r) => (!catEff || catKey(r) === catEff) && hit(r));
  const totalBy = (s) => state.data.recipes.filter((r) => r.station === s).length;
  const stations = STATION_ORDER.filter((s) => list.some((r) => r.station === s));

  /* 分类区块:summary 折叠,表格列按站点差异显示(机器:相别/耗时;手工/飞船:稀有度) */
  const categorySection = (s, name, rows) => {
    const phases = [...new Set(rows.map(recipePhase).filter(Boolean))];
    const showPhase = s === "machine" && phases.length > 1;
    const showTime = rows.some((r) => r.craftTimeSec != null);
    const showRarity = rows.some((r) => r.rarity != null);
    const machine = rows.find((r) => r.machineId);
    return `<details class="rgroup" open>
      <summary title="${esc(machine?.machineId ?? name)}">
        <span class="rg-name">${esc(name)}</span><span class="rg-cnt">${rows.length} 条</span>
        ${phases.length > 1 ? phases.map((p) =>
          `<span class="badge phase">${esc(p)} ${rows.filter((r) => recipePhase(r) === p).length}</span>`).join("") : ""}
      </summary>
      <table><thead><tr><th>产物</th><th>原料</th>
        ${showPhase ? "<th>相别</th>" : ""}${showTime ? "<th>耗时</th>" : ""}${showRarity ? "<th>稀有度</th>" : ""}
      </tr></thead><tbody>
      ${rows.map((r) => {
        const out = r.outcomes[0]?.group[0];
        return `<tr class="clickable" data-detail="recipes" data-sub="${esc(r.station)}" data-id="${esc(r.id)}">
          <td>${esc(r.name || out?.name || r.id)}${r.name && out && r.name !== out.name ? ` <span class="dim">${esc(out.name)}</span>` : ""} ×${out?.count ?? 1}</td>
          <td><div class="recipe-line">${recipeSide(r.ingredients) || '<span class="opt">—</span>'}</div></td>
          ${showPhase ? `<td>${recipePhase(r) ? `<span class="badge">${esc(recipePhase(r))}</span>` : "—"}</td>` : ""}
          ${showTime ? `<td class="num">${r.craftTimeSec != null ? `${trimN(r.craftTimeSec)}s` : "—"}</td>` : ""}
          ${showRarity ? `<td>${rarityTag(r.rarity)}</td>` : ""}
        </tr>`;
      }).join("")}
      </tbody></table>
    </details>`;
  };

  return `
    ${toolbar("recipes", "搜索配方 / 产物 / 原料名…", `
      <select onchange="window.__filter('recipes', this.value)">
        <option value="">全部站点</option>
        ${STATION_ORDER.map((s) => `<option value="${s}" ${st === s ? "selected" : ""}>${STATION_NAME[s]}</option>`).join("")}
      </select>
      <select onchange="window.__filter('recipeCat', this.value)">
        <option value="">全部分类</option>
        ${cats.map((c) => `<option ${c === catEff ? "selected" : ""}>${esc(c)}</option>`).join("")}
      </select>`)}
    <p class="note">共 ${state.data.recipes.length} 条配方:
      ${STATION_ORDER.filter(totalBy).map((s) => `${STATION_NAME[s]} ${totalBy(s)}`).join(" · ")}
      ${list.length !== state.data.recipes.length ? `,当前匹配 ${list.length} 条` : ""}。
      按站点与分类分组展示:手工/飞船按游戏内分类(应急食药/精制食药/随身装置/种植调配/素材转化等),
      基建工厂按生产设施(灌装机/拆解机/精炼炉/…),同设施多进料模式以相别(液相/气液/气相/常规)细分,点击分类标题可折叠。</p>
    ${stations.map((s) => {
      const rows = list.filter((r) => r.station === s);
      const grouped = new Map();
      rows.forEach((r) => {
        if (!grouped.has(catKey(r))) grouped.set(catKey(r), []);
        grouped.get(catKey(r)).push(r);
      });
      const entries = [...grouped.entries()].map(([name, rs]) => {
        rs.sort((a, b) => (a.sortId ?? 0) - (b.sortId ?? 0) || a.id.localeCompare(b.id));
        return [name, rs];
      });
      // 机器分类按配方数降序;手工/飞船沿用分类下拉的 showingType 顺序
      if (s === "machine") entries.sort((a, b) => b[1].length - a[1].length);
      else entries.sort((a, b) => cats.indexOf(a[0]) - cats.indexOf(b[0]));
      return `<section class="rstation">
        <h3 class="rstation-h"><span class="badge ${s}">${STATION_BADGE[s]}</span>${STATION_NAME[s]}
          <span class="dim">${rows.length} 条 · ${entries.length} 个分类</span></h3>
        ${entries.map(([name, rs]) => categorySection(s, name, rs)).join("")}
      </section>`;
    }).join("") || '<div class="empty-state">无匹配结果</div>'}`;
}

function renderEquips() {
  if (!state.data.equips) {
    loadEquipDetails();
    return `<div class="empty-state">正在按 data/equips/index.json 清单加载装备…</div>`;
  }
  const equips = state.data.equips;
  const suits = (state.data.equipsGlobal ?? {}).suits ?? [];
  const q = state.search.equips ?? "";
  const part = state.filters.equips ?? "";
  const suit = state.filters.equipSuit ?? "";
  const list = equips
    .filter((e) => (!part || e.part === part) && (!suit || e.suit === suit)
      && (match(e.name, q) || match(e.suit, q)));
  const PART = { body: "躯体", hand: "手部", edc: "挂载" };
  return `
    ${toolbar("equips", "搜索装备名 / 套装…", `
      <select onchange="window.__filter('equips', this.value)">
        <option value="">全部部位</option>
        ${["body", "hand", "edc"].map((t) => `<option value="${t}" ${t === part ? "selected" : ""}>${PART[t]}</option>`).join("")}
      </select>
      <select onchange="window.__filter('equipSuit', this.value)">
        <option value="">全部套装</option>
        ${suits.map((x) => `<option value="${esc(x.id)}" ${x.id === suit ? "selected" : ""}>${esc(x.name)}</option>`).join("")}
      </select>`)}
    <p class="note">套装被动效果(悬停查看描述,详见装备详情页):
      ${suits.map((x) => `<span class="badge" title="${esc(x.effects.map((e2) => `${e2.count}件:${e2.desc ?? "—"}`).join("\n"))}">${esc(x.name)}(${x.effects.map((e2) => e2.count + "件").join("/")})</span>`).join(" ")}
    </p>
    <table><thead><tr><th>装备</th><th>稀有度</th><th>部位</th><th>套装</th><th>词条</th></tr></thead><tbody>
    ${list.map((e) => `<tr class="clickable" data-detail="equips" data-sub="${esc(e.suit ?? "unknown")}" data-id="${esc(e.id)}">
      <td>${e.icon ? `<img class="icon-sm" src="${esc(e.icon)}" alt="" loading="lazy" onerror="this.remove()">` : ""}${esc(e.name)} <span class="dim">${esc(e.id)}</span></td>
      <td>${rarityTag(e.rarity)}</td><td>${PART[e.part] ?? e.part ?? "—"}</td>
      <td>${e.suit ? `<span class="badge machine">${esc((suits.find((x) => x.id === e.suit) ?? {}).name ?? e.suit)}</span>` : "—"}</td>
      <td class="dim">${(e.attrs ?? []).map((a) => `${a.type} +${num(a.value)}`).join(" / ") || "—"}</td>
    </tr>`).join("")}
    </tbody></table>`;
}

function renderEnemies() {
  if (!state.data.enemies) {
    loadEnemyDetails();
    return `<div class="empty-state">正在按 data/enemies/index.json 清单加载敌人…</div>`;
  }
  const q = state.search.enemies ?? "";
  const list = state.data.enemies.filter(
    (e) => match(e.name, q) || match(e.nickname, q) || match(e.id, q)
  );
  return `
    ${toolbar("enemies", "搜索敌人名 / ID…")}
    <p class="note">显示名来自解包 EnemyTemplateDisplayInfoTable(默认语言,374/381,缺失以 ID 兜底),
      图标来自森空岛 Wiki「威胁」分区;data/enemies/ 按类型(EN slug)分子目录存放。</p>
    <table><thead><tr><th>敌人</th><th>类型</th><th>威胁</th><th>初始霸体</th><th>韧性</th><th>满级生命</th><th>满级攻击</th><th>抗性</th></tr></thead><tbody>
    ${list.slice(0, 400).map((e) => {
      const nm = e.name || e.nickname || e.id;
      return `<tr class="clickable" data-detail="enemies" data-sub="${esc(e.typeSlug ?? "")}" data-id="${esc(e.id)}">
      <td>${e.icon ? `<img class="icon-sm" src="${esc(e.icon)}" alt="" loading="lazy" onerror="this.remove()">` : ""}${esc(nm)} <span class="dim">${esc(e.id)}</span></td>
      <td>${esc(e.typeName ?? "—")}</td>
      <td>${e.dangerous ? '<span class="rarity r6">精英</span>' : "—"}</td>
      <td class="num">${e.superArmor ?? "—"}</td>
      <td class="num">${e.maxResilience ?? "—"}</td>
      <td class="num">${num(e.lvMax?.MaxHp)}</td><td class="num">${num(e.lvMax?.Atk)}</td>
      <td class="dim">${Object.entries(e.resists ?? {}).filter(([, v]) => v)
        .map(([k, v]) => `${RESIST_CN[k] ?? k} ${Math.round(v * 100)}%`).join(", ") || "—"}</td>
    </tr>`;
    }).join("")}
    </tbody></table>
    ${list.length > 400 ? `<p class="note">仅显示前 400 / ${list.length} 条。</p>` : ""}`;
}

/* ---------- 详情浮层:点击列表条目,懒加载 data/<产物>/<id>.json ---------- */

const RESIST_CN = { physical: "物理", fire: "火", pulse: "脉冲", cryst: "结晶", natural: "自然", ether: "以太" };
const PART_CN = { body: "躯体", hand: "手部", edc: "挂载" };

const trimN = (v) => (typeof v === "number" ? Math.round(v * 10000) / 10000 : v);
const fmtBB = (bb) => Object.entries(bb ?? {}).map(([k, v]) =>
  `<span class="bb">${esc(k)} <b>${typeof v === "number" ? trimN(v) : esc(v)}</b></span>`).join(" ");
const sec = (title, inner) => `<h4>${esc(title)}</h4>${inner}`;
const kvTable = (rows) => `<table><tbody>${rows.map(([k, v]) =>
  `<tr><td class="k">${esc(k)}</td><td>${v}</td></tr>`).join("")}</tbody></table>`;
const itemRef = (id, name, extra = "") =>
  `<span class="link" data-detail="items" data-id="${esc(id)}" title="${esc(id)}">${esc(name || id)}</span>${extra}`;
const dimP = `<p class="desc dim">—</p>`;

function detailCharacters(d) {
  const statRow = (k) =>
    `<tr><td class="k">${k}</td><td class="num">${num(d.lv1?.[k])}</td><td class="num">${num(d.lvMax?.[k])}</td></tr>`;
  return `
    <h3>${d.icon ? `<img class="avatar" src="${esc(d.icon)}" alt="" onerror="this.remove()">` : ""}${esc(d.name)} ${rarityTag(d.rarity)}</h3>
    <div class="sub">${esc(d.enName ?? "")} · ${esc(d.professionName ?? d.profession)} · 武器:${esc(d.weaponType ?? "—")}${d.cv ? ` · CV:${esc(d.cv)}` : ""} · 满级 ${d.maxLevel ?? "—"}</div>
    ${sec("面板(1 级 → 满级)", `<table><thead><tr><th>属性</th><th>1 级</th><th>满级</th></tr></thead><tbody>
      ${["MaxHp", "Atk", "Def", "Str", "Agi", "Wisd", "Will"].map(statRow).join("")}</tbody></table>`)}
    ${sec("技能", (() => {
      const FAMILY_LABEL = { NormalAttack: "普攻", NormalSkill: "战技",
                             UltimateSkill: "终结技", ComboSkill: "连携技", unknown: "附属技能" };
      // 富文本:<@ba.xx>/<#ba.xx> 开标签 → span.rt,</> 闭标签 → </span>(文本已先整体转义)
      const rich = (s) => !s ? "" : esc(s).replace(
        /&lt;[@#]([a-zA-Z0-9_.-]+)&gt;|&lt;\/&gt;/g,
        (m, name) => name ? `<span class="rt" data-rt="${esc(name)}">` : "</span>");
      return Object.entries(d.skillGroupMap ?? {}).map(([gid, grp]) => {
        const family = gid.startsWith(d.id + "_") ? gid.slice(d.id.length + 1) : gid;
        return `
      <div class="sub"><strong>${FAMILY_LABEL[family] ?? family}</strong>${grp.name ? ` · ${rich(grp.name)}` : ""}(${grp.skillList.length})</div>
      ${grp.desc ? `<p class="desc">${rich(grp.desc)}</p>` : ""}
      ${grp.skillList.map((sk) => `
      <div class="block"><h5>${esc(sk.skillId.split("_").slice(-2).join("_"))}</h5>
        <div class="sub">${esc(sk.skillId)}${sk.castCost ? ` · 终结点消耗 ${sk.castCost}` : ""}${sk.coolDown ? ` · 冷却 ${trimN(sk.coolDown)}s` : ""}${sk.costValue ? ` · 费用 ${trimN(sk.costValue)}` : ""}</div>
        <div class="bb-line">${(sk.levels ?? []).map((l) =>
          `<span class="bb">Lv${l.level ?? "?"}:${fmtBB(l.blackboard) || "—"}</span>`).join("")}</div>
      </div>`).join("")}`;
      }).join("") || dimP})())}
    ${sec("潜能 / 天赋", (d.potentials ?? []).map((p) => `
      <div class="block"><h5>${esc(p.name ?? `潜能 ${p.level}`)}</h5>
        ${p.desc ? `<p class="desc">${esc(p.desc)}</p>` : ""}
        ${p.values ? `<div class="bb-line">${fmtBB(p.values)}</div>` : ""}
        ${(p.materials ?? []).length ? `<div class="sub">解锁材料:${p.materials.map((m2) => itemRef(m2.id, m2.name, ` ×${m2.count}`)).join("、")}</div>` : ""}
      </div>`).join("") || dimP)}
    ${sec("武器", d.weapon ? kvTable([
      ["专武", `${esc(d.weapon.name)} ${rarityTag(d.weapon.rarity)}`],
      ["推荐武器(1/2/3 阶)", Object.values(d.recommendedWeapons ?? {}).map((arr) => arr.map(esc).join("、") || "—").join(" / ")],
    ]) : dimP)}
    ${sec("突破阶段", `<table><thead><tr><th>阶段</th><th>干员等级上限</th><th>技能等级上限(普攻/战技/连携/终结)</th></tr></thead><tbody>
      ${(state.data.breakStages ?? []).map((b) => `<tr><td>${b.stage}</td><td class="num">${b.maxLevel ?? "—"}</td>
        <td class="num">${["normalAttack", "normal", "combo", "ultimate"].map((k) => b.skillLevels?.[k] ?? "—").join(" / ")}</td></tr>`).join("")}
      </tbody></table>`)}
    ${(d.battleTags ?? []).length || (d.stationTags ?? []).length ? sec("标签", `<div class="sub">
      ${(d.battleTags ?? []).map((t2) => `<span class="badge">${esc(t2)}</span>`).join(" ")}
      ${(d.stationTags ?? []).map((t2) => `<span class="badge" title="${esc(t2.desc ?? "")}">派驻:${esc(t2.tag)}</span>`).join(" ")}</div>`) : ""}
    ${d.wiki ? sec("Wiki 百科", `<div class="sub">森空岛条目 ${esc(d.wiki.itemId ?? "—")}${d.wiki.illustration ? ` · <a href="${esc(d.wiki.illustration)}" target="_blank">立绘</a>` : ""}</div>
      ${(d.wiki.detail?.chapters ?? []).map((ch) => `<h5>${esc(ch.title ?? "")}</h5>
        ${(ch.widgets ?? []).map((w) => `<div class="block"><h5>${esc(w.title ?? "")}</h5>
          ${(w.table ?? []).length ? `<table><tbody>${w.table.map((r) =>
            `<tr><td class="k">${esc(r.label ?? "")}</td><td>${esc(r.value ?? "")}</td></tr>`).join("")}</tbody></table>` : ""}
          ${(w.tabs ?? []).map((t2) => `<div class="block"><h5>${esc(t2.name ?? "")}${t2.type ? ` <span class="badge">${esc(t2.type)}</span>` : ""}</h5>
            ${t2.imgUrl ? `<img class="wiki-img" src="${esc(t2.imgUrl)}" loading="lazy" alt="" onerror="this.remove()">` : ""}
            ${t2.desc ? `<p class="desc">${esc(t2.desc)}</p>` : ""}
            ${t2.text ? `<p class="desc">${esc(t2.text)}</p>` : ""}</div>`).join("")}
        </div>`).join("")}`).join("")}`) : ""}`;
}

function detailWeapons(d) {
  return `
    <h3>${esc(d.name)} ${rarityTag(d.rarity)}</h3>
    <div class="sub">${esc(d.weaponType ?? "—")} · 满级 ${d.maxLevel ?? "—"} · ${esc(d.id)}</div>
    ${d.desc ? `<p class="desc">${esc(d.desc)}</p>` : ""}
    ${sec("升级曲线", d.upgrade ? kvTable([
      ["1 级攻击", num(d.upgrade.baseAtkLv1)], ["满级攻击", num(d.upgrade.baseAtkMax)],
      ["满级累计经验", num(d.upgrade.totalExp)], ["满级累计龙门币", num(d.upgrade.totalGold)],
    ]) : dimP)}
    ${sec("潜能技能", d.potentialSkill ? `
      <div class="block"><h5>${esc(d.potentialSkill.name ?? d.potentialSkill.skillId)}</h5>
        <p class="desc">${esc(d.potentialSkill.desc ?? "")}</p>
        <div class="bb-line">${(d.potentialSkill.levels ?? []).map((l) =>
          `<span class="bb">Lv${l.level}:${fmtBB(l.blackboard) || "—"}${l.desc ? `(${esc(l.desc)})` : ""}</span>`).join("")}</div>
      </div>` : dimP)}
    ${sec("天赋(技能位等级加成)", d.talent ? `<table><thead><tr><th>天赋等级</th><th>各技能位区间</th></tr></thead><tbody>
      ${(d.talent.levels ?? []).map((l) => `<tr><td>Lv${l.talentLv}</td><td>${(l.skillLevelExtraBounds ?? []).map((b) =>
        b.skill ? `${esc(b.skill)}:${b.lowerBound}~${b.upperBound}` : null).filter(Boolean).join("<br>") || "—"}</td></tr>`).join("")}
      </tbody></table>` : dimP)}
    ${sec("突破", d.breakthrough ? `<table><thead><tr><th>阶段</th><th>需武器等级</th><th>龙门币</th><th>材料</th><th>技能位等级区间</th></tr></thead><tbody>
      ${(d.breakthrough.stages ?? []).map((s) => `<tr><td class="num">${s.stage}</td><td class="num">${s.level ?? "—"}</td><td class="num">${num(s.gold)}</td>
        <td>${(s.materials ?? []).map((m2) => itemRef(m2.id, null, ` ×${m2.count}`)).join("<br>") || "—"}</td>
        <td>${(s.skillLevelBounds ?? []).map((b) => b.skill ? `${esc(b.skill)}:${b.lowerBound}~${b.upperBound}` : null).filter(Boolean).join("<br>") || "—"}</td></tr>`).join("")}
      </tbody></table>` : dimP)}
    ${(d.potentialUpItems ?? []).length ? sec("潜能道具", d.potentialUpItems.map((i) => itemRef(i.id ?? i, null)).join("、")) : ""}`;
}

function detailItems(d) {
  const statView = (s) => s ? `<table><thead><tr><th>站点</th><th>配方数</th></tr></thead><tbody>
    ${[["total", "合计"], ["manual", "手工"], ["machine", "工厂"], ["spaceship", "飞船"]].map(([k, label]) =>
      `<tr><td class="k">${label}</td><td class="num">${s[k] ?? 0}</td></tr>`).join("")}</tbody></table>` : dimP;
  return `
    <h3>${d.iconUrl ? `<img class="avatar" src="${esc(d.iconUrl)}" alt="" onerror="this.remove()">` : ""}${esc(d.name ?? d.id)} ${rarityTag(d.rarity)}</h3>
    <div class="sub">${esc(d.typeName ?? d.type ?? "—")} · ${esc(d.id)}</div>
    ${d.desc ? `<p class="desc">${esc(d.desc)}</p>` : ""}
    ${(d.obtainWays ?? []).length ? sec("获取途径", `<ul>${d.obtainWays.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>`) : ""}
    ${sec("作为原料出现的配方数(按站点)", statView(d.usedInRecipes))}
    ${sec("作为产物的配方数(按站点)", statView(d.producedBy))}`;
}

function detailRecipes(d) {
  return `
    <h3>${esc(d.name || d.formulaDesc || (d.outcomes?.[0]?.group?.[0]?.name ?? d.id))}</h3>
    <div class="sub"><span class="badge ${d.station}">${STATION_BADGE[d.station] ?? d.station}</span>
      ${esc(STATION_NAME[d.station] ?? d.station)} · ${esc(d.id)}</div>
    ${sec("原料", `<div class="recipe-line">${recipeSide(d.ingredients) || '<span class="opt">—</span>'}</div>`)}
    ${sec("产物", `<div class="recipe-line">${recipeSide(d.outcomes)}</div>`)}
    ${kvTable([
      ["分类", esc(recipeCategory(d) ?? "—")],
      ...(d.formulaGroupId ? [["配方组", `${esc(d.formulaDesc ?? "")} <span class="dim">${esc(d.formulaGroupId)}</span>${recipePhase(d) ? ` <span class="badge">${esc(recipePhase(d))}</span>` : ""}`]] : []),
      ...(d.station === "machine" ? [["气体环境", GAS_ENV_CN[d.gasEnv] ?? d.gasEnv ?? "—"]] : []),
      ["制造耗时", d.craftTimeSec ? `${d.craftTimeSec} 秒` : "—"],
      ["生产设施", d.facility ? esc(d.facility) : "—"],
      ["稀有度", d.rarity ?? "—"],
    ])}`;
}

function detailEquips(d) {
  const suits = (state.data.equipsGlobal ?? {}).suits ?? [];
  const suit = suits.find((s) => s.id === d.suit);
  return `
    <h3>${d.icon ? `<img class="avatar" src="${esc(d.icon)}" alt="" onerror="this.remove()">` : ""}${esc(d.name)} ${rarityTag(d.rarity)}</h3>
    <div class="sub">${PART_CN[d.part] ?? d.part ?? "—"}${suit ? ` · ${esc(suit.name)}` : " · 无套装"} · 穿戴等级 ${d.minWearLv ?? "—"} · ${esc(d.id)}</div>
    ${d.baseAttr ? sec("基础属性", kvTable([[esc(d.baseAttr.type ?? ""), `+${num(d.baseAttr.value)}`]])) : ""}
    ${sec("词条", `<table><thead><tr><th>类型</th><th>数值</th></tr></thead><tbody>
      ${(d.attrs ?? []).map((a) => `<tr><td class="k">${esc(a.type)}</td><td class="num">+${num(a.value)}</td></tr>`).join("")}
      </tbody></table>`)}
    ${suit ? sec(`套装效果 · ${esc(suit.name)}(成员 ${suit.members} 件)`, `<ul>${(suit.effects ?? []).map((e) =>
      `<li><b>${e.count} 件</b>${e.desc ? `:${esc(e.desc)}` : ""}</li>`).join("")}</ul>`) : ""}
    ${d.formula ? sec("合成公式", kvTable([
      ["档位", esc(d.formula.level ?? "—")],
      ["装备组", esc(d.formula.packName ?? d.formula.packId ?? "—")],
      ["解锁", d.formula.unlock ? `${esc(d.formula.unlock.type)} ${esc(d.formula.unlock.key ?? "")} ${esc(d.formula.unlock.value ?? "")}` : "—"],
    ]) + (d.formula.craftOptions ?? []).map((c) => `
      <div class="block"><h5>加工链 ${c.chainId}${c.isDefault ? " <span class=\"badge\">默认</span>" : ""}${c.discount != null && c.discount !== 1 ? ` · 代币 ${Math.round(c.discount * 100 / 10) / 10} 折` : ""}</h5>
        <div class="sub">${c.gold ? `${esc(c.gold.name)} ×${c.gold.count}` : ""}${(c.materials ?? []).length ? ` + ${(c.materials ?? []).map((m2) => itemRef(m2.id, m2.name, ` ×${m2.count}`)).join(" + ")}` : ""}</div>
      </div>`).join("")) : dimP}
    ${(d.enhancePity ?? []).length ? sec("强化保底规则", `<span class="dim">${esc(d.enhancePity.join(", "))}</span>`) : ""}`;
}

function detailEnemies(d) {
  return `
    <h3>${d.icon ? `<img class="avatar" src="${esc(d.icon)}" alt="" onerror="this.remove()">` : ""}${esc(d.name ?? d.nickname ?? d.id)}
      ${d.dangerous ? '<span class="rarity r6">精英</span>' : ""}</h3>
    <div class="sub">${[d.nickname, d.typeName, d.id].filter(Boolean).map((x) => esc(x)).join(" · ")}</div>
    ${d.desc ? `<p class="desc">${esc(d.desc)}</p>` : ""}
    ${sec("档案", kvTable([
      ["初始霸体", d.superArmor ?? "—"], ["韧性", d.maxResilience ?? "—"],
      ["满级生命", num(d.lvMax?.MaxHp)], ["满级攻击", num(d.lvMax?.Atk)], ["满级防御", num(d.lvMax?.Def)],
      ["抗性", Object.entries(d.resists ?? {}).filter(([, v]) => v)
        .map(([k, v]) => `${RESIST_CN[k] ?? k} ${Math.round(v * 100)}%`).join(", ") || "—"],
    ]))}
    ${(d.abilities ?? []).length ? sec("特殊能力", `<ul>${d.abilities.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`) : ""}
    ${(d.deathTips ?? []).length ? sec("击杀提示", `<ul>${d.deathTips.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`) : ""}
    ${(d.distributions ?? []).length ? sec("出没区域", esc(d.distributions.join("、"))) : ""}`;
}

const DETAIL_RENDERERS = {
  characters: detailCharacters, weapons: detailWeapons, items: detailItems,
  recipes: detailRecipes, equips: detailEquips, enemies: detailEnemies,
};

function ensureModal() {
  let box = document.getElementById("detail-modal");
  if (box) return box;
  box = document.createElement("div");
  box.id = "detail-modal";
  box.className = "modal-backdrop";
  box.addEventListener("click", (e) => { if (e.target === box) closeDetail(); });
  document.body.appendChild(box);
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });
  return box;
}

function closeDetail() {
  const box = document.getElementById("detail-modal");
  if (box) {
    box.style.display = "none";
    box.innerHTML = "";
  }
}

async function openDetail(product, id, sub = "") {
  // 清单式数据集:未显式给出子目录时经 id→slug 映射解析
  if (!sub) sub = (state.slugMap?.[product] ?? {})[id] ?? "";
  const box = ensureModal();
  box.innerHTML = `<div class="modal"><button class="modal-close" title="关闭 (Esc)">✕</button>
    <div class="modal-body"><div class="empty-state">加载中…</div></div></div>`;
  box.style.display = "block";
  box.querySelector(".modal-close").addEventListener("click", closeDetail);
  try {
    const d = await (await fetch(`/data/${product}/${sub ? sub + "/" : ""}${id}.json`)).json();
    const render = DETAIL_RENDERERS[product] ?? ((x) => `<pre>${esc(JSON.stringify(x, null, 2))}</pre>`);
    box.querySelector(".modal-body").innerHTML = render(d);
  } catch {
    box.querySelector(".modal-body").innerHTML =
      `<div class="error-state">详情加载失败(缺少 data/${esc(product)}/${sub ? esc(sub) + "/" : ""}${esc(id)}.json?)</div>`;
  }
}

/* 列表与浮层内统一走事件委托:[data-detail="<产物>"] data-id="<id>"
   data-sub 为可选分类子目录(如配方数据集) */
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-detail]");
  if (el) openDetail(el.dataset.detail, el.dataset.id, el.dataset.sub ?? "");
});

const RENDERERS = {
  overview: renderOverview, characters: renderCharacters, weapons: renderWeapons,
  equips: renderEquips, items: renderItems, recipes: renderRecipes, enemies: renderEnemies,
};

function render() {
  main.innerHTML = (RENDERERS[state.current] ?? renderOverview)();
}

window.__filter = (tab, v) => {
  state.filters[tab] = v;
  render();
};

tabs.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  state.current = btn.dataset.tab;
  tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
  render();
});

loadData().then(render).catch(() => {
  main.innerHTML = '<div class="error-state">数据加载失败,请通过本地 HTTP 服务访问(如 python3 -m http.server)。</div>';
});
