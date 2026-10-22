#!/usr/bin/env python3
"""Capture the README and guide screenshots from the fictional demo.

Builds examples/demo into a temporary folder (with the demo's own settings plus
a contact address, the duplicates page, the surname and the tree name the
README describes), serves it over a local-only server, and captures each page
listed in SHOTS at 1440 x 1000 as a WebP under docs/images/. The upload screens
come from ``genealogy serve`` on a temporary workspace, with the demo's own
fictional GEDCOM chosen in the form. Nothing leaves the machine.

    python tools/readme_screenshots.py            # every image
    python tools/readme_screenshots.py people tree  # just these

Needs the optional browser extras: ``pip install -e '.[browser]'`` and
``python -m playwright install chromium`` (or GENEALOGY_BROWSER_EXECUTABLE).
"""
from __future__ import annotations

import http.server
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
DEMO = ROOT / "examples" / "demo"
WIDTH, HEIGHT = 1440, 1000

# name -> (path, action before the shot: None, a CSS selector to click, or a callable(page))
SHOTS: dict[str, tuple[str, object]] = {
    "overview": ("index.html", None),
    "people": ("catalogue.html", "summary:has-text('Places')"),
    "tree": ("tree.html", "button:has-text('Hourglass')"),
    "dossier": ("catalogue.html#first", None),  # the first person listed in the catalogue, resolved at run time
    "research": ("research.html", None),
    "study": ("studies/", None),  # the first study
    "findings": ("findings.html", None),
    "branches": ("branches.html", None),
    "places": ("places.html", None),
    "evidence": ("evidence.html", None),
    "records": ("records.html", None),
    "statistics": ("statistics.html", None),
    "about-data": ("about-data.html", None),
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args, **kwargs):  # noqa: D102 - keep the capture log readable
            pass
    handler = partial(Quiet, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def build_demo(target: Path) -> Path:
    project = target / "demo"
    shutil.copytree(DEMO, project)
    config = project / "genealogy.toml"
    text = config.read_text(encoding="utf-8")
    text = text.replace("[site]\n", '[site]\ncontact_email = "corrections@example.org"\nduplicates = true\ntree_name = "WikiTree"\n', 1)
    text += '\n[names]\nsurname = "Alderwick"\n'
    config.write_text(text, encoding="utf-8")
    out = target / "site"
    subprocess.run([sys.executable, "-m", "genealogy", "--project", str(project), "build", "--output", str(out)],
                   check=True, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, capture_output=True)
    return out


def save(page, name: str) -> None:
    from PIL import Image
    png = page.screenshot(type="png")
    IMAGES.mkdir(parents=True, exist_ok=True)
    Image.open(io.BytesIO(png)).convert("RGB").save(IMAGES / f"{name}.webp", "WEBP", quality=82, method=6)
    print(f"wrote docs/images/{name}.webp")


def first(site: Path, folder: str) -> str:
    return folder + sorted(p.name for p in (site / folder).glob("*.html"))[0]


def capture_site(wanted: set[str]) -> None:
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as temporary, sync_playwright() as playwright:
        site = build_demo(Path(temporary))
        server, base = serve(site)
        browser = playwright.chromium.launch(executable_path=os.environ.get("GENEALOGY_BROWSER_EXECUTABLE") or None)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        try:
            for name, (path, action) in SHOTS.items():
                if name not in wanted:
                    continue
                if path.endswith("/"):
                    path = first(site, path)
                elif path == "catalogue.html#first":
                    page.goto(base + "catalogue.html")
                    path = page.locator("tbody tr td a").first.get_attribute("href")
                page.goto(base + path)
                page.wait_for_load_state("networkidle")
                if callable(action):
                    action(page)
                elif action:
                    page.locator(action).first.click()
                page.wait_for_timeout(400)
                save(page, name)
        finally:
            browser.close()
            server.shutdown()


def capture_upload(wanted: set[str]) -> None:
    """The ``genealogy serve`` upload form, empty and after importing the demo GEDCOM."""
    if not wanted & {"upload", "upload-result"}:
        return
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as temporary, sync_playwright() as playwright:
        port = free_port()
        process = subprocess.Popen([sys.executable, "-m", "genealogy", "--project", str(Path(temporary) / "workspace"), "serve", "--port", str(port)],
                                   cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        browser = playwright.chromium.launch(executable_path=os.environ.get("GENEALOGY_BROWSER_EXECUTABLE") or None)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        try:
            for _ in range(50):
                try:
                    page.goto(f"http://127.0.0.1:{port}/")
                    break
                except Exception:  # noqa: BLE001 - the server is still starting
                    page.wait_for_timeout(200)
            page.wait_for_load_state("networkidle")
            if "upload" in wanted:
                save(page, "upload")
            if "upload-result" in wanted:
                page.set_input_files("#file", str(DEMO / "input" / "family.ged"))
                page.fill("#name", "The Alderwick family (fictional)")
                page.check("#review")
                page.click("#submit")
                page.locator("#result a").first.wait_for(timeout=60000)
                page.locator("#result").scroll_into_view_if_needed()
                page.wait_for_timeout(600)
                save(page, "upload-result")
        finally:
            browser.close()
            process.terminate()


def main(argv: list[str]) -> int:
    wanted = set(argv) or set(SHOTS) | {"upload", "upload-result"}
    unknown = wanted - set(SHOTS) - {"upload", "upload-result"}
    if unknown:
        print("unknown screenshot(s): " + ", ".join(sorted(unknown)), file=sys.stderr)
        return 2
    capture_site(wanted)
    capture_upload(wanted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
