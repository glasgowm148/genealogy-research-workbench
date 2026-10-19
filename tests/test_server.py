"""Real HTTP checks of the loopback upload boundary using fictional input."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from genealogy.server import UploadServer

INPUT = b'0 HEAD\n0 @I1@ INDI\n1 NAME Invented /Example/\n1 DEAT Y\n0 TRLR\n'


class UploadServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = UploadServer(self.root, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        status, data = response.status, response.read()
        connection.close()
        return status, data

    def upload(self, **overrides):
        headers = {"Origin": self.server.origin, "X-CSRF-Token": self.server.token,
                   "X-Filename": "invented.ged", "X-Project-Name": "Invented%20research",
                   "Content-Type": "application/octet-stream", "X-Publish-Deceased": "true"}
        headers.update(overrides)
        return self.request("POST", "/upload", INPUT, headers)

    def test_wizard_and_generated_preview_only(self):
        status, page = self.request("GET", "/")
        self.assertEqual(200, status)
        self.assertIn(self.server.token.encode(), page)
        status, raw = self.upload()
        self.assertEqual(201, status, raw)
        report = json.loads(raw)
        self.assertEqual(1, report["people"])
        status, page = self.request("GET", report["preview"])
        self.assertEqual(200, status)
        self.assertIn(b"Invented", page)
        for path in ("/private/imports/input.ged", "/cases/research-case.json",
                     report["preview"]+"../cases/research-case.json",
                     report["preview"]+"%2e%2e/%2e%2e/genealogy.toml"):
            self.assertEqual(404, self.request("GET", path)[0])
        self.assertTrue((Path(report["project"]) / "cases" / "research-case.json").is_file())

    def test_cross_origin_csrf_bad_host_and_unsafe_filenames_rejected(self):
        for override in ({"Origin": "https://attacker.invalid"}, {"X-CSRF-Token": "wrong"},
                         {"Host": "attacker.invalid"}):
            self.assertEqual(403, self.upload(**override)[0])
        for filename in ("../evil.ged", "%2fetc%2fdata.ged", "C:%5ctree.ged", "secret.txt"):
            self.assertEqual(400, self.upload(**{"X-Filename": filename})[0])
        self.assertEqual(403, self.request("GET", "/", headers={"Host": "attacker.invalid"})[0])
        self.assertFalse(self.server.previews)

    def test_oversize_and_invalid_upload_leave_no_preview(self):
        self.assertEqual(400, self.upload(**{"Content-Length": str(33*1024*1024)})[0])
        headers = {"Origin": self.server.origin, "X-CSRF-Token": self.server.token,
                   "X-Filename": "invalid.json", "Content-Type": "application/octet-stream"}
        status, _ = self.request("POST", "/upload", b'{"not":"a tree"}', headers)
        self.assertEqual(400, status)
        self.assertFalse(self.server.previews)
        self.assertFalse(list((self.root / "private" / "previews").glob("*/genealogy.toml")))
