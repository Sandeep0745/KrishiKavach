"""Regression checks for tab focus and automatic filing recovery; no LLM credits used."""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from apps.filer import agent_mode, browser, main
from apps.filer.scripted import PortalBrowser
from tests import _util as u
from tests.test_phase3 import HERO_FORM, PHOTO


class FilerRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_auto_recovers_when_agent_initialization_raises(self):
        portal = AsyncMock()
        portal.reference_on_screen.return_value = None
        portal.fill.return_value = ('FCS-000001', 25)
        with patch.object(main, 'portal', portal), patch.object(main, 'open_window', AsyncMock()), \
                patch.object(agent_mode, 'available', return_value=(True, 'ready')), \
                patch.object(agent_mode, 'run', AsyncMock(side_effect=RuntimeError('provider unavailable'))), \
                patch.object(main, 'scripted_available', return_value=(True, 'ready')), \
                patch.object(main, 'read_claim', return_value={**HERO_FORM, 'has_photo': True}), \
                patch.object(main.http, 'post_event') as events, patch.object(main.http, 'flush_events'):
            out = await main.file_claim('test_case', HERO_FORM, 'photo.jpg', 'auto')
        self.assertEqual(out['mode_used'], 'scripted')
        self.assertEqual(out['mismatches'], [])
        self.assertIn('provider unavailable', out['fallback_reason'])
        self.assertTrue(any(call.args[1] == 'fallback.used' for call in events.call_args_list))

    async def test_agent_only_failure_is_reported_without_scripted_submission(self):
        portal = AsyncMock()
        portal.reference_on_screen.return_value = None
        with patch.object(main, 'portal', portal), patch.object(main, 'open_window', AsyncMock()), \
                patch.object(agent_mode, 'available', return_value=(True, 'ready')), \
                patch.object(agent_mode, 'run', AsyncMock(side_effect=RuntimeError('provider unavailable'))):
            with self.assertRaisesRegex(RuntimeError, 'agent mode failed'):
                await main.file_claim('test_case', HERO_FORM, 'photo.jpg', 'agent')
        portal.fill.assert_not_awaited()

    async def test_confirmation_after_agent_error_is_not_submitted_twice(self):
        portal = AsyncMock()
        portal.reference_on_screen.return_value = 'FCS-000001'
        with patch.object(main, 'portal', portal), patch.object(main, 'open_window', AsyncMock()), \
                patch.object(agent_mode, 'available', return_value=(True, 'ready')), \
                patch.object(agent_mode, 'run', AsyncMock(side_effect=RuntimeError('cleanup failed after submit'))), \
                patch.object(main, 'read_claim', return_value={**HERO_FORM, 'has_photo': True}), \
                patch.object(main.http, 'flush_events'):
            out = await main.file_claim('test_case', HERO_FORM, 'photo.jpg', 'auto')
        self.assertEqual(out['claim_ref'], 'FCS-000001')
        self.assertEqual(out['mode_used'], 'agent')
        portal.fill.assert_not_awaited()


class FilerBrowserRecovery(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import playwright.async_api, browser_use
        except ImportError:
            raise unittest.SkipTest('Run browser recovery checks from .venv-browser')
        usable, why = u.filer_can_run()
        if not usable:
            raise unittest.SkipTest(why)
        cls.services = u.Services('portal', 'orchestrator')
        cls.addClassCleanup(cls.services.close)

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='filer_recovery_')
        self.addCleanup(self.tmp.cleanup)
        self.patches = [patch.object(browser, 'CDP_PORT', u.BASE_PORT + 334),
                        patch.object(browser, 'HEADLESS', True),
                        patch.object(browser, 'PROFILE_DIR', pathlib.Path(self.tmp.name) / 'profile'),
                        patch.object(main.config, 'ORCH_URL', u.url('orchestrator')),
                        patch.object(main, 'PORTAL', u.url('portal')),
                        patch.object(main, 'window', browser.BrowserProcess()),
                        patch.object(main, 'portal', PortalBrowser(u.url('portal'), field_delay_ms=0))]
        for item in self.patches:
            item.start()
        self.photo = pathlib.Path(self.tmp.name) / 'crop.jpg'
        self.photo.write_bytes(PHOTO)
        await main.open_window()

    async def asyncTearDown(self):
        await main.portal.close()
        main.window.close()
        for item in reversed(self.patches):
            item.stop()

    async def test_provider_exception_falls_back_and_files_one_correct_record(self):
        before = u.call('GET', u.url('portal', '/api/claims/count'))[1]['claims']
        with patch.object(agent_mode, 'available', return_value=(True, 'ready')), \
                patch.object(agent_mode, 'run', AsyncMock(side_effect=RuntimeError('503 provider unavailable'))):
            out = await main.file_claim('test_case', HERO_FORM, str(self.photo), 'auto')
        self.assertEqual(out['mode_used'], 'scripted')
        self.assertEqual(out['mismatches'], [])
        self.assertIn('503', out['fallback_reason'])
        after = u.call('GET', u.url('portal', '/api/claims/count'))[1]['claims']
        self.assertEqual(after - before, 1)
        self.assertTrue(any(e['type'] == 'fallback.used' for e in self.services.events()))

    async def test_agent_focus_ignores_blank_tabs_and_cleanup_preserves_form(self):
        from browser_use import Browser

        await main.portal.open_form()
        page = await main.portal.page()
        for _ in range(3):
            blank = await page.context.new_page()
            await blank.bring_to_front()
            session = Browser(cdp_url=main.window.http_url, keep_alive=True, allowed_domains=['127.0.0.1'])
            try:
                await agent_mode.focus_form(session, main.portal)
                self.assertEqual(await session.get_current_page_url(), page.url)
            finally:
                await session.stop()
            self.assertEqual(await main.portal.where(), 1)
            self.assertFalse(page.is_closed())
            await blank.close()
