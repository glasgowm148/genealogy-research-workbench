"""The browser runner keeps one browser/tab and preserves real audit failures."""
from __future__ import annotations

from types import SimpleNamespace
import unittest
import signal
import os
import subprocess
from unittest.mock import Mock, patch

from tools.browser_check import BrowserOwner, supervise


class Page:
    def __init__(self, context):
        self.context, self.closed = context, False
        self.add_script_tag = Mock()
        self.evaluate = Mock(return_value=True)
        self.main_frame = object()
        self.on = Mock()

    def close(self):
        self.closed = True
        self.context.pages.remove(self)

    def is_closed(self):
        return self.closed


class Context:
    def __init__(self):
        self.pages = []
        self.add_init_script = Mock()
        self.set_default_timeout = Mock()
        self.set_default_navigation_timeout = Mock()

    def new_page(self):
        page = Page(self)
        self.pages.append(page)
        return page

    def close(self):
        for page in list(self.pages):
            page.close()


class BrowserRunnerTests(unittest.TestCase):
    def setUp(self):
        pressure = patch('tools.browser_check.memory_pressure', return_value=1)
        pressure.start()
        self.addCleanup(pressure.stop)
        self.browser = Mock(contexts=[])
        def context(**kwargs):
            value = Context()
            self.browser.contexts.append(value)
            return value
        self.browser.new_context.side_effect = context
        self.runtime = Mock()
        self.runtime.chromium.launch.return_value = self.browser
        self.factory = Mock()
        self.factory.return_value.start.return_value = self.runtime
        self.owner = BrowserOwner(self.factory, 'fictional axe source')
        self.owner.snapshot = Mock()

    def test_fixture_leases_share_one_browser_and_release_only_their_contexts(self):
        first = self.owner.start().chromium.launch(headless=True)
        second = self.owner.start().chromium.launch(headless=True)
        context = first.new_context()
        page = context.new_page()
        first.close()
        self.assertTrue(page.is_closed())
        self.browser.close.assert_not_called()
        self.assertIsNotNone(second.new_context().new_page())
        self.assertEqual(1, self.owner.launches)
        self.factory.return_value.start.assert_called_once()
        self.runtime.chromium.launch.assert_called_once()
        self.owner.close()
        self.browser.close.assert_called_once()
        self.runtime.stop.assert_called_once()

    def test_new_page_closes_previous_working_tab_before_creating_another(self):
        lease = self.owner.start().chromium.launch()
        first = lease.new_context().new_page()
        second = lease.new_context(java_script_enabled=False).new_page()
        self.assertTrue(first.is_closed())
        self.assertFalse(second.is_closed())
        self.assertEqual(1, self.owner.peak_pages)

    def test_preloaded_axe_is_checked_and_failure_is_never_silently_skipped(self):
        context = self.owner.start().chromium.launch().new_context()
        context.add_init_script.assert_called_once_with(script='fictional axe source')
        page = context.new_page()
        page.add_script_tag(content='fictional axe source')
        page.evaluate = Mock(return_value=False)
        with self.assertRaisesRegex(AssertionError, 'checker is unavailable'):
            page.add_script_tag(content='fictional axe source')

    def test_runtime_stops_and_final_inventory_runs_even_when_browser_close_fails(self):
        self.owner.start().chromium.launch()
        self.browser.close.side_effect = RuntimeError('fixture failure')
        with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
            self.owner.close()
        self.runtime.stop.assert_called_once()
        self.owner.snapshot.assert_called_with('after cleanup')

    @patch('tools.browser_check.memory_pressure', return_value=2)
    @patch('tools.browser_check.subprocess.Popen')
    def test_memory_pressure_prevents_any_browser_worker_launch(self, launch, _):
        with self.assertRaisesRegex(SystemExit, 'no browser was launched'):
            supervise(SimpleNamespace(tests=[], receipt=Mock()))
        launch.assert_not_called()

    @unittest.skipUnless(os.name != 'nt', 'POSIX owned process-group cleanup')
    @patch('tools.browser_check.os.killpg')
    @patch('tools.browser_check.time.time', side_effect=[0, 100])
    @patch('tools.browser_check.subprocess.Popen')
    def test_stalled_worker_gets_graceful_stop_then_only_its_owned_group_is_terminated(self, launch, _, kill_group):
        def signal_group(pid, signum):
            if signum == 0:
                raise ProcessLookupError
        kill_group.side_effect = signal_group
        process = launch.return_value
        process.pid = 12345
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('owned worker', 10), -signal.SIGTERM]
        with self.assertRaises(TimeoutError):
            supervise(SimpleNamespace(tests=[], receipt=__import__('pathlib').Path('/tmp/fictional-receipt.json')))
        process.send_signal.assert_called_once_with(signal.SIGINT)
        self.assertEqual([(12345, signal.SIGTERM), (12345, 0)],
                         [call.args for call in kill_group.call_args_list])


if __name__ == '__main__':
    unittest.main()
