"""Scenario controller: start, pause, resume and reset of the district run, and the clock messages for the dashboard.

Order of a run (SystemDesign §12): the clock jumps to the detection time and starts; the Sentinel reports the storm; the
Dispatcher opens the cases, ranks them and calls; the Simulator plays the farmers; the pipeline files. The live (hero) farmer is
ranked with the others but called only when the presenter presses the key.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import time

from ghante_shared import config, models

from .cases import CaseStore
from .clock import SimClock
from .dispatcher import Dispatcher
from .pipeline.service import Pipeline
from .sentinel import Sentinel

IDLE, RUNNING, PAUSED, FINISHED = "idle", "running", "paused", "finished"


class Scenario:
    def __init__(self, store: CaseStore, clock: SimClock, pipeline: Pipeline, scenario: dict) -> None:
        self.store, self.clock, self.pipeline, self.scenario = store, clock, pipeline, scenario
        self.state = IDLE
        self.paused_by: str | None = None     # "presenter", "live call" or "fleet finished"
        self.dispatcher: Dispatcher | None = None
        self.fleet_finished = False
        self._task: asyncio.Task | None = None
        self._ticker: asyncio.Task | None = None
        self._real_started = 0.0
        self._real_running = 0.0              # real seconds the fleet has been running (pauses excluded)
        self._resumed_at: float | None = None
        store.scenario_info = self.info
        pipeline.hold = self.hold

    async def hold(self) -> None:
        """Simulated cases wait here while a started run is paused. With no run going (a single case opened by hand), nothing waits."""
        while self.state == PAUSED and not self.fleet_finished:
            await asyncio.sleep(0.05)

    # ---------- reading ----------
    def deadline(self) -> str:
        return (dt.datetime.fromisoformat(self.scenario["storm"]["started_at"]) + dt.timedelta(hours=self.store.deadline_hours)).isoformat()

    def running_seconds(self) -> float:
        return round(self._real_running + (time.monotonic() - self._resumed_at if self._resumed_at is not None else 0.0), 1)

    def info(self) -> dict:
        out = {"state": self.state, "paused_by": self.paused_by, "fleet_finished": self.fleet_finished, "speed": self.clock.speed,
               "running_seconds": self.running_seconds() if self.state != IDLE else 0.0}
        if self.dispatcher is not None:
            out.update(self.dispatcher.info())
        return out

    def _announce(self) -> None:
        self.store.emit("scenario.state", self.info(), agent="system", live=False)
        self._tick()

    def _tick(self) -> None:
        self.store.emit("sim.clock", self.clock.state(self.deadline()), agent="system", live=False)

    # ---------- control ----------
    def start(self, speed: float | None = None) -> None:
        if self.state != IDLE:
            raise ValueError("the scenario has already been started; reset first")
        hero_sim = config.env("HERO_SIM", "0") == "1"
        self.store.live_hero = not hero_sim
        self.dispatcher = Dispatcher(self.store, self.clock, self.pipeline, self.scenario, hero_sim=hero_sim,
                                     max_parallel=config.env_int("MAX_PARALLEL_CALLS", 8))
        self.clock.reset()
        if speed:
            self.clock.set_speed(speed)
        # The storm began at 15:30; the weather service has it on record at the detection time. That is where the run starts.
        self.clock.jump_to(dt.datetime.fromisoformat(self.scenario["detected_at"]))
        self.clock.resume()
        self.state, self.paused_by, self.fleet_finished = RUNNING, None, False
        self._real_running, self._resumed_at, self._real_started = 0.0, time.monotonic(), time.monotonic()
        self._task = asyncio.create_task(self._run())
        if self._ticker is None or self._ticker.done():
            self._ticker = asyncio.create_task(self._tick_loop())
        self._announce()

    def pause(self, by: str = "presenter") -> bool:
        if self.state != RUNNING:
            return False
        self.clock.pause()
        if self._resumed_at is not None:
            self._real_running += time.monotonic() - self._resumed_at
            self._resumed_at = None
        self.state, self.paused_by = PAUSED, by
        self._announce()
        return True

    def resume(self, speed: float | None = None) -> bool:
        if speed:
            self.clock.set_speed(speed)
        if self.state != PAUSED or self.fleet_finished:
            if speed and self.state == RUNNING:
                self._announce()
            return False
        self.clock.resume()
        self._resumed_at = time.monotonic()
        self.state, self.paused_by = RUNNING, None
        self._announce()
        return True

    def reset(self) -> None:
        for task in (self._task, self._ticker):
            if task is not None:
                task.cancel()
        if self.dispatcher is not None:
            self.dispatcher.cancel()
        self._task = self._ticker = self.dispatcher = None
        self.state, self.paused_by, self.fleet_finished = IDLE, None, False
        self._real_running, self._resumed_at = 0.0, None

    # ---------- the run ----------
    async def _run(self) -> None:
        d = self.dispatcher
        try:
            storm = await Sentinel(self.store, self.scenario).detect()
            if storm is None:
                return
            pairs = await d.open_cases(storm)
            self._announce()
            self.store.emit("agent.started", {"summary": f"Ranking {len(pairs)} cases and placing calls, {d.max_parallel} at a time"}, agent="dispatcher", live=False)
            t0 = time.perf_counter()
            triage = asyncio.create_task(d.triage(storm, pairs))
            try:
                await d.run_calls()
                await triage
            finally:
                triage.cancel()
            counts = self.store.stats()
            self.store.emit("agent.finished", {"summary": f"Every simulated farmer's case is settled: {counts['filed']} filed.", "seconds": round(time.perf_counter() - t0, 1),
                                               "ok": True}, agent="dispatcher", live=False)
            # Stop the clock so the hours left stay as they were when the last simulated case was settled.
            if self.state == RUNNING:
                self.clock.pause()
                if self._resumed_at is not None:
                    self._real_running += time.monotonic() - self._resumed_at
                    self._resumed_at = None
                self.state, self.paused_by = PAUSED, "fleet finished"
            self.fleet_finished = True
            self.store.emit_stats(force=True)
            self._announce()
            self.check_finished()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - say what stopped the run instead of dying silently
            self.store.emit("fallback.used", {"component": "scenario", "from": "the district run", "to": "stopped", "reason": f"{type(e).__name__}: {str(e)[:120]}"},
                            agent="system", live=False)

    def check_finished(self) -> None:
        """The scenario is finished when the fleet is done and no case (the live one included) is still open."""
        if not self.fleet_finished or self.state == FINISHED:
            return
        if any(status not in models.TERMINAL for status in self.store.statuses().values()):
            return
        self.state, self.paused_by = FINISHED, None
        counts = self.store.stats()
        self.store.emit("scenario.finished", {"totals": {k: counts[k] for k in ("filed", "unreachable", "no_damage", "escalated", "ineligible", "failed")},
                                              "affected": counts["affected"], "hours_left": self.clock.hours_left(self.deadline()),
                                              "sim_ts": self.clock.now_iso(), "running_seconds": self.running_seconds()}, agent="system", live=False)
        self._announce()

    async def _tick_loop(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            while self.state != IDLE:
                await asyncio.sleep(0.5)
                if self.state == RUNNING:
                    self._tick()
                elif self.state == PAUSED and self.fleet_finished:
                    self.check_finished()  # the live case may have been settled since
