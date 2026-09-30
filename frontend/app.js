/* CYCLOPS frontend. No build step: plain JS + Leaflet + Cytoscape. */
"use strict";

const S = {
  scenario: "expected",
  interventions: [],
  history: [],
  resources: null,
  meta: null,
  sim: null,
  baseSim: null,
  assets: null,
  hazard: null,
  track: null,
  plan: null,
  reach: null,
  offline: false,
  maps: {},
  layers: {},
  cy: null,
};

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const fmt = (n) => (n == null ? "–" : Math.round(n).toLocaleString("en-IN"));
const pct = (p) => (p == null ? "–" : `${Math.round(p * 100)}%`);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const riskColor = (p) => (p >= 0.7 ? "#C1272D" : p >= 0.5 ? "#E0701B" : p >= 0.3 ? "#E8B622" : "#3F8A55");
const riskPill = (p) => (p >= 0.7 ? "red" : p >= 0.5 ? "orange" : p >= 0.3 ? "yellow" : "green");
const TYPE_NAME = { substation: "Substation", telecom: "Telecom", phc: "Health facility", bridge: "Bridge", road: "Road", shelter: "Shelter", pump: "Water pump", village: "Community" };

function toast(msg, ms = 3200) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), ms);
}

/* ---------------- API with retry ---------------- */
async function api(path, opts = {}, tries = 3) {
  let last;
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(path, opts);
      if (r.status >= 500) throw new Error(`Server error ${r.status}`);
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw Object.assign(new Error(body.detail || `Request failed (${r.status})`), { fatal: true });
      return body;
    } catch (e) {
      last = e;
      if (e.fatal) break;
      await new Promise((res) => setTimeout(res, 400 * 2 ** i));
    }
  }
  throw last;
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const simBody = (extra = {}) => ({ scenario: S.scenario, interventions: S.interventions, ...extra });

/* ---------------- navigation ---------------- */
function showPage(name) {
  if (!$(`#page-${name}`)) name = "command";
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${name}`));
  $$(".rail a").forEach((a) => { if (a.dataset.page !== name) a.removeAttribute("aria-current"); else a.setAttribute("aria-current", "page"); });
  const init = { command: renderCommandMap, impact: renderImpact, cascade: renderCascade, action: renderAction, reach: renderReach, verify: renderVerify, evaluation: renderEvaluation, safety: renderSafety }[name];
  if (init) setTimeout(init, 0);
  Object.values(S.maps).forEach((m) => setTimeout(() => m.invalidateSize(), 50));
}
window.addEventListener("hashchange", () => showPage(location.hash.slice(1)));
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) location.hash = g.dataset.goto;
});

/* ---------------- data loading ---------------- */
async function loadScenario() {
  const [hz, tr, as, sim, base] = await Promise.all([
    api(`/api/hazard?scenario=${S.scenario}`),
    api(`/api/cyclones?scenario=${S.scenario}`),
    api(`/api/assets?scenario=${S.scenario}`),
    post("/api/simulate", simBody()),
    post("/api/simulate", { scenario: S.scenario, interventions: [] }),
  ]);
  S.hazard = hz; S.track = tr; S.assets = as; S.sim = sim; S.baseSim = base;
  renderBand();
  renderFigures();
  updatePlanStatus();
}

async function refreshSim() {
  S.sim = await post("/api/simulate", simBody());
  S.assets = await api(`/api/assets?scenario=${S.scenario}`);
  S.baseSim = await post("/api/simulate", { scenario: S.scenario, interventions: [] });
  renderFigures();
  updatePlanStatus();
}

function currentPage() { return (location.hash || "#command").slice(1); }
function rerenderCurrent() { showPage(currentPage()); }

/* ---------------- band + figures ---------------- */
function renderBand() {
  const m = S.baseSim.metrics;
  const share = m.expected_degraded_pop / m.total_pop;
  const level = share >= 0.45 || m.phcs_severe_risk >= 2 ? "RED" : share >= 0.2 ? "ORANGE" : "YELLOW";
  $("#band").dataset.level = level;
  document.querySelector('meta[name="theme-color"]').content = { RED: "#C1272D", ORANGE: "#E0701B", YELLOW: "#E8B622" }[level];
  const e = S.meta.event;
  const peak = Math.max(...S.track.track.map((p) => p.vmax_kmh));
  $("#bandEvent").innerHTML = `${esc(e.name)}, ${esc(e.district)}<span>Landfall ${esc(e.landfall_label)}. Peak wind in this scenario ${fmt(peak)} km/h. ${level === "RED" ? "Red" : level === "ORANGE" ? "Orange" : "Yellow"} threat level from simulated impact.</span>`;
  $$(".scenario-switch button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.scenario === S.scenario)));
}

function figure(v, l, delta) {
  return `<div class="figure"><div class="v">${v}${delta ? `<span class="delta">${delta}</span>` : ""}</div><div class="l">${l}</div></div>`;
}

function renderFigures() {
  const m = S.sim.metrics, b = S.baseSim.metrics;
  const d = (a, c) => (S.interventions.length && c - a > 0 ? `−${fmt(c - a)}` : "");
  $("#cmdFigures").innerHTML =
    figure(m.critical_assets_disrupted, "critical assets likely disrupted", d(m.critical_assets_disrupted, b.critical_assets_disrupted)) +
    figure(fmt(m.expected_degraded_pop), "residents with degraded access to care or shelter (expected)", d(m.expected_degraded_pop, b.expected_degraded_pop)) +
    figure(S.reach ? S.reach.summary["POSSIBLE BLIND SPOT"] : "–", "possible coverage gaps to verify") +
    figure(S.plan ? S.plan.plan.slice(0, 3).length : "–", "high-priority actions ready");
  $("#cmdHeadline").textContent = `${S.meta.event.name}: ${S.meta.scenarios[S.scenario]} scenario`;
}

function updatePlanStatus() {
  $("#planStatus").textContent = S.interventions.length ? `${S.interventions.length} action${S.interventions.length > 1 ? "s" : ""} applied. Resilience ${S.sim.metrics.resilience_score} of 100.` : `No actions applied. Resilience ${S.sim.metrics.resilience_score} of 100.`;
}

/* ---------------- maps ---------------- */
function makeMap(id) {
  if (S.maps[id]) return S.maps[id];
  const map = L.map(id, { preferCanvas: true, zoomSnap: 0.25 }).setView([19.93, 85.98], 11);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap contributors &copy; CARTO", subdomains: "abcd", maxZoom: 18,
  }).addTo(map);
  S.maps[id] = map;
  S.layers[id] = {};
  // coastline drawn from API data so the map stays legible offline, without basemap tiles
  L.polyline(S.meta.coast, { color: "#235E78", weight: 3, opacity: 0.9, interactive: false }).addTo(map);
  const pts = S.sim.nodes.map((n) => [n.lat, n.lon]);
  map.fitBounds(L.latLngBounds(pts).pad(0.08));
  return map;
}

function setLayer(mapId, key, layer, visible = true) {
  const map = S.maps[mapId];
  const L_ = S.layers[mapId];
  if (L_[key]) map.removeLayer(L_[key]);
  L_[key] = layer;
  if (visible) layer.addTo(map);
}

function hazardLayer(field, color) {
  const step = S.hazard.step / 2;
  const g = L.layerGroup();
  for (const c of S.hazard.cells) {
    const v = c[field];
    if (v < 0.08) continue;
    L.rectangle([[c.lat - step, c.lon - step], [c.lat + step, c.lon + step]], {
      stroke: false, fillColor: color, fillOpacity: Math.min(0.62, v * 0.7), interactive: false,
    }).addTo(g);
  }
  return g;
}

function trackLayer() {
  const pts = S.track.track.map((p) => [p.lat, p.lon]);
  const g = L.layerGroup();
  L.polyline(pts, { color: "#15222D", weight: 2.5, dashArray: "6 5" }).addTo(g);
  S.track.track.filter((p) => p.hour % 6 === 0).forEach((p) => {
    L.circleMarker([p.lat, p.lon], { radius: 5, color: "#15222D", weight: 2, fillColor: "#fff", fillOpacity: 1 })
      .bindTooltip(`${p.hour >= 0 ? "+" : ""}${p.hour} h: ${p.vmax_kmh} km/h`).addTo(g);
  });
  return g;
}

function assetLayer(types, onClick) {
  const g = L.layerGroup();
  for (const n of S.sim.nodes.filter((n) => n.kind === "asset" && (!types || types.includes(n.type)))) {
    const icon = L.divIcon({
      className: "",
      html: `<div class="asset-chip ${n.active === false ? "inactive" : ""}" style="background:${riskColor(n.p)}">${esc(n.id)}</div>`,
      iconSize: null,
    });
    L.marker([n.lat, n.lon], { icon, keyboard: true, title: `${n.name}: ${pct(n.p)}` })
      .on("click", () => onClick && onClick(n.id)).addTo(g);
  }
  return g;
}

function villageLayer(colorFn, tip) {
  const g = L.layerGroup();
  for (const n of S.sim.nodes.filter((n) => n.kind === "village")) {
    L.circleMarker([n.lat, n.lon], { radius: 5 + Math.sqrt(n.pop) / 12, color: "#15222D", weight: 1, fillColor: colorFn(n), fillOpacity: 0.55 })
      .bindTooltip(tip(n)).addTo(g);
  }
  return g;
}

function renderCommandMap() {
  const id = "mapCommand";
  makeMap(id);
  setLayer(id, "inund", hazardLayer("inundation_risk", "#235E78"));
  setLayer(id, "track", trackLayer());
  setLayer(id, "vill", villageLayer((n) => riskColor(n.p), (n) => `${n.name}: ${fmt(n.pop)} residents, ${pct(n.p)} degraded-access probability`));
  setLayer(id, "assets", assetLayer(null, openEvidence));
  S.maps[id].invalidateSize();
}

/* ---------------- command: next best actions ---------------- */
async function loadPlan() {
  try {
    S.plan = await post("/api/optimize", { scenario: S.scenario, resources: S.resources, interventions: [] });
    const top = S.plan.plan.slice(0, 4);
    $("#nbaNote").textContent = `${S.plan.algorithm}. Top ${top.length} of ${S.plan.plan.length} actions using the default resources.`;
    $("#nbaList").innerHTML = top.map((s) => `<li><span class="t">${esc(s.label)}</span><span class="gain">${fmt(s.people_protected)} fewer residents with degraded access</span><span class="why">${esc(s.why)}</span></li>`).join("");
    $("#btnApplyPlan").disabled = !S.plan.plan.length;
    renderFigures();
  } catch (e) {
    $("#nbaNote").textContent = `Could not compute the plan: ${e.message}. Retry by switching scenario.`;
  }
}

/* ---------------- impact ---------------- */
const LAYERS = [
  { key: "combined", label: "Combined hazard", on: false, make: () => hazardLayer("combined_hazard", "#C1272D") },
  { key: "wind", label: "Wind hazard", on: false, make: () => hazardLayer("wind_risk", "#E0701B") },
  { key: "inund", label: "Inundation exposure", on: true, make: () => hazardLayer("inundation_risk", "#235E78") },
  { key: "rain", label: "Rainfall", on: false, make: () => hazardLayer("rain_risk", "#5B6CB0") },
  { key: "track", label: "Cyclone track", on: true, make: trackLayer },
  { key: "pop", label: "Communities", on: true, make: () => villageLayer((n) => riskColor(n.p), (n) => `${n.name}: ${fmt(n.pop)} residents`) },
  { key: "phc", label: "Health facilities", on: true, make: () => assetLayer(["phc"], openEvidence) },
  { key: "power", label: "Power and water", on: true, make: () => assetLayer(["substation", "pump"], openEvidence) },
  { key: "tel", label: "Telecom", on: true, make: () => assetLayer(["telecom"], openEvidence) },
  { key: "roads", label: "Roads and bridges", on: true, make: () => assetLayer(["road", "bridge"], openEvidence) },
  { key: "shel", label: "Shelters", on: true, make: () => assetLayer(["shelter"], openEvidence) },
  { key: "reports", label: "Field reports", on: true, make: reportsLayer },
  { key: "gaps", label: "Possible coverage gaps", on: true, make: gapsLayer },
];

function reportsLayer() {
  const g = L.layerGroup();
  (S.reports || []).forEach((r) => {
    L.circleMarker([r.lat, r.lon], { radius: 7, color: "#15222D", weight: 2, fillColor: "#fff", fillOpacity: 1 })
      .bindTooltip(`${r.id}: ${r.extraction ? r.extraction.incident_type : "needs review"} (${r.status})`).addTo(g);
  });
  return g;
}
function gapsLayer() {
  const g = L.layerGroup();
  (S.reach ? S.reach.villages : []).filter((v) => v.status === "POSSIBLE BLIND SPOT").forEach((v) => {
    L.circle([v.lat, v.lon], { radius: 1400, color: "#C1272D", weight: 2, dashArray: "5 4", fill: false })
      .bindTooltip(`Possible blind spot: ${v.name}`).addTo(g);
  });
  return g;
}

function renderImpact() {
  const id = "mapImpact";
  makeMap(id);
  const list = $("#layerList");
  if (!list.dataset.ready) {
    list.innerHTML = LAYERS.map((l) => `<label><input type="checkbox" data-layer="${l.key}" ${l.on ? "checked" : ""}> ${esc(l.label)}</label>`).join("");
    list.addEventListener("change", (e) => {
      const l = LAYERS.find((x) => x.key === e.target.dataset.layer);
      l.on = e.target.checked;
      const layer = S.layers[id][l.key];
      if (layer) l.on ? layer.addTo(S.maps[id]) : S.maps[id].removeLayer(layer);
    });
    list.dataset.ready = "1";
  }
  LAYERS.forEach((l) => setLayer(id, l.key, l.make(), l.on));
  const rows = [...S.assets.assets].filter((a) => !a.inactive).sort((a, b) => b.risk_after_dependencies - a.risk_after_dependencies);
  $("#assetRows").innerHTML = rows.map((a) => `<tr class="clickable" data-asset="${a.id}" tabindex="0"><td><b>${esc(a.id)}</b> <span class="muted">${esc(TYPE_NAME[a.type])}</span></td><td class="r">${pct(a.direct_risk)}</td><td class="r"><span class="pill ${riskPill(a.risk_after_dependencies)}">${pct(a.risk_after_dependencies)}</span></td><td class="r">${fmt(a.population_served)}</td></tr>`).join("");
  S.maps[id].invalidateSize();
}
document.addEventListener("click", (e) => { const r = e.target.closest("tr[data-asset]"); if (r) openEvidence(r.dataset.asset); });
document.addEventListener("keydown", (e) => { const r = e.target.closest && e.target.closest("tr[data-asset]"); if (r && e.key === "Enter") openEvidence(r.dataset.asset); });

/* ---------------- evidence drawer ---------------- */
function rangeBar(lo, mid, hi) {
  return `<div class="range" aria-label="Low ${pct(lo)}, expected ${pct(mid)}, high ${pct(hi)}"><div class="track"></div><div class="span" style="left:${lo * 100}%;width:${Math.max(0.5, (hi - lo) * 100)}%"></div><div class="mark" style="left:calc(${mid * 100}% - 1px)"></div></div><div class="small muted">Low scenario ${pct(lo)}, expected ${pct(mid)}, high scenario ${pct(hi)}</div>`;
}

function openEvidence(assetId) {
  const a = S.assets.assets.find((x) => x.id === assetId);
  if (!a) return;
  const meta = S.assets.meta;
  const ups = a.upstream.filter((u) => u.carried_risk > 0.01);
  $("#drawerBody").innerHTML = `
    <h2>${esc(a.name)}</h2>
    <p class="muted">${esc(TYPE_NAME[a.type])}${a.elevated ? ", elevated structure" : ""}${a.inactive ? ", not yet activated" : ""}</p>
    <div class="figures" style="grid-template-columns:1fr 1fr">
      ${figure(pct(a.direct_risk), "direct disruption risk")}
      ${figure(pct(a.risk_after_dependencies), "with upstream dependencies")}
    </div>
    <h3>Why this risk</h3>
    <p class="small muted">Actual shares of the exposure term E = ${a.exposure}. Capacity threshold ${a.capacity_threshold} from vulnerability ${a.vulnerability}.</p>
    ${a.contributions.map((c) => `<div class="contrib"><span>${esc(c.factor)}</span><span class="num">${Math.round(c.share * 100)}%</span><div class="bar"><i style="width:${c.share * 100}%"></i></div></div>`).join("")}
    <h3 style="margin-top:14px">Uncertainty</h3>${rangeBar(a.risk_low, a.direct_risk, a.risk_high)}
    <dl class="kv">
      <dt>Wind at site</dt><dd>${fmt(a.physical.wind_kmh)} km/h (proxy)</dd>
      <dt>Rain accumulation</dt><dd>${fmt(a.physical.rain_mm)} mm (proxy)</dd>
      <dt>Surge depth proxy</dt><dd>${a.physical.surge_depth_m} m</dd>
      <dt>Elevation + plinth</dt><dd>${a.physical.elevation_m} m (synthetic DEM)</dd>
      <dt>Distance to coast</dt><dd>${a.physical.coast_km} km</dd>
      <dt>People served</dt><dd>${fmt(a.population_served)} (${esc(a.villages_served.join(", ") || "none")})</dd>
      <dt>Confidence</dt><dd>${a.confidence}</dd>
      <dt>Field evidence</dt><dd>${a.field_evidence ? `report raises floor to ${pct(a.field_evidence)}` : "none"}</dd>
      <dt>Model</dt><dd>${esc(meta.model_versions.asset)}, ${esc(meta.model_versions.hazard)}</dd>
      <dt>Input version</dt><dd>${esc(meta.input_version)}</dd>
      <dt>Computed</dt><dd>${new Date(meta.timestamp * 1000).toLocaleString()}</dd>
    </dl>
    <h3>Depends on</h3>
    ${ups.length ? `<table><thead><tr><th>Upstream</th><th>Type</th><th class="r">Carried</th></tr></thead><tbody>${ups.map((u) => `<tr><td>${esc(u.from)} (${pct(u.upstream_risk)})</td><td>${esc(u.dependency_type)}${u.backup ? `, backup ${pct(u.backup)}` : ""}</td><td class="r">${pct(u.carried_risk)}</td></tr>`).join("")}</tbody></table>` : `<p class="small muted">No upstream dependency carries meaningful risk.</p>`}
    <h3 style="margin-top:14px">Feeds</h3><p class="small">${esc(a.downstream.join(", ") || "Nothing downstream")}</p>
    <div class="btn-row" style="margin-top:12px"><button class="btn secondary" data-goto="cascade" data-seed="${a.id}">Show its cascade</button></div>`;
  $("#drawer").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#drawerClose").focus();
}
$("#drawerClose").addEventListener("click", () => { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#drawerClose").click(); });
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-seed]");
  if (b) { $("#drawerClose").click(); setTimeout(() => { $("#cascadeSeed").value = b.dataset.seed; animateCascade(); }, 300); }
});

/* ---------------- cascade ---------------- */
function colOf(n) {
  if (n.kind === "village") return 4;
  if (n.id === "GS1") return 0;
  if (n.type === "substation") return 1;
  if (n.type === "telecom" || n.type === "pump") return 2;
  return 3;
}

function renderCascade() {
  const nodes = S.sim.nodes;
  const cols = [[], [], [], [], []];
  nodes.forEach((n) => cols[colOf(n)].push(n));
  const order = { phc: 0, bridge: 1, road: 2, shelter: 3, telecom: 0, pump: 1 };
  cols.forEach((c) => c.sort((a, b) => (order[a.type] ?? 0) - (order[b.type] ?? 0) || a.id.localeCompare(b.id, undefined, { numeric: true })));
  const W = 1000, H = 760;
  const els = [];
  cols.forEach((c, ci) => c.forEach((n, i) => {
    els.push({ data: { id: n.id, label: n.id === "VK" ? "Village K" : n.id, p: n.p, kind: n.kind, type: n.type }, position: { x: 60 + ci * (W - 120) / 4, y: 30 + (i + 0.5) * ((H - 60) / c.length) } });
  }));
  S.sim.edges.forEach((e, i) => els.push({ data: { id: `e${i}`, source: e.source, target: e.target, t: e.dependency_type } }));
  if (S.cy) S.cy.destroy();
  S.cy = cytoscape({
    container: $("#cy"), elements: els, layout: { name: "preset" }, wheelSensitivity: 0.2, autoungrabify: true,
    style: [
      { selector: "node", style: { "background-color": "#fff", "border-width": 2, "border-color": "#9AA8B1", label: "data(label)", "font-family": "Barlow Condensed, sans-serif", "font-size": 15, "font-weight": 600, color: "#15222D", "text-valign": "center", "text-halign": "center", width: 64, height: 26, shape: "round-rectangle", "transition-property": "background-color, border-color, color", "transition-duration": "0.35s" } },
      { selector: "node[kind='village']", style: { shape: "ellipse", width: 70 } },
      { selector: "node.hit", style: { "background-color": "data(color)", "border-color": "#15222D", color: "#fff" } },
      { selector: "node.dim", style: { opacity: 0.35 } },
      { selector: "node.sel", style: { "border-width": 4, "border-color": "#1B6FD1" } },
      { selector: "edge", style: { width: 1, "line-color": "#C7D1D6", "curve-style": "bezier", "target-arrow-shape": "triangle", "target-arrow-color": "#C7D1D6", "arrow-scale": 0.8, "transition-property": "line-color, width", "transition-duration": "0.35s" } },
      { selector: "edge.hot", style: { width: 3.5, "line-color": "#C1272D", "target-arrow-color": "#C1272D", "z-index": 10 } },
      { selector: "edge.dim", style: { opacity: 0.25 } },
    ],
  });
  S.cy.on("tap", "node", (ev) => nodeDetail(ev.target.id()));
  const seeds = S.sim.cascade.seeds;
  const sel = $("#cascadeSeed");
  const prev = sel.value;
  sel.innerHTML = `<option value="__all">All at-risk assets</option>` + seeds.map((s) => `<option value="${s}">${s} (${pct(S.sim.nodes.find((n) => n.id === s).direct)})</option>`).join("");
  sel.value = seeds.includes(prev) || prev === "__all" ? prev : seeds.includes("P04") ? "P04" : "__all";
  $("#ciDirect").textContent = S.sim.cascade.direct_impact_count;
  $("#ciCascade").textContent = S.sim.cascade.downstream_count + S.sim.cascade.villages_reached;
  $("#ciHuman").textContent = fmt(S.sim.cascade.human_impact_expected);
}

function cascadeFrom(seed) {
  const edges = S.sim.cascade.edges;
  if (seed === "__all") return { levels: S.sim.cascade.levels.map((l) => l.nodes), edges };
  const level = { [seed]: 0 }; const q = [seed]; const used = [];
  while (q.length) {
    const u = q.shift();
    edges.filter((e) => e.source === u).forEach((e) => {
      used.push({ ...e, level: level[u] + 1 });
      if (!(e.target in level)) { level[e.target] = level[u] + 1; q.push(e.target); }
    });
  }
  const levels = [];
  Object.entries(level).forEach(([n, l]) => { (levels[l] = levels[l] || []).push(n); });
  return { levels, edges: used };
}

async function animateCascade() {
  if (!S.cy) renderCascade();
  const seed = $("#cascadeSeed").value;
  const { levels, edges } = cascadeFrom(seed);
  const cy = S.cy;
  cy.elements().removeClass("hit hot dim sel");
  const involved = new Set(levels.flat());
  cy.nodes().forEach((n) => { if (!involved.has(n.id())) n.addClass("dim"); });
  cy.edges().addClass("dim");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pOf = (id) => S.sim.nodes.find((n) => n.id === id).p;
  for (let l = 0; l < levels.length; l++) {
    if (l > 0) edges.filter((e) => e.level === l).forEach((e) => {
      const ed = cy.edges(`[source = "${e.source}"][target = "${e.target}"]`);
      ed.removeClass("dim").addClass("hot");
    });
    (levels[l] || []).forEach((id) => { const n = cy.getElementById(id); n.data("color", riskColor(pOf(id))); n.addClass("hit"); });
    if (!reduce) await new Promise((r) => setTimeout(r, 650));
  }
  const vill = S.sim.nodes.filter((n) => n.kind === "village" && involved.has(n.id));
  const human = vill.reduce((s, n) => s + n.village.expected_degraded_pop, 0);
  const names = (arr) => arr.map((id) => (id === "VK" ? "Village K" : id)).join(", ");
  $("#chainTitle").textContent = seed === "__all" ? "Cascade from all at-risk assets" : `Cascade from ${seed}`;
  $("#chainText").innerHTML = levels.map((ns, i) => `<div>${i === 0 ? "" : "↓ "}${esc(names(ns))}</div>`).join("") +
    `<p class="small muted" style="margin-top:8px">${vill.length} communities downstream, ${fmt(vill.reduce((s, n) => s + n.pop, 0))} residents, ${fmt(human)} expected to have degraded access. Probabilities, not certainties.</p>`;
}
$("#btnCascade").addEventListener("click", animateCascade);
$("#btnCascadeReset").addEventListener("click", () => { if (S.cy) S.cy.elements().removeClass("hit hot dim sel"); $("#chainText").textContent = "Press Show cascade."; });

function nodeDetail(id) {
  S.cy.nodes().removeClass("sel");
  S.cy.getElementById(id).addClass("sel");
  const n = S.sim.nodes.find((x) => x.id === id);
  const ins = S.sim.edges.filter((e) => e.target === id);
  if (n.kind === "village") {
    const v = n.village;
    $("#nodeDetail").innerHTML = `<b class="num" style="font-size:20px">${esc(n.name)}</b>, ${fmt(n.pop)} residents<dl class="kv"><dt>Degraded access</dt><dd>${pct(v.p_degraded)}</dd><dt>Health access loss</dt><dd>${pct(v.p_health_loss)} via ${esc(v.phc)} ${v.health_route.length ? "over " + esc(v.health_route.join(" + ")) : ""}</dd><dt>Shelter route loss</dt><dd>${pct(v.p_shelter_loss)} to ${esc(v.shelter)} ${v.shelter_route.length ? "over " + esc(v.shelter_route.join(" + ")) : ""}</dd><dt>Power loss</dt><dd>${pct(v.p_power_loss)} (${esc(v.power)})</dd><dt>Comms loss</dt><dd>${pct(v.p_comms_loss)} (${esc(v.comms)})</dd></dl>`;
  } else {
    $("#nodeDetail").innerHTML = `<b class="num" style="font-size:20px">${esc(n.name)}</b><dl class="kv"><dt>Direct risk</dt><dd>${pct(n.direct)}</dd><dt>With dependencies</dt><dd>${pct(n.p)}</dd><dt>Depends on</dt><dd>${esc(ins.map((e) => `${e.source} (${e.dependency_type}${e.backup ? ", backup " + pct(e.backup) : ""})`).join(", ") || "nothing modelled")}</dd><dt>People downstream</dt><dd>${fmt(n.population_served)}</dd></dl><button class="btn quiet" onclick="openEvidence('${n.id}')">Open evidence</button>`;
  }
}

/* ---------------- action lab ---------------- */
let CANDS = null;
const RES_LABEL = { generators: "Backup generators", ambulances: "Ambulances", rescue_teams: "Rescue teams", telecom_units: "Portable telecom units" };
const GROUPS = [
  ["generator", "Deploy generator"], ["relocate_generator", "Move an existing generator"], ["portable_telecom", "Portable telecom"],
  ["ambulance", "Pre-position ambulance"], ["reroute", "Reroute evacuation"], ["activate_shelter", "Open secondary shelter"], ["rescue_team", "Assisted evacuation"],
];
const keyOf = (i) => JSON.stringify([i.type, i.target, i.village, i.source, i.option, i.activate || null]);
const strip = (c) => { const o = {}; ["type", "target", "village", "source", "option", "activate"].forEach((k) => { if (c[k] != null) o[k] = c[k]; }); return o; };

function used() {
  const u = { generators: 0, ambulances: 0, rescue_teams: 0, telecom_units: 0 };
  const R = { generator: "generators", ambulance: "ambulances", rescue_team: "rescue_teams", portable_telecom: "telecom_units" };
  S.interventions.forEach((i) => { if (R[i.type]) u[R[i.type]]++; });
  return u;
}

async function renderAction() {
  if (!CANDS) CANDS = (await api("/api/interventions/candidates")).candidates;
  const u = used();
  $("#resourceInputs").innerHTML = Object.keys(RES_LABEL).map((k) => `<div class="res-row"><label for="res-${k}">${RES_LABEL[k]} <span class="muted small">(${u[k]} in use)</span></label><input id="res-${k}" type="number" min="0" max="20" value="${S.resources[k]}" data-res="${k}"></div>`).join("");
  const applied = new Set(S.interventions.map(keyOf));
  const R = { generator: "generators", ambulance: "ambulances", rescue_team: "rescue_teams", portable_telecom: "telecom_units" };
  $("#candidateList").innerHTML = GROUPS.map(([t, name]) => {
    const items = CANDS.filter((c) => c.type === t && (t !== "rescue_team" || (S.sim.nodes.find((n) => n.id === c.target)?.village?.p_shelter_loss ?? 0) >= 0.3));
    if (!items.length) return "";
    return `<div class="cand-group"><h4>${name}</h4>${items.map((c) => {
      const k = keyOf(strip(c)); const on = applied.has(k);
      const out = R[c.type] && !on && u[R[c.type]] >= S.resources[R[c.type]];
      return `<div class="cand ${on ? "on" : ""}"><span>${esc(c.label)}</span><button class="btn ${on ? "secondary" : "quiet"}" data-cand='${esc(JSON.stringify(strip(c)))}' ${out ? "disabled title='No resource left'" : ""}>${on ? "Remove" : "Apply"}</button></div>`;
    }).join("")}</div>`;
  }).join("");
  $("#appliedList").innerHTML = S.interventions.length ? (S.sim.intervention_labels || []).map((l) => `<li>${esc(l)}</li>`).join("") : `<li class="muted">None yet.</li>`;
  renderCompare();
}

function renderCompare(flash = false) {
  const b = S.baseSim.metrics, m = S.sim.metrics;
  const rows = [
    ["Residents with degraded access", b.expected_degraded_pop, m.expected_degraded_pop, fmt],
    ["Without robust shelter route", b.expected_without_shelter_route, m.expected_without_shelter_route, fmt],
    ["Losing health access", b.expected_health_access_loss, m.expected_health_access_loss, fmt],
    ["Critical assets disrupted", b.critical_assets_disrupted, m.critical_assets_disrupted, (x) => x],
    ["PHCs at severe risk", b.phcs_severe_risk, m.phcs_severe_risk, (x) => x],
    ["Resilience score", b.resilience_score, m.resilience_score, (x) => x, true],
  ];
  $("#compareRows").innerHTML = `<tr><th></th><th class="r">Without</th><th></th><th class="r">With</th></tr>` + rows.map(([l, a, c, f, up]) => {
    const better = up ? c > a : c < a;
    return `<tr class="${flash && a !== c ? "flash" : ""}"><td>${l}</td><td class="r num" style="font-size:18px">${f(a)}</td><td class="arrow">→</td><td class="r num ${better ? "better" : ""}" style="font-size:18px">${f(c)}</td></tr>`;
  }).join("") + `<tr><td colspan="4" class="small muted">${esc(m.resilience_formula)}</td></tr>`;
}

async function setInterventions(list, note) {
  S.history.push(S.interventions);
  S.interventions = list;
  try {
    await refreshSim();
    renderCompare(true);
    if (currentPage() === "action") renderAction();
    if (note) toast(note);
  } catch (e) {
    S.interventions = S.history.pop();
    toast(`Could not apply: ${e.message}`);
  }
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-cand]");
  if (!b) return;
  const c = JSON.parse(b.dataset.cand);
  const k = keyOf(c);
  const exists = S.interventions.some((i) => keyOf(i) === k);
  let next = exists ? S.interventions.filter((i) => keyOf(i) !== k) : [...S.interventions.filter((i) => !(c.type === "reroute" && i.type === "reroute" && i.village === c.village)), c];
  setInterventions(next);
});
document.addEventListener("change", (e) => {
  if (e.target.dataset.res) { S.resources[e.target.dataset.res] = Math.max(0, parseInt(e.target.value || "0", 10)); renderAction(); }
});
$("#btnUndo").addEventListener("click", async () => {
  if (!S.history.length) return toast("Nothing to undo.");
  S.interventions = S.history.pop();
  await refreshSim(); renderAction(); renderCompare(true);
});
$("#btnReset").addEventListener("click", () => setInterventions([], "All actions removed."));
$("#btnOptimize").addEventListener("click", async () => {
  $("#btnOptimize").disabled = true;
  try {
    const out = await post("/api/optimize", { scenario: S.scenario, resources: S.resources, interventions: S.interventions });
    $("#planPanel").hidden = false;
    $("#planAlgo").textContent = `${out.algorithm}. Starts from the actions already applied.`;
    $("#planList").innerHTML = out.plan.length ? out.plan.map((s) => `<li><span class="t">${esc(s.label)}</span><span class="gain">${fmt(s.people_protected)} fewer residents with degraded access</span><span class="why">Why: ${esc(s.why)}</span></li>`).join("") : `<li><span class="t">No further action improves the objective with these resources.</span></li>`;
    await setInterventions(out.interventions, `Plan applied: ${out.plan.length} action${out.plan.length === 1 ? "" : "s"} added.`);
  } catch (e) { toast(`Optimizer failed: ${e.message}`); }
  $("#btnOptimize").disabled = false;
});
$("#btnStress").addEventListener("click", async () => {
  const r = await post("/api/stress-test", {});
  $("#stressPanel").hidden = false;
  $("#stressBody").innerHTML = `<p class="small">${esc(r.description)}</p><table class="compare"><tr><td>Residents with degraded access</td><td class="r num">${fmt(r.metrics.expected_degraded_pop)}</td><td class="arrow">→</td><td class="r num better">${fmt(r.after.expected_degraded_pop)}</td></tr><tr><td>Critical assets disrupted</td><td class="r num">${r.metrics.critical_assets_disrupted}</td><td class="arrow">→</td><td class="r num">${r.after.critical_assets_disrupted}</td></tr></table><p class="small" style="margin-top:6px">${r.system_still_produced_plan ? `System still produced a ${r.plan.length}-step plan. First: ${esc(r.plan[0].label)}.` : "No feasible plan with current resources."}</p>`;
});
$("#btnApplyPlan").addEventListener("click", async () => {
  if (!S.plan) return;
  await setInterventions(S.plan.interventions, "Recommended plan applied.");
  location.hash = "action";
});

/* ---------------- reach + reports ---------------- */
const SAMPLES = [
  { text: "Electric pole fallen across the road near the substation, wires on the ground, road blocked", lang: "en", near: "P04" },
  { text: "गाँव में बाढ़ का पानी घरों में घुस गया है, सड़क पर पानी भरा है", lang: "hi", near: "V12" },
  { text: "ରାସ୍ତା ଉପରେ ଗଛ ପଡିଛି, ରାସ୍ତା ବନ୍ଦ", lang: "or", near: "R21" },
];

async function loadReach() {
  S.reach = await post("/api/reach-gap", simBody());
  const rep = await api("/api/reports");
  S.reports = rep.reports;
}

async function renderReach() {
  await loadReach();
  const id = "mapReach";
  makeMap(id);
  const col = { "POSSIBLE BLIND SPOT": "#C1272D", UNVERIFIED: "#E0701B", "PARTIALLY OBSERVED": "#E8B622", REACHED: "#3F8A55" };
  const g = L.layerGroup();
  S.reach.villages.forEach((v) => L.circleMarker([v.lat, v.lon], { radius: 7 + Math.sqrt(v.pop) / 10, color: "#15222D", weight: 1.5, fillColor: col[v.status], fillOpacity: 0.7 }).bindTooltip(`${v.name}: ${v.status.toLowerCase()}`).addTo(g));
  setLayer(id, "reach", g);
  setLayer(id, "reports", reportsLayer());
  S.maps[id].invalidateSize();
  $("#reachLabel").textContent = S.reach.data_label;
  $("#reachCaveat").textContent = S.reach.caveat;
  const pill = { "POSSIBLE BLIND SPOT": "red", UNVERIFIED: "orange", "PARTIALLY OBSERVED": "yellow", REACHED: "green" };
  const label = { "POSSIBLE BLIND SPOT": "Possible blind spot", UNVERIFIED: "Unverified", "PARTIALLY OBSERVED": "Partially observed", REACHED: "Reached" };
  $("#reachRows").innerHTML = S.reach.villages.map((v) => `<tr><td><b>${esc(v.name)}</b><div class="small muted">${esc(v.recommendation)}</div></td><td><span class="pill ${pill[v.status]}">${label[v.status]}</span></td><td class="r">~${fmt(v.predicted_affected)}</td><td class="r">${fmt(v.observed)}</td><td class="r">${fmt(v.reports)}</td><td class="small" style="min-width:230px">${v.status === "REACHED" ? "" : esc(v.reason)}</td></tr>`).join("");
  const near = $("#rNear");
  if (!near.options.length) {
    const opts = [...S.sim.nodes.filter((n) => n.kind === "village"), ...S.sim.nodes.filter((n) => n.kind === "asset")];
    near.innerHTML = opts.map((n) => `<option value="${n.id}">${esc(n.id === "VK" ? "Village K" : n.id)}: ${esc(TYPE_NAME[n.type])}</option>`).join("");
    near.addEventListener("change", setNear);
    near.value = "V14"; setNear();
    $("#alertVillage").innerHTML = S.sim.nodes.filter((n) => n.kind === "village").map((n) => `<option value="${n.id}">${esc(n.name)}</option>`).join("");
    $("#alertVillage").value = "V14";
  }
  renderReports();
  renderQueue();
}

function setNear() {
  const n = S.sim.nodes.find((x) => x.id === $("#rNear").value);
  $("#rLat").value = (n.lat + 0.004).toFixed(4);
  $("#rLon").value = (n.lon + 0.004).toFixed(4);
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-sample]");
  if (!b) return;
  const s = SAMPLES[+b.dataset.sample];
  $("#rText").value = s.text; $("#rLang").value = s.lang; $("#rNear").value = s.near; setNear();
});

function renderReports() {
  const list = S.reports || [];
  if (!list.length) { $("#reportList").innerHTML = "No reports yet. Send one with the form above."; return; }
  const st = { PENDING_REVIEW: ["yellow", "Pending review"], APPROVED: ["green", "Approved"], REJECTED: ["grey", "Rejected"], NEEDS_REVIEW_INVALID_AI_OUTPUT: ["red", "Invalid AI output, manual review"] };
  $("#reportList").innerHTML = list.map((r) => `<div class="report">
    <div><b>${esc(r.id)}</b> <span class="pill ${st[r.status][0]}">${st[r.status][1]}</span> ${r.duplicate_of ? `<span class="pill grey">Near-duplicate of ${esc(r.duplicate_of)}</span>` : ""}</div>
    <div class="muted">${esc(r.text || "(photo only)")}</div>
    <div>Linked asset: <b>${esc(r.linked_asset ? `${r.linked_asset.id} (${r.linked_asset.distance_km} km)` : "none")}</b>. Community: ${esc(r.linked_village || "none")}. Extractor: ${esc(r.extraction_meta.model)}. Validation: ${esc(r.extraction_meta.validation || r.extraction_meta.error)}</div>
    ${r.extraction ? `<pre>${esc(JSON.stringify(r.extraction, null, 2))}</pre>` : ""}
    ${r.status === "PENDING_REVIEW" || r.status === "NEEDS_REVIEW_INVALID_AI_OUTPUT" ? `<div class="btn-row"><button class="btn" data-review="${r.id}" data-d="approve" ${r.extraction ? "" : "disabled"}>Approve as verified</button><button class="btn secondary" data-review="${r.id}" data-d="reject">Reject</button></div>` : ""}
  </div>`).join("");
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-review]");
  if (!b) return;
  try {
    await post(`/api/reports/${b.dataset.review}/review`, { decision: b.dataset.d });
    const beforeP = Object.fromEntries(S.sim.nodes.map((n) => [n.id, n.p]));
    await refreshSim();
    await loadReach();
    const changed = S.sim.nodes.filter((n) => n.p - (beforeP[n.id] ?? 0) >= 0.03).map((n) => `${n.id === "VK" ? "Village K" : n.id} ${pct(beforeP[n.id])}→${pct(n.p)}`);
    renderReach();
    toast(b.dataset.d === "approve" ? (changed.length ? `Digital twin updated: ${changed.slice(0, 4).join(", ")}` : "Approved. Evidence did not raise any risk above the model estimate.") : "Report rejected. It no longer affects the twin.", 5000);
  } catch (err) { toast(err.message); }
});

/* offline queue */
const QKEY = "cyclops-report-queue";
const getQ = () => { try { return JSON.parse(localStorage.getItem(QKEY) || "[]"); } catch { return []; } };
const setQ = (q) => { try { localStorage.setItem(QKEY, JSON.stringify(q)); } catch { toast("Local storage full: sync before adding more photos."); } };
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : `id-${Date.now()}-${Math.random().toString(16).slice(2)}`);

function compressImage(file) {
  return new Promise((resolve) => {
    if (!file) return resolve(null);
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, 1280 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      resolve(c.toDataURL("image/jpeg", 0.72));
    };
    img.onerror = () => resolve(null);
    img.src = URL.createObjectURL(file);
  });
}
function dataUrlToBlob(u) {
  const [h, b] = u.split(",");
  const bin = atob(b); const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return new Blob([arr], { type: h.match(/:(.*?);/)[1] });
}

async function sendReport(item) {
  const fd = new FormData();
  ["text", "lat", "lon", "language", "client_report_id", "captured_at"].forEach((k) => fd.append(k, item[k]));
  if (item.photo) fd.append("photo", dataUrlToBlob(item.photo), "photo.jpg");
  return api("/api/reports", { method: "POST", body: fd }, 2);
}

$("#reportForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const item = {
    text: $("#rText").value.trim(), lat: parseFloat($("#rLat").value), lon: parseFloat($("#rLon").value), language: $("#rLang").value,
    client_report_id: uuid(), captured_at: Date.now() / 1000, photo: await compressImage($("#rPhoto").files[0]),
  };
  if (!item.text && !item.photo) return toast("Describe what you see or attach a photo.");
  if (isNaN(item.lat) || isNaN(item.lon)) return toast("Enter a valid latitude and longitude.");
  if (S.offline || !navigator.onLine) {
    setQ([...getQ(), item]);
    toast("Saved on this device. Status: pending sync.");
    renderQueue();
  } else {
    try {
      const r = await sendReport(item);
      toast(r.idempotent_replay ? "Already received." : `Report ${r.id} received. Extracted: ${r.extraction ? r.extraction.incident_type : "invalid output, sent to manual review"}.`, 5000);
      await refreshSim(); renderReach();
    } catch (err) {
      setQ([...getQ(), item]); renderQueue();
      toast(`Network problem, saved for sync: ${err.message}`);
    }
  }
  $("#rText").value = ""; $("#rPhoto").value = "";
});

function renderQueue() {
  const q = getQ();
  $("#queueBox").innerHTML = q.length ? `<b>${q.length} report${q.length > 1 ? "s" : ""} pending sync</b> on this device. <button class="btn quiet" id="btnSync" ${S.offline ? "disabled" : ""}>Sync now</button>` : "";
  const s = $("#btnSync");
  if (s) s.addEventListener("click", syncQueue);
}
async function syncQueue() {
  let q = getQ(); let ok = 0;
  for (const item of [...q]) {
    try { await sendReport(item); q = q.filter((x) => x.client_report_id !== item.client_report_id); setQ(q); ok++; } catch (e) { break; }
  }
  toast(`${ok} report${ok === 1 ? "" : "s"} synced. Duplicates are ignored by report ID.`);
  await refreshSim(); renderReach();
}
$("#btnOffline").addEventListener("click", () => {
  S.offline = !S.offline;
  document.body.classList.toggle("offline", S.offline);
  $("#btnOffline").textContent = S.offline ? "Reconnect and sync" : "Switch to offline field mode";
  renderQueue();
  if (!S.offline && getQ().length) syncQueue();
});
window.addEventListener("online", () => { if (!S.offline && getQ().length) syncQueue(); });

$("#btnAlerts").addEventListener("click", async () => {
  $("#alertBox").textContent = "Drafting…";
  try {
    const r = await post("/api/alerts", { scenario: S.scenario, village_id: $("#alertVillage").value, interventions: S.interventions });
    const L = { official_en: "Official (English)", citizen_en: "Citizen (simple English)", hi: "Hindi", or: "Odia", voice_en: "Voice / IVR" };
    $("#alertBox").innerHTML = `<p class="muted" style="margin-top:8px">Source: ${esc(r.source)}. Review before sending.</p>` + Object.entries(L).map(([k, l]) => `<div class="msg"><b>${l}</b>${esc(r.messages[k])}</div>`).join("");
  } catch (e) { $("#alertBox").textContent = e.message; }
});

/* ---------------- verify ---------------- */
function drawCells(canvas, cells, step, key, color) {
  const ctx = canvas.getContext("2d");
  const lat0 = 19.70, lat1 = 20.10, lon0 = 85.66, lon1 = 86.30;
  const W = canvas.width, H = canvas.height;
  ctx.fillStyle = "#D5E4EA"; ctx.fillRect(0, 0, W, H);
  const cw = (step / (lon1 - lon0)) * W + 0.5, ch = (step / (lat1 - lat0)) * H + 0.5;
  for (const c of cells) {
    const x = ((c.lon - lon0) / (lon1 - lon0)) * W - cw / 2, y = H - ((c.lat - lat0) / (lat1 - lat0)) * H - ch / 2;
    ctx.fillStyle = c[key] ? color : "#F4F1E4";
    ctx.fillRect(x, y, cw, ch);
  }
  ctx.fillStyle = "#15222D"; ctx.font = "600 17px Barlow Condensed, Arial Narrow, sans-serif";
  for (const n of S.sim.nodes.filter((n) => ["B17", "R21", "B22"].includes(n.id))) {
    const x = ((n.lon - lon0) / (lon1 - lon0)) * W, y = H - ((n.lat - lat0) / (lat1 - lat0)) * H;
    ctx.fillRect(x - 2, y - 2, 4, 4); ctx.fillText(n.id, x + 4, y - 4);
  }
}

async function renderVerify() {
  const v = await api(`/api/verify?scenario=${S.scenario}`);
  $("#verifyLabel").textContent = v.data_label;
  drawCells($("#cvBefore"), v.flood.cells, v.flood.cell_step_deg, "base", "#235E78");
  drawCells($("#cvPred"), v.flood.cells, v.flood.cell_step_deg, "pred", "#E0701B");
  drawCells($("#cvObs"), v.flood.cells, v.flood.cell_step_deg, "obs", "#C1272D");
  const c = v.assets.confusion;
  $("#verifyFigures").innerHTML = figure(v.flood.iou.toFixed(2), "flood extent IoU") + figure(v.flood.precision.toFixed(2), "flood precision") + figure(v.flood.recall.toFixed(2), "flood recall") + figure(v.assets.brier.toFixed(3), `asset Brier score (${c.tp} hit, ${c.fp} false alarm, ${c.fn} missed)`);
  const pill = { CONFIRMED: "red", "FALSE POSITIVE": "orange", MISSED: "orange", "CORRECT (no disruption)": "green" };
  const sorted = [...v.assets.rows].sort((a, b) => ["FALSE POSITIVE", "MISSED", "CONFIRMED", "CORRECT (no disruption)"].indexOf(a.result) - ["FALSE POSITIVE", "MISSED", "CONFIRMED", "CORRECT (no disruption)"].indexOf(b.result));
  $("#verifyRows").innerHTML = sorted.map((r) => `<tr><td><b>${esc(r.asset_id)}</b> <span class="muted">${esc(TYPE_NAME[r.type])}</span></td><td class="r">${pct(r.predicted_risk)}</td><td>${esc(r.observed)}</td><td><span class="pill ${pill[r.result]}">${esc(r.result.toLowerCase().replace(/^./, (x) => x.toUpperCase()))}</span></td></tr>`).join("");
  $("#learnedList").innerHTML = v.learned.map((l) => `<li>${esc(l)}</li>`).join("");
  $("#memoryFlow").textContent = v.workflow;
  $("#memoryList").innerHTML = v.failure_memory.map((m) => `<div class="report"><b>${esc(m.id)}</b> <span class="pill ${m.error_type === "FALSE_POSITIVE" ? "orange" : "red"}">${m.error_type === "FALSE_POSITIVE" ? "False positive" : "False negative"}</span> <span class="pill grey">${esc(m.review_status.replace("_", " ").toLowerCase())}</span><div>${esc(m.asset_id)}: predicted ${esc(m.prediction)}, observed ${esc(m.observation)}.</div><div class="muted">${esc(m.possible_reason)}</div>${m.review_status === "PENDING" ? `<div class="btn-row" style="margin-top:6px"><button class="btn quiet" data-mem="${m.id}" data-d="approve">Confirm as model error</button><button class="btn quiet" data-mem="${m.id}" data-d="reject">Dismiss</button></div>` : ""}</div>`).join("") || "<p class='muted'>No mismatches.</p>";
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-mem]");
  if (!b) return;
  await post(`/api/verify/memory/${b.dataset.mem}`, { decision: b.dataset.d });
  toast(b.dataset.d === "approve" ? "Stored as a calibration record for the next model review." : "Dismissed.");
  renderVerify();
});

/* ---------------- evaluation ---------------- */
async function renderEvaluation() {
  const ev = await api(`/api/evaluation?scenario=${S.scenario}`);
  const s = ev.synthetic_stress_test, c = s.asset_disruption.confusion;
  $("#evalBody").innerHTML = `
  <div class="panel"><h3>${esc(ev.historical_validation.label)}</h3><p><span class="pill grey">${esc(ev.historical_validation.status)}</span></p><p class="small">${esc(ev.historical_validation.why)}</p></div>
  <div class="panel"><h3>${esc(s.label)}</h3>
    <div class="figures">${figure(s.flood_extent.iou.toFixed(2), "flood IoU")}${figure(s.flood_extent.precision.toFixed(2), "flood precision")}${figure(s.flood_extent.recall.toFixed(2), "flood recall")}${figure(s.asset_disruption.brier.toFixed(3), "asset Brier score")}</div>
    <div class="grid-2"><div><h3>Confusion matrix (threshold 0.5)</h3><table><tr><th></th><th class="r">Observed disrupted</th><th class="r">Observed operational</th></tr><tr><td>Predicted disrupted</td><td class="r">${c.tp}</td><td class="r">${c.fp}</td></tr><tr><td>Predicted operational</td><td class="r">${c.fn}</td><td class="r">${c.tn}</td></tr></table></div>
    <div><h3>Calibration</h3><table><tr><th>Predicted bin</th><th class="r">n</th><th class="r">Mean predicted</th><th class="r">Observed rate</th></tr>${s.asset_disruption.calibration.map((b) => `<tr><td>${b.bin}</td><td class="r">${b.n}</td><td class="r">${b.mean_predicted}</td><td class="r">${b.observed_rate}</td></tr>`).join("")}</table></div></div>
  </div>
  <div class="panel"><h3>${esc(ev.simulation_comparison.label)}</h3><p class="small muted">${esc(ev.simulation_comparison.algorithm)}. ${esc(ev.simulation_comparison.caveat)}</p><table><tr><th>Metric</th><th class="r">No action</th><th class="r">Greedy plan</th></tr>${ev.simulation_comparison.rows.map((r) => `<tr><td>${esc(r.metric)}</td><td class="r">${fmt(r.baseline)}</td><td class="r">${fmt(r.optimized)}</td></tr>`).join("")}</table></div>
  <div class="panel"><h3>Extraction test set</h3><p class="small muted">12 hand-labelled reports in English, Hindi and Odia. Tiny and indicative only.</p><button class="btn" id="btnExtract">Run extraction test</button><div id="extractBody" style="margin-top:10px"></div></div>`;
  $("#btnExtract").addEventListener("click", async () => {
    $("#extractBody").textContent = "Running…";
    const r = await post("/api/evaluation/extraction", {});
    $("#extractBody").innerHTML = `<div class="figures">${figure(pct(r.structured_output_success_rate), "structured output success")}${figure(pct(r.incident_type_accuracy), "incident type accuracy")}${figure(pct(r.severity_agreement), "severity agreement")}${figure(r.n, "labelled reports")}</div><p class="small">Extractor: ${esc(r.extractor)}${r.caveat ? `. <b>${esc(r.caveat)}</b>` : ""}</p><div class="table-wrap"><table><tr><th>Report</th><th>Expected</th><th>Got</th></tr>${r.rows.map((x) => `<tr><td>${esc(x.text)}</td><td>${esc(x.expected)}</td><td>${x.type_ok ? "" : "✗ "}${esc(x.got || x.error)}</td></tr>`).join("")}</table></div>`;
  });
}

/* ---------------- safety ---------------- */
function renderSafety() {
  const rows = [
    ["CYCLOPS supports officials; it does not replace disaster authorities.", "Every action is a recommendation the user applies manually. Warnings are drafts marked for review before sending."],
    ["Risk is probabilistic.", "All risks are shown as probabilities with Low / Expected / High scenario ranges and a confidence value. No asset is ever labelled as certain to fail."],
    ["Gemini never sets risk values.", "Hazard, fragility, cascade and optimizer are deterministic code. Gemini only extracts report content and rewrites verified facts."],
    ["AI output is schema-checked.", "Report extraction must pass a Pydantic schema; failures are stored as 'Invalid AI output, manual review' and never touch the twin."],
    ["Generated text cannot add facts.", "Warnings and briefs are rejected if they contain any number not present in the structured facts, and the template is used instead."],
    ["Citizen reports require verification.", "Unreviewed reports have a discounted effect; only approved reports count as observed damage. Rejected reports have no effect."],
    ["Missing reports do not prove no impact.", "Reach gap uses 'possible blind spot' wording and recommends field verification, never a conclusion."],
    ["Minimise personal data.", "Contact details are not stored, only whether one was provided. Maps show community-level markers, never individual households."],
    ["No silent learning from unverified data.", "Mismatches go to failure memory with human review. No automatic retraining."],
  ];
  $("#safetyRows").innerHTML = rows.map(([a, b]) => `<tr><td><b>${esc(a)}</b></td><td>${esc(b)}</td></tr>`).join("");
  $("#provenance").innerHTML = Object.entries(S.meta.provenance).map(([k, v]) => `<dt>${esc(k.replace("_", " "))}</dt><dd>${esc(v)}</dd>`).join("");
}

/* ---------------- brief ---------------- */
function md(src) {
  const lines = src.split("\n"); let html = ""; let inList = false;
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  for (const l of lines) {
    if (/^\s*[-*] /.test(l)) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(l.replace(/^\s*[-*] /, ""))}</li>`; continue; }
    if (inList) { html += "</ul>"; inList = false; }
    if (/^### /.test(l)) html += `<h3>${inline(l.slice(4))}</h3>`;
    else if (/^## /.test(l)) html += `<h2>${inline(l.slice(3))}</h2>`;
    else if (/^# /.test(l)) html += `<h1>${inline(l.slice(2))}</h1>`;
    else if (l.trim()) html += `<p>${inline(l)}</p>`;
  }
  return html + (inList ? "</ul>" : "");
}
let BRIEF = "";
$("#btnBrief").addEventListener("click", async () => {
  $("#briefBody").innerHTML = "<p>Generating from the current system state…</p>";
  $("#briefDialog").showModal();
  try {
    const r = await post("/api/brief", simBody());
    BRIEF = r.markdown;
    $("#briefSource").textContent = `Source: ${r.source}. Generated ${new Date(r.generated_at * 1000).toLocaleString()}.`;
    $("#briefBody").innerHTML = md(r.markdown);
  } catch (e) { $("#briefBody").textContent = e.message; }
});
$("#btnCloseBrief").addEventListener("click", () => $("#briefDialog").close());
$("#btnCopyBrief").addEventListener("click", async () => { try { await navigator.clipboard.writeText(BRIEF); toast("Brief copied."); } catch { toast("Copy blocked by the browser."); } });
$("#btnPrintBrief").addEventListener("click", () => {
  const w = window.open("", "_blank");
  w.document.write(`<html><head><title>Incident brief</title><style>body{font-family:Barlow,Arial,sans-serif;max-width:720px;margin:30px auto;color:#15222D}h2{border-top:1px solid #ccc;padding-top:8px}</style></head><body>${md(BRIEF)}</body></html>`);
  w.document.close(); w.print();
});

/* ---------------- scenario switch ---------------- */
$$(".scenario-switch button").forEach((b) => b.addEventListener("click", async () => {
  S.scenario = b.dataset.scenario;
  if (window.cycloneBg) window.cycloneBg.setIntensity({ conservative: 0.82, expected: 1.0, severe: 1.2 }[S.scenario]);
  try {
    await loadScenario(); await loadReach(); renderFigures(); loadPlan(); rerenderCurrent();
    toast(`${S.meta.scenarios[S.scenario]} scenario loaded.`);
  } catch (e) { toast(e.message); }
}));

/* ---------------- background control ---------------- */
(function bgControl() {
  const b = $("#btnBg");
  const sync = () => {
    const on = window.cycloneBg && window.cycloneBg.running;
    b.textContent = on ? "Pause background" : "Animate background";
    b.setAttribute("aria-pressed", String(!!on));
  };
  b.addEventListener("click", () => { if (window.cycloneBg) window.cycloneBg.toggle(); sync(); });
  sync();
})();

/* ---------------- boot ---------------- */
(async function boot() {
  try {
    S.meta = await api("/api/meta");
    S.resources = { ...S.meta.default_resources };
    const g = S.meta.gemini;
    $("#aiStatus").innerHTML = g.enabled ? `<span class="dot" style="background:#3F8A55"></span>Gemini ${esc(g.model)} connected` : `<span class="dot" style="background:#E8B622"></span>Gemini not configured. Report extraction uses transparent keyword rules; warnings and brief use templates.`;
    await loadScenario();
    await loadReach();
    renderFigures();
    showPage(currentPage());
    loadPlan();
  } catch (e) {
    $("#bandEvent").innerHTML = `Could not reach the CYCLOPS API<span>${esc(e.message)}. Start the backend (see README) and reload.</span>`;
  }
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
})();
