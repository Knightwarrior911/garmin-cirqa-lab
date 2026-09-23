"""Owner-private Flask entrypoint for Vercel; no health data in static assets."""

from datetime import datetime, timedelta
import hashlib
import hmac
import os
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory, session
from werkzeug.exceptions import HTTPException

import cloud_state
import store
import training

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard"
LOCAL_HTTP = os.environ.get("CIRQA_LOCAL_HTTP") == "1" and not os.environ.get("VERCEL")
app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.environ.get("CIRQA_SESSION_SECRET"),
    MAX_CONTENT_LENGTH=4096,
    SESSION_COOKIE_NAME="cirqa-local" if LOCAL_HTTP else "__Host-cirqa",
    SESSION_COOKIE_SECURE=not LOCAL_HTTP,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_PATH="/",
    SESSION_REFRESH_EACH_REQUEST=False,
    PERMANENT_SESSION_LIFETIME=timedelta(days=180),
)
PUBLIC_FILES = {
    "manifest.webmanifest": "application/manifest+json",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
    "apple-touch-icon.png": "image/png",
    "pwa.js": "text/javascript",
    "activity.js": "text/javascript",
    "activity.css": "text/css",
    "training.js": "text/javascript",
    "training.css": "text/css",
    "watch.js": "text/javascript",
    "watch.css": "text/css",
}
LOGIN = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#080a0d"><meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>Sign in · CIRQA</title><style>
*{box-sizing:border-box}body{margin:0;background:#080a0d;color:#f4f7fa;font:16px/1.5 system-ui,sans-serif;min-height:100dvh;display:grid;place-items:center;padding:24px;color-scheme:dark}
main{max-width:420px;width:100%;background:#14181e;border:1px solid #303944;border-radius:20px;padding:32px}
img{border-radius:14px}h1{margin:18px 0 8px}p{color:#98a4b5}label{display:block;font-weight:600;margin:22px 0 8px}
input,button{font:inherit;width:100%;padding:13px;border-radius:9px;border:1px solid #475464}input{background:#080a0d;color:#f4f7fa}button{margin-top:18px;background:#a3ff12;color:#080a0d;font-weight:700;cursor:pointer}
input:focus-visible,button:focus-visible{outline:3px solid #5edfff;outline-offset:3px}.error{color:#ff927d}small{color:#98a4b5;display:block;margin-top:22px}
</style></head><body><main><img src="/icon-192.png" width="56" height="56" alt="CIRQA">
<h1>Your CIRQA. With a screen.</h1><p>Sign in to your watch face, native Garmin metrics and training history.</p>
{% if error %}<p class="error" role="alert">{{ error }}</p>{% endif %}
<form action="/login" method="post"><label for="password">Owner access code</label>
<input id="password" name="password" type="password" autocomplete="current-password" required maxlength="128" autofocus>
<button type="submit">Open CIRQA</button></form><small>This is your dashboard access code, not your Garmin password. Once signed in, use Safari → Share → Add to Home Screen.</small>
</main></body></html>"""


def configured_origins():
    origins = {os.environ.get("CIRQA_ORIGIN", "").rstrip("/")}
    for key in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        if os.environ.get(key):
            origins.add("https://" + os.environ[key])
    return {origin for origin in origins if origin}


def owner_configured():
    return len(os.environ.get("CIRQA_ACCESS_HASH", "")) == 64 and len(app.config.get("SECRET_KEY") or "") >= 32


@app.before_request
def protect():
    origins = configured_origins()
    if request.host not in {urlparse(origin).netloc for origin in origins}:
        return jsonify(ok=False, error="Unrecognized dashboard host."), 400
    if not owner_configured():
        return jsonify(ok=False, error="Owner access is not configured."), 503
    if request.path == "/api/cron":
        expected = os.environ.get("CRON_SECRET", "")
        actual = request.headers.get("Authorization", "")
        if not expected or not hmac.compare_digest(actual, "Bearer " + expected):
            return jsonify(ok=False, error="Unauthorized."), 401
        return None
    if request.method == "POST":
        origin = request.headers.get("Origin", "")
        if origin not in origins or urlparse(origin).netloc != request.host:
            return jsonify(ok=False, error="Request must come from this dashboard."), 403
        if request.path != "/login" and request.headers.get("X-CIRQA-Request") != "1":
            return jsonify(ok=False, error="Invalid dashboard request."), 403
    if request.path in ("/login", "/api/health", "/favicon.ico") or request.path.lstrip("/") in PUBLIC_FILES:
        return None
    if not session.get("owner"):
        if request.path.startswith(("/api/", "/auth/")):
            return jsonify(ok=False, error="Sign in to your private dashboard."), 401
        return redirect("/login", code=303)
    return None


@app.after_request
def security_headers(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    if not LOCAL_HTTP:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.errorhandler(cloud_state.CloudStorageError)
def storage_error(error):
    return jsonify(ok=False, error=str(error)), 409 if isinstance(error, cloud_state.StateConflict) else 503


@app.errorhandler(Exception)
def unexpected_error(error):
    if isinstance(error, HTTPException):
        return jsonify(ok=False, error=error.description), error.code
    # Do not expose private Blob URLs, token contents or Garmin exception bodies.
    return jsonify(ok=False, error="Unable to complete this request. Stored cloud history is preserved."), 500


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        candidate = hashlib.sha256(password.encode()).hexdigest()
        if password and len(password) <= 128 and hmac.compare_digest(candidate, os.environ["CIRQA_ACCESS_HASH"]):
            session.clear()
            session["owner"] = True
            session.permanent = True
            return redirect("/", code=303)
        error = "That access code was not recognized."
    elif session.get("owner"):
        return redirect("/", code=303)
    return render_template_string(LOGIN, error=error), 401 if error else 200


@app.post("/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/")
@app.get("/index.html")
def homepage():
    return send_from_directory(DASHBOARD, "index.html")


@app.get("/training")
def training_page():
    return send_from_directory(DASHBOARD, "training.html")


@app.get("/activity")
@app.get("/activities")
def activity_page():
    return send_from_directory(DASHBOARD, "activity.html")


@app.get("/<filename>")
def public_asset(filename):
    if filename == "favicon.ico":
        filename = "icon-192.png"
    if filename not in PUBLIC_FILES:
        return jsonify(ok=False, error="Not found"), 404
    return send_from_directory(DASHBOARD, filename, mimetype=PUBLIC_FILES[filename])


@app.get("/api/health")
def health():
    return jsonify(ok=True, app="cirqa-dashboard", hosting="cloud")


def overview(conn):
    result = store.overview(conn)
    result["today"] = datetime.now(ZoneInfo(os.environ.get("CIRQA_TIMEZONE", "Asia/Kolkata"))).date().isoformat()
    return result


def count_arg(name, default, maximum):
    try:
        return min(maximum, max(1, int(request.args.get(name, default))))
    except (ValueError, TypeError):
        return default


@app.get("/api/dashboard")
def dashboard_data():
    state, _ = cloud_state.load_state()
    with cloud_state.open_snapshot(state) as (conn, _):
        return jsonify(ok=True, overview=overview(conn), days=[store.day_to_dict(r) for r in store.get_days(conn, 90)], activities=store.get_activities(conn, 100), sync=cloud_state.sync_status(state), hosting="cloud")


@app.get("/api/overview")
def overview_data():
    state, _ = cloud_state.load_state()
    with cloud_state.open_snapshot(state) as (conn, _):
        return jsonify(ok=True, overview=overview(conn))


@app.get("/api/days")
def daily_data():
    state, _ = cloud_state.load_state()
    with cloud_state.open_snapshot(state) as (conn, _):
        return jsonify(ok=True, days=[store.day_to_dict(r) for r in store.get_days(conn, count_arg("days", 90, 365))])


@app.get("/api/day")
def daily_detail_data():
    state, _ = cloud_state.load_state()
    with cloud_state.open_snapshot(state) as (conn, _):
        day = store.day_to_dict(store.get_day(conn, request.args.get("date", "")), detail=True)
        return jsonify(ok=True, day=day) if day else (jsonify(ok=False, error="Day not found"), 404)


@app.get("/api/activities")
def activity_data():
    state, _ = cloud_state.load_state()
    with cloud_state.open_snapshot(state) as (conn, _):
        return jsonify(ok=True, activities=store.get_activities(conn, count_arg("limit", 20, 1000)))


@app.route("/api/sync", methods=["GET", "POST"])
def daily_sync():
    state = cloud_state.run_job("sync") if request.method == "POST" else cloud_state.load_state()[0]
    return jsonify(cloud_state.sync_status(state))


@app.get("/api/activity/<aid>")
def activity_detail_data(aid):
    state, _ = cloud_state.load_state()
    with cloud_state.open_snapshot(state) as (conn, _):
        result = cloud_state.detail_response(conn, state, aid)
        return jsonify(result or {"ok": False, "error": "Activity not found"}), 200 if result else 404


@app.post("/api/activity/<aid>/fetch")
def activity_fetch(aid):
    if not aid.isdigit():
        return jsonify(ok=False, error="Not a Garmin activity identifier."), 400
    state = cloud_state.run_job("activity", aid)
    with cloud_state.open_snapshot(state) as (conn, _):
        result = cloud_state.detail_response(conn, state, aid)
        return jsonify(result or {"ok": False, "error": "Activity not found"}), 200 if result else 404


@app.get("/api/cron")
def scheduled_sync():
    return jsonify(cloud_state.sync_status(cloud_state.run_job("sync")))


def training_today():
    return datetime.now(ZoneInfo(os.environ.get("CIRQA_TIMEZONE", "Asia/Kolkata"))).date().isoformat()


@app.get("/api/training")
def training_data():
    try:
        period = int(request.args.get("period", "7"))
        if period not in (7, 28):
            raise ValueError()
    except ValueError:
        return jsonify(ok=False, error="Choose a 7 or 28 day comparison."), 400
    state, _ = cloud_state.load_state()
    with cloud_state.open_snapshot(state) as (conn, _):
        return jsonify(training.dashboard(conn, training_today(), period))


@app.post("/api/training/<kind>")
def training_update(kind):
    if kind not in ("profile", "feedback", "checkin", "plan"):
        return jsonify(ok=False, error="Not found."), 404
    if kind == "plan":
        request.max_content_length = 262144
    if not request.is_json:
        return jsonify(ok=False, error="Send a JSON object."), 400
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error="Send a JSON object."), 400
    try:
        cloud_state.update_training(kind, payload, training_today())
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    return jsonify(ok=True)
