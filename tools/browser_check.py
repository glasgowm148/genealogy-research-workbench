"""Run the existing browser contracts serially in one owned browser and one tab."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']



def memory_pressure():
    if sys.platform != 'darwin':
        return None
    return int(subprocess.check_output(['sysctl', '-n', 'kern.memorystatus_vm_pressure_level'],
                                       text=True, timeout=5).strip())


def progress(stage):
    path = os.environ.get('GENEALOGY_BROWSER_HEARTBEAT')
    if path:
        Path(path).write_text(json.dumps({'stage': stage, 'time': time.time()}) + '\n')


def process_inventory():
    """Inspect descendants of this runner; unrelated browsers are never owned."""
    if os.name == 'nt':
        return []
    with subprocess.Popen(['ps', '-axo', 'pid=,ppid=,rss='], text=True, stdout=subprocess.PIPE) as process:
        output, _ = process.communicate(timeout=5)
        inventory_pid = process.pid
    rows = [tuple(map(int, line.split())) for line in output.splitlines() if line.strip()]
    descendants, changed = {os.getpid()}, True
    while changed:
        before = len(descendants)
        descendants.update(pid for pid, parent, _ in rows if parent in descendants)
        changed = len(descendants) != before
    return [{'pid': pid, 'ppid': parent, 'rss_kib': rss} for pid, parent, rss in rows
            if pid in descendants and pid not in (os.getpid(), inventory_pid)]


class BrowserOwner:
    def __init__(self, playwright_factory, axe_source=None):
        self.factory, self.axe_source = playwright_factory, axe_source
        self.runtime = self.browser = self.page = None
        self.launches = self.navigations = self.peak_pages = 0
        self.snapshots = []

    def start(self):
        if self.runtime is None:
            self.runtime = self.factory().start()
        return SimpleNamespace(chromium=SimpleNamespace(launch=self.lease), stop=lambda: None)

    def lease(self, **kwargs):
        if self.browser is None:
            if memory_pressure() not in (None, 1):
                raise RuntimeError('Memory pressure is elevated; no browser was launched')
            self.browser = self.runtime.chromium.launch(**{**kwargs, 'timeout': 20000})
            self.launches += 1
            self.snapshot('after launch')
        return BrowserLease(self)

    def new_page(self, context, new_page):
        # A no-JavaScript check replaces the previous working tab, rather than
        # leaving an idle rendered page behind it.
        if self.page is not None and not self.page.is_closed():
            self.page.close()
        page = new_page()
        self.page = page
        self.peak_pages = max(self.peak_pages, sum(len(c.pages) for c in self.browser.contexts))
        if self.peak_pages > 1:
            raise AssertionError('Browser validation exceeded its single-tab budget')
        original_evaluate = page.evaluate
        def evaluate(expression, arg=None):
            if 'axe.run' in expression:
                wrapped = '''async arg => { let timer; try { return await Promise.race([
                    (%s)(arg), new Promise((_, reject) => {timer=setTimeout(() => reject(new Error('Accessibility audit exceeded 20s')),20000);})
                ]); } finally { clearTimeout(timer); } }''' % expression
                return original_evaluate(wrapped, arg)
            return original_evaluate(expression, arg)
        page.evaluate = evaluate
        original_add_script = page.add_script_tag
        def add_script_tag(**kwargs):
            if self.axe_source and kwargs.get('content') == self.axe_source:
                # Every navigation already runs these exact bytes as an init
                # script. Do not repeatedly inject a large script and wait for
                # a script element load event; assert readiness instead.
                if not page.evaluate("typeof window.axe?.run === 'function'"):
                    raise AssertionError('The preloaded accessibility checker is unavailable')
                return None
            return original_add_script(**kwargs)
        page.add_script_tag = add_script_tag
        def navigated(frame):
            if frame == page.main_frame:
                self.navigations += 1
                progress(f'navigation {self.navigations}')
                if self.navigations % 10 == 0:
                    self.snapshot('navigation batch')
        page.on('framenavigated', navigated)
        return page

    def snapshot(self, reason):
        rows = process_inventory()
        pressure = memory_pressure()
        progress(reason)
        self.snapshots.append({'reason': reason, 'navigations': self.navigations,
                               'open_pages': sum(len(c.pages) for c in self.browser.contexts) if self.browser else 0,
                               'memory_pressure_level': pressure, 'processes': rows})
        if self.browser and pressure not in (None, 1):
            raise RuntimeError('Memory pressure is elevated; stopping browser validation')

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        finally:
            try:
                if self.runtime:
                    self.runtime.stop()
            finally:
                self.browser = self.runtime = self.page = None
                self.snapshot('after cleanup')


class BrowserLease:
    """A fixture releases its contexts; the runner alone closes the browser."""
    def __init__(self, owner):
        self.owner, self.contexts = owner, []

    def new_context(self, **kwargs):
        context = self.owner.browser.new_context(**kwargs)
        self.contexts.append(context)
        context.set_default_timeout(15000)
        context.set_default_navigation_timeout(15000)
        if self.owner.axe_source:
            context.add_init_script(script=self.owner.axe_source)
        original_new_page = context.new_page
        context.new_page = lambda: self.owner.new_page(context, original_new_page)
        return context

    def new_page(self, **kwargs):
        return self.new_context(**kwargs).new_page()

    def close(self):
        for context in self.contexts:
            context.close()
        self.contexts.clear()


class BoundedResult(unittest.TextTestResult):
    latest = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed_test_ids = []
        type(self).latest = self

    def addSuccess(self, test):
        self.passed_test_ids.append(test.id())
        super().addSuccess(test)

    def startTest(self, test):
        super().startTest(test)
        self.started = time.monotonic()
        progress(test.id())

    def stopTest(self, test):
        self.stream.write(f' [{time.monotonic() - self.started:.1f}s]')
        self.stream.flush()
        super().stopTest(test)



def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tests', nargs='*', help='Optional unittest names (defaults to all browser tests)')
    parser.add_argument('--resume', action='store_true', help='Continue unfinished tests from the previous receipt')
    parser.add_argument('--receipt', type=Path, default=ROOT / 'output' / 'browser-validation.json')
    args = parser.parse_args(argv)
    if not os.environ.get('GENEALOGY_BROWSER_WORKER'):
        return supervise(args)
    sys.path.insert(0, str(ROOT / 'tests'))
    os.environ['GENEALOGY_BROWSER_TESTS'] = '1'
    from playwright.sync_api import sync_playwright
    axe_path = os.environ.get('GENEALOGY_AXE_PATH')
    axe_source = Path(axe_path).read_text(encoding='utf-8') if axe_path else None
    owner = BrowserOwner(sync_playwright, axe_source)
    loader = unittest.TestLoader()
    suite = (loader.loadTestsFromNames(args.tests) if args.tests else
             loader.discover(str(ROOT / 'tests'), pattern='test_browser*.py'))
    tests = list(flatten(suite))
    selected_test_ids = [test.id() for test in tests]
    previous = json.loads(args.receipt.read_text()) if args.resume and args.receipt.exists() else {}
    completed = set(previous.get('passed_test_ids', [])) & set(selected_test_ids)
    tests = [test for test in tests if test.id() not in completed]
    # Validate the formerly stalled DNA case first, in the same browser used
    # for every subsequent contract; there is no separate retry browser.
    tests.sort(key=lambda t: ('test_browser_dna_page' not in t.id(), t.id()))
    result = None
    started = time.monotonic()
    owner.snapshot('before launch')
    class FixtureSuite(unittest.TestSuite):
        def _handleClassSetUp(self, test, result):
            progress('fixture setup ' + type(test).__name__)
            return super()._handleClassSetUp(test, result)

    try:
        with patch('playwright.sync_api.sync_playwright', lambda: SimpleNamespace(start=owner.start)):
            result = unittest.TextTestRunner(verbosity=2, failfast=True, resultclass=BoundedResult).run(FixtureSuite(tests))
    finally:
        try:
            progress('cleanup')
            owner.close()
        finally:
            result = result or BoundedResult.latest
            passed = sorted(completed | set(result.passed_test_ids if result else []))
            report = {'passed_test_ids': passed, 'selected_test_ids': selected_test_ids,
                      'total_passed': len(passed), 'complete': set(passed) == set(selected_test_ids),
                      'tests_run': result.testsRun if result else None,
                      'failures': len(result.failures) if result else None,
                      'errors': len(result.errors) if result else None,
                      'skipped': len(result.skipped) if result else None,
                      'test_failures': [{'test': test.id(), 'traceback': trace} for test, trace in (result.failures + result.errors)] if result else [],
                      'browser_launches': owner.launches, 'peak_open_pages': owner.peak_pages,
                      'navigations': owner.navigations, 'seconds': round(time.monotonic() - started, 2),
                      'accessibility_enabled': bool(axe_source), 'resource_snapshots': owner.snapshots}
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if result and result.wasSuccessful() else 1



def supervise(args):
    """A lightweight watchdog owns the worker group, never an unrelated PID."""
    import tempfile
    pressure = memory_pressure()
    if pressure not in (None, 1):
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps({'status': 'blocked-memory-pressure',
            'memory_pressure_level': pressure, 'browser_launches': 0,
            'peak_open_pages': 0, 'tests_run': 0}, indent=2) + '\n')
        raise SystemExit('Memory pressure is elevated; no browser was launched')
    with tempfile.TemporaryDirectory(prefix='genealogy-browser-watch-') as directory:
        heartbeat = Path(directory) / 'progress.json'
        heartbeat.write_text(json.dumps({'stage': 'starting', 'time': time.time()}))
        env = {**os.environ, 'GENEALOGY_BROWSER_WORKER': '1',
               'GENEALOGY_BROWSER_HEARTBEAT': str(heartbeat)}
        command = [sys.executable, str(Path(__file__).resolve()), *args.tests,
                   '--receipt', str(args.receipt.resolve())]
        if getattr(args, 'resume', False):
            command.append('--resume')
        process = subprocess.Popen(command, env=env, start_new_session=os.name != 'nt')
        try:
            while process.poll() is None:
                try:
                    state = json.loads(heartbeat.read_text())
                except (OSError, ValueError):
                    state = {'stage': 'starting', 'time': time.time()}
                limit = 20 if state['stage'] == 'cleanup' else 300 if state['stage'].startswith('fixture setup ') else 60
                if time.time() - state['time'] > limit:
                    print(f"Browser validation stalled during {state['stage']}; stopping owned worker", file=sys.stderr)
                    raise TimeoutError(state['stage'])
                time.sleep(.25)
            return process.returncode
        finally:
            if process.poll() is None:
                if os.name == 'nt':
                    process.terminate()
                else:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name == 'nt':
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
            if os.name != 'nt':
                # Even if the worker exited first, reclaim only children in
                # the dedicated process group this supervisor created.
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    os.killpg(process.pid, signal.SIGTERM)

if __name__ == '__main__':
    raise SystemExit(main())
