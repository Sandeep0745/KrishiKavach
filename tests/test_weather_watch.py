"""Risk screening, safe automatic startup, real MCP and the judge demonstration."""
import asyncio
import copy
import datetime as dt
import json
import os
import pathlib
import tempfile
import time
import unittest
import urllib.request
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from ghante_shared import config, weather_risk as wr
from apps.orchestrator.weather_watch import WeatherWatch
from tests import _util as u


class RiskRules(unittest.TestCase):
    def setUp(self):
        self.now = wr.utc_now().replace(second=0, microsecond=0)
        self.points = [{'id': 'V01', 'name': 'Test village'}]
        self.records = wr.demo_forecasts(self.points, False, self.now)

    def assess(self):
        return wr.assess(self.records, self.points, self.now)

    def test_safe_weather_does_not_raise_an_alert(self):
        self.assertFalse(self.assess()['hazardous'])

    def test_each_crop_risk_is_detected(self):
        for field, value in [('weather_code', 96), ('weather_code', 99), ('weather_code', 95),
                             ('weather_code', 97), ('wind_gusts_10m', 50), ('temperature_2m', 40), ('temperature_2m', 2)]:
            with self.subTest(field=field, value=value):
                self.records = wr.demo_forecasts(self.points, False, self.now)
                self.records[0]['current'][field] = value
                self.assertTrue(self.assess()['hazardous'])

    def test_forecast_heavy_rain_is_detected(self):
        self.records[0]['hourly']['precipitation'] = [20]
        self.assertEqual(self.assess()['risks'][0]['kind'], 'forecast')

    def test_current_rain_is_not_mistaken_for_an_hourly_total(self):
        self.records[0]['current']['precipitation'] = 6
        self.assertFalse(self.assess()['hazardous'])

    def test_stale_and_future_current_weather_are_rejected(self):
        for hours in (-3, 2):
            self.records[0]['current']['time'] = (self.now + dt.timedelta(hours=hours)).isoformat()
            with self.assertRaises(ValueError):
                self.assess()

    def test_past_and_far_future_forecasts_cannot_trigger(self):
        for hours in (-3, 8):
            self.records[0]['hourly']['time'] = [(self.now + dt.timedelta(hours=hours)).isoformat()]
            self.records[0]['hourly']['weather_code'] = [99]
            with self.assertRaises(ValueError):
                self.assess()

    def test_missing_null_nan_wrong_units_and_incomplete_arrays_fail_closed(self):
        for problem in ('null', 'nan', 'unit', 'array', 'timezone'):
            self.records = wr.demo_forecasts(self.points, False, self.now)
            if problem == 'null': self.records[0]['current']['temperature_2m'] = None
            if problem == 'nan': self.records[0]['current']['temperature_2m'] = float('nan')
            if problem == 'unit': self.records[0]['hourly_units']['wind_gusts_10m'] = 'm/s'
            if problem == 'array': self.records[0]['hourly']['temperature_2m'] = []
            if problem == 'timezone': self.records[0]['utc_offset_seconds'] = 19800
            with self.subTest(problem=problem), self.assertRaises(ValueError): self.assess()

    def test_thresholds_can_be_configured(self):
        self.records[0]['current']['wind_gusts_10m'] = 55
        with patch.dict(os.environ, {'WEATHER_GUST_KMH': '60'}):
            self.assertFalse(self.assess()['hazardous'])

    def test_invalid_thresholds_do_not_silently_disable_screening(self):
        for settings in ({'WEATHER_HEAT_C': 'nan'}, {'WEATHER_HEAT_C': '0', 'WEATHER_FROST_C': '2'}):
            with patch.dict(os.environ, settings), self.assertRaises(ValueError): self.assess()

    def test_unknown_district_is_rejected(self):
        with self.assertRaises(ValueError): wr.villages('Unknown district')

    def test_live_network_error_never_uses_demo_weather(self):
        with patch.object(wr, 'fetch_forecasts', side_effect=OSError('offline')), patch.object(wr, 'demo_forecasts') as demo:
            with self.assertRaises(OSError): wr.get_crop_risk('Sehore')
            demo.assert_not_called()


class WatchRules(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'WEATHER_WATCH_MODE': 'live', 'WEATHER_STARTUP_GRACE_SECONDS': '0'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.var = patch.object(config, 'VAR_DIR', pathlib.Path(self.tmp.name))
        self.var.start(); self.addCleanup(self.var.stop)
        self.scenario = SimpleNamespace(state='idle', scenario={'id': 'test', 'district': 'Sehore', 'villages': [{}]})
        def start(): self.scenario.state = 'running'
        self.scenario.start = Mock(side_effect=start)
        self.store = Mock()
        self.watch = WeatherWatch(self.scenario, self.store)
        points = [{'id': 'V01', 'name': 'Village'}]
        now = wr.utc_now()
        self.report = wr.assess(wr.demo_forecasts(points, True, now), points, now)
        self.watch.fetch = AsyncMock(return_value=self.report)

    async def test_hazard_starts_once_and_never_resets_existing_run(self):
        await self.watch.tick(); await self.watch.tick()
        self.scenario.start.assert_called_once()
        self.assertEqual(self.watch.status['trigger_count'], 1)
        self.assertTrue(self.watch.state_file.exists())

    async def test_safe_weather_leaves_scenario_idle(self):
        self.watch.fetch.return_value = {**self.report, 'hazardous': False, 'risks': []}
        await self.watch.tick()
        self.scenario.start.assert_not_called()
        self.assertEqual(self.watch.status['state'], 'clear')

    async def test_error_and_stale_reports_never_trigger(self):
        reports = [{'error': 'offline'}, {**self.report, 'checked_at': '2000-01-01T00:00:00Z'},
                   {**self.report, 'provider': 'demo'}, {**self.report, 'monitored_villages': 0}]
        for report in reports:
            self.watch.fetch.return_value = report
            await self.watch.tick()
            self.assertEqual(self.watch.status['state'], 'error')
        self.scenario.start.assert_not_called()

    async def test_mcp_exception_does_not_trigger(self):
        self.watch.fetch.side_effect = TimeoutError()
        await self.watch.tick()
        self.scenario.start.assert_not_called()

    async def test_running_paused_finished_scenarios_are_preserved(self):
        for state in ('running', 'paused', 'finished'):
            self.scenario.state = state
            await self.watch.tick()
        self.scenario.start.assert_not_called()

    async def test_persisted_cooldown_survives_reset_and_restart(self):
        await self.watch.tick()
        self.scenario.state = 'idle'
        restarted = WeatherWatch(self.scenario, self.store)
        restarted.fetch = AsyncMock(return_value=self.report)
        await restarted.tick()
        self.scenario.start.assert_called_once()
        self.assertEqual(restarted.status['state'], 'cooldown')

    async def test_corrupt_or_unwritable_cooldown_fails_closed(self):
        self.watch.state_file.write_text('broken')
        bad = WeatherWatch(self.scenario, self.store); bad.fetch = AsyncMock(return_value=self.report)
        await bad.tick()
        self.scenario.start.assert_not_called()
        self.watch.state_file.unlink()
        with patch.object(pathlib.Path, 'write_text', side_effect=OSError('disk full')):
            await self.watch.tick()
        self.scenario.start.assert_not_called()

    async def test_source_change_during_request_discards_old_response(self):
        async def changed(severe):
            self.watch.mode = 'off'
            return self.report
        self.watch.fetch = changed
        await self.watch.tick()
        self.scenario.start.assert_not_called()

    async def test_demo_cannot_be_armed_over_an_active_run(self):
        self.scenario.state = 'running'
        with self.assertRaises(ValueError): self.watch.arm_demo()

    async def test_demo_uses_same_trigger_and_does_not_modify_live_cooldown(self):
        self.watch.arm_demo()
        self.watch.demo_at = time.monotonic() - 1
        self.watch.fetch.return_value = {**self.report, 'provider': 'demo'}
        await self.watch.tick()
        self.scenario.start.assert_called_once()
        self.assertFalse(self.watch.state_file.exists())
        self.scenario.state = 'idle'
        await self.watch.tick()
        self.scenario.start.assert_called_once()


class WeatherIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        usable, why = u.filer_can_run()
        if not usable: raise unittest.SkipTest(why)
        cls.services = u.Services('orchestrator','portal','weather','registry','mandi','s1','filer',
            S1_CHAIN_TEXT='mock', S1_CHAIN_REPORT='mock', S1_PRELOAD='0')
        cls.addClassCleanup(cls.services.close)

    def test_local_controls_reject_public_host_and_foreign_origin(self):
        for headers in ({'Host': 'demo.ngrok-free.dev'}, {'Origin': 'https://evil.example'}):
            req = urllib.request.Request(u.url('orchestrator','/api/weather/demo'), data=b'{}',
                                         headers=headers, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as caught: u._opener.open(req)
            self.assertEqual(caught.exception.code, 403)

    def test_weather_automatically_starts_district_without_manual_start(self):
        from ghante_shared import mcp_client
        u.call('POST',u.url('orchestrator','/api/scenario/reset'),{})
        live_cooldown = pathlib.Path(self.services.tmp) / 'var/weather-watch.json'
        safe = asyncio.run(mcp_client.call_tool(u.url('weather','/mcp'),'get_crop_risk',
                           {'district':'Sehore','mode':'demo','demo_severe':False}))
        self.assertFalse(safe['hazardous'])
        self.assertEqual(safe['monitored_villages'],12)
        code, armed = u.call('POST',u.url('orchestrator','/api/weather/demo'),{})
        self.assertEqual(code,200)
        time.sleep(2)
        self.assertEqual(u.call('GET',u.url('orchestrator','/api/state'))[1]['scenario']['state'],'idle')
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            watch=u.call('GET',u.url('orchestrator','/api/weather/status'))[1]
            state=u.call('GET',u.url('orchestrator','/api/state'))[1]
            if state['stats']['affected']==340: break
            time.sleep(.5)
        self.assertEqual(state['stats']['affected'],340, watch)
        self.assertEqual(watch['provider'],'demo')
        self.assertEqual(watch['trigger_count'],armed['trigger_count']+1)
        self.assertFalse(live_cooldown.exists())
        events=self.services.events()
        self.assertEqual(sum(e['type']=='weather.triggered' for e in events),1)
        self.assertTrue(any(e['type']=='storm.detected' for e in events))
        # Status remains visible on reload; projector geometry stays intact.
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return
        from tests.test_phase5 import FIT
        with sync_playwright() as p:
            browser=u.launch_chromium(p,headless=True)
            try:
                for width,height in ((1366,768),(1920,1080)):
                    page=browser.new_page(viewport={'width':width,'height':height})
                    errors=[]; page.on('pageerror',lambda error: errors.append(str(error)))
                    page.goto(u.url('orchestrator')); page.wait_for_timeout(1500)
                    self.assertIn('DEMO',page.inner_text('#weather-source'))
                    self.assertIn('risk',page.inner_text('#weather-summary').lower())
                    fit=page.evaluate(FIT)
                    self.assertEqual((fit['sw'],fit['sh']),(width,height))
                    self.assertEqual(fit['clipped'],[])
                    self.assertEqual(errors,[])
                    page.close()
            finally: browser.close()
