"""Phase 0 spike T0-2c (A): Laya accuracy when the Hindi reply is first translated to English."""
from __future__ import annotations
import statistics, sys, time, traceback

ASK_EN = {"identity": "Am I speaking with Ramlal ji?", "damage": "Was your wheat crop damaged?",
          "khasra": "Did the damage happen in the field with khasra number 214?", "cause": "What caused the damage?",
          "time": "At about what time did it happen?", "extent": "About how much of the field is damaged?",
          "stage": "Was the crop standing, or cut and lying in the field?", "consent": "Shall I register this report on your behalf?"}
CASES = [("identity", "Yes, speaking.", "yes"), ("damage", "Yes, there has been a lot of damage.", "yes"),
    ("cause", "Hail fell, the whole crop is flattened.", "gives_details"), ("time", "Around three thirty in the afternoon.", "gives_details"),
    ("extent", "More than half the field is ruined.", "gives_details"), ("stage", "The crop was standing, the harvest was still pending.", "gives_details"),
    ("extent", "When will the money come?", "asks_question"), ("khasra", "No.", "no"), ("cause", "I want to talk to a person.", "wants_human"),
    ("consent", "Yes, please do it.", "yes"), ("identity", "No, it is a wrong number.", "wrong_person"), ("damage", "No, the crop is fine.", "no"),
    ("consent", "No, do not do it now.", "no"), ("damage", "Yes, there is full damage.", "yes"), ("time", "When will the survey person come?", "asks_question"),
    ("khasra", "Yes, that is the field.", "yes"), ("damage", "Yes sir.", "yes"), ("khasra", "Yes yes, that is the one.", "yes"),
    ("consent", "Okay, do it.", "yes"), ("damage", "No, nothing happened.", "no"), ("khasra", "No no.", "no"),
    ("extent", "The whole field is destroyed, nothing is left.", "gives_details"), ("cause", "Connect me to some officer.", "wants_human"),
    ("identity", "Who are you? No Ramlal lives here.", "wrong_person")]
PERIL = [("Hail fell, the wheat is completely flattened.", "hailstorm"), ("Insects attacked the crop.", "not_covered"),
    ("The field is filled with water.", "inundation"), ("The cut crop got soaked in the rain.", "unseasonal_rain"),
    ("Very big hailstones fell.", "hailstorm"), ("Nilgai antelope ate the crop.", "not_covered"),
    ("Everything was destroyed by the hailstorm.", "hailstorm"), ("Caterpillars infested it.", "not_covered"), ("Flood water came into the field.", "inundation")]
R7 = {"intent": {"type": "choice", "instructions": "A phone agent asked `agent_question`. What is the farmer doing in `farmer_reply`?", "criteria": {
    "yes": "a plain yes, agreement or confirmation", "no": "a plain no, refusal or denial",
    "gives_details": "states facts such as cause of damage, time, how much area, or crop stage",
    "asks_question": "asks the agent a question, for example about money or the survey",
    "wants_human": "asks to talk to a person or an officer instead of the assistant",
    "wrong_person": "says it is a wrong number or that the person asked for is not here",
    "unclear": "unrelated, garbled or impossible to understand"}}}
P5 = {"peril": {"type": "choice", "instructions": "What caused the crop damage described in `cause_text`?", "criteria": {
    "hailstorm": "hail or hailstones", "inundation": "flooding or standing water in the field",
    "unseasonal_rain": "rain falling on a crop that was already cut", "natural_fire": "fire or lightning",
    "not_covered": "pests, insects, disease, drought, animals or theft"}}}

def main():
    import laya
    for model in ("convaiinnovations/laya-multilingual", "convaiinnovations/laya-typed-decisions", "convaiinnovations/laya"):
        try:
            t0 = time.perf_counter(); agent = laya.load(model); print(f"\n[{model}] load {time.perf_counter() - t0:.0f} s")
            agent.predict({"farmer_reply": "Yes."}, R7)
            ok, ms, bad, conf_ok, conf_bad = 0, [], [], [], []
            for step, text, want in CASES:
                t0 = time.perf_counter(); r = agent.predict({"agent_question": ASK_EN[step], "farmer_reply": text}, R7); ms.append((time.perf_counter() - t0) * 1000)
                a = r["answers"]["intent"]; got = a["choice"]; p = a["probabilities"][got]
                (conf_ok if got == want else conf_bad).append(p); ok += got == want
                if got != want: bad.append(f"{text} -> {got} {p:.2f} (want {want})")
            print(f"ROUTE English 7-way: {ok}/{len(CASES)} | median {statistics.median(ms):.0f} ms | mean prob when right {statistics.mean(conf_ok) if conf_ok else 0:.2f}, when wrong {statistics.mean(conf_bad) if conf_bad else 0:.2f}")
            for b in bad: print("    miss:", b)
            ok, ms, bad = 0, [], []
            for text, want in PERIL:
                t0 = time.perf_counter(); r = agent.predict({"cause_text": text}, P5); ms.append((time.perf_counter() - t0) * 1000)
                got = r["answers"]["peril"]["choice"]; ok += got == want
                if got != want: bad.append(f"{text} -> {got} (want {want})")
            print(f"PERIL English: {ok}/{len(PERIL)} | median {statistics.median(ms):.0f} ms")
            for b in bad: print("    miss:", b)
            del agent
        except Exception:
            print(f"[{model}] FAILED"); traceback.print_exc(file=sys.stdout)
    print("A DONE")

if __name__ == "__main__":
    try: main()
    except Exception: traceback.print_exc(file=sys.stdout); print("A FAILED")
