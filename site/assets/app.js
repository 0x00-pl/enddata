/* EndData 前端:加载 site/data/*.json 并渲染各分页。无框架、无构建。 */

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
  const names = ["meta", "characters", "weapons", "items", "recipes", "enemies"];
  const results = await Promise.allSettled(
    names.map(async (n) => (await fetch(`/data/processed/${n}.json`)).json())
  );
  names.forEach((n, i) => {
    if (results[i].status === "fulfilled") state.data[n] = results[i].value;
  });
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
  if (!m) return `<div class="error-state">未找到 site/data/meta.json —— 请先运行 scripts/build_dataset.py</div>`;
  const c = m.counts;
  return `
    <div class="kpis">
      <div class="kpi"><div class="n">${c.characters}</div><div class="l">干员</div></div>
      <div class="kpi"><div class="n">${c.weapons}</div><div class="l">武器</div></div>
      <div class="kpi"><div class="n">${c.items}</div><div class="l">物品</div></div>
      <div class="kpi"><div class="n">${c.recipes}</div><div class="l">生产配方</div></div>
      <div class="kpi"><div class="n">${c.enemies}</div><div class="l">敌人</div></div>
    </div>
    <p class="note">数据源:${esc(m.source.repo)}@${esc(m.source.branch)} · 抓取于 ${esc(m.source.fetchedAt)} · 构建于 ${esc(m.generatedAt)} (UTC)</p>
    <table><tbody>
      <tr><td class="dim">战斗数据</td><td>干员等级成长曲线、职业、武器类型、敌人属性模板(生命/攻击/防御、抗性、霸体)已入库;技能数值(SkillPatchTable)已抓取,待加工。</td></tr>
      <tr><td class="dim">生产数据</td><td>手工配方 ${c.recipes ? "" : ""}(大世界烹饪)、机器配方(工厂产线)、飞船制造已入库;电力/物流/流派加成待扩展。</td></tr>
      <tr><td class="dim">计划中</td><td>技能与 Buff 数值解析、产线规划器、敌人名字补全(森空岛 Wiki「威胁」分区)、配方产物图标。</td></tr>
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
      <div class="card">
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
    ${list.map((w) => `<tr>
      <td>${esc(w.name)}</td><td>${rarityTag(w.rarity)}</td>
      <td>${esc(w.weaponType ?? "—")}</td><td class="num">${w.maxLevel ?? "—"}</td>
    </tr>`).join("")}
    </tbody></table>`;
}

function renderItems() {
  const q = state.search.items ?? "";
  const type = state.filters.items ?? "";
  const types = [...new Set((state.data.items ?? []).map((i) => i.typeName).filter(Boolean))].sort();
  const list = (state.data.items ?? [])
    .filter((i) => (!type || i.typeName === type) && (match(i.name, q) || match(i.id, q)));
  return `
    ${toolbar("items", "搜索物品名 / ID…", `
      <select onchange="window.__filter('items', this.value)">
        <option value="">全部类型</option>
        ${types.map((t) => `<option ${t === type ? "selected" : ""}>${esc(t)}</option>`).join("")}
      </select>`)}
    <table><thead><tr><th>物品</th><th>稀有度</th><th>类型</th><th>堆叠</th></tr></thead><tbody>
    ${list.slice(0, 500).map((i) => `<tr>
      <td>${i.iconUrl ? `<img class="icon-sm" src="${esc(i.iconUrl)}" alt="" loading="lazy" onerror="this.remove()">` : ""}${esc(i.name ?? i.id)} <span class="dim">${esc(i.id)}</span></td>
      <td>${rarityTag(i.rarity)}</td><td>${esc(i.typeName ?? i.type ?? "—")}</td>
    </tr>`).join("")}
    </tbody></table>
    ${list.length > 500 ? `<p class="note">仅显示前 500 / ${list.length} 条,请用搜索缩小范围。</p>` : ""}`;
}

function recipeSide(side) {
  return side.map((ing) => {
    const opts = ing.options.map((o) =>
      `<span title="${esc(o.id)}">${esc(o.name)}</span>${ing.options.length > 1 ? "…" : ""}×${o.count}`);
    return opts.join(' <span class="opt">/</span> ');
  }).join(" + ");
}

function renderRecipes() {
  const q = state.search.recipes ?? "";
  const st = state.filters.recipes ?? "";
  const list = (state.data.recipes ?? [])
    .filter((r) => (!st || r.station === st) && match(r.outcomes.map((o) => o.options[0].name).join(), q));
  return `
    ${toolbar("recipes", "搜索产物名…", `
      <select onchange="window.__filter('recipes', this.value)">
        <option value="">全部站点</option>
        <option value="manual" ${st === "manual" ? "selected" : ""}>手工制作</option>
        <option value="machine" ${st === "machine" ? "selected" : ""}>工厂机器</option>
        <option value="spaceship" ${st === "spaceship" ? "selected" : ""}>飞船制造</option>
      </select>`)}
    <table><thead><tr><th>产物</th><th>配方</th><th>站点</th></tr></thead><tbody>
    ${list.map((r) => {
      const out = r.outcomes[0]?.options[0];
      return `<tr>
        <td>${esc(out?.name ?? r.id)} ×${out?.count ?? 1}</td>
        <td><div class="recipe-line">${recipeSide(r.ingredients) || '<span class="opt">—</span>'}</div></td>
        <td><span class="badge ${r.station}">${{ manual: "手工", machine: "工厂", spaceship: "飞船" }[r.station]}</span></td>
      </tr>`;
    }).join("")}
    </tbody></table>`;
}

function renderEnemies() {
  const q = state.search.enemies ?? "";
  const list = (state.data.enemies ?? []).filter(
    (e) => match(e.name, q) || match(e.templateId, q)
  );
  return `
    ${toolbar("enemies", "搜索敌人 ID…")}
    <p class="note">解包表中暂无敌人显示名,当前以模板 ID 展示;名字待接入森空岛 Wiki 数据补全。</p>
    <table><thead><tr><th>敌人</th><th>威胁</th><th>初始霸体</th><th>韧性</th><th>满级生命</th><th>满级攻击</th><th>抗性</th></tr></thead><tbody>
    ${list.slice(0, 400).map((e) => `<tr>
      <td>${esc(e.name ?? e.id)} <span class="dim">${esc(e.id)}</span></td>
      <td>${e.dangerous ? '<span class="rarity r6">精英</span>' : "—"}</td>
      <td class="num">${e.superArmor ?? "—"}</td>
      <td class="num">${e.maxResilience ?? "—"}</td>
      <td class="num">${num(e.lvMax?.MaxHp)}</td><td class="num">${num(e.lvMax?.Atk)}</td>
      <td class="dim">${Object.entries(e.resists ?? {}).filter(([, v]) => v)
        .map(([k, v]) => `${{ physical: "物理", fire: "火", pulse: "脉冲", cryst: "结晶", natural: "自然", ether: "以太" }[k] ?? k} ${Math.round(v * 100)}%`).join(", ") || "—"}</td>
    </tr>`).join("")}
    </tbody></table>
    ${list.length > 400 ? `<p class="note">仅显示前 400 / ${list.length} 条。</p>` : ""}`;
}

const RENDERERS = {
  overview: renderOverview, characters: renderCharacters, weapons: renderWeapons,
  items: renderItems, recipes: renderRecipes, enemies: renderEnemies,
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
