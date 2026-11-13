"""Local web server for Analog Atlas.

Run from this folder:   python serve.py          (then open http://localhost:8080)
                        python serve.py --open   (also opens Chrome or Edge)
                        python serve.py --open --offline   (opens it without the 3D globe, for no internet)

It only listens on this computer (127.0.0.1), so nothing is shared on the network.
It only answers requests addressed to localhost or 127.0.0.1 on its own port
(this blocks "DNS rebinding" web pages), and it never lists the files in a folder.
Other websites cannot show its pages in a frame (no clickjacking).
It never sends secrets or developer files: earthdata_token.txt (and every other .txt file
next to this one), dotfiles and dot folders (.git, .claude, .env), Python files and caches,
and the firmware build folders. It answers Range requests, so the promo videos can be scrubbed.
If the port is already in use, it says whether Analog Atlas or another program holds it, and stops
(with --open and Analog Atlas already running, it opens the running app in the browser first).
Use Chrome or Edge: the USB field kit (Web Serial) only works there, on localhost.
"""
import functools
import http.server
import importlib.util
import json
import os
import re
import pathlib
import socket
import subprocess
import sys
import urllib.request
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8080"))
# The only names this server answers to. A page on another site that points its own
# name at 127.0.0.1 sends its own name in the Host header, so it gets "403 Forbidden".
# No "[::1]": the server listens on 127.0.0.1 only (browsers fall back to it for "localhost").
ALLOWED_HOSTS = {f"{name}:{PORT}" for name in ("localhost", "127.0.0.1")}


def rel_parts(path):
    # The parts of a path inside ROOT, in lower case. None if the path is outside ROOT (a link).
    try:
        parts = [p.lower() for p in pathlib.PurePath(os.path.relpath(path, ROOT)).parts]
    except ValueError:  # another drive
        return None
    return None if parts[:1] == [".."] else parts


def private(parts):
    # Files this server never sends. config.js is not one of them: the app needs it.
    if not parts:
        return False
    names = [p.rstrip(". ") for p in parts]  # Windows ignores trailing dots and spaces: "serve.py." is serve.py
    return (any(p.startswith(".") or ":" in p for p in parts)  # .git, .claude, .env, .gitignore; "::$DATA" streams
            or "__pycache__" in names
            or names[-1].endswith((".py", ".pyc", ".pyw"))
            or (len(names) == 1 and names[0].endswith(".txt"))  # earthdata_token.txt and other keys in the top folder
            or (names[0] == "firmware" and "build" in names[1:]))


class Handler(http.server.SimpleHTTPRequestHandler):
    timeout = 30  # a client that stops sending for 30 s is dropped, so it cannot hold a server thread forever
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".json": "application/json",
        ".wasm": "application/wasm",
        ".glb": "model/gltf-binary",
        ".csv": "text/csv",
        ".ino": "text/plain",
        ".md": "text/plain",
    }
    range_left = None  # bytes still to send for a Range request (None: send the whole file)

    def guess_type(self, path):
        # LICENSE files have no extension. Show them as text in the browser instead of downloading them.
        if os.path.basename(path).upper() in ("LICENSE", "LICENCE"):
            return "text/plain; charset=utf-8"
        return super().guess_type(path)

    def end_headers(self):
        # Always serve the newest files (no stale browser cache while the team edits the app).
        self.send_header("Cache-Control", "no-store")
        # Only pages of this app may show our pages in a frame (no clickjacking from other sites),
        # and the browser must trust our file types (a .txt is never run as a script).
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def host_ok(self):
        return self.headers.get("Host", "").strip().lower() in ALLOWED_HOSTS

    def send_head(self):
        # Used for every GET and HEAD request.
        self.range_left = None
        if not self.host_ok():
            self.send_error(403, "unknown host name")
            return None
        path = self.translate_path(self.path)
        try:  # check the name as written and the real name on disk (Windows short names such as EARTHD~1.TXT)
            real = rel_parts(os.path.realpath(path))
            hidden = "\0" in path or private(rel_parts(path)) or private(real)
        except (OSError, ValueError):
            real, hidden = None, True
        # config.js holds the Cesium token: pages of this app may load it, a <script> tag on another site may not.
        if real == ["config.js"] and self.headers.get("Sec-Fetch-Site", "none") not in ("same-origin", "none"):
            hidden = True
        if hidden:
            self.send_error(404)
            return None
        rng = self.headers.get("Range")
        if rng is None or path.endswith("/") or not os.path.isfile(path):
            return super().send_head()
        return self.send_range(path, rng)

    def send_range(self, path, rng):
        # One byte range ("bytes=a-b", "bytes=a-" or "bytes=-n") gets "206 Partial Content", so videos
        # can be scrubbed. Another unit, several ranges, a range we cannot read ("bytes=abc", "bytes=9-3")
        # or an old If-Range get the whole file (RFC 9110 14.2); a range outside the file gets 416.
        unit, _, spec = rng.partition("=")
        m = re.fullmatch(r"\s*([0-9]*)\s*-\s*([0-9]*)\s*", spec)
        first, last = m.groups() if m else ("", "")
        if (unit.strip().lower() != "bytes" or not (first or last)
                or (first and last and int(last) < int(first))):
            return super().send_head()
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404)
            return None
        fs = os.fstat(f.fileno())
        size, modified = fs.st_size, self.date_time_string(fs.st_mtime)
        if self.headers.get("If-Range", modified) != modified:
            f.close()
            return super().send_head()
        if first:
            start, end = int(first), min(int(last), size - 1) if last else size - 1
        else:  # "bytes=-n": the last n bytes
            start, end = max(size - int(last), 0), size - 1
        if start > end:  # outside the file, "bytes=-0", or an empty file
            f.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        f.seek(start)
        self.range_left = end - start + 1
        self.send_response(206)
        self.send_header("Content-type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self.range_left))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Last-Modified", modified)
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        if self.range_left is None:
            return super().copyfile(source, outputfile)
        left = self.range_left
        while left > 0:
            chunk = source.read(min(left, 1 << 16))
            if not chunk:
                break
            outputfile.write(chunk)
            left -= len(chunk)

    def list_directory(self, path):
        # No folder listings: a folder without index.html answers "404 Not Found".
        self.send_error(404)
        return None

    def do_POST(self):
        # Local helpers, only accepted from this computer: the "3D" box in the app can save the
        # Cesium token into config.js, so it works in every browser on this computer.
        if not self.host_ok():
            self.send_error(403, "unknown host name")
            return
        origin = self.headers.get("Origin", "")
        if self.client_address[0] != "127.0.0.1" or origin not in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"):
            self.send_error(403)
            return
        # Second local helper: the promo video (pitch/promo.html) saves its own 30 s or 60 s recording
        # as pitch/analog-atlas-pitch-<name>.webm. Fixed names only, at most 400 MB.
        # The old video is only replaced at the very end, when the new one is complete and fixed;
        # if anything fails on the way, the old video stays as it was.
        m = re.fullmatch(r"/api/save-video\?name=(promo30|promo60)", self.path)
        if m:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400, "bad Content-Length")
                return
            if not 0 < length <= 400_000_000:
                self.send_error(413)
                return
            out = ROOT / "pitch" / f"analog-atlas-pitch-{m.group(1)}.webm"
            out.parent.mkdir(exist_ok=True)
            part = out.with_suffix(".part.webm")  # the upload goes here first
            fixed = out.with_suffix(".fixing.webm")  # the seekable copy made by fix_webm
            received, is_webm = 0, False
            try:
                with open(part, "wb") as f:
                    while received < length:
                        chunk = self.rfile.read(min(length - received, 1 << 20))
                        if not chunk:
                            break
                        if not received:
                            is_webm = chunk[:4] == b"\x1a\x45\xdf\xa3"  # every WebM file starts with these 4 bytes
                        f.write(chunk)
                        received += len(chunk)
            except OSError as err:  # the browser closed the connection, or the disk is full
                print(f"video upload failed: {err}", file=sys.stderr)
            error, status, keep_raw = None, 200, False
            if received != length:
                error, status = f"upload stopped after {received} of {length} bytes", 400
            elif not is_webm:
                error, status = "not a WebM video", 400
            else:
                try:  # add the duration and a seek index, so players can show the length and jump (pitch/fix_webm.py)
                    spec = importlib.util.spec_from_file_location("fix_webm", ROOT / "pitch" / "fix_webm.py")
                    fix_webm = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(fix_webm)
                    fix_webm.main(str(part), str(fixed))
                    os.replace(fixed, out)  # one step: other programs see the old video or the new one, never half a file
                except Exception as err:  # the recording is complete: keep it to look at, next to the old video
                    error, status, keep_raw = f"fix_webm failed ({err}); the raw recording is pitch/{part.name}", 500, True
            for leftover in (fixed,) if keep_raw else (part, fixed):  # temporary files we made: no use for them now
                try:
                    leftover.unlink()
                except OSError:
                    pass
            if error:
                print(f"video NOT saved, pitch/{out.name} was not changed: {error}", file=sys.stderr)
            result = {"saved": None if error else out.name, "bytes": received, "seekable": error is None}
            if error:
                result["error"] = error
            body = json.dumps(result).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:  # nobody is listening any more
                pass
            return
        if self.path != "/api/save-token":
            self.send_error(404)
            return
        try:
            length = max(0, min(int(self.headers.get("Content-Length", "0")), 10000))
            token = json.loads(self.rfile.read(length) or b"{}").get("token", "").strip()
        except (ValueError, AttributeError):
            token = ""
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token) or len(token) < 100:
            self.send_error(400, "not a Cesium token")
            return
        lines = [
            "// Analog Atlas - YOUR local settings. This file stays on your computer.",
            "// Saved by the app's 3D box. Do not send this token to anyone.",
            f"// It is visible in the browser, so keep it restricted to http://localhost:{PORT}",
            f"// and http://127.0.0.1:{PORT} (Allowed URLs) in your Cesium ion account.",
            "// Leave this file out when you copy, zip or share the project folder.",
            "window.ANALOG_ATLAS_CONFIG = {",
            f'  cesiumIonToken: "{token}",',
            "};",
        ]
        (ROOT / "config.js").write_text("\n".join(lines) + "\n", encoding="utf-8")
        body = b'{"saved":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if "--quiet" not in sys.argv:
            super().log_message(fmt, *args)


class Server(http.server.ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR lets a second server bind a port that is already in use, with no error,
    # so a second start.bat would quietly share port 8080. Here the port belongs to one server only.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows only
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        # A browser that stops a download (a video seek, a closed tab) or goes quiet is normal: no traceback for that.
        if not isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            super().handle_error(request, client_address)


def port_owner():
    # Who holds the port? "app" (Analog Atlas is already running), "other" (another program), or None (nobody answers).
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=2).close()
    except OSError:
        return None
    try:
        no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # ask this computer, never a proxy
        with no_proxy.open(f"http://localhost:{PORT}/", timeout=3) as res:
            return "app" if b"Analog Atlas" in res.read(20000) else "other"
    except (OSError, ValueError):  # an error page, or not a web server at all
        return "other"


def open_browser(url):
    # The USB field kit (Web Serial) needs Chrome or Edge. Use the default browser if it is one of them,
    # else Chrome, else Edge (on every Windows 10/11), else the default browser.
    if os.name == "nt":
        try:
            import winreg
            key = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                default = winreg.QueryValueEx(k, "ProgId")[0]
        except OSError:
            default = ""
        if not default.startswith(("ChromeHTML", "MSEdgeHTM")):
            for env, sub in (("PROGRAMFILES", r"Google\Chrome\Application\chrome.exe"),
                             ("PROGRAMFILES(X86)", r"Google\Chrome\Application\chrome.exe"),
                             ("LOCALAPPDATA", r"Google\Chrome\Application\chrome.exe"),
                             ("PROGRAMFILES(X86)", r"Microsoft\Edge\Application\msedge.exe"),
                             ("PROGRAMFILES", r"Microsoft\Edge\Application\msedge.exe")):
                exe = os.path.join(os.environ.get(env, ""), sub)
                if os.environ.get(env) and os.path.isfile(exe):
                    subprocess.Popen([exe, url])
                    return
    webbrowser.open(url)


def main():
    # --offline (start_offline.bat) opens the app without the 3D globe (?no3d), for a demo with no internet.
    page = "?no3d" if "--offline" in sys.argv else ""
    handler = functools.partial(Handler, directory=str(ROOT))
    try:
        httpd = Server(("127.0.0.1", PORT), handler)
    except OSError as err:
        owner = port_owner()
        if owner == "app":
            print(f"Port {PORT} is already in use: Analog Atlas is already running, open http://localhost:{PORT}")
            if "--open" in sys.argv:  # a second start.bat: open the running app again instead of only stopping
                open_browser(f"http://localhost:{PORT}/{page}")
                print("Opened it in the browser. This window can be closed; the first one keeps the app running.")
        elif owner == "other":
            print(f"Another program is using port {PORT}, so Analog Atlas cannot start."
                  f" Close that program, then start again. To find it, run: netstat -ano | findstr :{PORT}"
                  " (the last number is its PID; Task Manager > Details shows the program).")
        else:
            print(f"Could not start the server on port {PORT}: {err}")
        sys.exit(1)
    with httpd:
        url = f"http://localhost:{PORT}/"
        print(f"Analog Atlas is running at {url}   (press Ctrl+C to stop)")
        if "--open" in sys.argv:
            open_browser(url + page)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Stopped.")


if __name__ == "__main__":
    main()
