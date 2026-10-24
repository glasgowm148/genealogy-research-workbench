"""Local-only upload wizard. Uploaded inputs and cases are never HTTP resources."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shutil
from urllib.parse import unquote, urlsplit

from .importing import MAX_IMPORT_BYTES, SUFFIXES, detect_format, import_file, private_write

HTML = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Genealogy · Create your research site</title><style>
:root{color-scheme:light; font:17px/1.6 system-ui;color:#203630;background:#f4f2eb}*{box-sizing:border-box}main{max-width:740px;margin:7vh auto;padding:34px}h1{font:500 clamp(2rem,5vw,3.2rem)/1.15 Georgia,serif;margin:.3em 0}p{color:#52635c}label{display:block;margin:22px 0 6px}input[type=text],input[type=file]{width:100%;padding:13px;background:white;border:1px solid #a7b1a7;border-radius:7px;font:inherit}input[type=checkbox]{width:20px;height:20px;vertical-align:middle}button,a.preview{display:inline-block;background:#244e40;color:white;padding:12px 22px;border:0;border-radius:6px;font:inherit;cursor:pointer}button:disabled{opacity:.5}small{display:block;color:#52635c}#result{margin-top:28px;overflow-wrap:anywhere}.card{background:#fff;padding:24px;border:1px solid #d5dacd;border-radius:12px}ul{padding-left:22px}
</style><main><small>LOCAL RESEARCH WORKBENCH</small><h1>Turn your family tree into a research site.</h1>
<p>Import a GEDCOM or OneTree JSON export to make a private, local preview. Your file stays on this computer; this wizard does not publish or upload anything.</p>
<form id="upload" class="card"><label for="name">Public project title</label><input id="name" type="text" maxlength="120" value="Family research" required>
<small>Choose a public title without private personal details.</small>
<label for="file">Your tree export</label><input id="file" type="file" accept=".ged,.gedcom,.gdz,.json" required><small>GEDCOM (.ged), GEDCOM 7 archive (.gdz) or OneTree JSON · maximum 32 MiB</small>
<label><input id="review" type="checkbox"> I have reviewed this tree and permit basic deceased or historical facts to appear publicly.</label>
<small>Leave this off to keep all imported people private. Living, explicitly private, restricted and licensed records stay protected either way. Imported relationships remain unverified assertions.</small>
<label><input id="sources" type="checkbox"> I have also reviewed linked source titles, repositories, URLs and citation locators for public use.</label>
<small>Requires the deceased-facts review above. Source quotations, transcriptions and protected records remain private.</small>
<p><button id="submit">Create local preview</button></p></form><div id="result" role="status" aria-live="polite"></div>
<p><small><strong>What happens next:</strong> the preview is saved in a private project folder and opens only from this computer. Internet hosting is a separate, deliberate action: review the generated site and privacy choices before copying or deploying it. Maps use only coordinates already in your file.</small></p></main>
<script>
const form=document.getElementById('upload'), result=document.getElementById('result'), button=document.getElementById('submit');
form.addEventListener('submit',async e=>{e.preventDefault();const file=document.getElementById('file').files[0];if(!file)return;if(file.size>33554432){result.textContent='Choose a file smaller than 32 MiB.';return}button.disabled=true;result.textContent='Importing and building your site…';
try{const response=await fetch('/upload',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-CSRF-Token':'TOKEN','X-Filename':encodeURIComponent(file.name),'X-Project-Name':encodeURIComponent(document.getElementById('name').value),'X-Publish-Deceased':document.getElementById('review').checked?'true':'false','X-Publish-Reviewed-Sources':document.getElementById('sources').checked?'true':'false'},body:file});const data=await response.json();if(!response.ok)throw Error(data.error||'Import failed');result.replaceChildren();const p=document.createElement('p');p.textContent=`Imported ${data.people} people. Your local preview is ready.`;result.append(p);const privacy=document.createElement('p');privacy.textContent=data.published_people?`${data.published_people} people passed the selected deceased-facts review.`:'No people were marked public. The preview contains no public people; review the tree before choosing any publication settings.';result.append(privacy);const a=document.createElement('a');a.className='preview';a.href=data.preview;a.textContent='Open your local preview';result.append(a);const folder=document.createElement('p');folder.textContent='Saved project folder: '+data.project;result.append(folder);const next=document.createElement('p');next.textContent='Next: inspect the preview, check names, notes, sources and links, then keep this folder private or choose a separate hosting workflow.';result.append(next);const heading=document.createElement('strong');heading.textContent=data.warning_count?`Review ${data.warning_count} import note${data.warning_count===1?'':'s'} before sharing:`:'Import notes';result.append(heading);const ul=document.createElement('ul');for(const warning of data.warnings){const li=document.createElement('li');li.textContent=warning;ul.append(li)}result.append(ul)}catch(error){result.textContent=error.message}finally{button.disabled=false}});
</script></html>'''

STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".json": "application/json", ".geojson": "application/geo+json",
                ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
                ".woff2": "font/woff2", ".ico": "image/x-icon", ".csv": "text/csv; charset=utf-8",
                ".ged": "text/plain; charset=utf-8", ".xml": "application/xml"}


class UploadServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, directory: Path, port: int = 8000):
        if not 0 <= port <= 65535:
            raise ValueError("Port must be between 0 and 65535")
        self.directory = directory.resolve()
        self.token = secrets.token_urlsafe(32)
        self.previews: dict[str, Path] = {}
        super().__init__(("127.0.0.1", port), UploadHandler)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class UploadHandler(BaseHTTPRequestHandler):
    server: UploadServer
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, format: str, *args: object) -> None:
        # Input filenames/person data are never included in request logs.
        return

    def reply(self, status: int, data: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def json_reply(self, status: int, payload: dict) -> None:
        self.reply(status, json.dumps(payload).encode())

    def valid_host(self) -> bool:
        return self.headers.get("Host") == urlsplit(self.server.origin).netloc

    def do_GET(self) -> None:
        if not self.valid_host():
            self.json_reply(403, {"error": "Use the printed loopback URL"})
            return
        path = unquote(urlsplit(self.path).path)
        if path == "/":
            self.reply(200, HTML.replace("TOKEN", self.server.token).encode(), "text/html; charset=utf-8")
            return
        parts = path.split("/")
        if len(parts) < 4 or parts[1] != "site" or parts[2] not in self.server.previews:
            self.json_reply(404, {"error": "Not found"})
            return
        root = self.server.previews[parts[2]].resolve()
        relative = Path("/".join(parts[3:]) or "index.html")
        target = (root / relative).resolve()
        if target.is_dir():
            target = (target / "index.html").resolve()
        if not target.is_relative_to(root) or target.suffix.casefold() not in STATIC_TYPES or not target.is_file():
            self.json_reply(404, {"error": "Not found"})
            return
        self.reply(200, target.read_bytes(), STATIC_TYPES[target.suffix.casefold()])

    def do_POST(self) -> None:
        if (not self.valid_host() or self.path != "/upload"
                or self.headers.get("Origin") != self.server.origin
                or not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), self.server.token)):
            self.json_reply(403, {"error": "Upload must come from this local form"})
            return
        staging = None
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Streaming uploads are not supported")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_IMPORT_BYTES:
                raise ValueError("Choose a file of at most 32 MiB")
            if self.headers.get("Content-Type") != "application/octet-stream":
                raise ValueError("Use the local file upload form")
            filename = unquote(self.headers.get("X-Filename", ""))
            if not filename or filename != Path(filename).name or "/" in filename or "\\" in filename or any(ord(c)<32 for c in filename):
                raise ValueError("Invalid input filename")
            format = detect_format(filename)
            name = unquote(self.headers.get("X-Project-Name", "Family research"))
            review = self.headers.get("X-Publish-Deceased", "false")
            source_review = self.headers.get("X-Publish-Reviewed-Sources", "false")
            if source_review not in ("true", "false") or source_review == "true" and review != "true":
                raise ValueError("Source review requires deceased-facts review")
            if review not in ("true", "false"):
                raise ValueError("Invalid publication review choice")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Upload interrupted; retry with the complete file")
            from .cli import initialize_project, load_case, build_project
            identifier = secrets.token_hex(12)
            base = (self.server.directory / "private" / "previews").resolve()
            if not base.is_relative_to(self.server.directory):
                raise ValueError("Preview storage escapes the project directory")
            staging = base / identifier
            initialize_project(staging, name)
            source = staging / "private" / ("upload" + SUFFIXES[format])
            private_write(source, raw)
            case, config = load_case(staging)
            report = import_file(staging, case, config, source, format=format, publish_deceased=review == "true",
                                 publish_reviewed_sources=source_review == "true")
            source.unlink()
            case, config = load_case(staging)
            build_project(case, config, staging / "dist")
            self.server.previews[identifier] = staging / "dist"
            report.update({"preview": f"/site/{identifier}/", "project": str(staging)})
            self.json_reply(201, report)
        except (OSError, ValueError, TypeError, TimeoutError) as error:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            self.json_reply(400, {"error": str(error)[:1200]})


def serve(directory: Path, port: int = 8000) -> None:
    with UploadServer(directory, port) as server:
        print(f"Local upload wizard: {server.origin}/", flush=True)
        print("Files stay on this computer. Press Ctrl-C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
