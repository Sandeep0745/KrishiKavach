"""The four pipeline agents and the service that runs them for a case (SystemDesign §13).

Evidence and Eligibility read and judge; Filing submits the form (through the Filer's browser for the live case, through the
portal's API for simulated ones); Follow-up records the reference and tells the farmer. Each agent reports
agent.started / agent.finished, and only CaseStore changes a case.
"""
from __future__ import annotations

import asyncio
import time
import urllib.error
from collections.abc import Callable

from ghante_shared import config, geo, http, mcp_client, models

from ..cases import CaseStore
from . import graph, rules

WAIT_S = config.env_float("PIPELINE_WAIT_S", 90.0)


def filing_mode_setting() -> str:
    """FILING_MODE, or scripted while CREDIT_SAVER is on (the browser agent spends free-tier LLM requests)."""
    mode = config.env("FILING_MODE", "").strip().lower()
    if mode in ("auto", "agent", "scripted"):
        return mode
    return "scripted" if config.env("CREDIT_SAVER", "1") != "0" else "auto"


class Pipeline:
    def __init__(self, store: CaseStore, notify_farmer: Callable[[str, str, dict], int], engine: str | None = None) -> None:
        self.store, self.notify_farmer = store, notify_farmer
        self.live_ids: set[str] = set()   # cases known to be the live farmer's (looked up once)
        self.sim_ids: set[str] = set()
        self.hold = None                  # set by the scenario controller: waits while the district run is paused
        self.engine = engine or graph.engine_name()
        self.graph = graph.build({"evidence": self.evidence, "eligibility": self.eligibility, "filing": self.filing, "followup": self.followup}, self.engine)
        self.tasks: dict[str, asyncio.Task] = {}
        self.last: dict[str, dict] = {}

    # ---------- helpers ----------
    def _is_live(self, case_id: str) -> bool:
        """Is this the live farmer's case (not simulated)? A simulated hero (HERO_SIM=1) counts as simulated."""
        if case_id in self.live_ids:
            return True
        if case_id in self.sim_ids:
            return False
        live = self.store._is_hero(case_id)
        (self.live_ids if live else self.sim_ids).add(case_id)
        return live

    def _emit(self, type_: str, data: dict, case_id: str | None, agent: str) -> None:
        self.store.emit(type_, data, case_id=case_id, agent=agent, live=self._is_live(case_id) if case_id else False)

    async def _gate(self, case_id: str) -> None:
        """A simulated case does not move while the scenario clock is paused (the fleet freezes during the live call)."""
        if self.hold is not None and not self._is_live(case_id):
            await self.hold()

    def _started(self, agent: str, case_id: str, summary: str) -> float:
        self._emit("agent.started", {"summary": summary}, case_id, agent)
        return time.perf_counter()

    def _finished(self, agent: str, case_id: str, t0: float, summary: str, ok: bool = True, **extra) -> None:
        self._emit("agent.finished", {"summary": summary, "seconds": round(time.perf_counter() - t0, 2), "ok": ok, **extra}, case_id, agent)

    async def _tool(self, url: str, server: str, tool: str, args: dict, case_id: str, agent: str) -> dict | None:
        try:
            return await asyncio.wait_for(mcp_client.call_tool(url, tool, args, server=server, client="pipeline", case_id=case_id, agent=agent,
                                                               pooled=True, emit=self._emit), 8.0)
        except Exception as e:  # noqa: BLE001 - a tool server that is down must not stop the pipeline
            self._emit("fallback.used", {"component": f"mcp {server}", "from": tool, "to": "none", "reason": f"{type(e).__name__}: {str(e)[:80]}"}, case_id, agent)
            return None

    def _pack(self, case: dict) -> dict:
        """What the Evidence agent saved for the latest photo."""
        ev = self.store.latest_evidence(case["id"])
        return {"evidence": ev, "weather": (ev or {}).get("weather"), "distance_from_plot_m": (ev or {}).get("distance_from_plot_m"),
                "loss_estimate_inr": (ev or {}).get("loss_estimate_inr")}

    # ---------- Evidence ----------
    async def evidence(self, state: dict) -> dict:
        case_id = state["case_id"]
        await self._gate(case_id)
        t0 = self._started("evidence", case_id, "Checking the photo against the weather record and the insured plot")
        case = self.store.get(case_id)
        ev, policy, slots = self.store.latest_evidence(case_id), case.get("policy") or {}, case["slots"]
        lat = ev["lat"] if ev and ev.get("lat") is not None else policy.get("plot_lat")
        lon = ev["lon"] if ev and ev.get("lon") is not None else policy.get("plot_lon")
        at = rules.weather_time(case)
        weather = None
        if lat is not None and lon is not None and at:
            weather = await self._tool(config.MCP_WEATHER_URL, "weather", "get_weather_at", {"lat": lat, "lon": lon, "at": at}, case_id, "evidence")
        distance = None
        if ev and ev.get("lat") is not None and policy.get("plot_lat") is not None:
            distance = round(geo.haversine_km(ev["lat"], ev["lon"], policy["plot_lat"], policy["plot_lon"]) * 1000, 1)
        estimate = None
        village = case.get("village") or {}
        if slots.get("damage_pct") and policy.get("crop") and village.get("district"):
            price = await self._tool(config.MCP_MANDI_URL, "mandi", "get_price", {"crop": policy["crop"], "district": village["district"]}, case_id, "evidence")
            if price and price.get("modal_price_inr_per_quintal") and price.get("typical_yield_quintal_per_ha"):
                # Illustrative only: affected area x a typical yield x the market price. It is not an assessment and is never filed.
                estimate = round(float(policy.get("insured_area_ha") or 0) * slots["damage_pct"] / 100 * price["typical_yield_quintal_per_ha"]
                                 * price["modal_price_inr_per_quintal"])
        if ev:
            self.store.save_pack(ev["id"], weather, distance, estimate)
        parts = []
        if weather and not weather.get("error"):
            parts.append(f"Weather record at the spot: {'hail' if weather.get('hail') else 'no hail'}, {weather.get('precipitation_mm', 0)} mm rain.")
        else:
            parts.append("No weather record could be read.")
        if ev is None:
            parts.append("No photo was received.")
        elif ev.get("gps_source") == "plot":
            parts.append("The phone had no GPS fix; the plot's location was recorded.")
        elif distance is not None:
            parts.append(f"Photo taken {round(distance)} m from the insured plot.")
        self._finished("evidence", case_id, t0, " ".join(parts), ok=True, has_photo=ev is not None, sha256=(ev or {}).get("sha256"))
        return {"case": case, "policy": policy,
                "pack": {"evidence": self.store.latest_evidence(case_id), "weather": weather, "distance_from_plot_m": distance, "loss_estimate_inr": estimate}}

    # ---------- Eligibility ----------
    async def eligibility(self, state: dict) -> dict:
        case_id = state["case_id"]
        await self._gate(case_id)
        t0 = self._started("eligibility", case_id, "Checking the policy, the cause, the deadline and the evidence")
        case, pack = self.store.get(case_id), state.get("pack") or {}
        ev, weather, distance = pack.get("evidence"), pack.get("weather"), pack.get("distance_from_plot_m")
        checks = rules.run_checks(case, ev, weather, distance, self.store.clock.now())
        verdict, reasons = rules.verdict_of(checks)
        if verdict == "eligible":
            # Second opinion from the small model: do the statement, the photo and the weather tell one story?
            decision, problem = None, ""
            try:
                decision = await asyncio.to_thread(http.post_json, f"{config.S1_URL}/decide",
                                                   {"decision": "VERIFY", "case_id": case_id, "state": rules.verify_state(case, ev, weather, distance),
                                                    "sim": not self._is_live(case_id), "live": self._is_live(case_id)}, 30.0)
            except Exception as e:  # noqa: BLE001
                problem = f"{type(e).__name__}"
            p = rules.p_consistent(decision)
            if p is None:
                self._emit("fallback.used", {"component": "s1", "from": "VERIFY", "to": "human review", "reason": problem or "no answer"}, case_id, "eligibility")
                checks.append({"n": "8", "name": "verify", "passed": False, "fail": "review", "detail": "The consistency check could not be run"})
            else:
                checks.append({"n": "8", "name": "verify", "passed": p >= rules.VERIFY_MIN, "fail": "review", "p_consistent": round(p, 3),
                               "detail": f"Statement, photo and weather agree (model {round(p * 100)}% sure)" if p >= rules.VERIFY_MIN
                               else f"Evidence inconsistent: the model is only {round(p * 100)}% sure that statement, photo and weather agree"})
            verdict, reasons = rules.verdict_of(checks)
        self.store.set_verdict(case_id, verdict, reasons)
        passed = sum(1 for c in checks if c["passed"])
        if verdict == "ineligible":
            self.store.set_status(case_id, models.INELIGIBLE, reasons[0], agent="eligibility")
        elif verdict == "review":
            self.store.set_status(case_id, models.ESCALATED, "needs human review: " + reasons[0], agent="eligibility")
        summary = (f"Eligible: all {len(checks)} checks passed." if verdict == "eligible"
                   else f"{'Not eligible' if verdict == 'ineligible' else 'Sent to a person'}: {reasons[0]}.")
        self._finished("eligibility", case_id, t0, summary, ok=True, verdict=verdict, reasons=reasons, passed=passed, checks=len(checks))
        return {"checks": checks, "verdict": verdict, "reasons": reasons}

    # ---------- Filing ----------
    async def filing(self, state: dict) -> dict:
        case_id = state["case_id"]
        await self._gate(case_id)
        case = self.store.get(case_id)
        pack = state.get("pack") or self._pack(case)
        ev = pack.get("evidence")
        form = rules.build_form(case, ev, pack.get("weather"), pack.get("distance_from_plot_m"), state.get("note", ""))
        live = self._is_live(case_id)
        use_browser = live and ev is not None and bool(ev.get("photo_path"))
        mode = filing_mode_setting() if use_browser else "api"
        t0 = self._started("filing", case_id, "Filling the insurer's form in a browser" if use_browser else "Sending the report to the portal")
        self.store.set_status(case_id, models.FILING, state.get("note") or "eligible", agent="filing")
        if live and not use_browser:
            # The portal's page needs a photo. A report a reviewer approved without one goes through the portal's API, and says so.
            self._emit("fallback.used", {"component": "filer", "from": "browser form", "to": "portal api", "reason": "no photo to upload"}, case_id, "filing")
        claim_ref, used, failed, steps, differ = None, mode, "", None, []
        try:
            if use_browser:
                out = await asyncio.to_thread(http.post_json, f"{config.FILER_URL}/file",
                                              {"case_id": case_id, "form": form, "photo_path": ev["photo_path"], "mode": mode},
                                              config.env_float("FILING_TIMEOUT_S", 75.0) + 90.0)
                claim_ref, used, steps = out.get("claim_ref"), out.get("mode_used") or mode, out.get("steps")
                differ = list(out.get("mismatches") or [])
            else:
                out = await asyncio.to_thread(http.post_json, f"{config.PORTAL_URL}/api/claims",
                                              {**form, "declaration": True, "photo_ref": (ev or {}).get("id")}, 10.0)
                claim_ref, used = out.get("reference"), "api"
            if not claim_ref:
                failed = "no reference number came back"
        except http.HttpError as e:
            failed = f"{'the Filer' if use_browser else 'the portal'} answered {e.status}: {e.body[:160]}"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            failed = f"{'the Filer' if use_browser else 'the portal'} could not be reached ({type(e).__name__})"
        if failed:
            self.store.set_status(case_id, models.FAILED, failed, agent="filing")
            self._finished("filing", case_id, t0, f"Not filed: {failed}.", ok=False)
            return {"form": form, "failed": failed}
        warning = f" Warning: the portal's record differs from what was sent in {', '.join(differ)}." if differ else ""
        self._finished("filing", case_id, t0, f"Submitted, reference {claim_ref}.{warning}", ok=not differ, filing_mode=used, steps=steps, mismatches=differ)
        return {"form": form, "claim_ref": claim_ref, "filing_mode": used if used in models.FILING_MODES else "scripted",
                "seconds": round(time.perf_counter() - t0, 1)}

    # ---------- Follow-up ----------
    async def followup(self, state: dict) -> dict:
        case_id = state["case_id"]
        await self._gate(case_id)
        t0 = self._started("followup", case_id, "Recording the reference and telling the farmer")
        filed = self.store.set_filed(case_id, state["claim_ref"], state["filing_mode"])
        case = self.store.get(case_id)
        from apps.voice.lines import MESSAGE_FILED  # plain text, no voice packages needed

        phones = self.notify_farmer(case["farmer_id"], "message", {"text": MESSAGE_FILED.format(claim_ref=state["claim_ref"]),
                                                                   "claim_ref": state["claim_ref"], "simulated_sms": True})
        self._emit("claim.filed", {"claim_ref": state["claim_ref"], "filing_mode": state["filing_mode"], "seconds": state.get("seconds"),
                                   "time_to_file_s": filed["time_to_file_s"]}, case_id, "followup")
        self._finished("followup", case_id, t0, f"Reference {state['claim_ref']} recorded. Message sent to {phones} phone{'s' if phones != 1 else ''}.", ok=True)
        return {}

    # ---------- running ----------
    def result(self, case_id: str, state: dict | None = None, t0: float | None = None, error: str = "") -> dict:
        case = self.store.get(case_id)
        out = {"case_id": case_id, "status": case["status"], "verdict": case.get("verdict"), "reasons": case.get("verdict_reasons") or [],
               "claim_ref": case.get("claim_ref"), "filing_mode": case.get("filing_mode"), "time_to_file_s": case.get("time_to_file_s"),
               "pending": False, "engine": self.engine}
        if state is not None:
            out["checks"] = state.get("checks")
            if state.get("failed"):
                out["failed"] = state["failed"]
        if t0 is not None:
            out["seconds"] = round(time.perf_counter() - t0, 1)
        if error:
            out["error"] = error
        return out

    async def _run(self, case_id: str, start_at: str, note: str) -> dict:
        t0 = time.perf_counter()
        try:
            state = await self.graph.ainvoke({"case_id": case_id, "start_at": start_at, "note": note})
            out = self.result(case_id, state, t0)
        except Exception as e:  # noqa: BLE001 - never leave a case stuck in a working status
            error = f"{type(e).__name__}: {str(e)[:160]}"
            status = self.store.get(case_id)["status"]
            if status == models.PROCESSING:
                self.store.set_status(case_id, models.ESCALATED, f"pipeline error: {error}", agent="system")
            elif status == models.FILING:
                self.store.set_status(case_id, models.FAILED, f"pipeline error: {error}", agent="system")
            out = self.result(case_id, None, t0, error)
        self.last[case_id] = out
        return out

    def start(self, case_id: str, start_at: str = "evidence", note: str = "") -> asyncio.Task:
        """Start a run, or return the one already running for this case."""
        task = self.tasks.get(case_id)
        if task is None or task.done():
            task = asyncio.create_task(self._run(case_id, start_at, note))
            self.tasks[case_id] = task
            task.add_done_callback(lambda t, cid=case_id: self.tasks.pop(cid, None) if self.tasks.get(cid) is t else None)
        return task

    def running(self, case_id: str) -> asyncio.Task | None:
        task = self.tasks.get(case_id)
        return task if task is not None and not task.done() else None

    async def wait(self, task: asyncio.Task, case_id: str, seconds: float | None = None) -> dict:
        """Wait for a run. If it takes longer than the limit, answer `pending` and let it finish in the background."""
        done, _ = await asyncio.wait({task}, timeout=WAIT_S if seconds is None else seconds)
        if done:
            return task.result()
        return {**self.result(case_id), "pending": True}

    def reset(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()
        self.last.clear()
        self.live_ids.clear()
        self.sim_ids.clear()
