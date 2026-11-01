"""Generate the scenario, villages, farmers, policies and personas (deterministic), and load them into SQLite.

    python scripts/seed.py            # regenerate data files and load var/app.db
    python scripts/seed.py --check    # only print the counts of the existing files

Everything here is synthetic. Names are generated; none refers to a real person. Village names are illustrative.
Totals follow context/SystemDesign.md §12.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ghante_shared import config, db, geo  # noqa: E402

SEED = 72
N_FARMERS = 340
STORM = {"id": "storm_sehore_20260312", "type": "hailstorm", "started_at": "2026-03-12T15:30:00+05:30",
         "center_lat": 23.02, "center_lon": 76.72, "radius_km": 14.0, "direction": "ENE"}

# name, tehsil, km north of core, km east of core
VILLAGES = [
    ("Khajuriya Kalan", "Ashta", 0.8, 1.2), ("Bhanwra", "Ashta", -1.9, 2.6), ("Jatakheda", "Ashta", 2.7, -1.4),
    ("Pipliya Mira", "Ashta", 3.9, 3.1), ("Lasudiya Khas", "Ashta", -4.6, -2.2), ("Semli Jadid", "Ashta", 5.8, 4.9),
    ("Dhamanda", "Ashta", -6.3, 5.4), ("Bagdawda", "Ashta", 7.4, -3.8), ("Mogra Ram", "Ichhawar", 2.1, 9.2),
    ("Arniya Gazi", "Ichhawar", 8.6, 8.3), ("Hirapur Kheda", "Ichhawar", -5.2, 11.6), ("Chandbad Jagir", "Sehore", 6.9, 11.4),
]
VILLAGE_WEIGHTS = [38, 34, 33, 31, 30, 28, 27, 26, 25, 24, 22, 22]  # sums to 340

FIRST = ["Ramesh", "Suresh", "Mahesh", "Dinesh", "Kailash", "Mohan", "Sohan", "Gopal", "Bhagwan", "Shivnarayan", "Babulal", "Kishan", "Devkaran",
         "Hariom", "Jagdish", "Laxman", "Prahlad", "Radheshyam", "Santosh", "Vishnu", "Narayan", "Bherulal", "Ghanshyam", "Mangilal", "Rameshwar",
         "Kamla Bai", "Sita Bai", "Gita Bai", "Sunita", "Anita"]
LAST = ["Verma", "Patel", "Meena", "Thakur", "Malviya", "Parmar", "Rathore", "Yadav", "Kushwaha", "Dangi", "Mewada", "Jat", "Solanki", "Chouhan",
        "Vishwakarma", "Sen"]
NOTES = ["", "", "", "low-lying plot", "plot beside the canal", "sown late this season", "claim filed in 2024", "tenant farmer"]
CAUSES = ["Hail fell", "There was a hailstorm", "A lot of hail came down", "Hail and a strong wind came", "The crop fell because of the hail"]


def intensity_for(distance_km: float) -> str:
    return "severe" if distance_km <= 5 else "moderate" if distance_km <= 10 else "light"


def build() -> tuple[dict, list[dict], list[dict]]:
    rng = random.Random(SEED)
    villages, scenario_villages = [], []
    for i, (name, tehsil, north, east) in enumerate(VILLAGES, start=1):
        lat, lon = geo.offset(STORM["center_lat"], STORM["center_lon"], north, east)
        d = round(geo.haversine_km(STORM["center_lat"], STORM["center_lon"], lat, lon), 1)
        vid = f"V{i:02d}"
        villages.append({"id": vid, "name": name, "tehsil": tehsil, "district": "Sehore", "state": "Madhya Pradesh",
                         "lat": round(lat, 5), "lon": round(lon, 5)})
        scenario_villages.append({"village_id": vid, "intensity": intensity_for(d), "distance_km": d})

    # personas: SystemDesign §12.2 (the hero is the 312th FILED case and has no persona)
    outcomes = ["files"] * 311 + ["no_answer"] * 11 + ["no_damage"] * 9 + ["wants_human"] * 5 + ["pest"] * 1 + ["lapsed"] * 2
    assert len(outcomes) == N_FARMERS - 1
    rng.shuffle(outcomes)
    files_idx = [i for i, o in enumerate(outcomes) if o == "files"]
    second = set(rng.sample(files_idx, 40))
    third = set(rng.sample([i for i in files_idx if i not in second], 10))

    village_of = [v for v, n in zip(villages, VILLAGE_WEIGHTS) for _ in range(n)]
    assert len(village_of) == N_FARMERS
    hero_slot = 0  # first farmer of the first (severe) village is the hero
    farmers, used_names, persona_i = [], set(), 0
    for n in range(N_FARMERS):
        v = village_of[n]
        sv = scenario_villages[int(v["id"][1:]) - 1]
        is_hero = n == hero_slot
        if is_hero:
            name, app_no, mobile, khasra, area, notes = "Ramlal Verma", "APP-SEH-000451", "+91 00000 00451", "214", 1.8, ""
        else:
            while True:
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                key = (name, v["id"])
                if key not in used_names and name != "Ramlal Verma":
                    used_names.add(key)
                    break
            serial = 1000 + n
            app_no, mobile = f"APP-SEH-{serial:06d}", f"+91 00000 0{serial:04d}"
            khasra = str(rng.randint(11, 499))
            area = round(rng.choice([0.4, 0.6, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.4, 3.0, 3.5]), 1)
            notes = rng.choice(NOTES)
        plot_lat, plot_lon = geo.offset(v["lat"], v["lon"], rng.uniform(-1.2, 1.2), rng.uniform(-1.2, 1.2))
        sim = None
        status = "active"
        if not is_hero:
            outcome = outcomes[persona_i]
            attempt = 3 if persona_i in third else 2 if persona_i in second else 1
            persona_i += 1
            base = {"severe": 70, "moderate": 45, "light": 25}[sv["intensity"]]
            pct = max(10, min(100, base + rng.choice([-15, -10, -5, 0, 5, 10, 15, 20])))
            minute = rng.randint(28, 55)
            sim = {"outcome": outcome, "answer_on_attempt": attempt if outcome == "files" else (0 if outcome == "no_answer" else 1),
                   "answers": {"cause_text": "Insects attacked the crop" if outcome == "pest" else rng.choice(CAUSES),
                               "loss_time": f"15:{minute:02d}", "damage_pct": pct, "crop_stage": "standing"},
                   "photo": {"label": "hail_damage", "confidence": round(rng.uniform(0.62, 0.93), 2), "sample": f"hail_{rng.randint(1, 8):02d}.jpg"},
                   "gps_offset_m": rng.randint(20, 400)}
            if outcome == "lapsed":
                status = "lapsed"
        fid = f"F{n + 1:04d}"
        farmers.append({
            "id": fid, "name": name, "mobile": mobile, "village_id": v["id"], "is_hero": is_hero, "notes": notes, "sim": sim,
            "policy": {"id": f"P{n + 1:04d}", "application_no": app_no, "season": "Rabi 2025-26", "crop": "wheat", "khasra_no": khasra,
                       "insured_area_ha": area, "sum_insured_inr": int(area * 62000), "status": status,
                       "valid_from": "2025-11-01" if status == "active" else "2024-11-01",
                       "valid_to": "2026-04-30" if status == "active" else "2025-04-30",
                       "plot_lat": round(plot_lat, 5), "plot_lon": round(plot_lon, 5)}})

    started = dt.datetime.fromisoformat(STORM["started_at"])
    scenario = {
        "id": "sehore_hail", "district": "Sehore", "state": "Madhya Pradesh", "scenario_date": "2026-03-12",
        "storm": STORM, "detected_at": (started + dt.timedelta(minutes=20)).isoformat(),
        "calling_starts_at": (started + dt.timedelta(minutes=30)).isoformat(),
        "calling_window": {"from": "08:00", "to": "20:00"}, "deadline_hours": 72,
        "villages": scenario_villages,
        "expected_totals": {"FILED": 312, "UNREACHABLE": 11, "NO_DAMAGE": 9, "ESCALATED": 5, "INELIGIBLE": 3},
        "note": "Synthetic scenario. Coordinates are approximate; village names are illustrative.",
    }
    return scenario, villages, farmers


def summary(farmers: list[dict]) -> dict:
    c = collections.Counter(f["sim"]["outcome"] if f["sim"] else "HERO" for f in farmers)
    return dict(sorted(c.items()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="only report on the existing seed files")
    ap.add_argument("--no-db", action="store_true", help="write the data files but do not touch the database")
    args = ap.parse_args()
    if args.check:
        farmers = json.loads((config.SEED_DIR / "farmers.json").read_text(encoding="utf-8"))
        print(len(farmers), "farmers:", summary(farmers))
        return 0
    scenario, villages, farmers = build()
    config.SEED_DIR.mkdir(parents=True, exist_ok=True)
    config.SCENARIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    dump = lambda obj: json.dumps(obj, ensure_ascii=False, indent=1) + "\n"  # noqa: E731
    config.SCENARIO_PATH.write_text(dump(scenario), encoding="utf-8", newline="\n")
    (config.SEED_DIR / "villages.json").write_text(dump(villages), encoding="utf-8", newline="\n")
    (config.SEED_DIR / "farmers.json").write_text(dump(farmers), encoding="utf-8", newline="\n")
    print(f"wrote scenario, {len(villages)} villages, {len(farmers)} farmers: {summary(farmers)}")
    if not args.no_db:
        conn = db.connect()
        print("database loaded:", db.load_seed(conn))
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
