"""Dispatcher agent (SystemDesign §12.4, FR-02 to FR-04): opens a case for every insured farmer in the storm's path, ranks them
with the TRIAGE decision, and places calls in priority order, a limited number at a time, inside the calling hours, with retries."""
from __future__ import annotations

import asyncio
import datetime as dt
import heapq
import time

from ghante_shared import config, geo, http, mcp_client, models

from .cases import CaseStore
from .clock import SimClock
from .pipeline.service import Pipeline
from .simulator import HERO_PERSONA, RETRY_AFTER_S, Simulator

INTENSITY_RANK = {"severe": 0, "moderate": 1, "light": 2}
FALLBACK_PRIORITY = {"severe": 90.0, "moderate": 50.0, "light": 10.0}  # used only if the decision service gives no answer


def priority_of(answer: dict | None) -> float | None:
    """priority = 100·P(high) + 50·P(medium) (SystemDesign §8.2)."""
    probs = (answer or {}).get("probs")
    if isinstance(probs, dict):
        return round(100 * float(probs.get("high") or 0) + 50 * float(probs.get("medium") or 0), 2)
    value = (answer or {}).get("value")
    if value in ("high", "medium", "low"):
        confidence = float((answer or {}).get("confidence") or 1.0)
        return round({"high": 100, "medium": 50, "low": 0}[value] * confidence, 2)
    return None


def in_calling_hours(now: dt.datetime, window: dict) -> bool:
    return window["from"] <= now.strftime("%H:%M") < window["to"]


def next_opening(now: dt.datetime, window: dict) -> dt.datetime:
    hh, mm = (int(x) for x in window["from"].split(":"))
    opening = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return opening if opening > now else opening + dt.timedelta(days=1)


class Dispatcher:
    def __init__(self, store: CaseStore, clock: SimClock, pipeline: Pipeline, scenario: dict, hero_sim: bool = False, max_parallel: int = 6) -> None:
        self.store, self.clock, self.pipeline, self.scenario = store, clock, pipeline, scenario
        self.hero_sim, self.max_parallel = hero_sim, max(1, max_parallel)
        self.simulator = Simulator(store, clock)
        self.window = scenario.get("calling_window") or {"from": "08:00", "to": "20:00"}
        self.calling_starts = dt.datetime.fromisoformat(scenario["calling_starts_at"])
        self.ready: list[tuple[float, float, int, str]] = []      # (-priority, distance_km, sequence, case_id)
        self.waiting: list[tuple[dt.datetime, int, str]] = []     # (call again at, sequence, case_id)
        self.rank: dict[str, tuple[float, float]] = {}            # case_id -> (priority, distance_km)
        self.personas: dict[str, dict] = {}
        self.active: set[str] = set()                             # cases with a call in progress
        self.work: set[asyncio.Task] = set()
        self.call_order: list[str] = []                           # first attempts, in the order they were placed
        self.total = self.triaged = 0
        self.triage_done = False
        self.hero_case: str | None = None
        self.max_seen = 0
        self._seq = 0
        self._s1_reported = False

    # ---------- helpers ----------
    def _emit(self, type_: str, data: dict, case_id: str | None = None, agent: str = "dispatcher") -> None:
        self.store.emit(type_, data, case_id=case_id, agent=agent, live=(case_id is not None and case_id == self.hero_case and not self.hero_sim))

    def _push(self, case_id: str) -> None:
        priority, distance = self.rank[case_id]
        self._seq += 1
        heapq.heappush(self.ready, (-priority, distance, self._seq, case_id))

    def queue(self) -> list[dict]:
        """Cases waiting for their call, in the order they will be called."""
        return [{"case_id": c, "priority": -p, "distance_km": d} for p, d, _, c in sorted(self.ready)]

    def info(self) -> dict:
        return {"total": self.total, "triaged": self.triaged, "triage_done": self.triage_done, "waiting": len(self.ready), "retry_later": len(self.waiting),
                "on_call": len(self.active), "max_parallel": self.max_parallel, "max_on_call_seen": self.max_seen, "hero_case": self.hero_case}

    # ---------- opening cases ----------
    async def open_cases(self, storm: dict) -> list[tuple[dict, dict]]:
        """A case for every insured farmer in the affected villages, read through the registry MCP server. Returns (village, farmer) pairs."""
        self._emit("agent.started", {"summary": "Opening a case for every insured farmer in the storm's path"})
        t0 = time.perf_counter()
        villages = sorted(storm["villages"], key=lambda v: (INTENSITY_RANK.get(v["intensity"], 9), v["distance_km"]))
        pairs: list[tuple[dict, dict]] = []
        for village in villages:
            await self.clock.wait_running()
            out = await mcp_client.call_tool(config.MCP_REGISTRY_URL, "list_farmers_in_villages", {"village_ids": [village["village_id"]]},
                                             server="registry", client="dispatcher", agent="dispatcher", pooled=True, emit=self._emit)
            for farmer in out.get("farmers") or []:
                case = self.store.open_case(farmer["id"])
                if farmer.get("is_hero"):
                    self.hero_case = case["id"]
                pairs.append((village, farmer))
            await asyncio.sleep(0)
        self.total = len(pairs)
        self.store.emit_stats(force=True)
        self._emit("agent.finished", {"summary": f"{self.total} cases opened, each with 72 hours to report.", "seconds": round(time.perf_counter() - t0, 2), "ok": True})
        return pairs

    # ---------- ranking ----------
    async def triage(self, storm: dict, pairs: list[tuple[dict, dict]]) -> None:
        """TRIAGE for every case, village by village, the worst-hit village first. A village's farmers join the queue together,
        so calling starts as soon as the first village is ranked."""
        for village in sorted({v["village_id"]: v for v, _ in pairs}.values(), key=lambda v: (INTENSITY_RANK.get(v["intensity"], 9), v["distance_km"])):
            batch = []
            for v, farmer in pairs:
                if v["village_id"] != village["village_id"]:
                    continue
                await self.clock.wait_running()
                case_id = "case_" + farmer["id"][1:]
                distance = round(geo.haversine_km(farmer["plot_lat"], farmer["plot_lon"], storm["center_lat"], storm["center_lon"]), 1)
                is_live = bool(farmer.get("is_hero")) and not self.hero_sim
                # The report gives the distance in whole kilometres. Farms whose reports read the same are then ranked from one
                # computation (the repeats are shown as "cached"), which keeps 340 rankings ahead of the calls on a laptop CPU.
                # The exact distance still breaks ties in the queue.
                state = {"crop": farmer.get("crop") or "wheat", "crop_stage": "close to harvest", "hail_intensity": village["intensity"],
                         "distance_km": round(distance), "insured_area_ha": farmer.get("insured_area_ha"), "notes": farmer.get("notes") or ""}
                priority = None
                try:
                    out = await asyncio.to_thread(http.post_json, f"{config.S1_URL}/decide",
                                                  {"decision": "TRIAGE", "case_id": case_id, "state": state, "sim": not is_live, "live": is_live}, 30.0)
                    priority = priority_of((out.get("answers") or {}).get("damage_likelihood"))
                except Exception as e:  # noqa: BLE001
                    if not self._s1_reported:
                        self._s1_reported = True
                        self._emit("fallback.used", {"component": "s1", "from": "TRIAGE", "to": "ranking by hail intensity", "reason": f"{type(e).__name__}"})
                if priority is None:
                    priority = FALLBACK_PRIORITY.get(village["intensity"], 10.0)
                self.store.set_priority(case_id, priority)
                self.rank[case_id] = (priority, distance)
                self.triaged += 1
                batch.append((case_id, farmer))
            for case_id, farmer in batch:
                if self.store.status_of(case_id) == models.AFFECTED:
                    self.store.set_status(case_id, models.QUEUED, "triaged", agent="dispatcher")
                if farmer.get("is_hero") and not self.hero_sim:
                    continue  # the live farmer is called when the presenter says so
                persona = HERO_PERSONA if farmer.get("is_hero") else self.store.persona(case_id)
                if persona is None:
                    continue
                self.personas[case_id] = persona
                if self.store.status_of(case_id) == models.QUEUED:
                    self._push(case_id)
        self.triage_done = True

    # ---------- calling ----------
    async def _handle(self, case_id: str) -> None:
        try:
            result = await self.simulator.call(case_id, self.personas[case_id])
        except Exception as e:  # noqa: BLE001 - one broken case must not stop the fleet
            self._emit("fallback.used", {"component": "simulator", "from": case_id, "to": "skipped", "reason": f"{type(e).__name__}: {str(e)[:80]}"}, case_id)
            result = "closed"
        finally:
            self.active.discard(case_id)
        if result == "retry":
            self._seq += 1
            heapq.heappush(self.waiting, (self.clock.now() + dt.timedelta(seconds=RETRY_AFTER_S), self._seq, case_id))
        elif result == "process":
            await self.pipeline.wait(self.pipeline.start(case_id), case_id, seconds=120)

    def _spawn(self, case_id: str) -> None:
        self.active.add(case_id)
        self.max_seen = max(self.max_seen, len(self.active))
        if self.store.conn.execute("SELECT attempts FROM cases WHERE id = ?", (case_id,)).fetchone()["attempts"] == 0:
            self.call_order.append(case_id)
        task = asyncio.create_task(self._handle(case_id))
        self.work.add(task)
        task.add_done_callback(self.work.discard)

    def fleet_done(self) -> bool:
        return self.triage_done and not self.ready and not self.waiting and not self.active and not self.work

    async def run_calls(self) -> None:
        """Place calls until every simulated farmer's case is settled."""
        while not self.fleet_done():
            await self.clock.wait_running()
            now = self.clock.now()
            while self.waiting and self.waiting[0][0] <= now:
                _, _, case_id = heapq.heappop(self.waiting)
                self._push(case_id)
            open_now = now >= self.calling_starts and in_calling_hours(now, self.window)
            while open_now and self.ready and len(self.active) < self.max_parallel:
                _, _, _, case_id = heapq.heappop(self.ready)
                self._spawn(case_id)
            if not open_now and now >= self.calling_starts and not self.active and not self.work and (self.ready or self.waiting):
                # Night: nobody is called between the end of calling hours and the morning. Nothing is in progress, so skip ahead.
                opening = next_opening(now, self.window)
                self._emit("agent.finished", {"summary": f"Calling hours are over. Calls start again at {opening.strftime('%H:%M')}.", "seconds": 0, "ok": True})
                self.clock.jump_to(opening)
            elif self.waiting and not self.ready and not self.active and not self.work and self.waiting[0][0] > now:
                await self.clock.sleep_until(min(self.waiting[0][0], now + dt.timedelta(seconds=60)))
            else:
                await asyncio.sleep(0.01)

    def cancel(self) -> None:
        for task in list(self.work):
            task.cancel()
        self.work.clear()
