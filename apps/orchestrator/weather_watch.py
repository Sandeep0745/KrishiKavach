"""Background weather polling; real forecasts start only the synthetic sandbox scenario."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import time

from ghante_shared import config, mcp_client
from ghante_shared.weather_risk import parse_time, utc_now


class WeatherWatch:
    def __init__(self, scenario, store):
        self.scenario, self.store = scenario, store
        self.mode = config.env('WEATHER_WATCH_MODE', 'live')
        self.interval = max(300, config.env_float('WEATHER_POLL_SECONDS', 300))
        self.cooldown = max(300, config.env_float('WEATHER_COOLDOWN_SECONDS', 21600))
        self.ready_at = time.monotonic() + max(0, config.env_float('WEATHER_STARTUP_GRACE_SECONDS', 45))
        self.state_file = config.VAR_DIR / 'weather-watch.json'
        self.saved = {}
        self.persistence_error = False
        try:
            if self.state_file.exists():
                self.saved = json.loads(self.state_file.read_text(encoding='utf-8'))
                if not isinstance(self.saved, dict):
                    raise ValueError('Invalid cooldown state')
                if self.saved.get('triggered_at'):
                    if not isinstance(self.saved['triggered_at'], str):
                        raise ValueError('Invalid cooldown timestamp')
                    parse_time(self.saved['triggered_at'])
        except (OSError, ValueError, TypeError):
            self.persistence_error = True
        self.demo_at = None
        self.demo_triggered = False
        self.triggered_run = None
        self.wake = asyncio.Event()
        self.status = {'mode': self.mode, 'state': 'waiting', 'summary': 'Waiting for the first weather check',
                       'district': scenario.scenario['district'], 'sandbox': True, 'checked_at': None,
                       'provider': None, 'risks': [], 'observations': [], 'trigger_count': 0}

    async def fetch(self, severe=False):
        return await asyncio.wait_for(mcp_client.call_tool(config.MCP_WEATHER_URL, 'get_crop_risk',
            {'district': self.scenario.scenario['district'], 'mode': self.mode, 'demo_severe': severe},
            server='weather', client='weather-watch', agent='sentinel',
            emit=lambda kind, data, case_id, agent: self.store.emit(kind, data, case_id=case_id, agent=agent)), timeout=25)

    def info(self):
        out = {**self.status, 'mode': self.mode, 'poll_seconds': self.interval}
        if self.mode == 'demo' and self.demo_at is not None and not self.demo_triggered:
            out['demo_seconds_left'] = max(0, round(self.demo_at - time.monotonic()))
        return out

    def announce(self, state, summary):
        self.status.update(state=state, summary=summary)
        self.store.emit('weather.watch', self.info(), agent='sentinel', live=self.mode == 'live')

    def arm_demo(self):
        if self.scenario.state != 'idle':
            raise ValueError('Reset the sandbox scenario before arming demo weather')
        self.mode = 'demo'
        self.demo_at = time.monotonic() + 20
        self.demo_triggered = False
        self.status.update(provider='demo', checked_at=None, risks=[], observations=[])
        self.announce('waiting', 'DEMO: clear weather, then a simulated hail alert in 20 seconds')
        self.wake.set()

    def use_live(self):
        self.mode, self.demo_at = 'live', None
        self.status.update(provider='open-meteo', checked_at=None, risks=[], observations=[])
        self.announce('waiting', 'Live Open-Meteo monitoring resumed')
        self.wake.set()

    async def tick(self):
        if self.mode == 'off':
            self.status.update(state='off', summary='Automatic weather monitoring is off')
            return
        if self.mode not in ('live', 'demo'):
            self.announce('error', 'Unknown weather monitoring mode; automatic start disabled')
            return
        severe = self.mode == 'demo' and self.demo_at is not None and time.monotonic() >= self.demo_at
        source_mode = self.mode
        try:
            report = await self.fetch(severe)
            if self.mode != source_mode:
                return  # a presenter changed source while this request was in flight
            if report.get('error'):
                raise ValueError('Weather service unavailable or data invalid')
            age = (utc_now() - parse_time(report['checked_at'])).total_seconds()
            expected = 'open-meteo' if self.mode == 'live' else 'demo'
            if age < -60 or age > 120 or report.get('provider') != expected:
                raise ValueError('Weather response is stale or source does not match')
            if not isinstance(report.get('hazardous'), bool) or report.get('monitored_villages') != len(self.scenario.scenario['villages']):
                raise ValueError('Incomplete weather report')
            if report['hazardous'] and not report.get('risks'):
                raise ValueError('Hazard has no supporting measurements')
            self.status.update({k: report[k] for k in ('provider', 'checked_at', 'risks', 'observations', 'thresholds', 'monitored_villages', 'attribution')})
            if not report['hazardous']:
                self.announce('clear', 'No configured crop-risk threshold crossed in the next six hours')
                return
            if self.scenario.state != 'idle':
                own_run = self.triggered_run is not None and getattr(self.scenario, 'dispatcher', None) is self.triggered_run
                self.announce('active', 'Crop risk: sandbox storm started automatically' if own_run
                              else 'Crop risk detected; existing sandbox run kept intact')
                return
            if self.mode == 'demo' and self.demo_triggered:
                self.announce('cooldown', 'This demonstration already triggered; arm a new demo after reset')
                return
            if self.mode == 'live':
                if time.monotonic() < self.ready_at:
                    self.announce('waiting', 'Crop risk detected; waiting for startup to finish')
                    return
                if self.persistence_error:
                    raise ValueError('Cooldown record cannot be read; automatic start disabled')
                previous = self.saved.get('triggered_at')
                if previous and (utc_now() - parse_time(previous)).total_seconds() < self.cooldown:
                    self.announce('cooldown', 'Crop risk detected; recent automatic trigger is still in cooldown')
                    return
                saved = {'triggered_at': utc_now().isoformat(), 'incident_key': report['incident_key']}
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.state_file.with_suffix('.tmp')
                temporary.write_text(json.dumps(saved), encoding='utf-8')
                temporary.replace(self.state_file)
                self.saved = saved
            self.scenario.start()
            self.triggered_run = getattr(self.scenario, 'dispatcher', None)
            self.demo_triggered = self.mode == 'demo'
            self.status['trigger_count'] += 1
            self.announce('triggered', 'Crop risk detected: sandbox storm started automatically')
            self.store.emit('weather.triggered', {'provider': report['provider'], 'checked_at': report['checked_at'],
                'risks': report['risks'], 'sandbox': True, 'scenario_id': self.scenario.scenario['id']},
                agent='sentinel', live=self.mode == 'live')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.status.update(risks=[], observations=[])
            self.announce('error', f'{type(exc).__name__}: weather could not be verified; no automatic start')

    async def run(self):
        while True:
            self.wake.clear()
            await self.tick()
            delay = 1 if self.mode == 'demo' else self.interval
            if self.status['state'] == 'error':
                delay = min(delay, 60)
            if self.mode == 'live' and time.monotonic() < self.ready_at:
                delay = min(delay, max(1, self.ready_at - time.monotonic()))
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
