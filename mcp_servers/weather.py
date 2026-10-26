"""Weather MCP server (SystemDesign §9). Port 8101.

WEATHER_MODE=replay (default): answers from the scenario file. The separate crop-risk tool provides live Open-Meteo forecasts for automatic sandbox startup.
"""
from __future__ import annotations

import datetime as dt

from ghante_shared import config, db, geo

from ._base import make_server, run_http

HOST, PORT = "127.0.0.1", config.port_of(config.MCP_WEATHER_URL, 8101)
server = make_server("weather", "Storm events for a district and the weather record at a place and time.", HOST, PORT)
STORM_MINUTES = 60  # how long the replayed hail lasts at any point inside the footprint


VILLAGE_KM = 2.0    # farms are seeded within about 1.7 km of their village point
_scenario_cache: dict | None = None
_points: list[tuple[float, float]] | None = None


def _scenario() -> dict:
    global _scenario_cache
    if _scenario_cache is None:  # read once: the fleet asks for the weather hundreds of times
        _scenario_cache = db.load_scenario()
    return _scenario_cache


def _village_points() -> list[tuple[float, float]]:
    global _points
    if _points is None:
        import json

        hit = {v["village_id"] for v in _scenario()["villages"]}
        try:
            villages = json.loads((config.SEED_DIR / "villages.json").read_text(encoding="utf-8"))
        except OSError:
            villages = []
        _points = [(v["lat"], v["lon"]) for v in villages if v["id"] in hit]
    return _points


def _parse(ts: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))


@server.tool()
def list_storm_events(district: str, since: str) -> dict:
    """List storm events recorded for a district since an ISO datetime. Each event lists affected villages with intensity."""
    if config.env("WEATHER_MODE", "replay") != "replay":
        return {"error": "live weather mode is not built yet; set WEATHER_MODE=replay", "events": []}
    sc = _scenario()
    storm = sc["storm"]
    events = []
    if district.strip().lower() == sc["district"].lower() and _parse(storm["started_at"]) >= _parse(since):
        events.append({**storm, "district": sc["district"], "state": sc["state"], "villages": sc["villages"], "source": "replay"})
    return {"events": events}


@server.tool()
def get_weather_at(lat: float, lon: float, at: str) -> dict:
    """Weather record at a point and ISO datetime: hail yes/no, rainfall in mm, wind gust in km/h."""
    if config.env("WEATHER_MODE", "replay") != "replay":
        return {"error": "live weather mode is not built yet; set WEATHER_MODE=replay"}
    storm = _scenario()["storm"]
    start = _parse(storm["started_at"])
    when = _parse(at)
    distance = geo.haversine_km(lat, lon, storm["center_lat"], storm["center_lon"])
    minutes = (when - start).total_seconds() / 60
    # The footprint is the circle around the core plus the land of every village the scenario lists as hit: the storm moved,
    # so a few farms of the outer villages lie just outside the circle.
    in_footprint = distance <= storm["radius_km"] or any(geo.haversine_km(lat, lon, v_lat, v_lon) <= VILLAGE_KM for v_lat, v_lon in _village_points())
    inside = in_footprint and -10 <= minutes <= STORM_MINUTES
    if inside:
        closeness = max(0.0, 1 - distance / storm["radius_km"])  # 1 at the core, 0 at the edge
        return {"hail": True, "precipitation_mm": round(6 + 22 * closeness, 1), "wind_gust_kmh": round(45 + 40 * closeness),
                "weather_code": 99 if closeness > 0.5 else 96, "distance_from_core_km": round(distance, 1),
                "minutes_from_storm_start": round(minutes), "source": "replay"}
    return {"hail": False, "precipitation_mm": 0.0, "wind_gust_kmh": 12, "weather_code": 1, "distance_from_core_km": round(distance, 1),
            "minutes_from_storm_start": round(minutes), "source": "replay"}


@server.tool()
def get_crop_risk(district: str, mode: str = "live", demo_severe: bool = False) -> dict:
    """Screen current and six-hour forecast weather; errors never turn into synthetic storm alerts."""
    from ghante_shared.weather_risk import get_crop_risk as screen
    try:
        return screen(district, mode, demo_severe)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: weather unavailable or invalid", "hazardous": False}


if __name__ == "__main__":
    run_http(server, HOST, PORT)
