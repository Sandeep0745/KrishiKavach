// 72 Ghante dashboard. Renders the orchestrator's event stream (SystemDesign §7 and §15).
// It keeps no state of its own beyond what the snapshot and the events tell it.

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const MAP = { w: 760, h: 720, pad: 46 };

const GROUP = {
  AFFECTED: "wait", QUEUED: "wait", NO_ANSWER: "wait", CALLING: "call", IN_CALL: "call",
  EVIDENCE: "work", PROCESSING: "work", FILING: "work", FILED: "done", ESCALATED: "human",
  NO_DAMAGE: "nodamage", UNREACHABLE: "unreach", INELIGIBLE: "inelig", FAILED: "failed",
};
const LEGEND = [
  ["wait", "To call"], ["call", "On a call"], ["work", "Being filed"], ["done", "Filed"],
  ["human", "Needs a person"], ["nodamage", "No damage"], ["unreach", "Not reachable"], ["inelig", "Not eligible"], ["failed", "Failed"],
];
const AGENTS = [
  ["sentinel", "Sentinel"], ["dispatcher", "Dispatcher"], ["intake", "Intake"], ["evidence", "Evidence"],
  ["eligibility", "Eligibility"], ["filing", "Filing"], ["followup", "Follow-up"],
];
const SLOTS = [
  ["identity_confirmed", "Identity confirmed"], ["damage_confirmed", "Damage reported"], ["khasra_confirmed", "Plot number confirmed"],
  ["peril", "Cause of loss"], ["loss_datetime", "When it happened"], ["damage_pct", "Share of crop lost"],
  ["crop_stage", "Crop stage"], ["consent", "Consent to file"],
];
const PHOTO = { hail_damage: "hail damage", lodged: "crop flattened", waterlogged: "field under water", healthy: "healthy crop", not_a_crop: "not a crop photo" };
const PATH = { fast: "fast path", llm: "language model", scripted: "scripted line" };
const STEP_VERB = { fill: "filling", click: "pressing", select: "choosing", choose: "choosing", upload: "uploading", tick: "ticking", open: "opening" };
const FILED_BY = { agent: "Submitted by the browser agent.", scripted: "Submitted by the scripted fill.", api: "Submitted through the portal's API." };
const ACTIVE_HERO = new Set(["CALLING", "IN_CALL", "EVIDENCE", "PROCESSING", "FILING"]);
const TICKER_ROWS = 40, MCP_ROWS = 30, TURNS = 7;

const state = {
  villages: new Map(), cases: new Map(), farms: new Map(), storm: null, stormShown: false, project: null, scenario: { state: "idle" },
  hoursLeft: null, deadlineHours: 72, simTs: null,
  s1: { n: 0, ms: [] }, mcp: { n: 0 }, fallbacks: [],
  hero: null, // {caseId, startedAt, stoppedAt, slots, steps}
};
const dots = new Map(); // case id -> <circle>
let layers = null, dirtyCounts = false, heroTimer = null;

// ---------- helpers ----------
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function svg(tag, attrs) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  return node;
}
function prepend(list, node, max) {
  list.insertBefore(node, list.firstChild);
  while (list.children.length > max) list.removeChild(list.lastChild);
}
function fmtClock(hours) {
  if (hours === null || hours === undefined || Number.isNaN(hours)) return "72 h 00 m";
  const mins = Math.max(0, Math.round(hours * 60));
  return `${Math.floor(mins / 60)} h ${String(mins % 60).padStart(2, "0")} m`;
}
function fmtSim(iso) {
  // The scenario runs on Sehore's clock, so read the wall-clock fields straight from the ISO text.
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || "");
  if (!m) return "";
  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m[2]) - 1];
  return `${Number(m[3])} ${month} ${m[1]}, ${m[4]}:${m[5]}`;
}
function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
}
function fmtValue(v) {
  if (v === true) return "yes";
  if (v === false) return "no";
  return String(v).replaceAll("_", " ");
}
function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

// ---------- map ----------
function buildProjection() {
  const pts = [...state.villages.values()].map((v) => [v.lat, v.lon]);
  for (const c of state.cases.values()) if (c.lat != null) pts.push([c.lat, c.lon]);
  for (const f of state.farms.values()) if (f.lat != null) pts.push([f.lat, f.lon]);
  let lat0, lon0, halfKm;
  const kmLat = 110.57;
  if (state.storm) {
    lat0 = state.storm.center_lat; lon0 = state.storm.center_lon; halfKm = state.storm.radius_km;
  } else if (pts.length) {
    lat0 = pts.reduce((a, p) => a + p[0], 0) / pts.length; lon0 = pts.reduce((a, p) => a + p[1], 0) / pts.length; halfKm = 1;
  } else {
    return null;
  }
  const kmLon = 111.32 * Math.cos((lat0 * Math.PI) / 180);
  for (const [lat, lon] of pts) halfKm = Math.max(halfKm, Math.abs(lat - lat0) * kmLat, Math.abs(lon - lon0) * kmLon);
  const scale = (Math.min(MAP.w, MAP.h) / 2 - MAP.pad) / halfKm; // pixels per km
  const fn = (lat, lon) => [MAP.w / 2 + (lon - lon0) * kmLon * scale, MAP.h / 2 - (lat - lat0) * kmLat * scale];
  fn.scale = scale;
  return fn;
}

function drawMap() {
  const map = $("map");
  map.setAttribute("viewBox", `0 0 ${MAP.w} ${MAP.h}`);
  map.replaceChildren();
  dots.clear();
  layers = { storm: svg("g"), villages: svg("g"), dots: svg("g"), hero: svg("g") };
  map.append(layers.storm, layers.dots, layers.villages, layers.hero);
  state.project = buildProjection();
  if (!state.project) return;
  for (const v of state.villages.values()) {
    const [x, y] = state.project(v.lat, v.lon);
    const label = svg("text", { x, y: y - 16, "text-anchor": "middle", class: "village-label" });
    label.textContent = v.name;
    layers.villages.append(label);
  }
  if (state.stormShown) drawStorm(false);
  // every insured farm is on the map from the start, in grey; a farm takes its status colour when its case is opened
  for (const [id, f] of state.farms) if (!state.cases.has(id)) addIdleDot(id, f);
  for (const [id, c] of state.cases) addDot(id, c);
  $("map-empty").hidden = state.cases.size > 0 || state.stormShown || state.farms.size > 0;
}

function drawStorm(animate) {
  if (!layers || !state.project || !state.storm) return;
  layers.storm.replaceChildren();
  const [x, y] = state.project(state.storm.center_lat, state.storm.center_lon);
  const r = state.storm.radius_km * state.project.scale;
  const g = svg("g", { class: animate ? "storm-g sweep" : "storm-g" });
  g.append(svg("circle", { cx: x, cy: y, r, class: "storm" }), svg("circle", { cx: x, cy: y, r: r * 0.45, class: "storm-core" }));
  layers.storm.append(g);
  $("map-empty").hidden = true;
}

function addIdleDot(id, f) {
  if (!layers || !state.project || f.lat == null || f.lon == null) return;
  const [x, y] = state.project(f.lat, f.lon);
  const dot = svg("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: f.is_hero ? 7 : 3.5, class: "dot g-idle" });
  dots.set(id, dot);
  layers.dots.append(dot);
}

function addDot(id, c) {
  if (!layers || !state.project || c.lat == null || c.lon == null) return;
  const idle = dots.get(id);
  if (idle) { idle.remove(); dots.delete(id); }
  const [x, y] = state.project(c.lat, c.lon);
  const dot = svg("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: c.is_hero ? 9 : 4.5 });
  dots.set(id, dot);
  paintDot(id, c);
  layers.dots.append(dot);
  if (c.is_hero) {
    const label = svg("text", { x: x + 14, y: y + 5, class: "hero-label" });
    label.textContent = "LIVE";
    layers.hero.replaceChildren(label);
    layers.dots.append(dot); // keep the hero on top
  }
  $("map-empty").hidden = true;
}

function paintDot(id, c) {
  const dot = dots.get(id);
  if (!dot) return;
  const group = GROUP[c.status] || "wait";
  dot.setAttribute("class", `dot g-${group}${group === "call" ? " calling" : ""}${c.is_hero ? " hero" : ""}`);
}

// ---------- counters, clock, banner ----------
function counts() {
  const out = { total: state.cases.size, live: 0 };
  for (const [key] of LEGEND) out[key] = 0;
  for (const c of state.cases.values()) {
    out[GROUP[c.status] || "wait"] += 1;
    if (c.is_hero) out.live += 1;
  }
  return out;
}

function renderCounts() {
  dirtyCounts = false;
  const n = counts();
  const legend = $("legend");
  if (!legend.children.length) {
    const total = el("li", "total");
    total.append(el("span"), el("span", "", "Affected and insured"), el("span", "n"));
    total.dataset.key = "total";
    legend.append(total);
    for (const [key, label] of LEGEND) {
      const row = el("li");
      row.dataset.key = key;
      row.append(el("span", `sw g-${key}`), el("span", "", label), el("span", "n"));
      legend.append(row);
    }
  }
  for (const row of legend.children) row.lastChild.textContent = n[row.dataset.key];
  $("truth").textContent = `Simulated farmers: ${n.total - n.live}. Live: ${n.live}.`;

  const open = n.wait + n.call + n.work;
  const banner = $("banner");
  if (n.total > 0 && open === 0) {
    const followUp = n.human + n.unreach + n.failed;
    const hours = state.hoursLeft == null ? "" : ` ${Math.round(state.hoursLeft)} hours left.`;
    banner.textContent = `${n.done} of ${n.total} claims filed.${hours} ${followUp} need follow-up.`;
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}
function countsSoon() {
  if (dirtyCounts) return;
  dirtyCounts = true;
  requestAnimationFrame(renderCounts);
}

function renderClock() {
  $("clock-num").textContent = fmtClock(state.hoursLeft);
  const share = state.hoursLeft == null ? 1 : Math.max(0, Math.min(1, state.hoursLeft / state.deadlineHours));
  $("clock-fill").style.transform = `scaleX(${share})`;
  $("simtime").textContent = fmtSim(state.simTs);
}

// ---------- ticker, tool calls, agents, notices ----------
function onDecision(e) {
  const d = e.data || {};
  state.s1.n += 1;
  if (typeof d.latency_ms === "number" && !d.cached) {
    state.s1.ms.push(d.latency_ms);
    if (state.s1.ms.length > 300) state.s1.ms.shift();
  }
  const [name, answer] = Object.entries(d.answers || {})[0] || ["", {}];
  const row = el("li", `${e.live ? "live" : ""}${d.fallback_from ? " fallback" : ""}`.trim());
  row.title = name;
  row.append(
    el("span", "kind", d.decision || ""),
    el("span", "ans", answer && answer.value !== undefined ? fmtValue(answer.value) : ""),
    el("span", "conf", answer && typeof answer.confidence === "number" ? answer.confidence.toFixed(2) : ""),
    el("span", "ms", d.cached ? "cached" : typeof d.latency_ms === "number" ? `${Math.round(d.latency_ms)} ms` : ""),
    el("span", "prov", d.fallback_from ? `${d.provider}, fallback` : d.provider || ""),
  );
  prepend($("ticker"), row, TICKER_ROWS);
  $("ticker-empty").hidden = true;
  const mid = median(state.s1.ms);
  if (d.cached) state.s1.cached = (state.s1.cached || 0) + 1;
  const repeats = state.s1.cached ? `, ${state.s1.cached.toLocaleString("en-IN")} repeats served from cache` : "";
  $("s1-count").textContent = `${state.s1.n.toLocaleString("en-IN")} made${mid == null ? "" : `, median ${Math.round(mid)} ms`}${repeats}`;
}

function onToolCall(e) {
  const d = e.data || {};
  state.mcp.n += 1;
  const row = el("li");
  const call = el("span", "call");
  call.append(el("span", "server", d.server || ""), document.createTextNode(`.${d.tool || ""}`));
  if (d.args_summary) call.append(el("span", "args", `  ${d.args_summary}`));
  row.append(call, el("span", "ms", typeof d.ms === "number" ? `${Math.round(d.ms)} ms` : ""));
  prepend($("mcp"), row, MCP_ROWS);
  $("mcp-empty").hidden = true;
  $("mcp-count").textContent = `${state.mcp.n.toLocaleString("en-IN")} made`;
}

const agentTimers = new Map();
function buildAgents() {
  const strip = $("agents");
  strip.replaceChildren();
  for (const [key, label] of AGENTS) {
    const item = el("li", "", label);
    item.dataset.agent = key;
    strip.append(item);
  }
}
function lightAgent(agent, hold) {
  const item = $("agents").querySelector(`[data-agent="${agent}"]`);
  if (!item) return;
  item.classList.add("on");
  clearTimeout(agentTimers.get(agent));
  if (!hold) agentTimers.set(agent, setTimeout(() => item.classList.remove("on"), 900));
}

function renderNotices() {
  const box = $("notices");
  box.replaceChildren();
  for (const text of state.fallbacks.slice(-3)) box.append(el("li", "", text));
  box.hidden = state.fallbacks.length === 0;
}

// ---------- live call panel ----------
function openHero(caseId, started) {
  if (!state.hero || state.hero.caseId !== caseId) {
    state.hero = { caseId, startedAt: started ? Date.now() : null, stoppedAt: null, slots: {}, steps: 0 };
    $("transcript").replaceChildren();
    $("evidence").textContent = "Waiting for the photo.";
    $("filing").textContent = "Not started.";
    $("hero-result").hidden = true;
    renderSlots();
  } else if (started && !state.hero.startedAt) {
    state.hero.startedAt = Date.now();
  }
  showHero(true);
  clearInterval(heroTimer);
  heroTimer = setInterval(renderWatch, 250);
  renderWatch();
  fetch(`/api/cases/${encodeURIComponent(caseId)}`).then((r) => (r.ok ? r.json() : null)).then((c) => {
    if (!c || !state.hero || state.hero.caseId !== caseId) return;
    if (c.farmer) $("hero-name").textContent = `${c.farmer.name}${c.village ? `, ${c.village.name}` : ""}`;
    for (const [k, v] of Object.entries(c.slots || {})) if (v !== null && state.hero.slots[k] === undefined) state.hero.slots[k] = v;
    renderSlots();
  }).catch(() => {});
}
function showHero(show) {
  // The presenter can put the call panel away to show the whole map again, and bring it back.
  $("hero").hidden = !show;
  document.querySelector(".map-wrap").classList.toggle("hero-open", show);
  const btn = $("btn-live");
  btn.disabled = !state.hero;
  btn.textContent = show ? "Show map" : "Show live call";
}
function closeHero() {
  state.hero = null;
  clearInterval(heroTimer);
  $("hero-name").textContent = "Live call";
  showHero(false);
}
function renderWatch() {
  const h = state.hero;
  if (h && h.took != null) { $("hero-watch").textContent = fmtDuration(h.took); return; }
  if (!h || !h.startedAt) { $("hero-watch").textContent = ""; return; }
  $("hero-watch").textContent = fmtDuration(((h.stoppedAt || Date.now()) - h.startedAt) / 1000);
}
function renderSlots() {
  const list = $("slots");
  list.replaceChildren();
  const have = (state.hero && state.hero.slots) || {};
  for (const [key, label] of SLOTS) {
    const value = have[key];
    const done = value !== undefined && value !== null && value !== false;
    const row = el("li", done ? "done" : "");
    const text = el("span", "", label);
    if (done && value !== true) {
      text.append(document.createTextNode(": "), el("span", "val", key === "damage_pct" ? `${value}%` : key === "loss_datetime" ? (fmtSim(value) || fmtValue(value)) : fmtValue(value)));
    }
    row.append(el("span", "tick", done ? "✓" : ""), text);
    list.append(row);
  }
}
function onTurn(e) {
  const d = e.data || {};
  const turn = el("div", `turn ${d.speaker === "farmer" ? "farmer" : "agent"}`);
  turn.append(el("div", "said", d.text || ""));
  const total = d.latency_ms && typeof d.latency_ms.total === "number" ? `, ${Math.round(d.latency_ms.total)} ms` : "";
  const meta = el("div", "meta");
  const language = {"hi-IN": "Hindi", "en-IN": "English", "ml-IN": "Malayalam", "ta-IN": "Tamil"}[d.language];
  const languageLabel = language ? ` · ${language}${d.translated ? " → English translation" : ""}` : "";
  meta.append(el("span", `path-${d.path || "scripted"}`, PATH[d.path] || d.path || ""), document.createTextNode(total + languageLabel));
  turn.append(meta);
  const box = $("transcript");
  box.append(turn);
  while (box.children.length > TURNS) box.removeChild(box.firstChild);
}
function onEvidence(e) {
  const d = e.data || {};
  const box = $("evidence");
  box.replaceChildren();
  if (d.thumb_url) {
    const img = el("img");
    img.src = d.thumb_url; img.alt = "Photo taken by the farmer";
    box.append(img);
  }
  const sure = typeof d.edge_confidence === "number" ? `, ${Math.round(d.edge_confidence * 100)}% sure` : "";
  const ms = typeof d.edge_latency_ms === "number" ? `, ${Math.round(d.edge_latency_ms)} ms` : "";
  box.append(el("div", "", d.edge_label ? `Checked on the phone: ${PHOTO[d.edge_label] || fmtValue(d.edge_label)}${sure}${ms}.` : "Photo received. It was not checked on the phone."));
  if (typeof d.lat === "number") {
    const source = d.gps_source === "plot" ? " (the insured plot; the phone had no GPS fix)" : "";
    box.append(el("div", "muted", `Location ${d.lat.toFixed(4)}, ${d.lon.toFixed(4)}${source}${d.captured_offline ? ". Taken with no network." : "."}`));
  }
  const match = el("div", "muted");
  match.id = "evidence-match";
  box.append(match);
  const pack = el("a", "pack-link", "Open the evidence pack");
  pack.href = `/api/cases/${encodeURIComponent(e.case_id)}/evidence-pack`;
  pack.target = "_blank"; pack.rel = "noopener";
  box.append(pack);
}
function onFilingStep(e) {
  const d = e.data || {};
  if (!state.hero) return;
  state.hero.steps = Math.max(state.hero.steps, d.n || 0);
  const who = d.mode === "scripted" ? "Scripted fill" : "Browser agent";
  $("filing").textContent = `${who}, step ${state.hero.steps}: ${STEP_VERB[d.action] || fmtValue(d.action || "working on")} ${fmtValue(d.field || "the page")}.`;
}
function onFiled(e) {
  const d = e.data || {};
  if (!state.hero || state.hero.caseId !== e.case_id) return;
  state.hero.stoppedAt = Date.now();
  const took = typeof d.time_to_file_s === "number" ? d.time_to_file_s : (state.hero.startedAt ? (state.hero.stoppedAt - state.hero.startedAt) / 1000 : null);
  state.hero.took = took;
  clearInterval(heroTimer);
  const result = $("hero-result");
  result.className = "hero-result";
  result.textContent = `${took == null || took < 1 ? "Filed" : `Filed in ${fmtDuration(took)}`}. Reference ${d.claim_ref || ""}`;
  result.hidden = false;
  $("filing").textContent = FILED_BY[d.filing_mode] || "Submitted.";
  renderWatch();
}

// ---------- after a reconnect: the true totals behind the replayed rows ----------
function applyTallies(t) {
  state.s1.n = t.s1 || 0;
  state.s1.cached = t.s1_cached || 0;
  state.mcp.n = t.mcp || 0;
  if (state.s1.n) {
    const mid = median(state.s1.ms);
    const repeats = state.s1.cached ? `, ${state.s1.cached.toLocaleString("en-IN")} repeats served from cache` : "";
    $("s1-count").textContent = `${state.s1.n.toLocaleString("en-IN")} made${mid == null ? "" : `, median ${Math.round(mid)} ms`}${repeats}`;
  }
  if (state.mcp.n) $("mcp-count").textContent = `${state.mcp.n.toLocaleString("en-IN")} made`;
}

// ---------- the district run ----------
function renderScenario() {
  const sc = state.scenario || { state: "idle" };
  $("btn-start").disabled = sc.state !== "idle";
  const pause = $("btn-pause");
  const resumable = sc.state === "paused" && !sc.fleet_finished;
  pause.disabled = !(sc.state === "running" || resumable);
  pause.textContent = resumable ? "Resume" : "Pause";
  let text = "";
  if (sc.state === "running" && sc.total && !sc.triage_done) text = `Ranking farmers: ${sc.triaged} of ${sc.total}`;
  else if (sc.state === "paused" && sc.paused_by === "live call") text = "Simulated farmers paused for the live call. Press P to resume.";
  else if (sc.state === "paused" && sc.paused_by === "presenter") text = "Paused. Press P to resume.";
  else if (sc.state === "paused" && sc.fleet_finished) text = "Simulated farmers are all settled. The live case is still open.";
  $("runstate").textContent = text;
}
async function scenarioAction(path, failText) {
  try {
    const r = await fetch(`/api/scenario/${path}`, { method: "POST" });
    if (!r.ok) throw new Error(((await r.json().catch(() => ({}))).error) || String(r.status));
  } catch (err) {
    state.fallbacks.push(`${failText}: ${err.message}.`);
    renderNotices();
  }
}

// ---------- a person's decisions on the live case ----------
function heroCase() {
  for (const [id, c] of state.cases) if (c.is_hero) return [id, c];
  return [null, null];
}
function renderHeroActions() {
  const [, c] = heroCase();
  $("btn-approve").hidden = !(c && c.status === "ESCALATED" && c.verdict === "review");
  $("btn-retry").hidden = !(c && c.status === "FAILED");
}
async function heroAction(btn, path, body, failText) {
  const [id] = heroCase();
  if (!id) return;
  btn.disabled = true;
  try {
    const r = await fetch(`/api/cases/${encodeURIComponent(id)}/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(((await r.json().catch(() => ({}))).error) || String(r.status));
  } catch (err) {
    state.fallbacks.push(`${failText}: ${err.message}.`);
    renderNotices();
  }
  btn.disabled = false;
  renderHeroActions();
}
function onAgentWork(e) {
  // What the pipeline's agents report about the live case, shown in the Filing box of the call panel.
  const d = e.data || {};
  const c = state.cases.get(e.case_id);
  if (e.type === "agent.finished" && e.agent === "eligibility" && c) { c.verdict = d.verdict || c.verdict; renderHeroActions(); }
  if (!e.live || !state.hero || state.hero.caseId !== e.case_id) return;
  if (e.type === "agent.started") {
    if (e.agent === "eligibility") $("filing").textContent = "Checking the policy, the cause, the deadline and the evidence.";
    if (e.agent === "filing") { state.hero.steps = 0; $("filing").textContent = `${d.summary || "Filing"}.`; }
    return;
  }
  if (e.agent === "evidence" && $("evidence-match")) $("evidence-match").textContent = d.summary || "";
  if (e.agent === "eligibility") $("filing").textContent = d.summary || "";
  if (e.agent === "filing" && d.ok === false) {
    $("filing").textContent = d.summary || "Not filed.";
    if (!d.filing_mode) showResult("Not filed. Press F to try again.", "warn");
  }
}
function showResult(text, kind) {
  const result = $("hero-result");
  result.textContent = text;
  result.className = `hero-result${kind ? ` ${kind}` : ""}`;
  result.hidden = false;
}

// ---------- events ----------
function applySnapshot(s) {
  state.villages = new Map((s.villages || []).map((v) => [v.id, v]));
  state.cases = new Map((s.cases || []).map((c) => [c.id, { status: c.status, lat: c.lat, lon: c.lon, is_hero: !!c.is_hero, village_id: c.village_id, verdict: c.verdict || null }]));
  state.farms = new Map((s.farms || []).map((f) => [f.case_id, f]));
  state.scenario = s.scenario || { state: "idle" };
  state.storm = s.storm || null;
  state.stormShown = state.cases.size > 0;
  if (s.clock) { state.simTs = s.clock.sim_ts; state.hoursLeft = s.clock.hours_left ?? null; }
  // Start the panels empty: after a reset they stay so; after a reconnect the server replays their latest rows next.
  state.replaying = true;
  state.s1 = { n: 0, ms: [] }; state.mcp = { n: 0 }; state.fallbacks = [];
  for (const id of ["ticker", "mcp"]) $(id).replaceChildren();
  for (const id of ["s1-count", "mcp-count"]) $(id).textContent = "";
  $("ticker-empty").hidden = false; $("mcp-empty").hidden = false;
  renderNotices();
  const before = state.hero;
  closeHero();
  drawMap();
  renderCounts();
  renderClock();
  renderScenario();
  const hero = [...state.cases].find(([, c]) => c.is_hero && ACTIVE_HERO.has(c.status));
  if (hero) {
    openHero(hero[0], false);
    if (before && before.caseId === hero[0] && before.startedAt) state.hero.startedAt = before.startedAt; // a reconnect keeps the stopwatch
  }
  renderHeroActions();
}

function apply(e) {
  const d = e.data || {};
  if (e.sim_ts && e.type !== "sim.clock") state.simTs = e.sim_ts;
  switch (e.type) {
    case "snapshot": applySnapshot(d); return;
    case "sim.clock":
      state.simTs = d.sim_ts || state.simTs;
      if (typeof d.hours_left === "number") state.hoursLeft = d.hours_left;
      renderClock();
      countsSoon(); // the closing banner quotes the hours left
      return;
    case "storm.detected":
      if (d.center) state.storm = { ...(state.storm || {}), center_lat: d.center.lat, center_lon: d.center.lon, radius_km: d.radius_km };
      state.stormShown = true;
      if (!state.project) drawMap();
      drawStorm(true);
      break;
    case "case.created": {
      const c = { status: "AFFECTED", lat: d.lat, lon: d.lon, is_hero: !!d.is_hero, village_id: d.village_id };
      const known = state.cases.has(e.case_id);
      state.cases.set(e.case_id, c);
      if (!state.project) drawMap(); else if (!known) addDot(e.case_id, c);
      countsSoon();
      break;
    }
    case "case.status_changed": {
      const c = state.cases.get(e.case_id);
      if (c) { c.status = d.to; paintDot(e.case_id, c); countsSoon(); if (c.is_hero) renderHeroActions(); }
      if (e.live && state.hero && state.hero.caseId === e.case_id && state.hero.took == null) {
        if (d.to === "ESCALATED" && String(d.reason || "").startsWith("needs human review")) showResult("Sent to a person to check. Press A to approve as the reviewer.", "warn");
        if (d.to === "INELIGIBLE") showResult(`Not eligible: ${d.reason || "see the checks"}.`, "warn");
      }
      break;
    }
    case "scenario.state": state.scenario = d; renderScenario(); return;
    case "tallies": state.replaying = false; applyTallies(d); return;
    case "scenario.finished": countsSoon(); return;
    case "s1.decision": onDecision(e); break;
    case "mcp.tool_called": onToolCall(e); break;
    case "call.started": if (e.live) { openHero(e.case_id, true); restartWatch(); } break;
    case "call.ended": if (e.live) onCallEnded(e); break;
    case "call.turn":
      if (e.live && (state.hero || !state.replaying)) { if (!state.hero) openHero(e.case_id, true); onTurn(e); }
      break;
    case "call.slot":
      if (e.live) { if (!state.hero) openHero(e.case_id, true); state.hero.slots[d.slot] = d.value; renderSlots(); }
      break;
    case "evidence.received": if (e.live && state.hero) onEvidence(e); break;
    case "filing.step": if (e.live) onFilingStep(e); break;
    case "claim.filed": {
      const c = state.cases.get(e.case_id);
      if (c) c.claim_ref = d.claim_ref;
      if (e.live) onFiled(e);
      break;
    }
    case "agent.started":
    case "agent.finished": onAgentWork(e); break;
    case "review.decision":
      if (e.live && state.hero) $("filing").textContent = d.approve ? "Approved by a person. Filing now." : "A person looked at it and did not approve.";
      break;
    case "fallback.used":
      state.fallbacks.push(`Fallback in use for ${fmtValue(d.component || "a component")}: ${fmtValue(d.from || "")} replaced by ${fmtValue(d.to || "")}.`);
      renderNotices();
      break;
    default: break;
  }
  if (e.agent && e.agent !== "system" && !state.replaying) {
    if (e.type === "agent.started") lightAgent(e.agent, true);
    else lightAgent(e.agent, false);
  }
  renderClockSoon();
}
let clockDirty = false;
function renderClockSoon() {
  if (clockDirty) return;
  clockDirty = true;
  requestAnimationFrame(() => { clockDirty = false; $("simtime").textContent = fmtSim(state.simTs); });
}

function restartWatch() {
  // a new ring for the same case (the first call dropped or was not answered): time this call from its own start
  if (!state.hero) return;
  state.hero.startedAt = Date.now();
  state.hero.stoppedAt = null;
  state.hero.took = null;
  $("hero-result").hidden = true;
  clearInterval(heroTimer);
  heroTimer = setInterval(renderWatch, 250);
}
const ENDED = {
  completed: "Call finished. The details are collected.", escalated: "Handed to a person.", wrong_person: "Wrong person on the line. Handed to a person.",
  no_answer: "No answer.", declined: "Call declined.", dropped: "Call dropped.",
};
function onCallEnded(e) {
  const d = e.data || {};
  if (!state.hero || state.hero.caseId !== e.case_id || state.hero.took != null) return;
  state.hero.stoppedAt = Date.now();
  clearInterval(heroTimer);
  renderWatch();
  const result = $("hero-result");
  result.textContent = ENDED[d.outcome] || "Call ended.";
  result.className = `hero-result${d.outcome === "completed" ? " neutral" : " warn"}`;
  result.hidden = false;
}

async function callHero() {
  const btn = $("btn-hero");
  btn.disabled = true;
  try {
    const r = await fetch("/api/hero/call", { method: "POST" });
    const out = await r.json();
    if (!r.ok) throw new Error(out.error || String(r.status));
    if (!out.phones) {
      state.fallbacks.push("The hero's phone is not connected. Open /farmer on the phone and press the start button; it will ring.");
      renderNotices();
    }
  } catch (err) {
    state.fallbacks.push(`The call could not be placed: ${err.message}.`);
    renderNotices();
  }
  setTimeout(() => { btn.disabled = false; }, 2000);
}

// ---------- controls ----------
let resetArmed = null;
async function resetScenario() {
  const btn = $("btn-reset");
  if (!resetArmed) {
    btn.textContent = "Press again to reset";
    resetArmed = setTimeout(() => { resetArmed = null; btn.textContent = "Reset"; }, 3000);
    return;
  }
  clearTimeout(resetArmed); resetArmed = null;
  btn.textContent = "Resetting";
  btn.disabled = true;
  try {
    const r = await fetch("/api/scenario/reset", { method: "POST" });
    if (!r.ok) throw new Error(String(r.status));
    btn.textContent = "Reset";
  } catch {
    btn.textContent = "Reset failed. Is the orchestrator running?";
    setTimeout(() => { btn.textContent = "Reset"; }, 4000);
  }
  btn.disabled = false;
}

function connect() {
  const conn = $("conn");
  const es = new EventSource("/api/events/stream");
  es.onopen = () => { conn.textContent = "connected"; conn.classList.remove("bad"); };
  es.onerror = () => { conn.textContent = "Connection lost. Retrying."; conn.classList.add("bad"); };
  es.onmessage = (m) => {
    let event;
    try { event = JSON.parse(m.data); } catch { return; }
    try { apply(event); } catch (err) { console.error("could not apply event", event && event.type, err); }
  };
}

buildAgents();
renderScenario();
renderCounts();
renderClock();
$("btn-reset").addEventListener("click", resetScenario);
$("btn-hero").addEventListener("click", callHero);
$("btn-start").addEventListener("click", () => scenarioAction("start", "The storm could not be started"));
$("btn-pause").addEventListener("click", () => scenarioAction(state.scenario && state.scenario.state === "paused" ? "resume" : "pause", "The run could not be paused or resumed"));
$("btn-approve").addEventListener("click", (ev) => heroAction(ev.currentTarget, "review", { approve: true, note: "approved on the dashboard" }, "The approval could not be recorded"));
$("btn-retry").addEventListener("click", (ev) => heroAction(ev.currentTarget, "pipeline/run", {}, "Filing could not be started again"));
$("btn-live").addEventListener("click", () => { if (state.hero) showHero($("hero").hidden); });
document.addEventListener("keydown", (ev) => {
  if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.repeat) return;
  const btn = document.querySelector(`.controls button[data-key="${ev.key.toLowerCase()}"]`);
  if (btn && !btn.disabled && !btn.hidden) btn.click();
});
connect();


// Read cached monitoring status; browser polling never calls the external provider.
function renderWeather(w) {
  const panel = document.querySelector(".weather-watch");
  panel.dataset.state = w.state;
  $("weather-source").textContent = w.mode === "demo" ? "DEMO / SIMULATED" : w.mode === "off" ? "OFF" : "LIVE / Open-Meteo";
  $("weather-summary").textContent = w.summary;
  const first = (w.risks || [])[0];
  $("weather-detail").textContent = first ? `${first.village}: ${first.reasons.slice(0, 2).join("; ")} (${first.kind})` : `${w.monitored_villages || 12} villages in ${w.district}; next 6 hours`;
  $("weather-time").textContent = w.demo_seconds_left != null ? `Simulated alert in ${w.demo_seconds_left}s` : w.checked_at ? `Checked ${new Date(w.checked_at).toLocaleTimeString()}` : "No verified reading yet";
}
async function refreshWeather() {
  try {
    const response = await fetch("/api/weather/status", { cache: "no-store" });
    if (!response.ok) throw new Error("Weather status unavailable");
    renderWeather(await response.json());
  } catch { $("weather-summary").textContent = "Weather status unavailable; reconnecting."; }
}
async function weatherControl(action) {
  try {
    const response = await fetch(`/api/weather/${action}`, { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Weather control failed");
    renderWeather(result);
  } catch (error) { $("weather-summary").textContent = error.message; }
}
const localWeatherControls = ["localhost", "127.0.0.1", "::1", "[::1]"].includes(location.hostname);
$("btn-weather-demo").hidden = !localWeatherControls;
$("btn-weather-live").hidden = !localWeatherControls;
$("btn-weather-demo").addEventListener("click", () => weatherControl("demo"));
$("btn-weather-live").addEventListener("click", () => weatherControl("live"));
refreshWeather();
setInterval(refreshWeather, 1000);
