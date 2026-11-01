r"""Compute the label half of the on-phone photo check once, on the laptop (SystemDesign §11).

    .venv\Scripts\python.exe scripts\build_label_embeddings.py

MobileCLIP-S0 compares a photo with short English descriptions of each label. The descriptions never change, so their
embeddings are computed here with the model's text encoder and saved to apps/web/label_embeddings.json. The phone then loads
only the image encoder. Needs: transformers (tokenizer), onnxruntime, huggingface_hub; downloads the text encoder once (about 170 MB).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL = "Xenova/mobileclip_s0"
OUT = ROOT / "apps" / "web" / "label_embeddings.json"
# Several descriptions per label; their embeddings are averaged (SystemDesign §11).
LABELS = [
    ("hail_damage", "Hail damage", ["a wheat field damaged by hail with broken stems and shredded leaves", "crops battered by a hailstorm, hailstones on the ground"]),
    ("waterlogged", "Field under water", ["a flooded crop field with standing water", "waterlogged farmland after heavy rain"]),
    ("lodged", "Crop flattened", ["a wheat crop flattened to the ground by wind and rain", "lodged cereal crop lying flat"]),
    ("healthy", "Crop is healthy", ["a healthy standing wheat field", "an undamaged crop field"]),
    ("not_a_crop", "Not a crop photo", ["an indoor photo", "a photo of a person", "a photo of a wall or a floor", "a screenshot"]),
]


def main() -> int:
    import numpy as np
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer

    t0 = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(MODEL)
    path = hf_hub_download(MODEL, "onnx/text_model.onnx")
    session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    wanted = [i.name for i in session.get_inputs()]
    print(f"text encoder loaded in {time.perf_counter() - t0:.1f} s; inputs {wanted}; outputs {[o.name for o in session.get_outputs()]}")

    def embed(texts: list[str]):
        enc = tokenizer(texts, padding="max_length", truncation=True, return_tensors="np")
        feeds = {name: enc[name].astype(np.int64) for name in wanted if name in enc}
        out = session.run(None, feeds)
        names = [o.name for o in session.get_outputs()]
        vectors = out[names.index("text_embeds")] if "text_embeds" in names else out[0]
        return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)

    labels = []
    for label, name, prompts in LABELS:
        mean = embed(prompts).mean(axis=0)
        mean = mean / np.linalg.norm(mean)
        labels.append({"id": label, "name": name, "prompts": prompts, "embedding": [round(float(x), 6) for x in mean]})
    matrix = np.array([l["embedding"] for l in labels])
    sims = matrix @ matrix.T
    print("how alike the labels are to each other (1.00 = identical):")
    for l, row in zip(labels, sims):
        print(f"  {l['id']:<12}" + " ".join(f"{v:5.2f}" for v in row))
    OUT.write_text(json.dumps({"model": MODEL, "text_dtype": "fp32", "vision_dtype": "fp32", "temperature": 100, "dim": int(matrix.shape[1]),
                               "labels": labels}, ensure_ascii=False), encoding="utf-8", newline="\n")
    print(f"saved {OUT.relative_to(ROOT)}: {len(labels)} labels, {matrix.shape[1]} numbers each, {OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
