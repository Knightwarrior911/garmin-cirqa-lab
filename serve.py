"""Loopback-only Garmin dashboard with single-flight, rate-limited cloud refresh."""

import argparse
import json
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import store
import activity_detail
import training
import imported_plan

ROOT = Path(__file__).parent
COOLDOWN = 30 * 60
sync_lock = threading.Lock()
sync_state = {"running": False, "last_attempt": 0.0, "error": None}
STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/index.html": ("index.html", "text/html"),
    "/activity": ("activity.html", "text/html"),
    "/activities": ("activity.html", "text/html"),
    "/activity.js": ("activity.js", "text/javascript"),
    "/activity.css": ("activity.css", "text/css"),
    "/training": ("training.html", "text/html"),
    "/training.js": ("training.js", "text/javascript"),
    "/training.css": ("training.css", "text/css"),
    "/watch.js": ("watch.js", "text/javascript"),
    "/watch.css": ("watch.css", "text/css"),
    "/pwa.js": ("pwa.js", "text/javascript"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
}


def sync_status():
    with sync_lock:
        return {
            "ok": True,
            "running": sync_state["running"],
            "error": sync_state["error"],
            "cooldown_seconds": max(
                0, round(COOLDOWN - (time.time() - sync_state["last_attempt"]))
            ),
        }


def sync_worker():
    error = None
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "sync.py"), "--days", "2", "--quiet"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=240,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            error = "Garmin refresh did not fully complete. Stored readings remain available. Check login or try again after 30 minutes."
    except (OSError, subprocess.TimeoutExpired):
        error = "Unable to finish Garmin refresh. Stored readings remain available."
    finally:
        with sync_lock:
            sync_state["running"] = False
            sync_state["error"] = error


def request_sync():
    with sync_lock:
        if (
            not sync_state["running"]
            and time.time() - sync_state["last_attempt"] >= COOLDOWN
        ):
            sync_state.update(running=True, last_attempt=time.time(), error=None)
            threading.Thread(target=sync_worker, daemon=True).start()
    return sync_status()


class Handler(BaseHTTPRequestHandler):
    def allowed_host(self):
        return self.headers.get("Host") in (
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        )

    def send_json(self, payload, status=200):
        body = json.dumps(payload, default=str, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed_host():
            self.send_json({"ok": False, "error": "Invalid host"}, 403)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "app": "cirqa-dashboard", "hosting": "local"})
            return
        if parsed.path == "/api/sync":
            self.send_json(sync_status())
            return
        if parsed.path in STATIC_FILES:
            filename, content_type = STATIC_FILES[parsed.path]
            body = (ROOT / "dashboard" / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        qs = parse_qs(parsed.query)
        conn = store.connect_db()
        try:
            if parsed.path.startswith("/api/activity/"):
                aid = parsed.path[len("/api/activity/") :]
                result = activity_detail.get_detail(conn, aid)
                self.send_json(
                    result or {"ok": False, "error": "Activity not found"},
                    200 if result else 404,
                )
            elif parsed.path == "/api/dashboard":
                ov = store.overview(conn)
                ov["today"] = date.today().isoformat()
                self.send_json({
                    "ok": True, "overview": ov,
                    "days": [store.day_to_dict(r) for r in store.get_days(conn, 90)],
                    "activities": store.get_activities(conn, 100),
                    "sync": sync_status(), "hosting": "local",
                })
            elif parsed.path == "/api/training":
                try:
                    period = int(qs.get("period", ["7"])[0])
                    if period not in (7, 28):
                        raise ValueError()
                except ValueError:
                    self.send_json({"ok": False, "error": "Choose a 7 or 28 day comparison."}, 400)
                    return
                self.send_json(training.dashboard(conn, date.today().isoformat(), period))
            elif parsed.path == "/api/overview":
                ov = store.overview(conn)
                ov["today"] = date.today().isoformat()
                self.send_json({"ok": True, "overview": ov})
            elif parsed.path == "/api/day":
                day = store.day_to_dict(store.get_day(conn, qs.get("date", [""])[0]), detail=True)
                self.send_json({"ok": True, "day": day} if day else {"ok": False, "error": "Day not found"}, 200 if day else 404)
            elif parsed.path == "/api/days":
                try:
                    n = min(365, max(1, int(qs.get("days", ["90"])[0])))
                except ValueError:
                    n = 90
                self.send_json(
                    {
                        "ok": True,
                        "days": [store.day_to_dict(r) for r in store.get_days(conn, n)],
                    }
                )
            elif parsed.path == "/api/activities":
                try:
                    n = min(1000, max(1, int(qs.get("limit", ["20"])[0])))
                except ValueError:
                    n = 20
                self.send_json(
                    {"ok": True, "activities": store.get_activities(conn, n)}
                )
            else:
                self.send_json({"ok": False, "error": "Not found"}, 404)
        finally:
            conn.close()

    def do_POST(self):
        # A custom header and exact origin/host checks prevent other sites triggering cloud calls.
        origin = self.headers.get("Origin")
        expected = f"http://{self.headers.get('Host')}"
        if (
            not self.allowed_host()
            or self.headers.get("X-CIRQA-Request") != "1"
            or (origin and origin != expected)
        ):
            self.send_json(
                {"ok": False, "error": "Request must come from the local dashboard"},
                403,
            )
            return
        if self.path.startswith("/api/training/"):
            actions = {
                "/api/training/profile": training.save_profile,
                "/api/training/feedback": training.save_feedback,
                "/api/training/checkin": lambda conn, data: training.save_checkin(conn, data, date.today().isoformat()),
                "/api/training/plan": lambda conn, data: imported_plan.update(conn, data, date.today().isoformat()),
            }
            if self.path not in actions:
                self.send_json({"ok": False, "error": "Not found"}, 404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                limit = 262144 if self.path == "/api/training/plan" else 4096
                if not 0 < size <= limit:
                    raise ValueError(f"Send a JSON object no larger than {limit} bytes.")
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("Send a JSON object.")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("Send a JSON object.")
                conn = store.connect_db()
                try:
                    actions[self.path](conn, payload)
                finally:
                    conn.close()
            except (ValueError, UnicodeError) as error:
                self.send_json({"ok": False, "error": str(error)}, 400)
                return
            self.send_json({"ok": True})
            return
        if self.path.startswith("/api/activity/") and self.path.endswith("/fetch"):
            aid = self.path[len("/api/activity/") : -len("/fetch")]
            result = activity_detail.request_detail(aid)
            self.send_json(
                result or {"ok": False, "error": "Activity not found"},
                200 if result else 404,
            )
            return
        if self.path != "/api/sync":
            self.send_json({"ok": False, "error": "Not found"}, 404)
            return
        self.send_json(request_sync())

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    conn = store.connect_db()
    last = store.last_sync(conn)
    conn.close()
    if last and last["mode"] == "garmin":
        try:
            sync_state["last_attempt"] = datetime.fromisoformat(
                last["finished_at"]
            ).timestamp()
        except ValueError:
            pass
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"CIRQA dashboard on http://127.0.0.1:{args.port}", flush=True)
    if not args.no_open:
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
