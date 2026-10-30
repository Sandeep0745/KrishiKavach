// Farmer phone app (SystemDesign §11). Rings when the orchestrator places a call, joins the LiveKit room, takes a photo,
// checks it on the phone, and uploads it with GPS and time. Photos taken with no network wait in a queue on the phone.

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const FARMER = params.get("farmer") || "F0001";
const SCREENS = ["start", "idle", "ring", "call", "camera", "photo"];
const RETAKE_BELOW = 0.45;
const LABEL = { hail_damage: "Hail damage", waterlogged: "Field under water", lodged: "Crop flattened", healthy: "Crop is healthy", not_a_crop: "Not a crop photo" };

const state = {
  started: false, screen: "start", back: "idle",
  ringing: null,            // {call_id, case_id, caller_name}
  ringingSince: 0,
  handled: new Set(),       // call ids answered, declined or cancelled here: a late poll must not ring them again
  call: null,               // {call_id, case_id, room, startedAt}
  room: null, muted: false,
  lastCase: null,           // the case photos belong to when no call is running
  photo: null,              // {blob, url, result, capturedAt, offline}
  retakeAsked: false,
  model: "loading",
  stream: null, audio: null, ringTimer: null, callTimer: null,
};
try { state.lastCase = localStorage.getItem("ghante.lastCase"); } catch { /* private mode */ }

// ---------- screens ----------
function show(name) {
  state.screen = name;
  for (const s of SCREENS) $(`screen-${s}`).hidden = s !== name;
}
function home() { show(state.call ? "call" : "idle"); }
function setPill(id, text, cls) {
  const el = $(id);
  el.textContent = text;
  el.className = `pill${cls ? ` ${cls}` : ""}`;
}
function note(text) {
  const el = $("queue-note");
  el.textContent = text || "";
  el.hidden = !text;
}

// ---------- on-phone photo check (Web Worker) ----------
let worker = null, jobs = new Map(), jobId = 0;
function startWorker() {
  try {
    worker = new Worker("/static/edge-worker.js", { type: "module" });
  } catch (err) {
    state.model = "error";
    setPill("model", "Photo check unavailable", "bad");
    return;
  }
  worker.onmessage = (ev) => {
    const m = ev.data || {};
    if (m.type === "progress") setPill("model", `Photo check loading ${m.percent}%`);
    else if (m.type === "ready") { state.model = "ready"; setPill("model", "Photo check ready", "ok"); window.__edge = m; }
    else if (m.type === "error") { state.model = "error"; setPill("model", "Photo check unavailable", "bad"); window.__edgeError = m.message; failJobs(m.message); }
    else if (m.type === "result" || m.type === "failed") {
      const job = jobs.get(m.id);
      if (job) { jobs.delete(m.id); job(m.type === "result" ? m : null); }
    }
  };
  worker.onerror = (ev) => { state.model = "error"; setPill("model", "Photo check unavailable", "bad"); window.__edgeError = ev.message || "worker failed"; failJobs(); };
  worker.postMessage({ type: "load", dtype: params.get("dtype") || undefined });
}
function failJobs() { for (const job of jobs.values()) job(null); jobs.clear(); }
function classify(blob) {
  if (!worker || state.model === "error") return Promise.resolve(null);
  return new Promise((resolve) => {
    const id = ++jobId;
    const timer = setTimeout(() => { jobs.delete(id); resolve(null); }, 30000);
    jobs.set(id, (result) => { clearTimeout(timer); resolve(result); });
    worker.postMessage({ type: "classify", id, blob });
  });
}

// ---------- the queue of photos on the phone (IndexedDB) ----------
function db() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("ghante72", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("captures", { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function store(mode, fn) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const tx = d.transaction("captures", mode);
    const out = fn(tx.objectStore("captures"));
    tx.oncomplete = () => resolve(out && "result" in out ? out.result : undefined);
    tx.onerror = () => reject(tx.error);
  });
}
const queuePut = (item) => store("readwrite", (s) => s.put(item));
const queueAll = () => store("readonly", (s) => s.getAll());

let syncing = false;
async function sync() {
  if (syncing || !navigator.onLine) return;
  syncing = true;
  try {
    const items = (await queueAll()) || [];
    let waiting = 0;
    for (const item of items) {
      if (item.state !== "pending") continue;
      const caseId = item.case_id || state.lastCase;
      if (!caseId) { waiting += 1; continue; }
      const form = new FormData();
      form.append("photo", item.blob, "photo.jpg");
      form.append("meta", JSON.stringify(item.meta));
      let res;
      try { res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/evidence`, { method: "POST", body: form }); } catch { waiting += 1; break; }
      if (res.ok) {
        const out = await res.json();
        await queuePut({ ...item, case_id: caseId, state: "uploaded", evidence_id: out.evidence_id, uploaded_at: new Date().toISOString() });
        tellAgent(caseId, out.evidence_id, item.meta);
      } else if (res.status >= 500 || res.status === 404) {
        waiting += 1;   // the server is not ready for it yet: keep it
      } else {
        await queuePut({ ...item, state: "refused", error: res.status });
      }
    }
    note(waiting ? `${waiting} photo${waiting === 1 ? " is" : "s are"} saved on the phone and will be sent automatically when the network is back.` : "");
    window.__queue = { waiting, total: items.length };
  } finally {
    syncing = false;
  }
}
function tellAgent(caseId, evidenceId, meta) {
  // The agent on the call learns about the photo on the room's data channel (SystemDesign §10.5).
  if (!state.room || !state.call || state.call.case_id !== caseId) return;
  const payload = new TextEncoder().encode(JSON.stringify({ evidence_id: evidenceId, edge_label: meta.label, edge_confidence: meta.confidence }));
  try { state.room.localParticipant.publishData(payload, { reliable: true, topic: "evidence" }); } catch (err) { console.warn("could not tell the agent about the photo", err); }
}

// ---------- camera and photo ----------
async function openCamera() {
  state.back = state.call ? "call" : "idle";
  state.retakeAsked = state.retakeAsked && state.screen === "photo";
  show("camera");
  try {
    state.stream = await startCamera();
    $("video").srcObject = state.stream;
    await $("video").play();
  } catch (err) {
    console.warn("camera did not start; opening the photo picker instead:", err && err.name, err && err.message);
    stopCamera();
    $("file").click();   // no camera access: fall back to the system's photo picker
    show(state.back);
  }
}
// A camera that was just released (the shutter, then "retake") can refuse to start again for a moment on some phones, and an
// exact size request can be refused outright. Try the preferred settings, then simpler ones, with a short pause between.
async function startCamera() {
  const asks = [{ video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false },
                { video: { facingMode: { ideal: "environment" } }, audio: false },
                { video: true, audio: false }];
  let last = null;
  for (const ask of asks) {
    try {
      return await navigator.mediaDevices.getUserMedia(ask);
    } catch (err) {
      last = err;
      console.warn("camera attempt failed:", err && err.name, err && err.message);
      if (err && err.name === "NotAllowedError") break;   // permission refused: asking again changes nothing
      await new Promise((resolve) => setTimeout(resolve, 400));
    }
  }
  throw last;
}
function stopCamera() {
  if (state.stream) for (const track of state.stream.getTracks()) track.stop();
  state.stream = null;
  $("video").srcObject = null;
}
function shoot() {
  const video = $("video");
  if (!video.videoWidth) return;
  const scale = Math.min(1, 1024 / Math.max(video.videoWidth, video.videoHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  canvas.toBlob((blob) => { stopCamera(); if (blob) review(blob); else show(state.back); }, "image/jpeg", 0.85);
}
async function review(blob) {
  if (state.photo && state.photo.url) URL.revokeObjectURL(state.photo.url);
  state.photo = { blob, url: URL.createObjectURL(blob), result: null, capturedAt: new Date().toISOString(), offline: !navigator.onLine };
  $("thumb").src = state.photo.url;
  $("photo-label").textContent = "Checking";
  $("photo-detail").textContent = "";
  $("photo-warn").hidden = true;
  $("btn-send").disabled = true;
  show("photo");
  const result = await classify(blob);
  if (!state.photo || state.photo.blob !== blob) return;
  state.photo.result = result;
  $("btn-send").disabled = false;
  if (!result) {
    $("photo-label").textContent = "Photo taken";
    $("photo-detail").textContent = "The check on the phone is not available. The photo will be sent as it is.";
    return;
  }
  $("photo-label").textContent = LABEL[result.label] || result.label;
  $("photo-detail").textContent = `Confidence ${Math.round(result.confidence * 100)}%. Checked on the phone in ${Math.round(result.ms)} ms. No internet needed.`;
  const weak = result.label === "not_a_crop" || result.confidence < RETAKE_BELOW;
  if (weak && !state.retakeAsked) {
    state.retakeAsked = true;
    $("photo-warn").textContent = result.label === "not_a_crop" ? "No crop can be seen in this photo. Please take a photo of the damaged crop again." : "The photo is not clear. Please take it once more.";
    $("photo-warn").hidden = false;
    $("btn-send").textContent = "Send anyway";
  } else {
    $("btn-send").textContent = "Send";
  }
  window.__lastResult = result;
}
function position() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    const timer = setTimeout(() => resolve(null), 5000);
    navigator.geolocation.getCurrentPosition(
      (p) => { clearTimeout(timer); resolve({ lat: p.coords.latitude, lon: p.coords.longitude }); },
      () => { clearTimeout(timer); resolve(null); },
      { enableHighAccuracy: true, timeout: 5000, maximumAge: 60000 });
  });
}
async function sendPhoto() {
  const photo = state.photo;
  if (!photo) return;
  $("btn-send").disabled = true;
  const where = await position();
  const r = photo.result;
  const meta = {
    label: r ? r.label : null, confidence: r ? Number(r.confidence.toFixed(4)) : null, latency_ms: r ? Math.round(r.ms) : null,
    edge_mode: r ? "zeroshot" : "none", lat: where ? where.lat : null, lon: where ? where.lon : null, gps_source: where ? "phone" : "none",
    captured_at: photo.capturedAt, captured_offline: photo.offline || !navigator.onLine,
  };
  const id = `cap_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  await queuePut({ id, case_id: state.call ? state.call.case_id : state.lastCase, blob: photo.blob, meta, state: "pending" });
  state.retakeAsked = false;
  $("btn-send").textContent = "Send";
  home();
  if (!navigator.onLine) note("The photo is saved on the phone and will be sent automatically when the network is back.");
  sync();
}

// ---------- calls ----------
function beep(on) {
  clearInterval(state.ringTimer);
  state.ringTimer = null;
  if (navigator.vibrate) navigator.vibrate(0);
  if (!on) return;
  const ring = () => {
    if (navigator.vibrate) navigator.vibrate([350, 150, 350]);
    if (!state.audio) return;
    for (const [at, freq] of [[0, 880], [0.28, 660]]) {
      const osc = state.audio.createOscillator(), gain = state.audio.createGain();
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, state.audio.currentTime + at);
      gain.gain.exponentialRampToValueAtTime(0.25, state.audio.currentTime + at + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.0001, state.audio.currentTime + at + 0.24);
      osc.connect(gain).connect(state.audio.destination);
      osc.start(state.audio.currentTime + at);
      osc.stop(state.audio.currentTime + at + 0.26);
    }
  };
  ring();
  state.ringTimer = setInterval(ring, 1400);
}
function incoming(data) {
  if (state.call) return;   // already on a call
  if (state.ringing && state.ringing.call_id === data.call_id) return;   // already ringing (stream and poll both report it)
  state.ringing = data;
  state.ringingSince = Date.now();
  if (data.case_id) rememberCase(data.case_id);
  $("caller").textContent = data.caller_name || "Crop Insurance Help";
  if (!state.started) { $("screen-start").querySelector(".lead").textContent = "A call is coming in. Turn on the phone."; return; }
  stopCamera();
  show("ring");
  beep(true);
}
function rememberCase(caseId) {
  state.lastCase = caseId;
  try { localStorage.setItem("ghante.lastCase", caseId); } catch { /* private mode */ }
}
async function accept() {
  const ringing = state.ringing;
  if (!ringing) return;
  state.handled.add(ringing.call_id);
  beep(false);
  state.ringing = null;
  state.call = { call_id: ringing.call_id, case_id: ringing.case_id, startedAt: Date.now() };
  state.muted = false;
  $("btn-mute").setAttribute("aria-pressed", "false");
  $("btn-mute").textContent = "Mute";
  $("call-state").textContent = "Connecting";
  $("timer").textContent = "0:00";
  show("call");
  try {
    const res = await fetch(`/api/calls/${encodeURIComponent(ringing.call_id)}/accept`, { method: "POST" });
    if (!res.ok) throw new Error(`accept ${res.status}`);
    const info = await res.json();
    const LK = window.LivekitClient;
    if (!LK) throw new Error("call library not loaded");
    const room = new LK.Room();
    state.room = room;
    room.on(LK.RoomEvent.TrackSubscribed, (track) => {
      if (track.kind !== LK.Track.Kind.Audio) return;
      const el = track.attach();
      el.autoplay = true;
      $("audio-host").append(el);
    });
    room.on(LK.RoomEvent.Disconnected, () => endCall(false));
    await room.connect(info.livekit_url, info.token);
    await room.startAudio().catch(() => {});
    try {
      await room.localParticipant.setMicrophoneEnabled(true);
    } catch (err) {
      // connected, but the browser refused the microphone: say so, because "call failed" would send the farmer looking for a network problem
      window.__callError = `microphone: ${String(err && err.message || err)}`;
      $("call-state").textContent = "Microphone permission was not given. Allow the microphone in the browser.";
      setTimeout(() => endCall(true), 4000);
      return;
    }
    $("call-state").textContent = "Call in progress";
    clearInterval(state.callTimer);
    state.callTimer = setInterval(() => {
      const s = Math.floor((Date.now() - state.call.startedAt) / 1000);
      $("timer").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    }, 500);
  } catch (err) {
    console.error("call failed", err);
    window.__callError = String(err && err.message || err);
    $("call-state").textContent = "The call could not connect";
    setTimeout(() => endCall(true), 1500);
  }
}
async function decline() {
  const ringing = state.ringing;
  if (ringing) state.handled.add(ringing.call_id);
  beep(false);
  state.ringing = null;
  show("idle");
  if (ringing) fetch(`/api/calls/${encodeURIComponent(ringing.call_id)}/decline`, { method: "POST" }).catch(() => {});
}
async function endCall(byFarmer) {
  const call = state.call;
  if (!call) return;
  state.call = null;
  clearInterval(state.callTimer);
  stopCamera();
  const room = state.room;
  state.room = null;
  $("audio-host").replaceChildren();
  if (room) { try { await room.disconnect(); } catch { /* already gone */ } }
  // The first report of how a call ended wins, so this changes nothing when the assistant has already closed the call.
  fetch(`/api/calls/${encodeURIComponent(call.call_id)}/end`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outcome: "dropped" }) }).catch(() => {});
  $("idle-text").textContent = byFarmer ? "Call ended." : "Call finished.";
  if (state.screen !== "photo" && state.screen !== "camera") show("idle");
}
function toggleMute() {
  if (!state.room) return;
  state.muted = !state.muted;
  state.room.localParticipant.setMicrophoneEnabled(!state.muted);
  $("btn-mute").setAttribute("aria-pressed", String(state.muted));
  $("btn-mute").textContent = state.muted ? "Unmute" : "Mute";
}

// ---------- messages from the server ----------
const shownCards = new Set();
function addCard(data) {
  // The server sends a filed-report message again when the phone reconnects, so that a phone that was offline still gets it.
  const key = data.claim_ref || data.text || "";
  if (shownCards.has(key)) return;
  shownCards.add(key);
  const li = document.createElement("li");
  const text = document.createElement("div");
  text.textContent = data.text || "";
  li.append(text);
  if (data.claim_ref) { const ref = document.createElement("div"); ref.className = "ref"; ref.textContent = data.claim_ref; li.append(ref); }
  const small = document.createElement("div");
  small.className = "note"; small.lang = "en";
  small.textContent = "Demo message (simulated SMS)";
  li.append(small);
  $("cards").prepend(li);
}
function cancelled(callId) {
  if (!state.ringing || state.ringing.call_id !== callId) return;
  state.handled.add(callId);
  beep(false); state.ringing = null;
  if (state.started) show("idle");
  $("idle-text").textContent = "You missed a call.";
}
// Backup for the event stream: some tunnels (the phone link) hold streamed replies back, so the ring would never arrive.
async function poll() {
  let out;
  try {
    const res = await fetch(`/api/farmer/${encodeURIComponent(FARMER)}/poll`, { cache: "no-store" });
    if (!res.ok) return;
    out = await res.json();
  } catch { return; }
  setPill("net", "Online", "ok");
  const ring = out.ringing;
  if (ring && ring.call_id) { if (!state.handled.has(ring.call_id)) incoming(ring); }
  else { state.handled.clear(); }   // nothing rings on the server: call ids may be reused after a reset
  if (!ring && state.ringing && Date.now() - state.ringingSince > 5000) cancelled(state.ringing.call_id);
  for (const m of out.messages || []) if (m.type === "message") addCard(m.data || {});
}
function connect() {
  const es = new EventSource(`/api/farmer/${encodeURIComponent(FARMER)}/stream`);
  es.onopen = () => setPill("net", "Online", "ok");
  es.onerror = () => setPill("net", navigator.onLine ? "Cannot reach the server" : "No network", "bad");
  es.onmessage = (m) => {
    let e;
    try { e = JSON.parse(m.data); } catch { return; }
    if (e.type === "call.incoming") incoming(e.data || {});
    else if (e.type === "call.cancelled") cancelled((e.data || {}).call_id);
    else if (e.type === "message") addCard(e.data || {});
  };
}

// ---------- start ----------
async function start() {
  state.started = true;
  try { state.audio = new (window.AudioContext || window.webkitAudioContext)(); await state.audio.resume(); } catch { state.audio = null; }
  // Ask for the microphone now, with the farmer looking at the phone, instead of in the first seconds of a call.
  try { const mic = await navigator.mediaDevices.getUserMedia({ audio: true }); for (const t of mic.getTracks()) t.stop(); } catch { /* asked again when a call is answered */ }
  position();
  if (state.ringing) { const r = state.ringing; state.ringing = null; show("idle"); incoming(r); } else show("idle");
}

async function who() {
  $("foot-id").textContent = FARMER;
  try {
    const res = await fetch(`/api/farmers/${encodeURIComponent(FARMER)}`);
    if (res.ok) { const f = await res.json(); $("who").textContent = `${f.name}, ${f.village || ""}`; }
  } catch { /* shown without the name */ }
}

$("btn-start").addEventListener("click", start);
$("btn-accept").addEventListener("click", accept);
$("btn-decline").addEventListener("click", decline);
$("btn-hangup").addEventListener("click", () => endCall(true));
$("btn-mute").addEventListener("click", toggleMute);
$("btn-photo-idle").addEventListener("click", openCamera);
$("btn-photo-call").addEventListener("click", openCamera);
$("btn-camera-cancel").addEventListener("click", () => { stopCamera(); show(state.back); });
$("btn-shutter").addEventListener("click", shoot);
$("btn-retake").addEventListener("click", openCamera);
$("btn-send").addEventListener("click", sendPhoto);
$("file").addEventListener("change", (ev) => { const f = ev.target.files && ev.target.files[0]; ev.target.value = ""; if (f) { stopCamera(); state.back = state.call ? "call" : "idle"; review(f); } });
window.addEventListener("online", () => { setPill("net", "Online", "ok"); sync(); });
window.addEventListener("offline", () => setPill("net", "No network", "bad"));
setInterval(sync, 4000);
setInterval(poll, 2000);

who();
connect();
startWorker();
sync();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
if (params.get("autostart") === "1") start();
window.__farmer = state;   // for the automated check
