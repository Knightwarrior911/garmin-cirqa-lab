"""Local dashboard server. Stdlib only - no extra dependencies.

    .venv\\Scripts\\python serve.py            # http://127.0.0.1:8787
    .venv\\Scripts\\python serve.py --port 8790 --no-open
"""
import argparse
import csv
import io
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import insights
import store

ROOT = Path(__file__).parent
DASHBOARD = ROOT / "dashboard" / "index.html"
LOG_FIELDS = ["date", "session", "exercise", "sets", "reps", "load_kg", "rpe", "soreness", "notes"]


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _int_arg(self, qs, name, default):
        try:
            return max(1, int(qs.get(name, [default])[0]))
        except (ValueError, TypeError):
            return default

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        conn = store.connect_db()
        try:
            if parsed.path in ("/", "/index.html"):
                body = DASHBOARD.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/api/overview":
                self._json({"ok": True, "overview": store.overview(conn)})
            elif parsed.path == "/api/days":
                n = min(365, self._int_arg(qs, "days", 90))
                self._json({"ok": True, "days": [store.day_to_dict(r) for r in store.get_days(conn, n)]})
            elif parsed.path == "/api/activities":
                acts = store.get_activities(conn, min(100, self._int_arg(qs, "limit", 20)))
                for a in acts:
                    if store.has_splits(conn, a["activity_id"]):
                        a["splits"] = store.get_splits(conn, a["activity_id"])
                self._json({"ok": True, "activities": acts})
            elif parsed.path == "/api/insights":
                self._json({"ok": True, **insights.generate(conn)})
            elif parsed.path == "/api/log":
                self._json({"ok": True, "entries": store.get_log(conn, min(200, self._int_arg(qs, "limit", 50)))})
            elif parsed.path == "/api/log.csv":
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=LOG_FIELDS + ["created_at"], extrasaction="ignore")
                writer.writeheader()
                for row in store.get_log(conn, 1000):
                    writer.writerow(row)
                body = buf.getvalue().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=training_log.csv")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        finally:
            conn.close()

    def do_POST(self):
        if urlparse(self.path).path != "/api/log":
            self._json({"ok": False, "error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"ok": False, "error": "invalid JSON"}, 400)
            return
        if not payload.get("date"):
            self._json({"ok": False, "error": "date is required (YYYY-MM-DD)"}, 400)
            return
        entry = {}
        for k in LOG_FIELDS:
            v = payload.get(k)
            if isinstance(v, str):
                v = v.strip() or None
            elif isinstance(v, (int, float)):
                v = v
            else:
                v = None
            entry[k] = v
        conn = store.connect_db()
        try:
            entry_id = store.add_log_entry(conn, entry)
        finally:
            conn.close()
        self._json({"ok": True, "id": entry_id})

    def log_message(self, *args):  # quiet default access logging
        pass


def main():
    ap = argparse.ArgumentParser(description="Serve the CIRQA dashboard locally.")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-open", action="store_true", help="do not open a browser window")
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"CIRQA dashboard on {url}  (Ctrl+C to stop)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
