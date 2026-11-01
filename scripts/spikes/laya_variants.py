"""Phase 0 spike T0-2b: does better question design fix Laya's zero-shot accuracy on Hindi? Compact output."""
from __future__ import annotations
import statistics, sys, time, traceback
from laya_speed import ASK, ROUTE_CASES, PERIL_CASES, ROUTE_Q, PERIL_Q, pick, MODEL

EXTRA_ROUTE = [
    ("damage", "जी हाँ।", "yes"), ("khasra", "हाँ हाँ, वही है।", "yes"), ("consent", "ठीक है, कर दो।", "yes"),
    ("damage", "ना, कुछ नहीं हुआ।", "no"), ("khasra", "नहीं नहीं।", "no"),
    ("extent", "पूरा खेत बर्बाद हो गया, कुछ नहीं बचा।", "gives_details"),
    ("cause", "किसी साहब से बात करवा दो।", "wants_human"), ("identity", "आप कौन? यहाँ कोई रामलाल नहीं रहता।", "wrong_person"),
]
CASES = ROUTE_CASES + EXTRA_ROUTE

R2 = {"intent": {"type": "choice", "instructions": "Classify the Hindi phone reply in `farmer_reply`.", "criteria": {
    "yes": "हाँ, जी हाँ, हाँ जी, ठीक है, सही है, कर दीजिए, वही है — agreement only",
    "no": "नहीं, ना, मत कीजिए, ऐसा नहीं है — refusal or denial only",
    "gives_details": "बताता है क्या हुआ: ओले गिरे, फसल गिर गई, कितने बजे, कितना खेत खराब, फसल खड़ी थी — facts about damage, time, area",
    "asks_question": "सवाल पूछता है: कब मिलेगा? कौन आएगा? कितना पैसा? — a question to the agent",
    "wants_human": "किसी आदमी, साहब या अधिकारी से बात करनी है — wants a human",
    "wrong_person": "गलत नंबर, यहाँ कोई नहीं रहता, मैं वह नहीं हूँ — wrong number",
    "unclear": "समझ नहीं आया, असंबंधित बात — unrelated or garbled"}}}
R3 = {"answer": {"type": "choice", "instructions": "The agent asked a yes/no question: `agent_question`. How does `farmer_reply` answer it?", "criteria": {
    "yes": "हाँ, जी हाँ, ठीक है, सही, कर दीजिए — says yes",
    "no": "नहीं, ना, मत कीजिए, ठीक है फसल, गलत — says no",
    "other": "not a yes or no: gives other information, asks something, or wants a person"}}}
R4 = {"said_yes": {"type": "noul", "instructions": "Does `farmer_reply` say yes or agree (हाँ, जी हाँ, ठीक है, कर दीजिए)?"},
      "said_no": {"type": "noul", "instructions": "Does `farmer_reply` say no or refuse (नहीं, ना, मत कीजिए)?"},
      "wants_human": {"type": "noul", "instructions": "Does `farmer_reply` ask to talk to a person, sahab or officer?"},
      "is_question": {"type": "noul", "instructions": "Is `farmer_reply` a question asked to the agent?"}}
P2 = {"peril": {"type": "choice", "instructions": "What damaged the crop according to `cause_text`?", "criteria": {
    "hailstorm": "ओले, ओलावृष्टि, ओले गिरे, बर्फ़ के गोले — hail",
    "inundation": "खेत में पानी भर गया, बाढ़, जलभराव — flood water standing in the field",
    "unseasonal_rain": "कटी हुई फसल बारिश में भीग गई — rain on a harvested crop",
    "natural_fire": "आग, बिजली गिरी — fire or lightning",
    "not_covered": "कीड़े, रोग, सूखा, जानवर, नीलगाय, चोरी — pests, disease, drought, animals, theft"}}}
T2 = {"damage_likelihood": {"type": "choice", "instructions": "Read `report`. How likely is serious crop damage on this farm?", "criteria": {
    "high": "severe hail and the farm is very close to the storm core",
    "medium": "moderate hail at a middle distance",
    "low": "light hail and the farm is far from the storm core"}}}

def timed(agent, state, q):
    t0 = time.perf_counter(); r = agent.predict(state, q); return r, (time.perf_counter() - t0) * 1000

def run_route(agent, name, q, mode):
    ok, ms, bad = 0, [], []
    for step, text, want in CASES:
        state = {"farmer_reply": text} if mode == "reply_only" else {"agent_question": ASK[step], "farmer_reply": text}
        r, t = timed(agent, state, q); ms.append(t); a = r["answers"]
        if mode == "three":
            got = pick(a["answer"])[0]; want2 = want if want in ("yes", "no") else "other"
        elif mode == "nouls":
            p = {k: a[k]["noul"] for k in a}
            got = "wants_human" if p["wants_human"] > 0.5 else "asks_question" if p["is_question"] > 0.5 else "yes" if p["said_yes"] > max(0.5, p["said_no"]) else "no" if p["said_no"] > 0.5 else "other"
            want2 = want if want in ("yes", "no", "wants_human", "asks_question") else "other"
        else:
            got = pick(a["intent"])[0]; want2 = want
        ok += got == want2
        if got != want2: bad.append(f"{text} -> {got} (want {want2})")
    print(f"{name}: {ok}/{len(CASES)} | median {statistics.median(ms):.0f} ms")
    for b in bad[:12]: print("    miss:", b)

def main():
    import laya, torch
    t0 = time.perf_counter(); agent = laya.load(MODEL); print(f"load (cached): {time.perf_counter() - t0:.1f} s | threads {torch.get_num_threads()}")
    agent.predict({"farmer_reply": "हाँ"}, R3)
    run_route(agent, "ROUTE v1 baseline 7-way (English criteria)", {"intent": ROUTE_Q["intent"]}, "seven")
    run_route(agent, "ROUTE v2 7-way, Hindi example criteria", R2, "seven")
    run_route(agent, "ROUTE v2b same, reply only (no agent question)", R2, "reply_only")
    run_route(agent, "ROUTE v3 yes/no/other", R3, "three")
    run_route(agent, "ROUTE v4 four yes/no questions", R4, "nouls")
    for name, q in (("PERIL v1 English criteria", PERIL_Q), ("PERIL v2 Hindi keyword criteria", P2)):
        ok, ms, bad = 0, [], []
        for text, want in PERIL_CASES + [("ओलावृष्टि से सब खत्म हो गया।", "hailstorm"), ("इल्ली लग गई थी।", "not_covered"), ("बाढ़ का पानी घुस गया।", "inundation")]:
            r, t = timed(agent, {"cause_text": text}, q); ms.append(t); got = pick(r["answers"]["peril"])[0]; ok += got == want
            if got != want: bad.append(f"{text} -> {got} (want {want})")
        print(f"{name}: {ok}/9 | median {statistics.median(ms):.0f} ms")
        for b in bad: print("    miss:", b)
    print("TRIAGE v2 (sentence report):")
    for inten, km, want in (("severe", 2, "high"), ("severe", 4, "high"), ("moderate", 7, "medium"), ("moderate", 9, "medium"), ("light", 13, "low"), ("light", 15, "low")):
        rep = f"Hail intensity at this village was {inten}. The farm is {km} km from the storm core. Crop: wheat, close to harvest."
        r, t = timed(agent, {"report": rep}, T2); a = r["answers"]["damage_likelihood"]
        print(f"    {inten:<9}{km:>3} km -> {a['choice']:<7} probs {a['probabilities']} {t:.0f} ms (want {want})")
    print("SPIKE OK")

if __name__ == "__main__":
    try: main()
    except Exception: traceback.print_exc(file=sys.stdout); print("SPIKE FAILED")
