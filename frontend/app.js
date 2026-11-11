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
  if (r.status === 401 && !path.startsWith("/api/login")) {
    location.href = "/login";                       // session expired or password changed
    throw new Error("Please log in again.");
  }
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
// One row of equal-width coloured cells, one per category: green = good, red = bad.
function catStrip(v, cats, punts = S.punts) {
  return `<div class="catstrip" style="grid-template-columns:repeat(${cats.length},1fr)">${cats.map((c) =>
    `<span class="${punts && punts.has && punts.has(c) ? "punted" : ""}" style="${heat(v[c])}" title="${LABEL[c]}: ${v[c] > 0 ? "+" : ""}${Number(v[c]).toFixed(2)}">${LABEL[c]}</span>`).join("")}</div>`;
}
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
  // prefs v3: only DURANT H2H (default) and Standard 9-cat are offered; reset older saved choices once
  if (store.get("prefsVersion", 1) < 3) { store.del("system"); store.del("spec"); store.set("prefsVersion", 3); }
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
  ["#search", "#ownerFilter", "#minGp", "#showValues"].forEach((s) =>
    $(s).addEventListener("input", () => { S.show = 200; renderRankings(); }));
  S.pos = new Set();
  $$("#posFilter .chip").forEach((b) => b.addEventListener("click", () => {
    const v = b.dataset.p;
    S.pos.has(v) ? S.pos.delete(v) : S.pos.add(v);
    b.classList.toggle("on", S.pos.has(v));
    S.show = 200; renderRankings();
  }));
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
  if (S.meta.auth) {
    $("#logoutBtn").classList.remove("hidden");
    $("#logoutBtn").addEventListener("click", async () => {
      try { await fetch("/api/logout", { method: "POST" }); } catch {}
      location.href = "/login";
    });
  }
  $("#myTeam").addEventListener("change", () => {
    S.myTeam = +$("#myTeam").value; store.set("myTeam", S.myTeam); S.selTeam = S.myTeam;
    S.build = null; S.buildPunts = null;
    renderLeague(); renderMatchups(); setupTrade(true); renderRankings();
    if ($("#tab-build").classList.contains("on")) loadBuild();
    S.stream = null; $("#sAdds").value = "";
    $("#sOut").innerHTML = `<p class="meta">Press <b>Plan my week</b> to find the best adds for your current matchup.</p>`;
    if ($("#tab-stream").classList.contains("on")) runStream(true);
  });
  $("#period").addEventListener("change", () => loadLeague());
  $("#tRun").addEventListener("click", runTrade);
  $("#sRun").addEventListener("click", () => runStream(false));
  $$("#viewMode button").forEach((b) => b.addEventListener("click", () => {
    S.view = b.dataset.v;
    $$("#viewMode button").forEach((x) => x.classList.toggle("on", x === b));
    $("#showValuesWrap").classList.toggle("hidden", S.view === "schedule");
    if (S.view === "schedule" && S.sort.key.startsWith("c_")) S.sort = { key: "value", dir: -1 };
    renderRankings();
  }));
  ["#sWeek", "#sMode"].forEach((id) => $(id).addEventListener("change", () => runStream(true)));
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
  if (["rankings", "league", "build", "matchups", "stream", "trade", "method"].includes(hash)) showTab(hash);
  await loadRankings();
  if (saved && saved.demo) loadLeagueKey(null, true);
  else if (saved && saved.league_id) importLeague(true);
}

function showTab(t) {
  if (t === "stream" && S.leagueKey && !S.stream) setTimeout(() => runStream(true), 0);
  if (t === "build" && S.leagueKey && !S.build) setTimeout(() => loadBuild(), 0);
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
function refreshAll() {
  S.build = null; loadRankings(); if (S.leagueKey) loadLeague();
  if ($("#tab-build").classList.contains("on")) loadBuild();
}
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

function schedCols() {
  const sc = S.rank && S.rank.schedule;
  if (!sc || !sc.weeks.length) return [];
  const wk = sc.weeks[0];
  const teamOf = (p) => (sc.teams[p.team] || { this: [], next: [] });
  const left = (p) => teamOf(p).this.filter((g, i) => g && !wk.days[i].past).length;
  const next = (p) => teamOf(p).next.filter(Boolean).length;
  return [
    ...wk.days.map((d, i) => ({ k: "d" + i, t: `${d.dow}<br><span class="meta" style="font-weight:400">${d.date}</span>`,
      day: i, f: (p) => teamOf(p).this[i] ? 1 : 0, title: `${d.nba_games} NBA games` })),
    { k: "left", t: "Left<br>this wk", f: left, title: "Games left in this matchup week" },
    { k: "next", t: "Next<br>week", f: next },
  ];
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
  if (S.view === "schedule" && !withSlot) {
    cols.push(...schedCols());
    cols.push({ k: "value", t: "Value", f: (p) => p.value });
    cols.push({ k: "chips", t: "Good / bad at", l: true, f: () => 0 });
    return cols;
  }
  cats.forEach((c) => cols.push({ k: "c_" + c, t: LABEL[c], cat: c, f: (p) => $("#showValues").checked ? p.v[c] : (c === "fg" || c === "ft" ? p.v[c] : p.stats[c]) }));
  cols.push({ k: "value", t: "Value", f: (p) => p.value });

  if (dur) cols.push({ k: "dropped", t: "Dropped", f: (p) => p.dropped || "" });
  return cols;
}

function playerRowHTML(p, cols, cats) {
  const showV = $("#showValues").checked;
  return cols.map((c) => {
    if (c.k === "name") {
      const owner = p.fantasy_team_name == null ? ""
        : p.fantasy_team === 0 ? ` <span class="tag ${p.status === "WAIVERS" ? "" : "acc"}">${p.status === "WAIVERS" ? "waivers" : "FA"}</span>`
        : `<span class="owner"> · ${esc(p.fantasy_team_name)}</span>`;
      return `<td class="l clickable" data-pid="${esc(p.id)}" title="Why is he ranked here?"><span class="name">${esc(p.name)}</span>${p.injury ? `<span class="inj">${esc(p.injury)}</span>` : ""}<br><span class="meta">${esc(p.team)} · ${esc(p.pos)}${p.no_stats ? " · no stats in this window" : ""}</span>${owner}</td>`;
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
    if (c.day != null) {
      const wk = S.rank.schedule.weeks[0], d = wk.days[c.day];
      return `<td class="${d.today ? "today-col" : ""}">${c.f(p) ? `<span class="cell ${d.past ? "past" : "start"}"></span>` : ""}</td>`;
    }
    if (c.k === "left" || c.k === "next") return `<td><b>${c.f(p)}</b></td>`;
    if (c.k === "chips") return `<td class="l strip-cell">${catStrip(p.v, cats)}</td>`;
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
  const pos = S.pos || new Set();
  const own = $("#ownerFilter").value;
  const minGp = +$("#minGp").value || 0;
  let rows = S.rank.players.filter((p) =>
    (!q || p.name.toLowerCase().includes(q)) &&
    (!pos.size || (p.pos || "").split("/").some((x) => pos.has(x))) &&
    p.g >= minGp &&
    (!own || (own === "avail" ? p.fantasy_team === 0
      : own === "fa" ? p.fantasy_team === 0 && p.status !== "WAIVERS"
      : own === "waivers" ? p.fantasy_team === 0 && p.status === "WAIVERS"
      : String(p.fantasy_team) === own)));
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
  $$(table + " td.clickable").forEach((td) => td.addEventListener("click", () => openPlayer(td.dataset.pid)));
}
function closeExplain() { $("#explain").classList.add("hidden"); $("#explain").classList.remove("wide-drawer"); }

/* ---------- player card ---------- */
const WINDOW_COLS = ["fg", "ft", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov"];
async function openPlayer(pid) {
  $("#explain").classList.remove("hidden");
  $("#explain").classList.add("wide-drawer");
  $("#exBody").innerHTML = `<p class="meta">Loading player…</p>`;
  const p = { ...params(), teams: $("#teams").value, roster: $("#roster").value, league: S.leagueKey };
  if (S.leagueKey) p.team_id = S.myTeam;
  let d;
  try { d = await api(`/api/player/${encodeURIComponent(pid)}?` + qs(p)); }
  catch (e) { $("#exBody").innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
  const sysLabel = $("#system").selectedOptions[0].textContent;
  const sn = d.snapshot;
  const statTd = (w, c) => c === "fg" || c === "ft" ? `<td title="${c === "fg" ? w.fga : w.fta} att/g">${pct(w[c])}</td>` : `<td>${w[c].toFixed(1)}</td>`;
  const schedRow = (wk) => `<div class="days"><span class="meta">${wk.label}</span>${wk.days.map((x) =>
    `<div class="day ${x.game ? "game" : ""} ${x.past ? "past" : ""} ${x.today ? "today" : ""}" title="${x.nba_games} NBA games">${x.dow}<br><span style="font-size:10px">${x.date}</span></div>`).join("")}</div>`;
  const nGames = (wk) => wk.days.filter((x) => x.game && !x.past).length;
  $("#exBody").innerHTML = `
    <div class="pc-head"><div>
      <h2>${esc(d.name)}</h2>
      <div class="meta">${esc(d.team)} · ${esc(d.pos)}</div>
      <div class="pc-tags">
        ${d.injury ? `<span class="tag bad">${esc(d.injury)}</span>` : ""}
        ${d.owner ? `<span class="tag ${d.owner === "Free agent" || d.owner === "Waivers" ? "acc" : ""}">${esc(d.owner)}</span>` : ""}
        <span class="tag">${d.owned.toFixed(1)}% rostered on ESPN</span>
      </div></div></div>

    ${sn ? `<div class="pc-snap">
      <div class="big">#${sn.rank}</div>
      <div><b>${esc(sysLabel)}</b> rank · value ${sn.value.toFixed(2)} <span class="meta">(${esc(S.meta.splits[d.split] || d.split)} stats${sn.dropped ? ` · Minus 1 drops ${sn.dropped}` : ""})</span><br>
        ${catStrip(sn.v, d.cats)}</div>
    </div>` : `<p class="meta">No stats in the selected window.</p>`}
    ${d.build ? `<div class="callout">For ${esc(d.build.team)}'s build (${d.build.punts.length ? "punt " + d.build.punts.map((c) => LABEL[c]).join(" + ") : "no punts"}):
      <b>#${d.build.build_rank}</b> vs #${d.build.std_rank} normally
      ${d.build.build_rank < d.build.std_rank - 5 ? '<span class="up">· fits your build</span>' : d.build.build_rank > d.build.std_rank + 5 ? '<span class="down">· doesn\'t fit your build</span>' : ""}</div>` : ""}

    <h3>Per game, by stats window</h3>
    <div class="table-wrap"><table class="grid"><thead><tr><th class="l">Window</th><th>GP</th><th>MPG</th>${WINDOW_COLS.map((c) => `<th>${LABEL[c]}</th>`).join("")}</tr></thead><tbody>
      ${d.windows.map((w) => `<tr class="${w.key === d.split ? "mine" : ""}"><td class="l">${esc(w.label)}</td><td>${w.g}</td><td>${w.mpg}</td>${WINDOW_COLS.map((c) => statTd(w, c)).join("")}</tr>`).join("")}
    </tbody></table></div>

    ${d.schedule.length ? `<h3>Schedule <span class="hint">· ${d.schedule.map((wk) => `${nGames(wk)} game${nGames(wk) === 1 ? "" : "s"} ${wk.label.toLowerCase()}`).join(" · ")}</span></h3>${d.schedule.map(schedRow).join("")}` : ""}

    <div id="pcEspn">${d.espn_extras ? `<p class="meta">Loading game log, news and career stats from ESPN…</p>`
      : `<p class="note">Game log, news and career stats come from ESPN and aren't available in the demo.</p>`}</div>

    <p style="margin-top:18px"><button class="ghost small" id="pcWhy">Compare how each ranking system ranks him →</button></p>`;
  $("#pcWhy").addEventListener("click", () => { $("#explain").classList.remove("wide-drawer"); openExplain(pid); });
  if (d.espn_extras) loadEspnExtras(pid);
}

async function loadEspnExtras(pid) {
  let e;
  try { e = await api(`/api/player/${encodeURIComponent(pid)}/espn`); }
  catch (err) { $("#pcEspn").innerHTML = `<p class="warn">${esc(err.message)}</p>`; return; }
  if (!$("#pcEspn")) return;
  const pick = (labels, want) => { const s = want.filter((x) => labels.includes(x)); return s.length >= 4 ? s : labels; };
  const GL = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "3PT", "FG", "FT", "TO"];
  const CR = ["GP", "MIN", "PTS", "REB", "AST", "STL", "BLK", "3PT", "FG%", "FT%", "TO"];
  const fmtDate = (s) => { const t = new Date(s); return isNaN(t) ? esc(s) : `${t.getMonth() + 1}/${t.getDate()}`; };
  let html = "";
  const g = e.gamelog;
  if (g.error) html += `<h3>Recent games</h3><p class="meta">${esc(g.error)}</p>`;
  else {
    const cols = pick(g.labels, GL);
    html += `<h3>Recent games</h3><div class="table-wrap"><table class="grid"><thead><tr><th class="l">Date</th><th class="l">Opp</th><th class="l">Result</th>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>
      ${g.games.map((x) => `<tr><td class="l">${fmtDate(x.date)}</td><td class="l">${esc(x.at)} ${esc(x.opp)}</td><td class="l ${x.result === "W" ? "up" : x.result === "L" ? "down" : ""}">${esc(x.result)} ${esc(x.score)}</td>${cols.map((c) => `<td>${esc(x.stats[c] ?? "")}</td>`).join("")}</tr>`).join("")}
    </tbody></table></div>`;
  }
  const n = e.news;
  html += `<h3>News</h3>` + (n.error ? `<p class="meta">${esc(n.error)}</p>` : n.items.map((x) =>
    `<div class="news-item"><b>${esc(x.headline)}</b>${esc(x.text)} <span class="meta">${x.published ? fmtDate(x.published) : ""}${x.link ? ` · <a href="${esc(x.link)}" target="_blank" rel="noopener">ESPN</a>` : ""}</span></div>`).join(""));
  const c = e.career;
  if (c.error) html += `<h3>Career</h3><p class="meta">${esc(c.error)}</p>`;
  else {
    const cols = pick(c.labels, CR);
    html += `<h3>Career averages</h3><div class="table-wrap"><table class="grid"><thead><tr><th class="l">Season</th><th class="l">Team</th>${cols.map((x) => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>
      ${[...c.seasons].reverse().map((r) => `<tr><td class="l">${esc(r.season)}</td><td class="l meta">${esc(r.team)}</td>${cols.map((x) => `<td>${esc(r.stats[x] ?? "")}</td>`).join("")}</tr>`).join("")}
      ${c.career ? `<tr><td class="l"><b>Career</b></td><td></td>${cols.map((x) => `<td><b>${esc(c.career[x] ?? "")}</b></td>`).join("")}</tr>` : ""}
    </tbody></table></div>`;
  }
  $("#pcEspn").innerHTML = html;
}
async function openExplain(pid, target) {
  const curKey = $("#system").value;
  target = target || (curKey === S.meta.default_system ? "z" : S.meta.default_system);
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
  $("#teamWrap").classList.remove("hidden");
  $("#ownerFilter").innerHTML = `<option value="">All players</option><option value="avail">Available (FA + waivers)</option><option value="fa">Free agents only</option><option value="waivers">On waivers</option>` +
    L.teams.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
  $("#period").innerHTML = L.periods.map((n) => `<option value="${n}">Week ${n}${n === L.current_period ? " (current)" : ""}</option>`).join("");
  if (!S.stream) {
    const up = L.periods.filter((n) => n >= L.current_period).slice(0, 3);
    const keep = $("#sWeek").value;
    $("#sWeek").innerHTML = up.map((n, i) => `<option value="${n}">Week ${n}${i === 0 ? " (this week)" : ""}</option>`).join("");
    if (keep && up.includes(+keep)) $("#sWeek").value = keep;
  }
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
  if (first) { S.stream = null; $("#sOut").innerHTML = `<p class="meta">Press <b>Plan my week</b> to find the best adds for your current matchup.</p>`; }
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

/* ---------- team build ---------- */
async function loadBuild() {
  if (!S.leagueKey) return;
  $("#bOut").innerHTML = `<p class="meta">Analysing your roster…</p>`;
  const p = { ...params(), team_id: S.myTeam };
  delete p.punt;
  if (S.buildPunts != null) p.build = S.buildPunts.length ? S.buildPunts.join(",") : "none";
  try { S.build = await api(`/api/league/${encodeURIComponent(S.leagueKey)}/build?` + qs(p)); }
  catch (e) { $("#bOut").innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
  renderBuild();
}

function renderBuild() {
  const B = S.build;
  const sysLabel = $("#system").selectedOptions[0].textContent;
  const puntName = (ps) => ps.length ? "Punt " + ps.map((c) => LABEL[c]).join(" + ") : "No punt";
  const cur = B.build;
  const tile = (x) => {
    const t = x.win_pct >= 60 ? "strong" : x.win_pct >= 45 ? "swing" : "weak";
    const punted = cur.punts.includes(x.cat);
    return `<div class="ptile ${t} ${punted ? "punted" : ""}"><div class="c">${LABEL[x.cat]}</div><div class="w">${x.win_pct.toFixed(0)}%</div><div class="r meta">${x.rank}${["st","nd","rd"][x.rank - 1] || "th"} of ${x.of}</div></div>`;
  };
  const tagCls = { core: "up", fits: "meta", "doesn't fit": "down", "no stats": "meta" };
  const rk = (n) => n == null ? "–" : `#${n}`;
  const statChips = (v) => catStrip(v, B.cats.filter((c) => !cur.punts.includes(c)), new Set());
  const misfits = B.players.filter((m) => m.label === "doesn't fit");

  $("#bOut").innerHTML = `
    <div class="s-head"><div>
      <h2>What should ${esc(B.team.name)} build around?</h2>
      <div class="meta">Win ${B.need} of ${B.cats.length} categories each week. In a typical week you currently win <b>${B.winning_now}</b>. Player ranks use ${esc(sysLabel)} (${esc(S.meta.splits[B.split] || B.split)} stats).</div>
    </div></div>

    <h3 style="margin-top:6px">Where your team stands <span class="hint">· chance to win each category in a typical week vs the league</span></h3>
    <div class="ptiles">${B.profile.map(tile).join("")}</div>

    <h3>Builds that suit your roster <span class="hint">· click one to analyse it</span></h3>
    <div class="builds">${B.builds.map((b, i) => {
      const on = JSON.stringify([...b.punts].sort()) === JSON.stringify([...cur.punts].sort());
      return `<button class="bcard ${on ? "on" : ""}" data-punts="${b.punts.join(",")}">
        <div class="bt">${puntName(b.punts)}${i === 0 ? ' <span class="rec">recommended</span>' : ""}</div>
        <div class="bm">Roster ranks <b>${b.team_rank}${["st","nd","rd"][b.team_rank - 1] || "th"}</b> of ${b.of} for this build</div>
        <div class="meta">Already winning ${b.winning} of the ${b.targets.length} categories you'd keep</div></button>`;
    }).join("")}</div>
    <p class="note">Each build re-values every player without the punted categories, then compares your roster with every other team's. Punting a category you currently win counts against a build; punting one you lose most weeks costs little. With no punts your roster ranks ${B.no_punt.team_rank} of ${B.no_punt.of}.</p>

    <h3>Your roster in this build: ${puntName(cur.punts)}</h3>
    <div class="table-wrap"><table class="grid"><thead><tr><th class="l">Player</th><th>Normal rank</th><th>Build rank</th><th>Change</th><th class="l">Fit</th><th class="l">Strengths for this build</th></tr></thead><tbody>
      ${B.players.map((m) => `<tr><td class="l clickable" data-pid="${esc(m.id)}"><span class="name">${esc(m.name)}</span>${m.injury ? `<span class="inj">${esc(m.injury)}</span>` : ""}<br><span class="meta">${esc(m.team)} · ${esc(m.pos)}</span></td>
        <td>${rk(m.std_rank)}</td><td><b>${rk(m.build_rank)}</b></td>
        <td>${m.delta == null ? "" : m.delta === 0 ? '<span class="meta">–</span>' : `<span class="${m.delta < 0 ? "up" : "down"}">${m.delta < 0 ? "▲" : "▼"}${Math.abs(m.delta)}</span>`}</td>
        <td class="l"><span class="${tagCls[m.label]}"><b>${m.label}</b></span></td>
        <td class="l">${m.v ? statChips(m.v) : ""}</td></tr>`).join("")}
    </tbody></table></div>

    <h3>Swap ideas <span class="hint">· similar normal rank (a similar trade price), much better fit for this build</span></h3>
    ${misfits.length ? misfits.map((m) => {
      const ts = B.targets[m.id] || [];
      return `<div class="card swapcard"><div class="sw-head"><b>${esc(m.name)}</b> <span class="meta">normal ${rk(m.std_rank)} · build ${rk(m.build_rank)}</span></div>
        ${ts.length ? `<table class="grid"><tbody>${ts.map((t) => `<tr>
          <td class="l clickable" data-pid="${esc(t.id)}"><span class="name">${esc(t.name)}</span>${t.injury ? `<span class="inj">${esc(t.injury)}</span>` : ""} <span class="meta">${esc(t.team)} · ${esc(t.pos)}</span><br><span class="meta">${esc(t.owner)}</span></td>
          <td>normal ${rk(t.std_rank)}</td><td>build <b>${rk(t.build_rank)}</b></td>
          <td class="l">${statChips(t.v)}</td>
          <td><button class="ghost small trybtn" data-give="${esc(m.id)}" data-get="${esc(t.id)}" data-owner="${t.owner_id}">${t.owner_id ? "Analyze trade →" : "Analyze add/drop →"}</button></td></tr>`).join("")}</tbody></table>`
          : `<p class="meta">No similarly ranked player fits this build clearly better.</p>`}</div>`;
    }).join("") : `<div class="card meta">Everyone on your roster fits this build reasonably well.</div>`}
    <div class="row" style="margin-top:14px">
      <button class="ghost" id="bRank">Rank all players for this build →</button>
      <span class="hint">Sets the punt buttons to this build and opens Rankings.</span></div>`;

  $$(".bcard").forEach((b) => b.addEventListener("click", () => {
    S.buildPunts = b.dataset.punts ? b.dataset.punts.split(",") : [];
    loadBuild();
  }));
  $$(".trybtn").forEach((b) => b.addEventListener("click", () => {
    S.trade.a = S.myTeam; S.trade.b = +b.dataset.owner;
    resetSel(); S.trade.aGive.add(b.dataset.give); S.trade.bGive.add(b.dataset.get);
    $("#tA").value = S.trade.a; $("#tB").value = S.trade.b;
    renderTradeLists(); showTab("trade"); runTrade();
  }));
  $("#bRank").addEventListener("click", () => {
    S.punts = new Set(cur.punts); store.set("punts", [...S.punts]);
    renderPuntChips(S.league.cats); showTab("rankings"); refreshAll();
  });
  bindExplain("#bOut");
}

/* ---------- streaming ---------- */
function dropKey() { return `drops:${S.leagueKey}:${S.myTeam}`; }
async function runStream(keepAdds) {
  if (!S.leagueKey) return;
  $("#sMsg").textContent = "Planning…";
  const body = { ...params(), team_id: S.myTeam, mode: $("#sMode").value };
  if ($("#sWeek").value) body.period = +$("#sWeek").value;
  const saved = store.get(dropKey(), null);
  if (saved) body.droppable = saved;
  if (keepAdds !== true && $("#sAdds").value !== "") body.adds_left = +$("#sAdds").value;
  try {
    S.stream = await api(`/api/league/${encodeURIComponent(S.leagueKey)}/stream`, { method: "POST", body: JSON.stringify(body) });
    $("#sMsg").textContent = "";
    renderStream();
  } catch (e) { $("#sMsg").textContent = e.message; }
}

function renderStream() {
  const R = S.stream;
  if (!R) return;
  const weekSel = $("#sWeek");
  const curVal = weekSel.value;
  weekSel.innerHTML = R.periods.map((p, i) => `<option value="${p}">Week ${p}${i === 0 ? " (this week)" : ""}</option>`).join("");
  weekSel.value = curVal && R.periods.includes(+curVal) ? curVal : R.period;
  $("#sAdds").value = R.adds_left;
  const win = R.objective === "win";
  const fmtObj = (x) => win ? `${x.win.toFixed(0)}%` : `${x.exp_cats.toFixed(2)}`;
  const objLabel = win ? "Chance to win the matchup" : `Expected categories won (of ${R.cats.length})`;
  const dropSet = new Set(R.droppable);
  const sv = (c, v) => c === "fg" || c === "ft" ? pct(v) : v.toFixed(c === "tov" || c === "stl" || c === "blk" || c === "fg3m" ? 1 : 0);
  const dayHead = (i) => `<th class="${i === R.today_index ? "today" : ""}" title="${R.nba_games[i]} NBA games">${R.week_days[i]}<br><span class="meta" style="font-weight:400">${R.week_dates[i] || ""}${i === R.today_index ? " · today" : ""}</span></th>`;
  const moves = R.moves.length ? R.moves.map((m) => `<div class="move">
      <div class="d">${m.day}<br><span class="meta" style="font-weight:400;letter-spacing:0">${R.week_dates[R.week_days.indexOf(m.day)] || ""}</span></div>
      <div><span class="drop">${esc(m.drop.name)}</span> → <b>${esc(m.add.name)}</b> <span class="meta">${esc(m.add.team)} · ${esc(m.add.pos)}</span><br>
        <span class="meta">Starts ${m.add_starts.length ? m.add_starts.join(", ") : "no games"} </span></div>
      <div class="g">+${m.gain.toFixed(win ? 1 : 2)}${win ? " pts" : ""}</div></div>`).join("")
    : `<div class="card meta">No pickup improves your odds enough to be worth an add${R.adds_left === 0 ? " (you have no adds left)" : ""}. Try marking more players as droppable.</div>`;

  const grid = (G, addedIds) => `<table class="sgrid"><thead><tr><th class="l">Player</th>${R.week_days.map((_, i) => dayHead(i)).join("")}<th>Starts</th></tr></thead><tbody>
    ${G.rows.map((r) => `<tr class="${addedIds.has(r.id) ? "added" : ""}"><td class="l"><span class="name">${esc(r.name)}</span>${r.injury ? `<span class="inj">${esc(r.injury)}</span>` : ""} <span class="meta">${esc(r.team)} · ${esc(r.pos)}</span></td>
      ${r.cells.map((c) => `<td>${c === "none" ? "" : `<span class="cell ${c}" title="${{ start: "Starts", bench: "Has a game but no open slot", past: "Already played", off: "Not on roster" }[c]}"></span>`}</td>`).join("")}
      <td>${r.starts}</td></tr>`).join("")}
    <tr><td class="l meta">Starters / slots</td>${G.per_day.map((d) => `<td class="meta">${d ? `${d.starts}/${d.slots}${d.benched ? ` <span class="down">+${d.benched}</span>` : ""}` : ""}</td>`).join("")}<td></td></tr>
    <tr><td class="l meta">NBA games that day</td>${R.nba_games.map((n) => `<td class="meta" style="${n <= 5 ? "color:rgb(var(--good));font-weight:600" : ""}">${n}</td>`).join("")}<td></td></tr>
    </tbody></table>`;
  const addedIds = new Set(R.moves.map((m) => m.add.id));
  S.streamView = S.streamView || "after";

  $("#sOut").innerHTML = `
    <div class="s-head">
      <div><h2>${esc(R.team.name)} vs ${esc(R.opponent.name)}</h2>
        <div class="meta">Week ${R.period}${R.is_current ? ` · today is ${R.week_days[R.today_index] || "–"}` : " · upcoming"} · ${R.adds_used ? `${R.adds_used} add${R.adds_used > 1 ? "s" : ""} used, ` : ""}${R.adds_limit != null && R.adds_limit >= 0 ? `limit ${R.adds_limit}` : "no add limit"} · stats: ${esc(S.meta.splits[R.split] || R.split)}</div></div>
      <div class="verdict" style="margin:0">
        <div class="kpi"><div class="k">${objLabel}</div><div class="v">${fmtObj(R.before)} → <span class="${(win ? R.after.win - R.before.win : R.after.exp_cats - R.before.exp_cats) > 0 ? "up" : ""}">${fmtObj(R.after)}</span></div>
          <div class="meta">${win ? `${R.before.exp_cats.toFixed(2)} → ${R.after.exp_cats.toFixed(2)} expected cats` : `win chance ${R.before.win.toFixed(0)}% → ${R.after.win.toFixed(0)}%`}</div></div>
        <div class="kpi"><div class="k">Starts left</div><div class="v">${R.before.starts} → ${R.after.starts}</div><div class="meta">${R.after.benched ? `${R.after.benched} games lost to full lineups` : "no games lost to full lineups"}</div></div>
      </div>
    </div>
    <div class="s-cols">
      <div>
        <h3 style="margin-top:0">Plan</h3>
        ${R.add_locked_today ? `<p class="note" style="margin-top:0">Today's games have started, so anyone added today plays from tomorrow.</p>` : ""}
        <div class="moves">${moves}</div>
        <h3>Droppable players <span class="hint">· defaults to your 3 lowest-valued; tap to change, then re-plan</span></h3>
        <div class="drops">${R.roster.map((p) => `<label class="${dropSet.has(p.id) ? "on" : ""}"><input type="checkbox" data-pid="${p.id}" ${dropSet.has(p.id) ? "checked" : ""}>${esc(p.name)} <span class="meta">${p.value.toFixed(2)}</span></label>`).join("")}</div>
        <button class="ghost small" id="sResetDrops" style="margin-top:6px">Reset to 3 lowest</button>
      </div>
      <div>
        <h3 style="margin-top:0">Categories</h3>
        <table class="grid"><thead><tr><th class="l">Cat</th><th>So far</th><th>You (proj)</th><th>Opp (proj)</th><th>Win % now → plan</th></tr></thead><tbody>
        ${R.cats.map((c) => {
          const b = R.before.probs[c], a = R.after.probs[c];
          return `<tr class="${S.punts.has(c) ? "punted" : ""}"><td class="l"><b>${LABEL[c]}</b></td>
            <td class="meta">${R.is_current ? `${sv(c, R.so_far.me[c])}–${sv(c, R.so_far.opp[c])}` : "–"}</td>
            <td>${sv(c, R.before.proj[c])}${Math.abs(R.after.proj[c] - R.before.proj[c]) > 1e-6 ? ` → <b>${sv(c, R.after.proj[c])}</b>` : ""}</td>
            <td>${sv(c, R.opp_proj[c])}</td>
            <td style="${heat((a - 50) / 20)}">${b.toFixed(0)}% → <b>${a.toFixed(0)}%</b></td></tr>`;
        }).join("")}</tbody></table>
        <p class="note">Your opponent is projected from their current roster; if they stream too, your real odds are a bit lower.</p>
      </div>
    </div>
    <h3>Schedule <span class="seg" id="sView">
      <button data-v="after" class="${S.streamView === "after" ? "on" : ""}">With plan</button>
      <button data-v="before" class="${S.streamView === "before" ? "on" : ""}">Current roster</button>
      <button data-v="opp" class="${S.streamView === "opp" ? "on" : ""}">Opponent</button></span></h3>
    <div class="legend"><span><i class="cell start"></i> starts</span><span><i class="cell bench"></i> game, but no open slot</span><span><i class="cell off"></i> not on roster</span><span><i class="cell past"></i> already played</span></div>
    <div class="table-wrap" id="sGrid">${grid(S.streamView === "before" ? R.grid_before : S.streamView === "opp" ? R.grid_opp : R.grid_after, S.streamView === "after" ? addedIds : new Set())}</div>
    <h3>Best available streamers <span class="hint">· each one's best single add vs your current roster</span></h3>
    <div class="table-wrap"><table class="grid"><thead><tr><th class="l">Player</th><th class="l">Games left</th><th>Starts</th><th class="l">Add on</th><th class="l">Drop</th><th>Gain</th><th>${win ? "Win %" : "Exp cats"}</th><th>Value</th></tr></thead><tbody>
      ${R.board.map((b) => `<tr><td class="l clickable" data-pid="${esc(b.id)}"><span class="name">${esc(b.name)}</span>${b.injury ? `<span class="inj">${esc(b.injury)}</span>` : ""} <span class="meta">${esc(b.team)} · ${esc(b.pos)}</span></td>
        <td class="l">${b.days.map((d) => `<span class="daychip">${d}</span>`).join("")}</td><td>${b.starts}</td>
        <td class="l meta">${b.add_day}</td><td class="l meta">${esc(b.drop)}</td>
        <td><b class="${b.gain > 0 ? "up" : "down"}">${b.gain > 0 ? "+" : ""}${b.gain.toFixed(win ? 1 : 2)}</b></td>
        <td>${win ? b.win.toFixed(0) + "%" : b.exp_cats.toFixed(2)}</td><td class="meta">${b.value.toFixed(2)}</td></tr>`).join("")}
    </tbody></table></div>`;

  $$("#sView button").forEach((b) => b.addEventListener("click", () => { S.streamView = b.dataset.v; renderStream(); }));
  $$(".drops input").forEach((cb) => cb.addEventListener("change", () => {
    const ids = $$(".drops input").filter((x) => x.checked).map((x) => x.dataset.pid);
    store.set(dropKey(), ids);
    runStream(false);
  }));
  $("#sResetDrops").addEventListener("click", () => { store.del(dropKey()); runStream(true); });
  bindExplain("#sOut");
}

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
      <span class="v">${p.no_stats ? "no stats yet" : `#${p.rank} · ${p.value.toFixed(2)}`}</span>
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
    a_drops: [...T.aDrop], b_drops: [...T.bDrop], fill: $("#tFill").checked };
  try {
    const r = await api(`/api/league/${encodeURIComponent(S.leagueKey)}/trade`, { method: "POST", body: JSON.stringify(body) });
    $("#tMsg").textContent = "";
    renderTrade(r);
  } catch (e) { $("#tMsg").textContent = e.message; }
}

function renderTrade(r) {
  const n = S.league.teams.length;
  const win = /MOST/.test(S.league.scoring_type || "");
  const primary = win
    ? { label: "Weekly win chance", get: (s) => s.allplay, fmt: (x) => `${x.toFixed(1)}%`, unit: " pts", even: 1.0, digits: 1 }
    : { label: "Categories won per week", get: (s) => s.exp_cats, fmt: (x) => x.toFixed(2), unit: " cats", even: 0.05, digits: 2 };
  const secondary = win
    ? { label: "Cats per week", get: (s) => s.exp_cats, fmt: (x) => x.toFixed(2), digits: 2 }
    : { label: "Weekly win chance", get: (s) => s.allplay, fmt: (x) => `${x.toFixed(1)}%`, digits: 1 };
  const list = (arr) => arr.map((p) => `${esc(p.name)}`).join(", ") || "–";

  const side = (s) => {
    const [b, a] = primary.get(s), d = a - b;
    const tone = Math.abs(d) < primary.even ? "even" : d > 0 ? "up" : "down";
    const word = tone === "even" ? "About even" : tone === "up" ? "Better" : "Worse";
    const cats = r.cats.map((c) => ({ c, b: s.cats[c].win_pct[0], a: s.cats[c].win_pct[1], d: s.cats[c].win_pct[1] - s.cats[c].win_pct[0] }))
      .sort((x, y) => y.d - x.d);
    const gains = cats.filter((x) => x.d >= 5 && !S.punts.has(x.c)).map((x) => LABEL[x.c]);
    const losses = cats.filter((x) => x.d <= -5 && !S.punts.has(x.c)).reverse().map((x) => LABEL[x.c]);
    const maxAbs = Math.max(30, ...cats.map((x) => Math.abs(x.d)));
    const bar = (x) => {
      const w = Math.min(Math.abs(x.d) / maxAbs, 1) * 50;
      return `<div class="dbar"><span class="mid"></span>${Math.abs(x.d) >= 0.5
        ? `<i class="${x.d > 0 ? "pos" : "neg"}" style="${x.d > 0 ? `left:50%` : `right:50%`};width:${w}%"></i>` : ""}</div>`;
    };
    return `<div class="card trade-card">
      <h2>${esc(s.name)}</h2>
      <div class="swaps"><div><span class="k">Gets</span> ${list(s.gets)}${s.auto_adds.length ? ` <span class="auto">+ picks up ${list(s.auto_adds)}</span>` : ""}</div>
        <div><span class="k">Gives</span> ${list(s.gives)}${s.drops.length ? `, drops ${list(s.drops)}` : ""}${s.auto_drops.length ? ` <span class="auto">+ drops ${list(s.auto_drops)}</span>` : ""}</div></div>
      <div class="verdict-line ${tone}">
        <div class="big">${word}</div>
        <div><b>${primary.fmt(b)} → ${primary.fmt(a)}</b> ${primary.label.toLowerCase()}
          <span class="${tone === "even" ? "meta" : tone}">(${d > 0 ? "+" : ""}${d.toFixed(primary.digits)}${primary.unit})</span><br>
          <span class="meta">${gains.length ? `Gains ${gains.join(", ")}` : "No big category gains"}${losses.length ? ` · loses ${losses.join(", ")}` : ""}</span></div>
      </div>
      <div class="cat-bars">
        ${cats.map((x) => `<div class="cb ${S.punts.has(x.c) ? "punted" : ""}">
          <span class="c">${LABEL[x.c]}${S.punts.has(x.c) ? ' <span class="meta">punt</span>' : ""}</span>
          ${bar(x)}
          <span class="d ${x.d >= 0.5 ? "up" : x.d <= -0.5 ? "down" : "meta"}">${Math.round(x.d) === 0 ? "0" : `${x.d > 0 ? "+" : ""}${Math.round(x.d)}`}</span>
          <span class="p meta">${x.b.toFixed(0)}% → ${x.a.toFixed(0)}%</span></div>`).join("")}
        <div class="cb-note meta">Chance of winning each category in a typical week vs a random league opponent.</div>
      </div>
      <div class="secondary meta">${secondary.label}: ${secondary.fmt(secondary.get(s)[0])} → ${secondary.fmt(secondary.get(s)[1])}
        · power rank ${s.power_rank[0]} → ${s.power_rank[1]} of ${n}</div>
      ${s.auto_before_adds.length ? `<p class="note">Already had an open spot, so the "before" numbers assume they'd add ${list(s.auto_before_adds)} anyway.</p>` : ""}
      ${s.roster_size_after !== s.roster_limit && !$("#tFill").checked ? `<div class="warn">Roster would be ${s.roster_size_after}/${s.roster_limit}. Turn on automatic fill/drop or mark drops with ✕.</div>` : ""}
      <details class="more"><summary>Weekly totals and category ranks</summary>
        <table class="grid"><thead><tr><th class="l">Cat</th><th>Weekly before</th><th>After</th><th>Rank</th></tr></thead><tbody>
        ${r.cats.map((c) => { const x = s.cats[c]; return `<tr><td class="l"><b>${LABEL[c]}</b></td><td>${weekly(c, x.weekly[0])}</td><td>${weekly(c, x.weekly[1])}</td><td>${x.rank[0]} → <b>${x.rank[1]}</b></td></tr>`; }).join("")}
        <tr><td class="l meta">Roster value (${esc($("#system").selectedOptions[0].textContent)})</td><td>${s.value_sum[0].toFixed(1)}</td><td>${s.value_sum[1].toFixed(1)}</td><td></td></tr>
        </tbody></table></details>
    </div>`;
  };
  $("#tResult").innerHTML = `<div class="result-grid">${r.sides.map(side).join("")}</div>
    <details class="more" style="margin-top:14px"><summary>League power rankings after the trade</summary>
    <div class="table-wrap"><table class="grid"><thead><tr><th>Rank</th><th class="l">Team</th><th>Was</th><th>Win chance</th></tr></thead><tbody>
    ${r.league.map((t) => `<tr class="${t.team_id === S.myTeam ? "mine" : ""}"><td><b>${t.rank[1]}</b></td><td class="l">${esc(t.name)}</td>
      <td>${t.rank[0]} ${t.rank[0] !== t.rank[1] ? delta(t.rank[0], t.rank[1], 0, true) : ""}</td>
      <td>${t.allplay[1].toFixed(1)}% ${delta(t.allplay[0], t.allplay[1])}</td></tr>`).join("")}
    </tbody></table></div></details>`;
}

/* ---------- method ---------- */
function renderMethod() {
  $("#methodText").innerHTML = `
  <h2>The two ranking systems</h2>
  <ul>
    <li><b>DURANT H2H (Josh Lloyd)</b>, the default. Each category goes through a Yeo-Johnson transform, which compresses extreme outliers, then is measured against the whole NBA, not just rostered players. Weights: PTS 1.00, REB 0.94, AST 0.75, and 0.60 for FG%, FT%, 3PM, STL and BLK. Turnovers are excluded, and each player's weakest category is dropped (Minus 1). Josh hasn't published every detail, so these parts are educated guesses: FG% and FT% use the standard volume-weighted impact; "the whole NBA" means players with at least 25% of the most games played and 10+ minutes a game; and Minus 1 drops the lowest category after weighting.</li>
    <li><b>Standard 9-cat</b>: z-scores against the top <i>teams × roster</i> players, all nine categories weighted equally. This is what Yahoo, ESPN and Basketball Monster show by default, and it reproduces Basketball Monster's published values.</li>
  </ul>
  <p><b>Minus 1</b> can be toggled on either system. <b>Model settings</b> lets you try other combinations (reference pool, transform, weights, turnover weight); any change makes a "Custom" system.</p>
  <p><b>Eligibility</b> scales with the season. To set the scale or fit the transform, a player needs 25% of the most games anyone has played (2 games in the first week, about 21 by season's end) and 10+ minutes a game. The Min GP filter on the rankings page uses the same 25% rule.</p>
  <p><b>Punting</b> removes a category from player values. Matchup and trade odds still score every category, because your opponents still win them.</p>

  <h2>What the draft simulations say</h2>
  <p>Background study (other systems tested here aren't offered in the app right now). The 2025-26 season was replayed for each system: 1,000 snake drafts of 12 teams × 13 rounds, then every week played from real box scores (all-play, 9-cat H2H). Eleven opponents draft off standard Z with some randomness; one test team uses the system being tested. <i>Perfect info</i> values players on the full season. <i>Real-world</i> values them on Oct–Dec and plays Jan–Apr. Numbers are the test team's matchup win %.</p>
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
  <h2>Team build</h2>
  <p>Your weekly win % in each category comes from the same typical-week model as power rankings. Every realistic punt set (up to 3 in a 9-cat league, since you need to win 5) is tried. For each one, every player is re-valued with your ranking system minus the punted categories, and your roster's total is compared with every other team's, as a z-score across teams. A build's score is that z-score minus a cost per punt: 0.15, plus 1.5 × (your weekly win chance − 35%) when you currently win that category more than 35% of the time. So punting a category you lose most weeks costs little, and punting a strength costs a lot.</p>
  <p>A player "doesn't fit" when his build rank is worse than his normal rank by more than 10 spots or 25% of his rank, whichever is larger. Swap ideas are players with a normal rank within about ±30% of his (a similar trade price) who rank higher in the build.</p>
  <h2>Streaming planner</h2>
  <p>Week total = this week's actual stats so far (from ESPN) + projected remaining games. A remaining game counts only if:</p>
  <ul>
    <li>the player is on your roster that day</li>
    <li>the game hasn't tipped off</li>
    <li>he gets a starting slot. Lineups are filled day by day under your league's position slots, maximizing starts and then player value.</li>
  </ul>
  <p>Injuries: OUT counts as 0 games, and day-to-day or questionable as 0.7 of a game.</p>
  <p>The planner tries every (day, drop, add) combination, with the add day set to one of the free agent's game days, and keeps the best one. It repeats until your adds run out or no move gains at least +0.5 points of win chance (+0.03 expected categories in each-category leagues). Players it streams in can be dropped again later in the week, which produces the "two streamers in one spot" plans. Waiver players are left out because they can't be added today. Your opponent is projected from their current roster, so if they stream too, your real odds are a little lower.</p>
  <h2>Matchup model</h2>
  <p>Weekly projection = per-game stats × games that week. Games come from the NBA schedule, capped at your daily starting slots with the best players starting. Week-to-week randomness uses dispersion estimated from 2025-26 game logs; FG% and FT% are binomial on the week's attempts. Win probabilities come from 4,000 simulated weeks. Matchup and trade odds use the stats directly, so they don't depend on which ranking system you pick.</p>`;
}

init();
