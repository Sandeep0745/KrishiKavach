"""Phase 3 measurement: how should the VERIFY report be worded so that Laya's answer is stable?

Found on 7 Oct: with the Phase 1 wording Laya called the hero's fully consistent case inconsistent (the only differences from an
evaluation example it gets right were "0 minutes", "27.8 mm" and "85 km/h"). This tries several wordings on
  (a) the 15 VERIFY examples of data/eval/s1_eval.jsonl,
  (b) 120 consistent cases with realistic numbers (every one passes the eligibility rules),
  (c) 12 grey cases the rules let through but a person would question (a photo that looks healthy, weakly).
Run:  .venv\\Scripts\\python.exe scripts\\spikes\\verify_wording.py
"""
from __future__ import annotations

import itertools
import json
import pathlib
import random
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.s1 import decisions as d  # noqa: E402

PHOTO = d.PHOTO_WORDS
Q_AGREE = {"evidence_consistent": {"type": "noul", "instructions": "Read `report`. Do the farmer's statement, the photo and the weather record agree with each other?"}}
Q_CONTRA = {"contradiction": {"type": "noul", "instructions": "Read `report`. Does the photo or the weather record contradict what the farmer says?"}}


def words(s: dict) -> dict:
    peril = str(s.get("peril", "unknown")).replace("_", " ")
    dist, mins = s.get("distance_from_plot_m") or 0, abs(s.get("minutes_from_storm") or 0)
    return {
        "peril": peril, "pct": s.get("damage_pct"), "photo": PHOTO.get(str(s.get("edge_label")), "an unclear scene"),
        "weather": (f"hail, {round(float(s.get('precipitation_mm') or 0))} mm of rain and strong wind" if s.get("hail") else "no hail and no storm"),
        "weather_plain": "a hailstorm" if s.get("hail") else "clear weather with no hail",
        "place": "at the insured plot" if dist <= 2000 else f"far from the insured plot, {round(dist / 1000)} km away",
        "time": "matches the time of the recorded storm" if mins <= 180 else f"is {round(mins / 60)} hours away from the recorded storm",
    }


def v_current(s):
    return d.render_report("VERIFY", s)


def v_rounded(s):
    s = {**s, "precipitation_mm": round(float(s.get("precipitation_mm") or 0)), "minutes_from_storm": max(5, abs(s.get("minutes_from_storm") or 0)),
         "distance_from_plot_m": max(20, round((s.get("distance_from_plot_m") or 0) / 10) * 10)}
    return d.render_report("VERIFY", s)


def v_plain(s):
    w = words(s)
    return (f"The farmer says the crop was damaged by {w['peril']}, about {w['pct']} percent of the field. The photo taken on the phone shows {w['photo']}. "
            f"The weather record for that place and time shows {w['weather']}. The photo was taken {w['place']}. The time the farmer gave {w['time']}.")


def v_no_numbers(s):
    w = words(s)
    return (f"The farmer says the crop was damaged by {w['peril']}. The photo taken on the phone shows {w['photo']}. "
            f"The weather record for that place and time shows {w['weather_plain']}. The photo was taken {w['place']}. The time the farmer gave {w['time']}.")


VARIANTS = [("current", v_current, Q_AGREE, False), ("rounded numbers", v_rounded, Q_AGREE, False), ("plain words", v_plain, Q_AGREE, False),
            ("no numbers", v_no_numbers, Q_AGREE, False), ("plain words, contradiction question", v_plain, Q_CONTRA, True),
            ("no numbers, contradiction question", v_no_numbers, Q_CONTRA, True)]


def main() -> None:
    import laya

    t0 = time.time()
    agent = laya.load(d.config.env("LAYA_MODEL", "convaiinnovations/laya-multilingual"))
    print(f"model loaded in {time.time() - t0:.0f} s")
    evals = [json.loads(line) for line in (ROOT / "data" / "eval" / "s1_eval.jsonl").read_text(encoding="utf-8").splitlines() if '"VERIFY"' in line]
    rng = random.Random(7)
    grid = list(itertools.product((30, 70, 100), (("hail_damage", 0.8), ("hail_damage", 0.62), ("lodged", 0.7)), (8.5, 27.8), (48, 85), (0, 7, 120, 900, 1800),
                                  (-20, 0, 5, 45, 150)))
    consistent = [{"peril": "hailstorm", "damage_pct": p, "edge_label": lab, "edge_confidence": c, "hail": True, "precipitation_mm": r, "wind_gust_kmh": g,
                   "distance_from_plot_m": dist, "minutes_from_storm": m} for p, (lab, c), r, g, dist, m in rng.sample(grid, 120)]
    hero = [{"peril": "hailstorm", "damage_pct": 70, "edge_label": "hail_damage", "edge_confidence": 0.8, "hail": True, "precipitation_mm": 27.8,
             "wind_gust_kmh": 85, "distance_from_plot_m": dm, "minutes_from_storm": 0} for dm in (120, 7, 0)]
    grey = [{"peril": "hailstorm", "damage_pct": p, "edge_label": "healthy", "edge_confidence": 0.5, "hail": True, "precipitation_mm": 27.8, "wind_gust_kmh": 85,
             "distance_from_plot_m": dist, "minutes_from_storm": m} for p in (60, 80, 100) for dist in (7, 120) for m in (0, 5)]

    def p_consistent(text: str, question: dict, negate: bool) -> float:
        a = next(iter(agent.predict({"report": text}, question)["answers"].values()))
        p = float(a.get("noul", 0.0))
        return 1 - p if negate else p

    print(f"\n{'wording':<38} {'eval set':>9} {'consistent':>11} {'hero x3':>8} {'grey caught':>12} {'min P ok':>9} {'ms':>5}")
    for name, render, question, negate in VARIANTS:
        t0, n = time.time(), 0
        right = 0
        for e in evals:
            p = p_consistent(render(e["state"]), question, negate)
            n += 1
            right += (p >= 0.6) == e["expected"]["evidence_consistent"]
        ps = [p_consistent(render(s), question, negate) for s in consistent]
        hs = [p_consistent(render(s), question, negate) for s in hero]
        gs = [p_consistent(render(s), question, negate) for s in grey]
        n += len(ps) + len(hs) + len(gs)
        print(f"{name:<38} {right:>3} of {len(evals):<3} {sum(p >= 0.6 for p in ps):>4} of {len(ps):<4} {sum(p >= 0.6 for p in hs):>3} of 3 {sum(p < 0.6 for p in gs):>5} of {len(gs):<4} "
              f"{min(ps):>9.2f} {round((time.time() - t0) * 1000 / n):>5}", flush=True)
        print(f"      hero P(consistent): {[round(p, 2) for p in hs]}   example: {render(hero[0])[:230]}", flush=True)
    print("\nRead it as: 'consistent' and 'hero' should be all passed; 'eval set' as high as possible; 'grey caught' is a bonus.")


if __name__ == "__main__":
    main()
