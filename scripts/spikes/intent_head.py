"""Phase 0 spike T0-2c (B): a small trained decision head for Hindi replies.

Sentence embedding (small multilingual encoder) + softmax regression trained on scripts/spikes/intent_data.py.
Non-generative, returns probabilities, runs on CPU.
"""
from __future__ import annotations
import statistics, sys, time, traceback
import numpy as np
from intent_data import ROUTE_TRAIN, ROUTE_TEST, PERIL_TRAIN, PERIL_TEST

def train_softmax(X, y, n_classes, l2=1e-2, lr=0.5, steps=600):
    """Plain softmax regression by gradient descent. X: (n, d) L2-normalised, y: (n,) ints."""
    n, d = X.shape
    W = np.zeros((n_classes, d)); b = np.zeros(n_classes)
    Y = np.eye(n_classes)[y]
    for _ in range(steps):
        z = X @ W.T + b; z -= z.max(1, keepdims=True)
        P = np.exp(z); P /= P.sum(1, keepdims=True)
        G = (P - Y) / n
        W -= lr * (G.T @ X + l2 * W); b -= lr * G.sum(0)
    return W, b

def predict(W, b, X, scale=1.0):
    z = scale * (X @ W.T + b); z -= z.max(1, keepdims=True)
    P = np.exp(z); return P / P.sum(1, keepdims=True)

def evaluate(name, embed, train, test):
    labels = list(train)
    Xtr = embed([t for l in labels for t in train[l]]); ytr = np.array([i for i, l in enumerate(labels) for _ in train[l]])
    t0 = time.perf_counter(); W, b = train_softmax(Xtr, ytr, len(labels), steps=1500, lr=2.0, l2=1e-3); fit_s = time.perf_counter() - t0
    ms, ok, bad, p_ok, p_bad = [], 0, [], [], []
    for text, want in test:
        t0 = time.perf_counter(); P = predict(W, b, embed([text]), scale=1.0)[0]; ms.append((time.perf_counter() - t0) * 1000)
        got = labels[int(P.argmax())]; p = float(P.max()); ok += got == want
        (p_ok if got == want else p_bad).append(p)
        if got != want: bad.append(f"{text} -> {got} {p:.2f} (want {want})")
    print(f"{name}: {ok}/{len(test)} | median {statistics.median(ms):.0f} ms per reply | fit {fit_s:.1f} s on {len(ytr)} examples | "
          f"mean prob right {statistics.mean(p_ok) if p_ok else 0:.2f}, wrong {statistics.mean(p_bad) if p_bad else 0:.2f}")
    for x in bad: print("    miss:", x)

def make_embedder(model_id, prefix):
    import torch
    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_id); model = AutoModel.from_pretrained(model_id); model.eval()
    def embed(texts):
        with torch.no_grad():
            enc = tok([prefix + t for t in texts], padding=True, truncation=True, max_length=64, return_tensors="pt")
            out = model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            v = (out * mask).sum(1) / mask.sum(1)
            v = torch.nn.functional.normalize(v, dim=-1)
        return v.cpu().numpy().astype(np.float64)
    return embed

def main():
    for model_id, prefix in (("intfloat/multilingual-e5-small", "query: "), ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "")):
        try:
            t0 = time.perf_counter(); embed = make_embedder(model_id, prefix); embed(["हाँ"]); print(f"\n[{model_id}] ready in {time.perf_counter() - t0:.0f} s")
            evaluate("ROUTE head (7 intents)", embed, ROUTE_TRAIN, ROUTE_TEST)
            evaluate("PERIL head (5 perils)", embed, PERIL_TRAIN, PERIL_TEST)
        except Exception:
            print(f"[{model_id}] FAILED"); traceback.print_exc(file=sys.stdout)
    print("B DONE")

if __name__ == "__main__":
    try: main()
    except Exception: traceback.print_exc(file=sys.stdout); print("B FAILED")
