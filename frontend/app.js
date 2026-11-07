"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const store = {
  get(k, d) { try { const v = localStorage.getItem("cl:" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("cl:" + k, JSON.stringify(v)); } catch {} },
  del(k) { try { localStorage.removeItem("cl:" + k); } catch {} },
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const S = {
  meta: null, rank: null, league: null, leagueKey: null,
  sort: { key: "value", dir: -1 }, show: 200,
  punts: new Set(store.get("punts", [])),
  myTeam: store.get("myTeam", null),
  selTeam: null,
  trade: { a: null, b: null, aGive: new Set(), bGive: new Set(), aDrop: new Set(), bDrop: new Set() },
};
const LABEL = { pts: "PTS", fg3m: "3PM", reb: "REB", ast: "AST", stl: "STL", blk: "BLK", fg: "FG%", ft: "FT%", tov: "TO" };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  let body = null;
  try { body = await r.json(); } catch {}
  if (!r.ok) throw new Error((body && body.detail) || `Request failed (${r.status})`);
  return body;
}

function readSpec() {
  return {
    reference: $("#o_ref").value, center: $("#o_center").value, weights: $("#o_weights").value,
    tov: parseFloat($("#o_tov").value), transform: $("#o_transform").checked, minus_one: $("#m1").checked,
  };
}
function writeSpec(sp) {
  $("#o_ref").value = sp.reference; $("#o_center").value = sp.center; $("#o_weights").value = sp.weights;
  $("#o_tov").value = Number(sp.tov).toFixed(1); $("#o_transform").checked = !!sp.transform; $("#m1").checked = !!sp.minus_one;
}
const sameSpec = (a, b) => ["reference", "center", "weights", "transform", "minus_one"].every((k) => a[k] === b[k]) && Number(a.tov) === Number(b.tov);
function syncSystemSelect() {
  const sp = readSpec();
  const match = S.meta.systems.find((s) => sameSpec(s.spec, sp));
  const sel = $("#system");
  let custom = sel.querySelector('option[value="custom"]');
  if (match) {
    if (custom) custom.remove();
    sel.value = match.key; S.base = match.key;
  } else {
    if (!custom) { custom = document.createElement("option"); custom.value = "custom"; custom.textContent = "Custom"; sel.appendChild(custom); }
    sel.value = "custom";
  }
  store.set("spec", sp); store.set("system", S.base);
  renderBlurb();
}
function params() {
  const sp = readSpec();
  return {
    system: S.base || S.meta.default_system,
    split: $("#split").value,
    punt: [...S.punts].join(","),
    m1: sp.minus_one ? 1 : 0, ref: sp.reference, center: sp.center, weights: sp.weights,
    tov: sp.tov, transform: sp.transform ? 1 : 0,
  };
}
const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v != null)).toString();

/* ---------- formatting ---------- */
function heat(v) {
  if (v == null || isNaN(v)) return "";
  const a = Math.min(Math.abs(v) / 2.5, 1) * 0.42;
  const rgb = v >= 0 ? "var(--good)" : "var(--bad)";
  return `background-color: rgba(${getComputedStyle(document.documentElement).getPropertyValue(v >= 0 ? "--good" : "--bad")}, ${a.toFixed(3)})`;
}
function rankHeat(rank, n) {
  const v = ((n + 1) / 2 - rank) / ((n - 1) / 2) * 2.2;
  return heat(v);
}
const pct = (x) => (x == null ? "–" : x.toFixed(3).replace(/^0/, ""));
function statCell(c, p) {
  const s = p.stats;
  if (c === "fg") return pct(s.fg);
  if (c === "ft") return pct(s.ft);
  return s[c].toFixed(1);
}
function weekly(c, x) { return c === "fg" || c === "ft" ? pct(x) : x.toFixed(1); }
function delta(a, b, digits = 1, lowerBetter = false) {
  const d = b - a;
  if (Math.abs(d) < Math.pow(10, -digits) / 2) return `<span class="meta">±0</span>`;
  const good = lowerBetter ? d < 0 : d > 0;
  return `<span class="${good ? "up" : "down"}">${d > 0 ? "+" : ""}${d.toFixed(digits)}</span>`;
}

/* ---------- init ---------- */
async function init() {
  S.meta = await api("/api/meta");
  $("#system").innerHTML = S.meta.systems.map((s) => `<option value="${s.key}">${esc(s.label)}</option>`).join("");
  $("#split").innerHTML = Object.entries(S.meta.splits).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  const O = S.meta.options;
  $("#o_ref").innerHTML = Object.entries(O.reference).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  $("#o_center").innerHTML = Object.entries(O.center).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  $("#o_weights").innerHTML = Object.entries(O.weights).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  $("#o_tov").innerHTML = Object.entries(O.tov).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  // prefs v2: default moved to DURANT H2H, so reset any older saved system once
  if (store.get("prefsVersion", 1) < 2) { store.del("system"); store.del("spec"); store.set("prefsVersion", 2); }
  S.base = store.get("system", S.meta.default_system);
  if (!S.meta.systems.find((s) => s.key === S.base)) S.base = S.meta.default_system;
  writeSpec(store.get("spec", S.meta.systems.find((s) => s.key === S.base).spec));
  syncSystemSelect();
  $("#split").value = store.get("split", "season");
  const y = S.meta.year;
  $("#lgYear").innerHTML = [y, y - 1].map((v) => `<option value="${v}">${v - 1}-${String(v).slice(2)}</option>`).join("");
  renderPuntChips(S.meta.cats.map((c) => c.key));
  renderBlurb();

  $$("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $("#system").addEventListener("change", () => {
    const sy = S.meta.systems.find((s) => s.key === $("#system").value);
    if (!sy) return;
    S.base = sy.key; writeSpec(sy.spec); syncSystemSelect(); refreshAll();
  });
  ["#m1", "#o_ref", "#o_center", "#o_weights", "#o_tov", "#o_transform"].forEach((id) =>
    $(id).addEventListener("change", () => { syncSystemSelect(); refreshAll(); }));
  $("#advBtn").addEventListener("click", () => {
    const open = $("#adv").classList.toggle("hidden");
    $("#advBtn").textContent = open ? "Model settings ▾" : "Model settings ▴";
  });
  $("#split").addEventListener("change", () => { store.set("split", $("#split").value); refreshAll(); });
  ["#search", "#posFilter", "#ownerFilter", "#minGp", "#showValues"].forEach((s) =>
    $(s).addEventListener("input", () => { S.show = 200; renderRankings(); }));
  $("#minGp").addEventListener("input", () => { S.minGpTouched = true; });
  ["#teams", "#roster"].forEach((s) => $(s).addEventListener("change", loadRankings));
  $("#more").addEventListener("click", () => { S.show += 200; renderRankings(); });
  $("#lgImport").addEventListener("click", importLeague);
  $("#refreshBtn").addEventListener("click", hardRefresh);
  $("#exClose").addEventListener("click", closeExplain);
  $("#explain").addEventListener("click", (e) => { if (e.target.id === "explain") closeExplain(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeExplain(); });
  // background refresh every 10 minutes while the tab is visible (server re-pulls ESPN when stale)
  setInterval(() => { if (!document.hidden) refreshAll(); }, 10 * 60 * 1000);
  setInterval(renderUpdated, 30 * 1000);
  $("#lgDemo").addEventListener("click", () => loadLeagueKey(null, true));
  $("#myTeam").addEventListener("change", () => {
    S.myTeam = +$("#myTeam").value; store.set("myTeam", S.myTeam); S.selTeam = S.myTeam;
    renderLeague(); renderMatchups(); setupTrade(true);
  });
  $("#period").addEventListener("change", () => loadLeague());
  $("#tRun").addEventListener("click", runTrade);
  $("#tClear").addEventListener("click", () => { setupTrade(true); $("#tResult").innerHTML = ""; });
  $("#tA").addEventListener("change", () => { S.trade.a = +$("#tA").value; resetSel(); renderTradeLists(); });
  $("#tB").addEventListener("change", () => { S.trade.b = +$("#tB").value; resetSel(); renderTradeLists(); });

  const saved = store.get("league", null);
  if (saved) {
    $("#lgId").value = saved.league_id || ""; $("#lgYear").value = saved.year || y;
    $("#lgS2").value = saved.espn_s2 || ""; $("#lgSwid").value = saved.swid || "";
    $("#lgRemember").checked = !!saved.espn_s2 || !!saved.remember;
  }
  renderMethod();
  const hash = location.hash.replace("#", "");
  if (["rankings", "league", "matchups", "trade", "method"].includes(hash)) showTab(hash);
  await loadRankings();
  if (saved && saved.demo) loadLeagueKey(null, true);
  else if (saved && saved.league_id) importLeague(true);
}

function showTab(t) {
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  $$(".tab").forEach((s) => s.classList.toggle("on", s.id === "tab-" + t));
  try { history.replaceState(null, "", "#" + t); } catch {}
}
function renderBlurb() {
  const s = S.meta.systems.find((x) => x.key === $("#system").value);
  if (s) { $("#systemBlurb").textContent = s.blurb; return; }
  const sp = readSpec(), O = S.meta.options;
  $("#systemBlurb").textContent = `Custom: ${sp.transform ? "transform on" : "no transform"}, scaled against ${O.reference[sp.reference].toLowerCase()}, zero at ${O.center[sp.center].toLowerCase()}, ${O.weights[sp.weights].toLowerCase()} weights, turnovers ${O.tov[Number(sp.tov).toFixed(1)].toLowerCase()}${sp.minus_one ? ", Minus 1" : ""}.`;
}
function renderPuntChips(cats) {
  $("#punts").innerHTML = cats.map((c) =>
    `<button class="chip ${S.punts.has(c) ? "on" : ""}" data-c="${c}">${LABEL[c]}</button>`).join("");
  $$("#punts .chip").forEach((b) => b.addEventListener("click", () => {
    const c = b.dataset.c;
    S.punts.has(c) ? S.punts.delete(c) : S.punts.add(c);
    store.set("punts", [...S.punts]);
    b.classList.toggle("on");
    refreshAll();
  }));
}
function refreshAll() { loadRankings(); if (S.leagueKey) loadLeague(); }
async function hardRefresh() {
  const b = $("#refreshBtn"); b.disabled = true; b.textContent = "↻ Refreshing…";
  try {
    if (S.leagueKey) await api(`/api/league/${encodeURIComponent(S.leagueKey)}/refresh`, { method: "POST" });
    await loadRankings(true);
    if (S.leagueKey) await loadLeague();
  } catch (e) { $("#source").textContent = e.message; }
  b.disabled = false; b.textContent = "↻ Refresh";
}
function renderUpdated() {
  const t = S.league ? S.league.updated * 1000 : S.rankLoaded;
  if (!t) { $("#updated").textContent = ""; return; }
  const m = Math.round((Date.now() - t) / 60000);
  $("#updated").textContent = m < 1 ? "· updated just now" : `· updated ${m} min ago`;
}

/* ---------- rankings ---------- */
async function loadRankings(force) {
  const p = { ...params(), teams: $("#teams").value, roster: $("#roster").value, league: S.leagueKey };
  if (force === true) p.refresh = 1;
  try {
    S.rank = await api("/api/rankings?" + qs(p));
  } catch (e) { $("#source").textContent = e.message; return; }
  $("#source").textContent = `Data: ${S.rank.source}`;
  if (!S.leagueKey) S.rankLoaded = Date.now();
  renderUpdated();
  if (!S.minGpTouched) {
    const maxG = Math.max(...S.rank.players.map((p) => p.g), 0);
    $("#minGp").value = Math.floor(maxG * 0.25);
  }
  $$("#split option").forEach((o) => { o.disabled = !S.rank.available_splits.includes(o.value); });
  if ($("#split").value !== S.rank.split) $("#split").value = S.rank.split;
  renderRankings();
}

function rankColumns(cats, withOwner, withSlot) {
  const dur = S.rank ? !!S.rank.minus_one : $("#m1").checked;
  const cols = [
    { k: "rank", t: "#", f: (p) => p.rank },
    { k: "dz", t: "vs Z", f: (p) => p.rank_z != null ? p.rank_z - p.rank : 0, title: "Rank change vs standard 9-cat Z" },
    { k: "name", t: "Player", l: true, f: (p) => p.name },
  ];
  if (withSlot) cols.push({ k: "slot", t: "Slot", l: true, f: (p) => p.slot === 13 ? "IR" : p.slot === 12 ? "BE" : "" });
  cols.push({ k: "g", t: "GP", f: (p) => p.g }, { k: "mpg", t: "MPG", f: (p) => p.mpg });
  cats.forEach((c) => cols.push({ k: "c_" + c, t: LABEL[c], cat: c, f: (p) => $("#showValues").checked ? p.v[c] : (c === "fg" || c === "ft" ? p.v[c] : p.stats[c]) }));
  cols.push({ k: "value", t: "Value", f: (p) => p.value });
  if (dur) cols.push({ k: "dropped", t: "Dropped", f: (p) => p.dropped || "" });
  return cols;
}

function playerRowHTML(p, cols, cats) {
  const showV = $("#showValues").checked;
  return cols.map((c) => {
    if (c.k === "name") {
      const owner = p.fantasy_team_name != null ? `<span class="owner"> · ${esc(p.fantasy_team_name)}</span>` : "";
      return `<td class="l clickable" data-pid="${esc(p.id)}" title="Why is he ranked here?"><span class="name">${esc(p.name)}</span>${p.injury ? `<span class="inj">${esc(p.injury)}</span>` : ""}<br><span class="meta">${esc(p.team)} · ${esc(p.pos)}</span>${owner}</td>`;
    }
    if (c.k === "dz") {
      if (p.rank_z == null) return "<td></td>";
      const d = p.rank_z - p.rank;
      return `<td title="Standard 9-cat rank: ${p.rank_z}">${d === 0 ? '<span class="meta">–</span>' : `<span class="${d > 0 ? "delta-up" : "delta-down"}">${d > 0 ? "▲" : "▼"}${Math.abs(d)}</span>`}</td>`;
    }
    if (c.cat) {
      const punted = S.punts.has(c.cat) ? " punted" : "";
      const txt = showV ? p.v[c.cat].toFixed(2) : statCell(c.cat, p);
      const title = c.cat === "fg" ? `${p.stats.fga} FGA/g` : c.cat === "ft" ? `${p.stats.fta} FTA/g` : `value ${p.v[c.cat]}`;
      return `<td class="cat${punted}" style="${heat(p.v[c.cat])}" title="${title}">${txt}</td>`;
    }
    if (c.k === "value") return `<td><b>${p.value.toFixed(2)}</b></td>`;
    if (c.k === "dropped") return `<td class="dropped">${esc(p.dropped)}</td>`;
    if (c.k === "slot") return `<td class="l meta">${c.f(p)}</td>`;
    return `<td>${c.f(p)}</td>`;
  }).join("");
}

function headerHTML(cols, sortable = true) {
  return "<thead><tr>" + cols.map((c) =>
    `<th class="${c.l ? "l" : ""} ${c.cat && S.punts.has(c.cat) ? "punted" : ""} ${S.sort.key === c.k && sortable ? "sorted" : ""}" data-k="${c.k}" title="${c.title || ""}">${c.t}${S.sort.key === c.k && sortable ? (S.sort.dir < 0 ? " ↓" : " ↑") : ""}</th>`).join("") + "</tr></thead>";
}

function renderRankings() {
  if (!S.rank) return;
  const cats = S.rank.cats;
  const withOwner = !!S.leagueKey;
  const cols = rankColumns(cats, withOwner, false);
  const q = $("#search").value.trim().toLowerCase();
  const pos = $("#posFilter").value;
  const own = $("#ownerFilter").value;
  const minGp = +$("#minGp").value || 0;
  let rows = S.rank.players.filter((p) =>
    (!q || p.name.toLowerCase().includes(q)) &&
    (!pos || (p.pos || "").split("/").includes(pos)) &&
    p.g >= minGp &&
    (!own || (own === "fa" ? p.fantasy_team === 0 : String(p.fantasy_team) === own)));
  const col = cols.find((c) => c.k === S.sort.key) || cols.find((c) => c.k === "value");
  rows.sort((a, b) => {
    const x = col.f(a), y = col.f(b);
    if (typeof x === "string") return S.sort.dir * x.localeCompare(y);
    return S.sort.dir * ((x ?? -1e9) - (y ?? -1e9));
  });
  const shown = rows.slice(0, S.show);
  $("#rankTable").innerHTML = headerHTML(cols) + "<tbody>" + shown.map((p) =>
    `<tr class="${withOwner && p.fantasy_team === S.myTeam ? "mine" : ""}">${playerRowHTML(p, cols, cats)}</tr>`).join("") + "</tbody>";
  $("#more").classList.toggle("hidden", rows.length <= S.show);
  bindExplain("#rankTable");
  $$("#rankTable th").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.k;
    if (S.sort.key === k) S.sort.dir *= -1; else { S.sort.key = k; S.sort.dir = ["name", "rank"].includes(k) ? 1 : -1; }
    renderRankings();
  }));
  $("#leagueSizeWrap").classList.toggle("hidden", withOwner);
}

/* ---------- explain ---------- */
function bindExplain(table) {
  $$(table + " td.clickable").forEach((td) => td.addEventListener("click", () => openExplain(td.dataset.pid)));
}
function closeExplain() { $("#explain").classList.add("hidden"); }
async function openExplain(pid, target) {
  const curKey = $("#system").value;
  target = target || (curKey === S.meta.default_system ? "tz" : S.meta.default_system);
  $("#explain").classList.remove("hidden");
  $("#exBody").innerHTML = `<p class="meta">Re-ranking the player pool under each setting…</p>`;
  const p = { ...params(), player: pid, target, teams: $("#teams").value, roster: $("#roster").value, league: S.leagueKey };
  let e;
  try { e = await api("/api/explain?" + qs(p)); }
  catch (err) { $("#exBody").innerHTML = `<p class="warn">${esc(err.message)}</p>`; return; }
  const cur = e.current, tg = e.target;
  const tgtLabel = S.meta.systems.find((s) => s.key === e.target_key).label;
  const curLabel = curKey === "custom" ? "Custom" : S.meta.systems.find((s) => s.key === curKey).label;
  const dr = (d) => d === 0 ? '<span class="meta">±0</span>' : `<span class="${d > 0 ? "up" : "down"}">${d > 0 ? "▲" : "▼"}${Math.abs(d)}</span>`;
  const biggest = [...e.singles].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))[0];
  const cats = Object.keys(cur.cats);
  $("#exBody").innerHTML = `
    <h2>${esc(e.player.name)} <span class="meta">${esc(e.player.team)} · ${e.player.g} GP · ${e.player.mpg} MPG</span></h2>
    <div class="row" style="margin:8px 0">
      <label class="inline">Compare ${esc(curLabel)} with
        <select id="exTarget">${S.meta.systems.filter((s) => s.key !== curKey).map((s) => `<option value="${s.key}" ${s.key === e.target_key ? "selected" : ""}>${esc(s.label)}</option>`).join("")}</select>
      </label>
    </div>
    <h3>Rank under each system</h3>
    <div class="preset-row">${e.presets.map((p) => `<div class="p ${p.key === curKey ? "cur" : ""}"><b>#${p.rank}</b>${esc(p.label)}</div>`).join("")}</div>
    ${biggest ? `<div class="callout">Going from <b>#${cur.rank}</b> to <b>#${tg.rank}</b>. The biggest single factor is <b>${esc(biggest.label.toLowerCase())}</b> (${dr(biggest.delta)} on its own).</div>` : `<div class="callout">Both systems use identical settings.</div>`}
    ${e.path.length ? `<h3>One setting at a time</h3>
    <table class="grid"><thead><tr><th class="l">Change</th><th>On its own</th><th>Cumulative rank</th></tr></thead><tbody>
      <tr><td class="l meta">Start: ${esc(curLabel)}</td><td></td><td><b>#${cur.rank}</b></td></tr>
      ${e.path.map((s, i) => `<tr><td class="l">${esc(s.label)}</td><td>#${e.singles[i].rank} ${dr(e.singles[i].delta)}</td><td><b>#${s.rank}</b> ${dr(s.delta)}</td></tr>`).join("")}
    </tbody></table>
    <p class="note">"On its own" changes only that setting from your current system. "Cumulative" applies the changes in order until you reach ${esc(tgtLabel)}.</p>` : ""}
    <h3>Category values</h3>
    <table class="grid"><thead><tr><th class="l">Cat</th><th>${esc(curLabel)}</th><th>× wt</th><th>${esc(tgtLabel)}</th><th>× wt</th></tr></thead><tbody>
      ${cats.map((c) => {
        const a = cur.cats[c], b = tg.cats[c];
        const da = cur.dropped === LABEL[c], db = tg.dropped === LABEL[c];
        return `<tr><td class="l"><b>${LABEL[c]}</b></td>
          <td style="${heat(a.v)}">${a.v.toFixed(2)}</td><td class="meta">${da ? "dropped" : a.contrib.toFixed(2)}</td>
          <td style="${heat(b.v)}">${b.v.toFixed(2)}</td><td class="meta">${db ? "dropped" : b.contrib.toFixed(2)}</td></tr>`;
      }).join("")}
      <tr><td class="l"><b>Value</b></td><td></td><td><b>${cur.value.toFixed(2)}</b></td><td></td><td><b>${tg.value.toFixed(2)}</b></td></tr>
    </tbody></table>
    <p class="note">Values are on each system's own scale, so compare the ranks rather than the raw numbers between systems.</p>`;
  $("#exTarget").addEventListener("change", () => openExplain(pid, $("#exTarget").value));
}

/* ---------- league ---------- */
async function importLeague(silent) {
  const body = {
    league_id: $("#lgId").value.trim(), year: +$("#lgYear").value,
    espn_s2: $("#lgS2").value.trim() || null, swid: $("#lgSwid").value.trim() || null,
  };
  if (!body.league_id) { if (silent !== true) msg("Enter your league ID.", true); return; }
  msg("Importing…");
  try {
    const r = await api("/api/league/import", { method: "POST", body: JSON.stringify(body) });
    store.set("league", $("#lgRemember").checked ? { ...body, remember: true } : { league_id: body.league_id, year: body.year });
    await loadLeagueKey(r.key, false);
  } catch (e) { msg(e.message, true); }
}
function msg(t, err) { $("#lgMsg").textContent = t; $("#lgMsg").classList.toggle("err", !!err); }

async function loadLeagueKey(key, demo) {
  if (demo) {
    msg("Building demo league…");
    try { key = (await api("/api/league/demo", { method: "POST" })).key; store.set("league", { demo: true }); }
    catch (e) { msg(e.message, true); return; }
  }
  S.leagueKey = key;
  await loadLeague(true);
  msg("");
  loadRankings();
}

async function loadLeague(first) {
  const p = { ...params() };
  if (!first && $("#period").value) p.period = $("#period").value;
  try {
    S.league = await api(`/api/league/${encodeURIComponent(S.leagueKey)}?` + qs(p));
  } catch (e) { msg(e.message, true); return; }
  const L = S.league;
  const ids = L.teams.map((t) => t.id);
  if (!ids.includes(S.myTeam)) S.myTeam = ids[0];
  if (!ids.includes(S.selTeam)) S.selTeam = S.myTeam;
  $("#myTeam").innerHTML = L.teams.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
  $("#myTeam").value = S.myTeam;
  $("#ownerFilter").innerHTML = `<option value="">All players</option><option value="fa">Free agents</option>` +
    L.teams.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
  $("#period").innerHTML = L.periods.map((n) => `<option value="${n}">Week ${n}${n === L.current_period ? " (current)" : ""}</option>`).join("");
  $("#period").value = L.period;
  $("#leagueChip").textContent = `League: ${L.name}`;
  renderUpdated();
  $("#importBox").classList.add("hidden");
  $("#leagueBody").classList.remove("hidden");
  $$(".needs-league").forEach((e) => e.classList.add("hidden"));
  $$(".league-only").forEach((e) => e.classList.remove("hidden"));
  renderPuntChips(L.cats);
  renderLeague();
  renderMatchups();
  setupTrade(first || S.trade.a == null);
}

function renderLeague() {
  const L = S.league;
  $("#lgName").innerHTML = `${esc(L.name)} <button class="ghost" id="lgChange" style="font-size:12px;padding:4px 8px;margin-left:8px">Change league</button>`;
  $("#lgChange").addEventListener("click", () => { $("#importBox").classList.remove("hidden"); });
  const notes = [`${L.teams.length} teams · ${L.starters} starters · ${L.scoring_type.replace(/_/g, " ").toLowerCase() || "category"} · ${L.source}`];
  if (L.unsupported_cats.length) notes.push(`Categories not modelled: ${L.unsupported_cats.join(", ")}`);
  if (L.punts.length) notes.push(`Punting ${L.punts.map((c) => LABEL[c]).join(", ")}: ignored for player values, still scored in matchups.`);
  $("#lgNote").textContent = notes.join(" · ");
  const n = L.power.length;
  const cols = `<thead><tr><th>#</th><th class="l">Team</th><th>Record</th><th title="Chance to win a typical week vs each other team, averaged">All-play</th><th title="Expected categories won per matchup">Cats</th>` +
    L.cats.map((c) => `<th class="${S.punts.has(c) ? "punted" : ""}">${LABEL[c]}</th>`).join("") + `<th>Value</th></tr></thead>`;
  $("#powerTable").innerHTML = cols + "<tbody>" + L.power.map((t) =>
    `<tr data-id="${t.team_id}" class="${t.team_id === S.myTeam ? "mine" : ""}" style="cursor:pointer">
      <td>${t.power_rank}</td><td class="l name">${esc(t.name)}</td>
      <td class="meta">${t.record.w}-${t.record.l}${t.record.t ? "-" + t.record.t : ""}</td>
      <td><b>${t.allplay.toFixed(1)}%</b></td><td>${t.exp_cats.toFixed(2)}</td>` +
      L.cats.map((c) => `<td class="cat ${S.punts.has(c) ? "punted" : ""}" style="${rankHeat(t.cats[c].rank, n)}" title="Rank ${t.cats[c].rank} · wins this category ${t.cats[c].win_pct}% of matchups">${weekly(c, t.cats[c].weekly)}</td>`).join("") +
      `<td>${t.value_sum.toFixed(1)}</td></tr>`).join("") + "</tbody>";
  $$("#powerTable tbody tr").forEach((tr) => tr.addEventListener("click", () => { S.selTeam = +tr.dataset.id; renderRoster(); }));
  renderRoster();
}

function renderRoster() {
  const L = S.league;
  const t = L.teams.find((x) => x.id === S.selTeam);
  if (!t) return;
  $("#rosterTitle").innerHTML = `${esc(t.name)} <span class="hint">· click a team above to switch</span>`;
  const cols = rankColumns(L.cats, false, true).filter((c) => c.k !== "dz");
  $("#rosterTable").innerHTML = headerHTML(cols, false) + "<tbody>" +
    t.players.map((p) => `<tr>${playerRowHTML(p, cols, L.cats)}</tr>`).join("") + "</tbody>";
  bindExplain("#rosterTable");
}

/* ---------- matchups ---------- */
function renderMatchups() {
  const L = S.league;
  $("#periodNote").textContent = L.has_schedule
    ? "Games counted from the NBA schedule, capped at your daily starting slots."
    : "No NBA schedule available: assuming 3.5 games per player.";
  const ms = [...L.matchups].sort((a, b) => (b.home.id === S.myTeam || b.away.id === S.myTeam) - (a.home.id === S.myTeam || a.away.id === S.myTeam));
  if (!ms.length) { $("#matchups").innerHTML = `<p class="meta">No matchups scheduled for this week.</p>`; return; }
  $("#matchups").innerHTML = ms.map((m) => {
    const mine = m.home.id === S.myTeam || m.away.id === S.myTeam;
    const live = Object.keys(m.home.live || {}).length;
    return `<div class="mu ${mine ? "mine" : ""}">
      <div class="mu-head">
        <div><div class="mu-team">${esc(m.home.name)}</div><div class="mu-games">${m.home.games} games · ${m.home_exp_cats.toFixed(1)} cats</div></div>
        <div class="meta">vs</div>
        <div class="r"><div class="mu-team">${esc(m.away.name)}</div><div class="mu-games">${m.away.games} games · ${m.away_exp_cats.toFixed(1)} cats</div></div>
      </div>
      <div class="mu-head" style="margin-top:6px">
        <div class="mu-pct">${m.home_win.toFixed(0)}%</div><div class="meta">${m.tie >= 1 ? `tie ${m.tie.toFixed(0)}%` : ""}</div><div class="mu-pct r">${m.away_win.toFixed(0)}%</div>
      </div>
      <div class="bar"><i class="h" style="width:${m.home_win}%"></i><i class="t" style="width:${m.tie}%"></i><i class="a" style="width:${m.away_win}%"></i></div>
      <table>${m.cats.map((c) => {
        const hw = c.home_p >= 50;
        const lv = live ? `<div class="live">${fmtLive(c.cat, m.home.live[c.cat])} – ${fmtLive(c.cat, m.away.live[c.cat])} live</div>` : "";
        return `<tr class="${S.punts.has(c.cat) ? "punted" : ""}">
          <td class="${hw ? "win" : ""}">${weekly(c.cat, c.home)}</td>
          <td class="c">${LABEL[c.cat]}<div class="mini"><i style="width:${c.home_p}%"></i></div>${lv}</td>
          <td class="r ${!hw ? "win" : ""}">${weekly(c.cat, c.away)}</td></tr>`;
      }).join("")}</table>
    </div>`;
  }).join("");
}
const fmtLive = (c, v) => v == null ? "–" : (c === "fg" || c === "ft" ? pct(v) : Math.round(v));

/* ---------- trade ---------- */
function resetSel() { ["aGive", "bGive", "aDrop", "bDrop"].forEach((k) => S.trade[k].clear()); }
function setupTrade(reset) {
  const L = S.league;
  const opts = L.teams.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
  if (reset || S.trade.a == null) {
    S.trade.a = S.myTeam;
    S.trade.b = (L.teams.find((t) => t.id !== S.myTeam) || {}).id;
    resetSel();
  }
  $("#tA").innerHTML = opts;
  $("#tB").innerHTML = opts + `<option value="0">Free agents (add/drop)</option>`;
  $("#tA").value = S.trade.a; $("#tB").value = S.trade.b;
  renderTradeLists();
}
function tradePlayers(teamId) {
  if (teamId === 0) return S.league.free_agents;
  return (S.league.teams.find((t) => t.id === teamId) || { players: [] }).players;
}
function renderTradeLists() {
  const draw = (el, teamId, give, drop) => {
    const ps = tradePlayers(teamId);
    $(el).innerHTML = ps.map((p) => `<div class="prow ${give.has(p.id) ? "sel" : ""} ${drop.has(p.id) ? "drop" : ""}" data-id="${p.id}">
      <input type="checkbox" ${give.has(p.id) ? "checked" : ""} tabindex="-1">
      <div><span class="name">${esc(p.name)}</span>${p.injury ? `<span class="inj">${esc(p.injury)}</span>` : ""} <span class="meta">${esc(p.team)} · ${esc(p.pos)}</span></div>
      <span class="v">#${p.rank} · ${p.value.toFixed(2)}</span>
      ${teamId === 0 ? "<span></span>" : `<button class="x" title="Drop this player">✕</button>`}
    </div>`).join("");
    $$(el + " .prow").forEach((row) => {
      const id = row.dataset.id;
      row.addEventListener("click", (ev) => {
        if (ev.target.classList.contains("x")) { drop.has(id) ? drop.delete(id) : (drop.add(id), give.delete(id)); }
        else { give.has(id) ? give.delete(id) : (give.add(id), drop.delete(id)); }
        renderTradeLists();
      });
    });
  };
  draw("#tAList", S.trade.a, S.trade.aGive, S.trade.aDrop);
  draw("#tBList", S.trade.b, S.trade.bGive, S.trade.bDrop);
}

async function runTrade() {
  const T = S.trade;
  if (T.a === T.b) { $("#tMsg").textContent = "Pick two different teams."; return; }
  if (!T.aGive.size && !T.bGive.size) { $("#tMsg").textContent = "Tick at least one player."; return; }
  $("#tMsg").textContent = "Simulating…";
  const body = { ...params(), team_a: T.a, team_b: T.b, a_gives: [...T.aGive], b_gives: [...T.bGive],
    a_drops: [...T.aDrop], b_drops: [...T.bDrop] };
  try {
    const r = await api(`/api/league/${encodeURIComponent(S.leagueKey)}/trade`, { method: "POST", body: JSON.stringify(body) });
    $("#tMsg").textContent = "";
    renderTrade(r);
  } catch (e) { $("#tMsg").textContent = e.message; }
}

function renderTrade(r) {
  const n = S.league.teams.length;
  const side = (s) => {
    const over = s.roster_size_after > s.roster_limit;
    const list = (arr) => arr.map((p) => `${esc(p.name)} <span class="meta">#${p.rank ?? "–"}</span>`).join(", ") || "–";
    return `<div class="card">
      <h2>${esc(s.name)}</h2>
      <div class="meta">Gets: ${list(s.gets)}<br>Gives: ${list(s.gives)}${s.drops.length ? `<br>Drops: ${list(s.drops)}` : ""}</div>
      ${over ? `<div class="warn">Roster would be ${s.roster_size_after}/${s.roster_limit}: mark someone to drop (✕) for an accurate read.</div>` : ""}
      <div class="verdict">
        <div class="kpi"><div class="k">All-play win</div><div class="v">${s.allplay[1].toFixed(1)}% ${delta(s.allplay[0], s.allplay[1])}</div><div class="meta">was ${s.allplay[0].toFixed(1)}%</div></div>
        <div class="kpi"><div class="k">Power rank</div><div class="v">${s.power_rank[1]} ${delta(s.power_rank[0], s.power_rank[1], 0, true)}</div><div class="meta">was ${s.power_rank[0]} of ${n}</div></div>
        <div class="kpi"><div class="k">Cats / week</div><div class="v">${s.exp_cats[1].toFixed(2)} ${delta(s.exp_cats[0], s.exp_cats[1], 2)}</div></div>
        <div class="kpi"><div class="k">Value</div><div class="v">${s.value_sum[1].toFixed(1)} ${delta(s.value_sum[0], s.value_sum[1])}</div></div>
      </div>
      <table class="grid"><thead><tr><th class="l">Cat</th><th>Weekly</th><th>After</th><th>Win % vs league</th><th>Change</th><th>Rank</th></tr></thead><tbody>
      ${r.cats.map((c) => {
        const x = s.cats[c];
        const lower = c === "tov";
        return `<tr class="${S.punts.has(c) ? "punted" : ""}"><td class="l"><b>${LABEL[c]}</b>${S.punts.has(c) ? ' <span class="meta">punted</span>' : ""}</td>
          <td>${weekly(c, x.weekly[0])}</td><td>${weekly(c, x.weekly[1])}</td>
          <td>${x.win_pct[0].toFixed(0)}% → <b>${x.win_pct[1].toFixed(0)}%</b></td>
          <td>${delta(x.win_pct[0], x.win_pct[1])}</td>
          <td>${x.rank[0]} → <b>${x.rank[1]}</b></td></tr>`;
      }).join("")}</tbody></table>
    </div>`;
  };
  const movers = r.league.filter((t) => t.rank[0] !== t.rank[1]);
  $("#tResult").innerHTML = `<div class="result-grid">${r.sides.map(side).join("")}</div>
    <h3>League power rankings after the trade</h3>
    <div class="table-wrap"><table class="grid"><thead><tr><th>Rank</th><th class="l">Team</th><th>Was</th><th>All-play</th></tr></thead><tbody>
    ${r.league.map((t) => `<tr class="${t.team_id === S.myTeam ? "mine" : ""}"><td><b>${t.rank[1]}</b></td><td class="l">${esc(t.name)}</td>
      <td>${t.rank[0]} ${t.rank[0] !== t.rank[1] ? delta(t.rank[0], t.rank[1], 0, true) : ""}</td>
      <td>${t.allplay[1].toFixed(1)}% ${delta(t.allplay[0], t.allplay[1])}</td></tr>`).join("")}
    </tbody></table></div>
    <p class="note">${movers.length ? "" : "No team changes rank. "}Category win % = chance of winning that category against a random league opponent in a typical week.</p>`;
}

/* ---------- method ---------- */
function renderMethod() {
  $("#methodText").innerHTML = `
  <h2>How a ranking is built</h2>
  <p>Each player's per-game line becomes one number per category, and the categories are averaged. Every system is a preset of the switches under <b>Model settings</b>. The default is DURANT H2H.</p>
  <ul>
    <li><b>Scale against</b> sets the spread that converts each category into a common unit. <i>Rostered players</i> uses the top teams × roster. <i>Rostered + waiver pool</i> uses 1.5× that. <i>Whole NBA</i> (DURANT) uses every eligible player.</li>
    <li><b>Zero point</b> sets what counts as 0: the pool average, or the waiver tier (so values read "better than a pickup"). It doesn't change a straight ranking, but it changes which category Minus 1 drops.</li>
    <li><b>Transform</b> applies DURANT's Yeo-Johnson step, which compresses extreme tails such as 3+ blocks a game.</li>
    <li><b>Weights</b>: <i>Equal</i>, <i>DURANT H2H</i> (PTS 1, REB .94, AST .75, rest .6), or <i>by weekly noise</i> (G-score, which shrinks volatile categories like steals and FT%).</li>
    <li><b>Turnovers</b> count at full weight, half weight (DURANT), or not at all (DURANT H2H).</li>
    <li><b>Minus 1</b> drops each player's weakest category. Use it when building around a player with one glaring hole, like Giannis' FT%. The Dropped column shows what was removed.</li>
  </ul>
  <p><b>Eligibility</b> scales with the season. To set the scale or fit the transform, a player needs 25% of the most games anyone has played (2 games in the first week, about 21 by season's end) and 10+ minutes a game. The Min GP filter on the rankings page uses the same 25% rule.</p>
  <p><b>Punting</b> removes a category from player values. Matchup and trade odds still score every category, because your opponents still win them.</p>

  <h2>What the draft simulations say</h2>
  <p>The 2025-26 season was replayed for each system: 1,000 snake drafts of 12 teams × 13 rounds, then every week played from real box scores (all-play, 9-cat H2H). Eleven opponents draft off standard Z with some randomness; one test team uses the system being tested. <i>Perfect info</i> values players on the full season. <i>Real-world</i> values them on Oct–Dec and plays Jan–Apr. Numbers are the test team's matchup win %.</p>
  <table>
    <tr><th>Settings</th><th>Perfect info</th><th>Real-world</th></tr>
    <tr><td>Standard Z (rostered)</td><td>56.8</td><td>57.2</td></tr>
    <tr><td><b>Transform + rostered + TO ½ (Category Lab preset)</b></td><td><b>62.8</b></td><td><b>68.5</b></td></tr>
    <tr><td>Transform + rostered, TO full</td><td>60.9</td><td>62.1</td></tr>
    <tr><td>Transform + rostered + waivers</td><td>56.8</td><td>61.3</td></tr>
    <tr><td>Transform + whole NBA</td><td>49.7</td><td>52.4</td></tr>
    <tr><td>Transform + rostered + DURANT H2H weights, no TO</td><td>55.8</td><td>61.6</td></tr>
    <tr><td>G-score</td><td>60.4</td><td>61.2</td></tr>
    <tr><td>DURANT</td><td>50.7</td><td>47.3</td></tr>
    <tr><td>DURANT H2H</td><td>49.3</td><td>53.7</td></tr>
    <tr><td>DURANT H2H, no Minus 1</td><td>50.5</td><td>66.0</td></tr>
    <tr><td>Category Lab + Minus 1</td><td>46.5</td><td>62.5</td></tr>
  </table>
  <ul>
    <li><b>DURANT's transform and half-weight turnovers both help</b>, and together they're the best setup found. Full-weight turnovers over-punish high-usage stars.</li>
    <li><b>Measuring against the whole NBA hurts.</b> Deep bench players distort the spread. Adding the waiver tier to the scale didn't help either; waiver players matter more as the zero point.</li>
    <li><b>Josh's H2H category weights didn't add anything</b> on top of the transform and the turnover change.</li>
    <li><b>Minus 1 hurt in this setup, with a big caveat:</b> the simulated drafter just takes the highest-ranked player and never builds around a punt, which is exactly what Minus 1 is for. These results show it's a weak <i>straight ranking</i>, not that it's a bad team-building tool.</li>
  </ul>
  <p>Other limits: one season, opponents all draft the same way, no waiver streaming, every game counts. Treat the results as directional.</p>
  <h2>Matchup model</h2>
  <p>Weekly projection = per-game stats × games that week. Games come from the NBA schedule, capped at your daily starting slots with the best players starting. Week-to-week randomness uses dispersion estimated from 2025-26 game logs; FG% and FT% are binomial on the week's attempts. Win probabilities come from 4,000 simulated weeks. Matchup and trade odds use the stats directly, so they don't depend on which ranking system you pick.</p>`;
}

init();
