"""Scenario clock (SystemDesign §12.4). Scenario time runs at `speed` scenario seconds per real second while not paused.

Everything the simulated fleet waits for (a phone ringing, a call lasting three minutes, a retry half an hour later) is waited
for on this clock, so pausing it freezes the fleet.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time


class SimClock:
    def __init__(self, start_iso: str, speed: float = 180.0) -> None:
        self.start = dt.datetime.fromisoformat(start_iso)
        self.speed = speed
        self.default_speed = speed
        self.paused = True
        self._sim_elapsed = 0.0  # scenario seconds elapsed while running
        self._real_anchor = time.monotonic()

    def now(self) -> dt.datetime:
        elapsed = self._sim_elapsed
        if not self.paused:
            elapsed += (time.monotonic() - self._real_anchor) * self.speed
        return self.start + dt.timedelta(seconds=elapsed)

    def now_iso(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def _fold(self) -> None:
        if not self.paused:
            self._sim_elapsed += (time.monotonic() - self._real_anchor) * self.speed
        self._real_anchor = time.monotonic()

    def resume(self) -> None:
        if self.paused:
            self._real_anchor = time.monotonic()
            self.paused = False

    def pause(self) -> None:
        if not self.paused:
            self._fold()
            self.paused = True

    def set_speed(self, speed: float) -> None:
        if speed > 0:
            self._fold()
            self.speed = float(speed)

    def jump_to(self, when: dt.datetime) -> None:
        """Move scenario time (forwards: to the detection time at the start, or over the night when no calls are allowed)."""
        self._sim_elapsed = (when - self.start).total_seconds()
        self._real_anchor = time.monotonic()

    def reset(self) -> None:
        self.paused, self._sim_elapsed, self._real_anchor, self.speed = True, 0.0, time.monotonic(), self.default_speed

    async def wait_running(self) -> None:
        while self.paused:
            await asyncio.sleep(0.05)

    async def sleep_until(self, target: dt.datetime) -> None:
        """Wait for a scenario time. Stands still while the clock is paused; notices speed changes and jumps."""
        while True:
            remaining = (target - self.now()).total_seconds()
            if remaining <= 0:
                return
            if self.paused:
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(min(max(remaining / self.speed, 0.001), 0.1))

    async def sleep(self, sim_seconds: float) -> None:
        await self.sleep_until(self.now() + dt.timedelta(seconds=sim_seconds))

    def hours_left(self, deadline_iso: str) -> float:
        return round((dt.datetime.fromisoformat(deadline_iso) - self.now()).total_seconds() / 3600, 2)

    def state(self, deadline_iso: str | None = None) -> dict:
        out = {"sim_ts": self.now_iso(), "paused": self.paused, "speed": self.speed}
        if deadline_iso:
            out["hours_left"] = self.hours_left(deadline_iso)
        return out
