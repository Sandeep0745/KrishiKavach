"""Evaluate a System One provider on data/eval/s1_eval.jsonl (SystemDesign §8.3, test T0-2 / FR-82).

    python scripts/eval_s1.py --provider head      # ROUTE and PERIL
    python scripts/eval_s1.py --provider laya      # TRIAGE and VERIFY (add --all to also try ROUTE and PERIL)
    python scripts/eval_s1.py --provider llm       # uses the free Groq tier: about 70 requests
    python scripts/eval_s1.py --provider mock      # test provider, to check the script itself

Prints accuracy and latency per decision and saves logs/s1_eval_<provider>.json.
For the head it also prints which confidence threshold makes the yes/no fast path safe.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", required=True, choices=["head", "laya", "llm", "mock"])
    ap.add_argument("--all", action="store_true", help="run every decision, not only the ones this provider is meant for")
    ap.add_argument("--limit", type=int, default=0, help="at most this many examples per decision (0 = all)")
    ap.add_argument("--pace", type=float, default=0.0, help="seconds to wait between examples (use 3 for the free LLM tier)")
    args = ap.parse_args()
    os.environ["S1_CHAIN_TEXT"] = os.environ["S1_CHAIN_REPORT"] = args.provider
    os.environ["S1_TIMEOUT_MS"] = "60000"
    os.environ["ORCH_URL"] = "http://127.0.0.1:9"  # do not send evaluation decisions to a running dashboard

    from ghante_shared import config
    from apps.s1 import main as s1

    meant_for = {"head": {"ROUTE", "PERIL"}, "laya": {"TRIAGE", "VERIFY"}, "llm": set(s1.decisions.KIND), "mock": set(s1.decisions.KIND)}[args.provider]
    rows = [json.loads(line) for line in (config.DATA_DIR / "eval" / "s1_eval.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    report: dict = {"provider": args.provider, "decisions": {}}
    route_rows = []
    for decision in ("ROUTE", "PERIL", "TRIAGE", "VERIFY"):
        cases = [r for r in rows if r["decision"] == decision]
        if args.limit:
            cases = cases[:: max(1, len(cases) // args.limit)][: args.limit]
        if not cases or (decision not in meant_for and not args.all):
            continue
        try:
            s1.decide_sync(decision, cases[0]["state"])  # warm-up: loads the model
        except Exception as e:
            print(f"{decision:<7} cannot run with {args.provider}: {e}")
            continue
        ok, ms, misses = 0, [], []
        for r in cases:
            if args.pace:
                time.sleep(args.pace)
            t0 = time.perf_counter()
            try:
                out = s1.decide_sync(decision, r["state"])
            except Exception as e:
                misses.append(f"ERROR {type(e).__name__}: {str(e)[:140]}")
                continue
            ms.append((time.perf_counter() - t0) * 1000)
            good = all(out["answers"][k]["value"] == v for k, v in r["expected"].items())
            ok += good
            if decision == "ROUTE":
                a = out["answers"]["intent"]
                route_rows.append((a["value"], a["confidence"] or 0.0, r["expected"]["intent"]))
            if not good:
                got = {k: out["answers"][k]["value"] for k in r["expected"]}
                text = r["state"].get("utterance") or r["state"].get("cause_text") or json.dumps(r["state"], ensure_ascii=False)[:90]
                misses.append(f"{text} -> {got} (expected {r['expected']})")
        if not ms:
            print(f"{decision:<7} every example failed: {misses[0]}")
            continue
        ms_sorted = sorted(ms)
        p95 = ms_sorted[min(len(ms_sorted) - 1, round(0.95 * (len(ms_sorted) - 1)))]
        print(f"{decision:<7} {ok}/{len(cases)} correct ({ok / len(cases):.0%}) | median {statistics.median(ms):.0f} ms | p95 {p95:.0f} ms")
        for m in misses:
            print("        miss:", m)
        report["decisions"][decision] = {"correct": ok, "total": len(cases), "median_ms": round(statistics.median(ms)), "p95_ms": round(p95), "misses": misses}
    if route_rows:
        print("\nFast path check (ROUTE answers of yes/no at or above a confidence threshold skip the LLM):")
        print("  threshold  fast-path turns  wrong among them")
        best = None
        for th in (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
            fast = [(g, c, w) for g, c, w in route_rows if g in ("yes", "no") and c >= th]
            wrong = sum(1 for g, _, w in fast if g != w)
            print(f"    {th:.2f}        {len(fast):>3}               {wrong}")
            if wrong == 0 and best is None:
                best = th
        print(f"  Lowest threshold with no wrong fast-path turn on this set: {best}. Use it (plus a margin of 0.05) as FAST_PATH_MIN.")
        report["fast_path_min_suggested"] = best
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.LOG_DIR / f"s1_eval_{args.provider}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved {out_path.relative_to(ROOT) if out_path.is_relative_to(ROOT) else out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
