"""Phase 0 spike T0-2: load Laya (open System One model) and measure speed and accuracy on this machine.

Prints everything to stdout. Needs no API key.
"""
from __future__ import annotations
import json, platform, statistics, sys, time, traceback

MODEL = "convaiinnovations/laya-multilingual"

ROUTE_Q = {
    "intent": {
        "type": "choice",
        "instructions": "A phone agent asked `agent_question`. What is the farmer doing in `farmer_reply`?",
        "criteria": {
            "yes": "a plain yes, agreement or confirmation, with no new facts",
            "no": "a plain no, refusal or denial",
            "gives_details": "states facts such as cause of damage, time, how much area, or crop stage",
            "asks_question": "asks the agent a question, for example about money or the survey",
            "wants_human": "asks to talk to a person or an officer instead of the assistant",
            "wrong_person": "says it is a wrong number or that they are not the person asked for",
            "unclear": "unrelated, garbled or impossible to understand",
        },
    },
    "distress": {"type": "noul", "instructions": "Is the speaker in `farmer_reply` crying, panicking or very angry?"},
}
PERIL_Q = {
    "peril": {
        "type": "choice",
        "instructions": "What caused the crop damage described in `cause_text`?",
        "criteria": {
            "hailstorm": "hail, hailstones, ole",
            "inundation": "flooding or standing water in the field",
            "unseasonal_rain": "rain falling on a crop that was already cut",
            "natural_fire": "fire or lightning",
            "not_covered": "pests, insects, disease, drought, animals or theft",
        },
    }
}
TRIAGE_Q = {
    "damage_likelihood": {
        "type": "choice",
        "instructions": "How likely is serious crop damage on this farm after the storm?",
        "criteria": {
            "high": "severe hail, crop near harvest, or within a few km of the storm core",
            "medium": "moderate hail or middle distance",
            "low": "light hail, far from the core, or an early-stage crop",
        },
    }
}

ASK = {
    "identity": "क्या मेरी बात रामलाल जी से हो रही है?",
    "damage": "क्या आपकी गेहूँ की फसल को नुकसान हुआ है?",
    "khasra": "क्या नुकसान खसरा नंबर 214 वाले खेत में हुआ है?",
    "cause": "नुकसान किस वजह से हुआ?",
    "time": "यह लगभग कितने बजे हुआ?",
    "extent": "खेत के लगभग कितने हिस्से में नुकसान है?",
    "stage": "फसल खेत में खड़ी थी, या कटकर रखी थी?",
    "consent": "क्या मैं आपकी तरफ़ से यह सूचना दर्ज कर दूँ?",
}
ROUTE_CASES = [
    ("identity", "हाँ, बोल रहा हूँ।", "yes"),
    ("damage", "हाँ, बहुत नुकसान हुआ है।", "yes"),
    ("cause", "ओले गिरे थे, पूरी फसल बिछ गई।", "gives_details"),
    ("time", "दोपहर करीब साढ़े तीन बजे।", "gives_details"),
    ("extent", "आधे से ज़्यादा खेत खराब हो गया।", "gives_details"),
    ("stage", "फसल खड़ी थी, कटाई बाकी थी।", "gives_details"),
    ("extent", "पैसा कब तक मिलेगा?", "asks_question"),
    ("khasra", "नहीं।", "no"),
    ("cause", "मुझे किसी आदमी से बात करनी है।", "wants_human"),
    ("consent", "हाँ, कर दीजिए।", "yes"),
    ("identity", "नहीं, गलत नंबर है।", "wrong_person"),
    ("damage", "नहीं, फसल ठीक है।", "no"),
    ("consent", "नहीं, अभी मत कीजिए।", "no"),
    ("damage", "हाँ जी, full damage हो गया।", "yes"),
    ("time", "सर्वे वाला कब आएगा?", "asks_question"),
    ("khasra", "हाँ, वही खेत है।", "yes"),
]
PERIL_CASES = [
    ("ओले गिरे थे, गेहूँ पूरा बिछ गया।", "hailstorm"),
    ("कीड़े लग गए थे फसल में।", "not_covered"),
    ("खेत में पानी भर गया है।", "inundation"),
    ("कटी हुई फसल बारिश में भीग गई।", "unseasonal_rain"),
    ("बहुत बड़े-बड़े ओले पड़े।", "hailstorm"),
    ("नीलगाय फसल खा गई।", "not_covered"),
]


def pick(answer):
    """Return (label, confidence) from whatever shape the library gives."""
    if isinstance(answer, dict):
        label = answer.get("choice", answer.get("value", answer.get("answer")))
        conf = answer.get("confidence", answer.get("probability", answer.get("p")))
        probs = answer.get("probabilities") or answer.get("probs")
        if conf is None and isinstance(probs, dict) and label in probs:
            conf = probs[label]
        return label, conf
    return answer, None


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def main():
    print("python", sys.version.split()[0], "|", platform.platform(), "|", platform.processor())
    try:
        import torch
        print("torch", torch.__version__, "| cuda:", torch.cuda.is_available(), "| threads:", torch.get_num_threads())
    except Exception as e:
        print("torch not importable:", e)
    import laya
    print("laya", getattr(laya, "__version__", "?"), "| exports:", [n for n in dir(laya) if not n.startswith("_")][:30])

    t0 = time.perf_counter()
    agent = laya.load(MODEL)
    print(f"model load: {time.perf_counter() - t0:.1f} s")

    q, text, _ = ROUTE_CASES[0]
    t0 = time.perf_counter()
    first = agent.predict({"agent_question": ASK[q], "farmer_reply": text}, ROUTE_Q)
    print(f"first call (warm-up): {(time.perf_counter() - t0) * 1000:.0f} ms")
    print("RAW RESULT SHAPE:", json.dumps(first, ensure_ascii=False, default=str)[:1500])

    print("\n== ROUTE (2 questions per call) ==")
    times, ok = [], 0
    for q, text, want in ROUTE_CASES:
        t0 = time.perf_counter()
        r = agent.predict({"agent_question": ASK[q], "farmer_reply": text}, ROUTE_Q)
        ms = (time.perf_counter() - t0) * 1000
        times.append(ms)
        got, conf = pick(r["answers"]["intent"])
        ok += got == want
        conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else str(conf)
        print(f"{'OK ' if got == want else 'BAD'} want={want:<14} got={str(got):<14} conf={conf_s:<5} {ms:5.0f} ms | {text}")
    print(f"ROUTE accuracy {ok}/{len(ROUTE_CASES)} | median {statistics.median(times):.0f} ms | p95 {pct(times, 0.95):.0f} ms | max {max(times):.0f} ms")

    print("\n== PERIL (1 question per call) ==")
    times, ok = [], 0
    for text, want in PERIL_CASES:
        t0 = time.perf_counter()
        r = agent.predict({"cause_text": text, "crop_stage": "standing"}, PERIL_Q)
        ms = (time.perf_counter() - t0) * 1000
        times.append(ms)
        got, conf = pick(r["answers"]["peril"])
        ok += got == want
        print(f"{'OK ' if got == want else 'BAD'} want={want:<16} got={str(got):<16} {ms:5.0f} ms | {text}")
    print(f"PERIL accuracy {ok}/{len(PERIL_CASES)} | median {statistics.median(times):.0f} ms")

    print("\n== TRIAGE: 30 farms one after another (fleet estimate) ==")
    farms = []
    for i in range(30):
        inten = ["severe", "moderate", "light"][i % 3]
        farms.append({"crop": "wheat", "crop_stage": "near harvest", "hail_intensity": inten,
                      "distance_km_from_storm_core": [2, 7, 13][i % 3], "insured_area_ha": 1.0 + (i % 5) * 0.4})
    t0 = time.perf_counter()
    labels = []
    for f in farms:
        r = agent.predict(f, TRIAGE_Q)
        labels.append(pick(r["answers"]["damage_likelihood"])[0])
    total = time.perf_counter() - t0
    print(f"30 decisions in {total:.2f} s = {total / 30 * 1000:.0f} ms each -> 340 farms would take about {total / 30 * 340:.0f} s")
    print("labels by intensity (severe, moderate, light repeating):", labels[:9])
    print("\nSPIKE OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("\nSPIKE FAILED")
