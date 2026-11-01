"""Numbers from the last run, read from the event log (SystemDesign §16, Testing T5-07).

    python scripts/report.py                     # the last run in logs/events.jsonl (everything since the last reset)
    python scripts/report.py path/to/events.jsonl
    python scripts/report.py --all               # the whole file, not only the last run

Every figure is measured: nothing here is estimated or filled in. A line is left out when the run has no data for it.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ghante_shared import config  # noqa: E402

TERMINAL = ("FILED", "UNREACHABLE", "NO_DAMAGE", "ESCALATED", "INELIGIBLE", "FAILED")


def pct(values: list[float], q: float) -> float:
    """The q-th percentile (nearest rank)."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q / 100 * len(ordered) + 0.5) - 1))]


def spread(values: list[float], unit: str = "ms") -> str:
    if not values:
        return "no data"
    return f"n {len(values)}, median {statistics.median(values):.0f} {unit}, 95th percentile {pct(values, 95):.0f} {unit}, slowest {max(values):.0f} {unit}"


def minutes(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min {seconds % 60:02d} s"


def build(events: list[dict]) -> dict:
    out: dict = {"events": len(events)}
    # ---- voice ----
    turns = [e["data"] for e in events if e["type"] == "call.turn" and e.get("live")]
    agent = [t for t in turns if t.get("speaker") == "agent" and isinstance((t.get("latency_ms") or {}).get("total"), (int, float))]
    out["voice"] = {path: [t["latency_ms"]["total"] for t in agent if t.get("path") == path] for path in ("fast", "llm")}
    out["voice_llm_only"] = [t["latency_ms"]["llm"] for t in turns if t.get("speaker") == "farmer" and "llm" in (t.get("latency_ms") or {})]
    out["farmer_turns"] = collections.Counter(t.get("path") for t in turns if t.get("speaker") == "farmer")
    # ---- decisions ----
    decisions: dict = collections.defaultdict(lambda: {"computed": [], "cached": 0, "fallback": 0})
    for e in events:
        if e["type"] == "s1.decision":
            d = e["data"]
            row = decisions[(d.get("decision"), d.get("provider"))]
            if d.get("cached"):
                row["cached"] += 1
            elif isinstance(d.get("latency_ms"), (int, float)):
                row["computed"].append(d["latency_ms"])
            row["fallback"] += 1 if d.get("fallback_from") else 0
    out["decisions"] = dict(decisions)
    # ---- tool calls ----
    tools: dict = collections.defaultdict(list)
    clients: set = set()
    for e in events:
        if e["type"] == "mcp.tool_called":
            tools[f"{e['data'].get('server')}.{e['data'].get('tool')}"].append(e["data"].get("ms") or 0)
            clients.add(e["data"].get("client"))
    out["tools"], out["tool_clients"] = dict(tools), sorted(c for c in clients if c)
    # ---- filing ----
    out["live_filed"] = [e["data"] for e in events if e["type"] == "claim.filed" and e.get("live")]
    out["sim_time_to_file_s"] = [e["data"]["time_to_file_s"] for e in events if e["type"] == "claim.filed" and not e.get("live")
                                 and isinstance(e["data"].get("time_to_file_s"), (int, float))]
    out["filing_modes"] = collections.Counter(e["data"].get("filing_mode") for e in events if e["type"] == "claim.filed")
    out["filing_steps"] = collections.Counter(e["data"].get("mode") for e in events if e["type"] == "filing.step")
    out["evidence"] = [e["data"] for e in events if e["type"] == "evidence.received" and e.get("live")]
    # ---- cases ----
    status: dict[str, str] = {}
    on_call: set[str] = set()
    most = 0
    for e in events:
        if e["type"] == "case.created":
            status[e["case_id"]] = "AFFECTED"
        elif e["type"] == "case.status_changed":
            status[e["case_id"]] = e["data"]["to"]
            (on_call.add if e["data"]["to"] in ("CALLING", "IN_CALL") else on_call.discard)(e["case_id"])
            most = max(most, len(on_call))
    out["final"] = collections.Counter(status.values())
    out["max_on_call"] = most
    out["calls"] = collections.Counter(e["data"].get("outcome") for e in events if e["type"] == "call.ended")
    finished = [e["data"] for e in events if e["type"] == "scenario.finished"]
    out["finished"] = finished[-1] if finished else None
    out["fallbacks"] = [e["data"] for e in events if e["type"] == "fallback.used"]
    out["reviews"] = [e["data"] for e in events if e["type"] == "review.decision"]
    return out


def show(r: dict) -> None:
    print(f"72 Ghante: report on {r['events']:,} events\n")
    print("VOICE (end of the farmer's speech to the agent's first audio)")
    for path, label, target in (("fast", "fast path", "target: median 800 ms or less"), ("llm", "language-model path", "target: median 1,500 ms or less, 95th percentile 2,500 ms or less")):
        if r["voice"][path]:
            print(f"  {label:<22} {spread(r['voice'][path])}   ({target})")
    if r["voice_llm_only"]:
        print(f"  {'language model alone':<22} {spread(r['voice_llm_only'])}")
    if r["farmer_turns"]:
        total = sum(r["farmer_turns"].values())
        print(f"  farmer turns: {total}, of which {r['farmer_turns'].get('fast', 0)} never reached the language model")
    if not any(r["voice"].values()) and not r["farmer_turns"]:
        print("  no live call in this run")
    print("\nFAST DECISIONS (System One)")
    for (decision, provider), row in sorted(r["decisions"].items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        n = len(row["computed"]) + row["cached"]
        extra = (f", {row['cached']} repeats served from cache" if row["cached"] else "") + (f", {row['fallback']} answered by a fallback provider" if row["fallback"] else "")
        print(f"  {decision:<7} {provider:<6} {n:>4} decisions; computed: {spread(row['computed'])}{extra}")
    if not r["decisions"]:
        print("  none")
    print("\nTOOL CALLS (MCP)")
    for name, ms in sorted(r["tools"].items()):
        print(f"  {name:<34} {len(ms):>4} calls, median {statistics.median(ms):.0f} ms")
    if r["tools"]:
        print(f"  made by: {', '.join(r['tool_clients'])}")
    print("\nFILING")
    for d in r["live_filed"]:
        mode = {"agent": "the browser agent", "scripted": "the scripted fill", "api": "the portal API"}.get(d.get("filing_mode"), str(d.get("filing_mode")))
        took = f"{d['seconds']:.0f} s to file" if isinstance(d.get("seconds"), (int, float)) else ""
        whole = f"; ring to reference {minutes(d['time_to_file_s'])} (target 3 min 30 s or less)" if isinstance(d.get("time_to_file_s"), (int, float)) else ""
        print(f"  live case: {d.get('claim_ref')} filed by {mode}, {took}{whole}")
    if r["filing_steps"]:
        print("  form actions on screen: " + ", ".join(f"{n} by the {'browser agent' if mode == 'agent' else 'scripted fill'}" for mode, n in r["filing_steps"].items()))
    for ev in r["evidence"]:
        if ev.get("edge_latency_ms") is not None:
            print(f"  photo checked on the phone in {ev['edge_latency_ms']:.0f} ms: {ev.get('edge_label')} ({ev.get('edge_confidence')})")
    if r["sim_time_to_file_s"]:
        print(f"  simulated farmers: {len(r['sim_time_to_file_s'])} filed through the portal API; scenario time from detection to filing, "
              f"median {minutes(statistics.median(r['sim_time_to_file_s']))}, longest {minutes(max(r['sim_time_to_file_s']))}")
    if not r["live_filed"] and not r["sim_time_to_file_s"]:
        print("  nothing was filed in this run")
    print("\nDISTRICT")
    if r["final"]:
        total = sum(r["final"].values())
        print(f"  {total} cases: " + ", ".join(f"{r['final'].get(s, 0)} {s}" for s in TERMINAL) + (f", {total - sum(r['final'].get(s, 0) for s in TERMINAL)} still open" if total != sum(r['final'].get(s, 0) for s in TERMINAL) else ""))
        print(f"  most calls in progress at once: {r['max_on_call']};  calls by outcome: " + ", ".join(f"{n} {k}" for k, n in r["calls"].most_common()))
    f = r["finished"]
    if f:
        print(f"  finished at scenario time {f['sim_ts'][11:16]} with {f['hours_left']} hours left of the 72; the fleet ran for {f['running_seconds']:.0f} real seconds (pauses excluded)")
        print(f"  closing line: {f['totals']['filed']} of {f['affected']} claims filed, {round(f['hours_left'])} hours left")
    elif r["final"]:
        print("  the scenario did not finish in this log")
    print("\nFALLBACKS AND PEOPLE")
    for d in r["fallbacks"]:
        print(f"  fallback: {d.get('component')}: {d.get('from')} -> {d.get('to')} ({d.get('reason')})")
    for d in r["reviews"]:
        print(f"  a person {'approved' if d.get('approve') else 'did not approve'} a case sent to review" + (f": {d['note']}" if d.get("note") else ""))
    if not r["fallbacks"] and not r["reviews"]:
        print("  none")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?", default=str(config.EVENTS_LOG))
    ap.add_argument("--all", action="store_true", help="use the whole file instead of the last run")
    args = ap.parse_args()
    path = pathlib.Path(args.log)
    if not path.exists():
        print(f"no event log at {path}")
        return 1
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not args.all:
        marks = [i for i, e in enumerate(events) if e["type"] == "snapshot"]  # a reset writes a snapshot
        if marks:
            events = events[marks[-1] + 1:]
    report = build(events)
    show(report)
    summary = {"events": report["events"], "final": dict(report["final"]), "finished": report["finished"],
               "voice_fast_median_ms": statistics.median(report["voice"]["fast"]) if report["voice"]["fast"] else None,
               "voice_llm_median_ms": statistics.median(report["voice"]["llm"]) if report["voice"]["llm"] else None,
               "live_filed": report["live_filed"], "fallbacks": report["fallbacks"]}
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    (config.LOG_DIR / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
