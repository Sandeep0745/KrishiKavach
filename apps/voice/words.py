"""English words for clock times, reference numbers and causes, so speech synthesis never has to guess how to read them."""
from __future__ import annotations

import re

_DIGITS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_HOURS = ("twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve")

PERIL_EN = {"hailstorm": "hailstorm", "inundation": "water standing in the field", "landslide": "landslide", "cloudburst": "cloudburst",
            "natural_fire": "fire", "unseasonal_rain": "unseasonal rain", "cyclone": "cyclone", "not_covered": "another cause"}


def digits(text: str) -> str:
    """Each digit and letter read on its own, with commas for short pauses: FCS-000147 -> F, C, S, zero, zero, zero, one, four, seven."""
    out = []
    for ch in str(text).upper():
        if ch.isdigit():
            out.append(_DIGITS[int(ch)])
        elif "A" <= ch <= "Z":
            out.append(ch)
    return ", ".join(out)


def clock(hour: int, minute: int) -> str:
    """Spoken time of day: (15, 30) -> half past three in the afternoon."""
    hour, minute = int(hour) % 24, int(minute) % 60
    if 4 <= hour < 12:
        period = "in the morning"
    elif 12 <= hour < 16:
        period = "in the afternoon"
    elif 16 <= hour < 19:
        period = "in the evening"
    else:
        period = "at night"
    h12 = hour % 12 or 12
    if minute == 0:
        body = f"{_HOURS[h12]} o'clock"
    elif minute == 15:
        body = f"quarter past {_HOURS[h12]}"
    elif minute == 30:
        body = f"half past {_HOURS[h12]}"
    elif minute == 45:
        body = f"quarter to {_HOURS[h12 % 12 + 1]}"
    else:
        body = f"{h12}:{minute:02d}"
    return f"{body} {period}"


def clock_from_iso(iso: str | None) -> str:
    m = re.search(r"T(\d{2}):(\d{2})", iso or "")
    return clock(int(m.group(1)), int(m.group(2))) if m else ""
