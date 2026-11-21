"""Built-in local ThreadingHTTPServer serving the app and bundled static assets."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
import os
import urllib.parse
from timecard.application import handle_request
from timecard.db import resource_root


class TimeCardRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Suppress noisy console output in standalone GUI mode.
        pass

    def _serve_static(self, rel_path):
        root = resource_root().resolve()
        target = (root / rel_path.lstrip("/")).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        ctype, _ = mimetypes.guess_type(str(target))
        if not ctype:
            ctype = "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path or "/"
        if path == "/favicon.ico":
            return self._serve_static("favicon.ico")
        if path.startswith("/images/"):
            return self._serve_static(path)

        query_params = {
            k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()
        }
        form_params = {}
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = 0
            raw = self.rfile.read(min(length, 5 * 1024 * 1024)) if length > 0 else b""
            form_params = {
                k: v[-1]
                for k, v in urllib.parse.parse_qs(
                    raw.decode("utf-8", errors="replace"), keep_blank_values=True
                ).items()
            }

        cookie_header = self.headers.get("Cookie", "")
        try:
            resp = handle_request(method, query_params, form_params, cookie_header)
        except Exception:
            body = b"Internal Server Error"
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        self.send_header("Cache-Control", "no-store")
        for hdr_name, hdr_val in resp.headers:
            self.send_header(hdr_name, hdr_val)
        self.end_headers()
        if resp.body:
            self.wfile.write(resp.body)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


class TimeCardHTTPServer(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR permits binding a port already in use; disable it there.
    allow_reuse_address = os.name != "nt"


def create_server(host="127.0.0.1", port=0):
    return TimeCardHTTPServer((host, port), TimeCardRequestHandler)
