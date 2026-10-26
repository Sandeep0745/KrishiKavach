"""Open-Meteo adapter and configurable prototype crop-risk screening."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import urllib.parse
import urllib.request

from . import config, db, usage

UTC = dt.timezone.utc
FIELDS = ('temperature_2m', 'precipitation', 'weather_code', 'wind_gusts_10m')
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def utc_now():
    return dt.datetime.now(UTC)


def parse_time(value):
    t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def thresholds():
    limits = {'gust_kmh': max(1, config.env_float('WEATHER_GUST_KMH', 50)),
            'rain_mm_h': max(1, config.env_float('WEATHER_RAIN_MM_H', 20)),
            'heat_c': config.env_float('WEATHER_HEAT_C', 40),
            'frost_c': config.env_float('WEATHER_FROST_C', 2)}
    if not all(math.isfinite(value) for value in limits.values()) or limits['frost_c'] >= limits['heat_c']:
        raise ValueError('Invalid crop-risk thresholds')
    return limits


def villages(district):
    sc = db.load_scenario()
    if district.casefold() != sc['district'].casefold():
        raise ValueError('Only the configured district is monitored')
    ids = {v['village_id'] for v in sc['villages']}
    rows = json.loads((config.SEED_DIR / 'villages.json').read_text(encoding='utf-8'))
    points = [v for v in rows if v['id'] in ids]
    if len(points) != len(ids):
        raise ValueError('Missing village coordinates')
    return points


def fetch_forecasts(points):
    query = urllib.parse.urlencode({'latitude': ','.join(str(v['lat']) for v in points),
        'longitude': ','.join(str(v['lon']) for v in points), 'current': ','.join(FIELDS),
        'hourly': ','.join(FIELDS), 'timezone': 'UTC', 'wind_speed_unit': 'kmh',
        'precipitation_unit': 'mm', 'temperature_unit': 'celsius', 'forecast_days': 2})
    request = urllib.request.Request('https://api.open-meteo.com/v1/forecast?' + query,
                                    headers={'User-Agent': 'KrishiKavach-educational-prototype/1.0'})
    usage.add('open-meteo', 'http_requests', 1)
    usage.add('open-meteo', 'forecast_locations', len(points))
    with OPENER.open(request, timeout=15) as response:
        payload = json.load(response)
    rows = payload if isinstance(payload, list) else [payload]
    if len(rows) != len(points):
        raise ValueError('Incomplete weather response')
    return rows


def demo_forecasts(points, severe, now):
    """Synthetic API-shaped data; never used as a fallback for a live failure."""
    current = {'time': now.isoformat(), 'interval': 900, 'temperature_2m': 24,
               'precipitation': 0, 'weather_code': 99 if severe else 1,
               'wind_gusts_10m': 75 if severe else 12}
    hourly = {'time': [now.replace(minute=0, second=0, microsecond=0).isoformat()]}
    for key in FIELDS:
        hourly[key] = [25 if severe and key == 'precipitation' else current[key]]
    units = {'temperature_2m': '°C', 'precipitation': 'mm', 'weather_code': 'wmo code', 'wind_gusts_10m': 'km/h'}
    return [{'current': dict(current), 'hourly': dict(hourly), 'current_units': units,
             'hourly_units': units, 'utc_offset_seconds': 0} for _ in points]


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('Missing or invalid weather measurement')
    return value


def reasons(record, limits, hourly):
    temp, rain, code, gust = [numeric(record[k]) for k in FIELDS]
    if not -100 <= temp <= 70 or rain < 0 or gust < 0 or int(code) != code:
        raise ValueError('Weather measurement out of range')
    out = []
    if code in (96, 99):
        out.append('Hail risk (weather code %d)' % code)
    elif code in (95, 97):
        out.append('Thunderstorm risk (weather code %d)' % code)
    if gust >= limits['gust_kmh']:
        out.append('Wind gust %.1f km/h ≥ %.1f' % (gust, limits['gust_kmh']))
    if hourly and rain >= limits['rain_mm_h']:
        out.append('Hourly rain %.1f mm ≥ %.1f' % (rain, limits['rain_mm_h']))
    if temp >= limits['heat_c']:
        out.append('Heat %.1f C ≥ %.1f' % (temp, limits['heat_c']))
    if temp <= limits['frost_c']:
        out.append('Frost risk %.1f C ≤ %.1f' % (temp, limits['frost_c']))
    return out


def assess(payloads, points, now=None, provider='open-meteo'):
    now = now or utc_now()
    limits = thresholds()
    risks, observations = [], []
    if len(payloads) != len(points):
        raise ValueError('Incomplete weather response')
    for point, payload in zip(points, payloads):
        if payload.get('error') or payload.get('utc_offset_seconds') != 0:
            raise ValueError('Invalid weather response or timezone')
        for group in ('current', 'hourly'):
            units = payload.get(group + '_units', {})
            for key, unit in (('temperature_2m', '°C'), ('precipitation', 'mm'), ('wind_gusts_10m', 'km/h')):
                if units.get(key) != unit:
                    raise ValueError('Unexpected weather units')
        current = payload['current']
        observed = parse_time(current['time'])
        age = (now - observed).total_seconds()
        if age < -900 or age > 5400:
            raise ValueError('Stale current weather; automatic trigger suppressed')
        observations.append({'village_id': point['id'], 'village': point['name'], 'at': observed.isoformat(),
                             **{k: numeric(current[k]) for k in FIELDS}})
        samples = [('current', observed, current, False)]
        hourly = payload['hourly']
        times = hourly['time']
        if not times or any(len(hourly[k]) != len(times) for k in FIELDS):
            raise ValueError('Incomplete hourly forecast')
        usable = 0
        for i, raw_time in enumerate(times):
            at = parse_time(raw_time)
            if now.replace(minute=0, second=0, microsecond=0) <= at <= now + dt.timedelta(hours=6):
                usable += 1
                samples.append(('forecast', at, {k: hourly[k][i] for k in FIELDS}, True))
        if not usable:
            raise ValueError('Forecast does not cover the current six-hour window')
        for kind, at, sample, is_hourly in samples:
            why = reasons(sample, limits, is_hourly)
            if why:
                risks.append({'village_id': point['id'], 'village': point['name'], 'kind': kind,
                              'at': at.isoformat(), 'reasons': why, **{k: sample[k] for k in FIELDS}})
    key = hashlib.sha256(json.dumps([(r['village_id'], r['at'], r['reasons']) for r in risks], sort_keys=True).encode()).hexdigest()
    return {'provider': provider, 'checked_at': now.isoformat(), 'hazardous': bool(risks),
            'risks': risks, 'observations': observations, 'thresholds': limits,
            'monitored_villages': len(points), 'incident_key': key,
            'attribution': 'Weather data by Open-Meteo.com' if provider == 'open-meteo' else 'Simulated demonstration weather'}


def get_crop_risk(district, mode='live', demo_severe=False):
    points = villages(district)
    now = utc_now()
    if mode == 'live':
        payloads, provider = fetch_forecasts(points), 'open-meteo'
    elif mode == 'demo':
        payloads, provider = demo_forecasts(points, demo_severe, now), 'demo'
    else:
        raise ValueError('Unknown weather source')
    return assess(payloads, points, now, provider)
