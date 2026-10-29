"""Eligibility rules and the claim form, as plain functions with no I/O (SystemDesign §13 and §14.2).

The rules decide policy status, covered peril, the 72-hour limit and the clear-cut evidence cases. The VERIFY model is asked
only when every rule has passed (it is a second opinion on whether statement, photo and weather tell one story).
"""
from __future__ import annotations

import datetime as dt

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# Check 3. Follows ProblemStudy.md F3; must be re-checked against the official guidelines (research item R2).
COVERED = {
    "standing": {"hailstorm", "inundation", "landslide", "cloudburst", "natural_fire"},
    "harvested": {"hailstorm", "unseasonal_rain", "cyclone"},
}
MAX_DISTANCE_M = 2000
MAX_MINUTES_FROM_STORM = 180
HEALTHY_MIN = 0.6
VERIFY_MIN = 0.6

# Portal option labels (apps/portal/main.py)
CAUSE_LABEL = {"hailstorm": "Hailstorm", "inundation": "Inundation", "landslide": "Landslide", "cloudburst": "Cloudburst",
               "natural_fire": "Natural fire", "unseasonal_rain": "Unseasonal rain (post-harvest)", "cyclone": "Cyclone (post-harvest)"}
STAGE_LABEL = {"standing": "Standing crop", "harvested": "Harvested (cut and spread)"}
SUBMITTED_BY = "Authorised assistant (on behalf of farmer)"
PHOTO_WORDS = {"hail_damage": "hail damage", "lodged": "crop flattened", "waterlogged": "field under water", "healthy": "healthy crop",
               "not_a_crop": "not a crop photo"}


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=IST)


def minutes_from_storm(case: dict) -> int | None:
    stated, storm = parse_time((case.get("slots") or {}).get("loss_datetime")), parse_time((case.get("storm") or {}).get("started_at"))
    if stated is None or storm is None:
        return None
    return round((stated - storm).total_seconds() / 60)


def weather_time(case: dict) -> str | None:
    """The moment to look up in the weather record. A farmer's "around three o'clock" is approximate, so when the stated time is
    within the allowed distance of the recorded storm (check 7b) the storm's own time is looked up; otherwise the stated time."""
    stated, storm = (case.get("slots") or {}).get("loss_datetime"), (case.get("storm") or {}).get("started_at")
    minutes = minutes_from_storm(case)
    if storm and (stated is None or (minutes is not None and abs(minutes) <= MAX_MINUTES_FROM_STORM)):
        return storm
    return stated or storm


def weather_confirms(peril: str | None, weather: dict | None) -> tuple[bool, str]:
    """Check 7a: does the weather record at the spot support the stated cause?"""
    if not weather or weather.get("error"):
        return False, "No weather record could be read for the place and time"
    rain, gust = float(weather.get("precipitation_mm") or 0), float(weather.get("wind_gust_kmh") or 0)
    if peril == "hailstorm":
        return (True, "Weather record shows hail") if weather.get("hail") else (False, "Evidence inconsistent: the weather record shows no hail at that place and time")
    if peril in ("inundation", "cloudburst", "unseasonal_rain"):
        return (True, f"Weather record shows {rain} mm of rain") if rain > 0 else (False, "Evidence inconsistent: the weather record shows no rain at that place and time")
    if peril == "cyclone":
        return (True, f"Weather record shows gusts of {round(gust)} km/h") if gust >= 60 else (False, "Evidence inconsistent: the weather record shows no storm winds")
    return True, "This cause cannot be checked against the weather record"


def run_checks(case: dict, evidence: dict | None, weather: dict | None, distance_m: float | None, now: dt.datetime) -> list[dict]:
    """The rule checks of SystemDesign §13, in order. Each is {n, name, passed, fail, detail}; `fail` is the verdict a failure gives."""
    slots, policy, storm = case.get("slots") or {}, case.get("policy") or {}, case.get("storm") or {}
    checks: list[dict] = []

    def add(n: str, name: str, passed: bool, fail: str, detail: str) -> None:
        checks.append({"n": n, "name": name, "passed": bool(passed), "fail": fail, "detail": detail})

    # 1 policy active on the storm date
    storm_day = str(storm.get("started_at") or "")[:10]
    active = policy.get("status") == "active"
    in_term = bool(storm_day) and str(policy.get("valid_from") or "") <= storm_day <= str(policy.get("valid_to") or "")
    add("1", "policy_active", active and in_term, "ineligible",
        "Policy active on the day of the storm" if active and in_term else "Policy not active" if not active else "Storm date is outside the policy period")
    # 2 insured crop on the plot the farmer confirmed
    crop = str(policy.get("crop") or "")
    crop_ok = bool(crop) and slots.get("khasra_confirmed") is not False
    add("2", "insured_crop", crop_ok, "ineligible",
        f"Insured crop {crop} on khasra {policy.get('khasra_no')}" if crop_ok else "The damaged crop is not the insured crop on this plot")
    # 3 peril covered for the crop stage
    peril, stage = slots.get("peril"), slots.get("crop_stage")
    if peril is None or stage not in COVERED:
        add("3", "peril_covered", False, "review", "Cause of loss or crop stage was not recorded")
    else:
        covered = peril in COVERED[stage]
        add("3", "peril_covered", covered, "ineligible",
            f"{peril.replace('_', ' ').capitalize()} is covered for a {stage} crop" if covered else f"Peril not covered ({peril.replace('_', ' ')}, {stage} crop)")
    # 4 inside the reporting window
    deadline = parse_time(case.get("deadline_at"))
    in_time = deadline is not None and now <= deadline
    hours = round((deadline - now).total_seconds() / 3600, 1) if deadline else None
    add("4", "within_72_hours", in_time, "ineligible", f"{hours} hours left of the 72" if in_time else "Reported outside 72 hours of the loss")
    # 5 consent
    add("5", "consent", slots.get("consent") is True, "review", "Farmer agreed to the report being filed" if slots.get("consent") is True else "No consent on record")
    # 6 usable photo
    label = (evidence or {}).get("edge_label")
    confidence = float((evidence or {}).get("edge_confidence") or 0)
    if evidence is None:
        add("6", "photo", False, "review", "No usable photo: none was received")
    elif label == "not_a_crop":
        add("6", "photo", False, "review", "No usable photo: it does not show a crop")
    elif label == "healthy" and confidence >= HEALTHY_MIN:
        add("6", "photo", False, "review", "Evidence inconsistent: the photo shows a healthy crop")
    else:
        add("6", "photo", True, "review", f"Photo received ({PHOTO_WORDS.get(label, 'not checked on the phone')})")
    # 7 photo taken at the plot
    if evidence is None or distance_m is None:
        add("7", "photo_location", False, "review", "No photo location to compare with the insured plot")
    else:
        near = distance_m <= MAX_DISTANCE_M
        where = "the phone had no GPS fix, so the plot's own location was recorded" if evidence.get("gps_source") == "plot" else f"{round(distance_m)} m from the insured plot"
        add("7", "photo_location", near, "review", f"Photo location: {where}" if near else f"Photo location far from insured plot ({round(distance_m / 1000, 1)} km)")
    # 7a weather supports the stated cause
    ok, detail = weather_confirms(peril, weather)
    add("7a", "weather_match", ok, "review", detail)
    # 7b stated time close to the recorded storm
    minutes = minutes_from_storm(case)
    add("7b", "time_match", minutes is not None and abs(minutes) <= MAX_MINUTES_FROM_STORM, "review",
        "Time of loss was not recorded" if minutes is None else f"Stated time is {abs(minutes)} minutes from the recorded storm"
        if abs(minutes) <= MAX_MINUTES_FROM_STORM else f"Evidence inconsistent: the stated time is {abs(minutes)} minutes from the recorded storm")
    return checks


def verdict_of(checks: list[dict]) -> tuple[str, list[str]]:
    """Ineligible if any ineligible-type check failed; else review if any other failed; else eligible."""
    failed = [c for c in checks if not c["passed"]]
    for kind in ("ineligible", "review"):
        reasons = [c["detail"] for c in failed if c["fail"] == kind]
        if reasons:
            return kind, reasons
    return "eligible", []


def verify_state(case: dict, evidence: dict | None, weather: dict | None, distance_m: float | None) -> dict:
    """The state for the VERIFY decision (SystemDesign §8.2)."""
    slots, weather = case.get("slots") or {}, weather or {}
    return {"peril": slots.get("peril"), "damage_pct": slots.get("damage_pct"), "loss_datetime": slots.get("loss_datetime"),
            "edge_label": (evidence or {}).get("edge_label"), "edge_confidence": (evidence or {}).get("edge_confidence"),
            "hail": bool(weather.get("hail")), "precipitation_mm": weather.get("precipitation_mm", 0), "wind_gust_kmh": weather.get("wind_gust_kmh", 0),
            "distance_from_plot_m": round(distance_m) if distance_m is not None else None, "minutes_from_storm": minutes_from_storm(case)}


def p_consistent(decision: dict | None) -> float | None:
    """P(evidence_consistent) from a VERIFY answer, or None when there is no answer."""
    answer = ((decision or {}).get("answers") or {}).get("evidence_consistent") or {}
    if not isinstance(answer.get("value"), bool):
        return None
    confidence = float(answer.get("confidence") or 0.0)
    return confidence if answer["value"] else 1 - confidence


def _number(value: float, places: int = 2) -> str:
    text = f"{round(float(value), places):.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


def build_form(case: dict, evidence: dict | None, weather: dict | None, distance_m: float | None, note: str = "") -> dict:
    """The portal form (SystemDesign §14.2). Every value is text, exactly as it is typed into the page."""
    slots, policy, farmer, village, storm = (case.get(k) or {} for k in ("slots", "policy", "farmer", "village", "storm"))
    when = parse_time(slots.get("loss_datetime")) or parse_time(storm.get("started_at"))
    area, pct = float(policy.get("insured_area_ha") or 0), int(slots.get("damage_pct") or 0)
    remarks = ["Reported by phone by an automated assistant on the farmer's behalf, with consent."]
    if evidence:
        sure = f", {round(float(evidence['edge_confidence']) * 100)}% sure" if evidence.get("edge_confidence") is not None else ""
        remarks.append(f"Photo check on the phone: {PHOTO_WORDS.get(evidence.get('edge_label'), 'not checked')}{sure}.")
    else:
        remarks.append("No photo was received.")
    if weather and not weather.get("error"):
        remarks.append(f"Weather record: {'hail' if weather.get('hail') else 'no hail'}, {weather.get('precipitation_mm', 0)} mm rain, gusts {weather.get('wind_gust_kmh', 0)} km/h.")
    if evidence and distance_m is not None and evidence.get("gps_source") != "plot":
        remarks.append(f"Photo taken {round(distance_m)} m from the plot.")
    if note:
        remarks.append(note)
    return {
        "application_no": str(policy.get("application_no") or ""), "farmer_name": str(farmer.get("name") or ""), "mobile": str(farmer.get("mobile") or ""),
        "state": str(village.get("state") or ""), "district": str(village.get("district") or ""), "tehsil": str(village.get("tehsil") or ""),
        "village": str(village.get("name") or ""),
        "season": str(policy.get("season") or ""), "crop": str(policy.get("crop") or "").capitalize(), "khasra_no": str(policy.get("khasra_no") or ""),
        "insured_area_ha": _number(area), "loss_date": when.strftime("%Y-%m-%d") if when else "", "loss_time": when.strftime("%H:%M") if when else "",
        "cause_of_loss": CAUSE_LABEL.get(slots.get("peril"), ""), "crop_stage": STAGE_LABEL.get(slots.get("crop_stage"), ""),
        "affected_area_ha": _number(area * pct / 100), "damage_pct": str(pct), "remarks": " ".join(remarks),
        "gps_lat": _number(evidence["lat"], 5) if evidence and evidence.get("lat") is not None else "",
        "gps_lon": _number(evidence["lon"], 5) if evidence and evidence.get("lon") is not None else "",
        "submitted_by": SUBMITTED_BY, "declaration": "on",
    }
