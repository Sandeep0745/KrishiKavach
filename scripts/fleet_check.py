"""Run the whole district headless with the real decision models and a scripted hero, and print how it went (Testing T4-04, T4-10).

    .venv\\Scripts\\python.exe scripts\\fleet_check.py                      # the demo settings
    .venv\\Scripts\\python.exe scripts\\fleet_check.py --speed 240 --parallel 8
    .venv\\Scripts\\python.exe scripts\\fleet_check.py --mock-s1            # the test decision provider (no models)

Uses spare ports and a temporary data folder, so it does not disturb a running demo. Target: the fleet finishes in 60 to 90 real
seconds and the closing line reads "312 of 340 claims filed, 68 hours left".
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import _util as u  # noqa: E402

TOTALS = {"filed": 312, "unreachable": 11, "no_damage": 9, "escalated": 5, "ineligible": 3, "failed": 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=180.0)
    ap.add_argument("--parallel", type=int, default=8)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--mock-s1", action="store_true")
    args = ap.parse_args()
    env = {"HERO_SIM": "1", "SIM_SPEED": str(args.speed), "MAX_PARALLEL_CALLS": str(args.parallel), "S1_SIM_CACHE": "1"}
    if args.mock_s1:
        env.update(S1_CHAIN_TEXT="mock", S1_CHAIN_REPORT="mock")
    s = u.Services("orchestrator", "portal", "weather", "registry", "mandi", "s1", **env)
    api = lambda method, path, payload=None: u.call(method, u.url("orchestrator", path), payload, timeout=30)  # noqa: E731
    failures = 0
    try:
        if not args.mock_s1:  # the first decision loads the model; do that before the clock starts, as on demo day
            t0 = time.time()
            u.call("POST", u.url("s1", "/decide"), {"decision": "TRIAGE", "state": {"hail_intensity": "severe", "distance_km": 1, "crop": "wheat", "crop_stage": "close to harvest"}}, timeout=900)
            u.call("POST", u.url("s1", "/decide"), {"decision": "VERIFY", "state": {"peril": "hailstorm", "edge_label": "hail_damage", "hail": True, "distance_from_plot_m": 100, "minutes_from_storm": 0}}, timeout=900)
            print(f"decision models loaded in {time.time() - t0:.0f} s")
        for run in range(1, args.runs + 1):
            api("POST", "/api/scenario/reset", {})
            print(f"\n== run {run}: speed {args.speed:g}, {args.parallel} calls at a time ==", flush=True)
            t0 = time.time()
            status, out = api("POST", "/api/scenario/start", {})
            assert status == 200, out
            last, ranked_at = "", None
            while time.time() - t0 < 600:
                time.sleep(1.0)
                st = api("GET", "/api/state")[1]
                sc, stats = st["scenario"], st["stats"]
                if ranked_at is None and sc.get("triage_done"):
                    ranked_at = time.time() - t0
                line = f"{st['clock']['sim_ts'][11:16]}  ranked {sc.get('triaged', 0):>3}  on call {sc.get('on_call', 0)}  to call {stats['queued']:>3}  filed {stats['filed']:>3}"
                if int(time.time() - t0) % 5 == 0 and line != last:
                    print(f"  {time.time() - t0:5.0f} s  {line}", flush=True)
                    last = line
                if sc["state"] == "finished":
                    break
            st = api("GET", "/api/state")[1]
            sc, stats = st["scenario"], st["stats"]
            got = {k: stats[k] for k in TOTALS}
            ok_totals = got == TOTALS
            ok_time = 60 <= sc["running_seconds"] <= 90
            hours = st["clock"].get("hours_left")
            ok_hours = hours is not None and round(hours) == 68
            failures += (not ok_totals) + (not ok_time) + (not ok_hours) + (sc["state"] != "finished")
            print(f"{'PASS' if sc['state'] == 'finished' else 'FAIL'}  the scenario finished  (state {sc['state']})")
            print(f"{'PASS' if ok_totals else 'FAIL'}  T4-04 final totals  ({got})")
            print(f"{'PASS' if ok_time else 'FAIL'}  T4-10 fleet time 60 to 90 real seconds  ({sc['running_seconds']:.0f} s; all cases ranked after {ranked_at or 0:.0f} s)")
            print(f"{'PASS' if ok_hours else 'FAIL'}  T4-10 closing line says 68 hours left  (finished at {st['clock']['sim_ts'][11:16]}, {hours} hours left)")
            claims = u.call("GET", u.url("portal", "/api/claims/count"))[1]["claims"]
            failures += claims != stats["filed"]
            print(f"{'PASS' if claims == stats['filed'] else 'FAIL'}  T4-05 the portal holds one record per filed case  ({claims} records)")
            print(f"      most calls at once: {sc['max_on_call_seen']} (limit {sc['max_parallel']})")
        print("\n---- report on the last run (scripts/report.py) ----", flush=True)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "report.py"), str(s.events_log)], cwd=ROOT, env=s.env)
    finally:
        s.close()
        if failures:
            print("---- end of the orchestrator log ----\n" + (s.logs / "orchestrator.log").read_text(encoding="utf-8", errors="replace")[-1500:])
    print(f"\nFLEET CHECK {'PASSED' if failures == 0 else f'FAILED ({failures})'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
