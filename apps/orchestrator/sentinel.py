"""Sentinel agent (SystemDesign §12, FR-01): asks the weather MCP server which storms hit the district, and reports the one found."""
from __future__ import annotations

from ghante_shared import config, mcp_client

from .cases import CaseStore


class Sentinel:
    def __init__(self, store: CaseStore, scenario: dict) -> None:
        self.store, self.scenario = store, scenario

    def _emit(self, type_: str, data: dict, case_id: str | None = None, agent: str = "sentinel") -> None:
        self.store.emit(type_, data, case_id=case_id, agent=agent, live=False)

    async def detect(self) -> dict | None:
        """Returns the storm event ({id, type, started_at, center_lat, center_lon, radius_km, villages:[{village_id, intensity,
        distance_km}]}) or None when the weather server reports nothing."""
        self._emit("agent.started", {"summary": f"Asking the weather service about storms in {self.scenario['district']}"})
        since = self.scenario["scenario_date"] + "T00:00:00+05:30"
        try:
            out = await mcp_client.call_tool(config.MCP_WEATHER_URL, "list_storm_events", {"district": self.scenario["district"], "since": since},
                                             server="weather", client="sentinel", agent="sentinel", pooled=True, emit=self._emit)
            events = out.get("events") or []
        except Exception as e:  # noqa: BLE001
            self._emit("fallback.used", {"component": "mcp weather", "from": "list_storm_events", "to": "scenario file", "reason": f"{type(e).__name__}: {str(e)[:80]}"})
            events = [{**self.scenario["storm"], "villages": self.scenario["villages"]}]  # the same record the server replays, read directly
        if not events:
            self._emit("agent.finished", {"summary": "No storm on record.", "seconds": 0, "ok": True})
            return None
        storm = events[0]
        self._emit("storm.detected", {"event_id": storm["id"], "type": storm["type"], "center": {"lat": storm["center_lat"], "lon": storm["center_lon"]},
                                      "radius_km": storm["radius_km"], "started_at": storm["started_at"], "villages": storm["villages"]})
        self._emit("agent.finished", {"summary": f"{storm['type'].capitalize()} over {len(storm['villages'])} villages.", "seconds": 0, "ok": True})
        return storm
