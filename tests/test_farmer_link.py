"""Stable-link launcher checks; no account, network, or paid service required."""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import farmer_link as link

PAGE = b'<button id="btn-start">Start</button>'
URL = "https://demo.ngrok-free.app"


def tunnels(addr=link.UPSTREAM, url=URL):
    return {"tunnels": [{"public_url": url, "config": {"addr": addr}}]}


class FarmerLinkTests(unittest.TestCase):
    def test_only_this_apps_https_tunnel_is_selected(self):
        for bad in (tunnels(addr="http://127.0.0.1:9000"), tunnels(url="http://demo.ngrok-free.app"),
                    tunnels(url="https://user:password@demo.ngrok-free.app"), tunnels(url=URL + "/other")):
            self.assertIsNone(link.farmer_url(bad))
        self.assertEqual(link.farmer_url(tunnels()), URL + "/farmer")

    def test_missing_token_does_not_start_a_tunnel(self):
        output = io.StringIO()
        with patch.object(link, "executable", return_value="ngrok"), patch.object(link.config, "env", return_value=""), \
                patch.object(link.subprocess, "Popen") as spawn, contextlib.redirect_stdout(output):
            self.assertEqual(link.main([]), 1)
            spawn.assert_not_called()
        self.assertIn("One-time setup", output.getvalue())

    def test_wrong_local_page_does_not_start_a_tunnel(self):
        with patch.object(link, "executable", return_value="ngrok"), patch.object(link.config, "env", return_value="test-token"), \
                patch.object(link, "fetch", return_value=b"Another app"), patch.object(link.subprocess, "Popen") as spawn, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(link.main([]), 1)
            spawn.assert_not_called()

    def test_existing_launcher_is_not_replaced(self):
        with patch.object(link, "executable", return_value="ngrok"), patch.object(link.config, "env", return_value="test-token"), \
                patch.object(link, "fetch", side_effect=[PAGE, b"{}"]), patch.object(link.subprocess, "Popen") as spawn, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(link.main([]), 1)
            spawn.assert_not_called()

    def test_matching_existing_tunnel_is_verified_and_reused(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(link, "ROOT", pathlib.Path(folder)), \
                patch.object(link, "executable", return_value="ngrok"), \
                patch.object(link.config, "env", return_value="test-token"), \
                patch.object(link, "fetch", side_effect=[PAGE, json.dumps(tunnels()).encode(), PAGE]), \
                patch.object(link.subprocess, "Popen") as spawn, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(link.main([]), 0)
            spawn.assert_not_called()
            self.assertEqual((pathlib.Path(folder) / "var/farmer-link.txt").read_text().strip(), URL + "/farmer")

    def test_existing_tunnel_with_wrong_public_page_is_not_reused(self):
        with patch.object(link, "executable", return_value="ngrok"), \
                patch.object(link.config, "env", return_value="test-token"), \
                patch.object(link, "fetch", side_effect=[PAGE, json.dumps(tunnels()).encode(), b"wrong app"]), \
                patch.object(link, "publish_link") as publish, patch.object(link.subprocess, "Popen") as spawn, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(link.main([]), 1)
            publish.assert_not_called()
            spawn.assert_not_called()

    def run_launcher(self, folder, replies, proc):
        output = io.StringIO()
        with patch.object(link, "ROOT", pathlib.Path(folder)), patch.object(link, "executable", return_value="ngrok"), \
                patch.object(link.config, "env", return_value="private-test-token"), \
                patch.object(link, "fetch", side_effect=replies), patch.object(link.subprocess, "Popen", return_value=proc) as spawn, \
                patch.object(link.time, "sleep"), contextlib.redirect_stdout(output):
            code = link.main([])
        self.assertNotIn("private-test-token", output.getvalue())
        self.assertNotIn("private-test-token", " ".join(spawn.call_args.args[0]))
        self.assertEqual(spawn.call_args.kwargs["env"]["NGROK_AUTHTOKEN"], "private-test-token")
        return code

    def test_verified_link_is_saved_without_token(self):
        proc = Mock()
        proc.poll.side_effect = [None, 0]
        proc.wait.return_value = 0
        with tempfile.TemporaryDirectory() as folder:
            replies = [PAGE, OSError(), json.dumps(tunnels()).encode(), PAGE]
            self.assertEqual(self.run_launcher(folder, replies, proc), 0)
            saved = pathlib.Path(folder) / "var" / "farmer-link.txt"
            self.assertEqual(saved.read_text().strip(), URL + "/farmer")
            config = (pathlib.Path(folder) / ".runtime" / "ngrok-farmer.yml").read_text()
            self.assertNotIn("private-test-token", config)
            proc.terminate.assert_not_called()

    def test_failed_public_verification_does_not_save_link_and_stops_child(self):
        proc = Mock()
        proc.poll.return_value = None
        with tempfile.TemporaryDirectory() as folder:
            replies = [PAGE, OSError(), json.dumps(tunnels()).encode()] + [OSError()] * 5
            self.assertEqual(self.run_launcher(folder, replies, proc), 1)
            self.assertFalse((pathlib.Path(folder) / "var" / "farmer-link.txt").exists())
            proc.terminate.assert_called_once()

    def test_early_agent_exit_does_not_save_link(self):
        proc = Mock()
        proc.poll.return_value = 1
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(self.run_launcher(folder, [PAGE, OSError()], proc), 1)
            self.assertFalse((pathlib.Path(folder) / "var" / "farmer-link.txt").exists())


if __name__ == "__main__":
    unittest.main()
