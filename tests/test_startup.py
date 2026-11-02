"""Repeated launches reuse only a complete healthy demo; no processes are started here."""
import contextlib
import io
import json
import unittest
from unittest.mock import MagicMock, patch
from scripts import check_startup


class StartupTests(unittest.TestCase):
    def check(self, socket_result, services, project_root=None):
        sock = MagicMock()
        sock.__enter__.return_value.connect_ex.return_value = socket_result
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.read.side_effect = [json.dumps({'ok': True, 'service': name, 'project_root': str(check_startup.ROOT) if project_root is None else project_root}).encode() for name in services]
        with patch.object(check_startup.socket, 'socket', return_value=sock), \
                patch.object(check_startup.urllib.request, 'build_opener', return_value=opener), \
                patch.object(check_startup.pathlib.Path, 'is_file', return_value=True), \
                contextlib.redirect_stdout(io.StringIO()):
            return check_startup.main()

    def test_free_ports_allow_new_start(self):
        self.assertEqual(self.check(111, []), 0)

    def test_complete_matching_demo_is_reused(self):
        self.assertEqual(self.check(0, ['orchestrator','portal','mcp-weather','mcp-registry','mcp-mandi','s1','filer']), 2)

    def test_unrelated_service_is_not_reused(self):
        self.assertEqual(self.check(0, ['other-app','portal','mcp-weather','mcp-registry','mcp-mandi','s1','filer']), 1)

    def test_unresponsive_occupied_ports_block_start(self):
        self.assertEqual(self.check(0, []), 1)

    def test_another_checkout_is_not_reused(self):
        services = ['orchestrator','portal','mcp-weather','mcp-registry','mcp-mandi','s1','filer']
        self.assertEqual(self.check(0, services, str(check_startup.ROOT / 'another-checkout')), 1)

    def test_older_demo_without_ownership_is_not_reused(self):
        services = ['orchestrator','portal','mcp-weather','mcp-registry','mcp-mandi','s1','filer']
        self.assertEqual(self.check(0, services, ''), 1)


class StartupIntegration(unittest.TestCase):
    def test_running_services_identify_the_checkout_and_are_reused(self):
        from contextlib import ExitStack
        from ghante_shared import config
        from tests import _util as u
        usable, why = u.filer_can_run()
        if not usable:
            self.skipTest(why)
        services = u.Services('orchestrator', 'portal', 'weather', 'registry', 'mandi', 's1', 'filer',
                              S1_ROUTE_PROVIDER='mock', S1_VERIFY_PROVIDER='rule', S1_PRELOAD='0')
        self.addCleanup(services.close)
        health = u.call('GET', u.url('orchestrator', '/health'))[1]
        self.assertEqual(health['project_root'], str(check_startup.ROOT))
        for path in ('/', '/farmer'):
            self.assertEqual(u.get_text(u.url('orchestrator', path))[0], 200)
        endpoints = {'ORCH_URL': 'orchestrator', 'PORTAL_URL': 'portal', 'MCP_WEATHER_URL': 'weather',
                     'MCP_REGISTRY_URL': 'registry', 'MCP_MANDI_URL': 'mandi', 'S1_URL': 's1', 'FILER_URL': 'filer'}
        with ExitStack() as stack:
            for key, service in endpoints.items():
                stack.enter_context(patch.object(config, key, u.url(service)))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.assertEqual(check_startup.main(), 2)
            with patch.object(check_startup, 'ROOT', check_startup.ROOT / 'different-checkout'), \
                    patch.object(check_startup.pathlib.Path, 'is_file', return_value=True):
                self.assertEqual(check_startup.main(), 1)
