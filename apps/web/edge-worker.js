// On-phone photo check (SystemDesign §11, FR-30). Runs in a Web Worker so the phone stays responsive.
// MobileCLIP-S0's image half runs here through transformers.js (WebAssembly). The label half was computed once on the laptop
// (scripts/build_label_embeddings.py) and arrives as /static/label_embeddings.json, so the phone never loads the text model.
// After the first load the model files are in the browser's cache and the check works with no network.

const LIB = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1";
const MODEL = "Xenova/mobileclip_s0";
let lib = null, processor = null, model = null, labels = null;

function softmax(values) {
  const max = Math.max(...values);
  const exps = values.map((v) => Math.exp(v - max));
  const sum = exps.reduce((a, b) => a + b, 0);
  return exps.map((v) => v / sum);
}
function dot(a, b) {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}

async function load(dtype) {
  const t0 = performance.now();
  const res = await fetch("/static/label_embeddings.json", { cache: "no-cache" });
  if (!res.ok) throw new Error("label_embeddings.json is missing: run scripts/build_label_embeddings.py on the laptop");
  labels = await res.json();
  lib = await import(LIB);
  lib.env.allowLocalModels = false;
  const files = new Map();
  const progress = (p) => {
    if (p.status !== "progress" || !p.total) return;
    files.set(p.file, [p.loaded, p.total]);
    let loaded = 0, total = 0;
    for (const [l, t] of files.values()) { loaded += l; total += t; }
    self.postMessage({ type: "progress", percent: Math.min(99, Math.round((loaded / total) * 100)) });
  };
  processor = await lib.AutoProcessor.from_pretrained(MODEL, { progress_callback: progress });
  model = await lib.CLIPVisionModelWithProjection.from_pretrained(MODEL, { dtype: dtype || labels.vision_dtype || "fp32", device: "wasm", progress_callback: progress });
  // one warm-up run, so the first real photo is not the slow one
  const blank = new lib.RawImage(new Uint8ClampedArray(64 * 64 * 3).fill(128), 64, 64, 3);
  await model(await processor(blank));
  self.postMessage({ type: "ready", ms: Math.round(performance.now() - t0), dtype: dtype || labels.vision_dtype || "fp32", labels: labels.labels.map((l) => l.id) });
}

async function classify(id, blob) {
  const image = await lib.RawImage.fromBlob(blob);
  const inputs = await processor(image);
  const t0 = performance.now();
  const { image_embeds } = await model(inputs);
  const ms = performance.now() - t0;
  const v = image_embeds.normalize(2, -1).tolist()[0];
  const sims = labels.labels.map((l) => dot(v, l.embedding));
  const probs = softmax(sims.map((s) => s * (labels.temperature || 100)));
  let best = 0;
  for (let i = 1; i < probs.length; i++) if (probs[i] > probs[best]) best = i;
  const out = {};
  labels.labels.forEach((l, i) => { out[l.id] = Number(probs[i].toFixed(4)); });
  self.postMessage({ type: "result", id, label: labels.labels[best].id, confidence: probs[best], ms, probs: out });
}

self.onmessage = async (ev) => {
  const m = ev.data || {};
  try {
    if (m.type === "load") await load(m.dtype);
    else if (m.type === "classify") {
      if (!model) throw new Error("model not loaded");
      await classify(m.id, m.blob);
    }
  } catch (err) {
    if (m.type === "classify") self.postMessage({ type: "failed", id: m.id, message: String(err && err.message || err) });
    else self.postMessage({ type: "error", message: String(err && err.message || err) });
  }
};
