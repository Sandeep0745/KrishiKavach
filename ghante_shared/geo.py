"""Distance helpers."""
from __future__ import annotations

import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def offset(lat: float, lon: float, north_km: float, east_km: float) -> tuple[float, float]:
    """Move a point by a few km north and east (small-distance approximation)."""
    return lat + north_km / 110.574, lon + east_km / (111.320 * math.cos(math.radians(lat)))
