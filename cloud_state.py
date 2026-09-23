"""Private, conditional-write snapshots for the single-owner cloud dashboard.

SQLite remains the query engine, not a persistent Vercel filesystem database.
One private Blob atomically contains its backup, Garmin tokens and job lease.
The wire headers mirror @vercel/blob's conditional writes (API version 12).
"""

import base64
from contextlib import contextmanager
import gzip
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import activity_detail
import store
import training
import imported_plan

ROOT = Path(__file__).resolve().parent
STATE_PATH = "cirqa/state-v1.json.gz"
COOLDOWN = 1800
LEASE_SECONDS = 330


class CloudStorageError(RuntimeError):
    pass


class StateConflict(CloudStorageError):
    pass


def _credentials():
    token = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
    parts = token.split("_")
    if len(parts) < 5 or not parts[3].isalnum():
        raise CloudStorageError("Private cloud storage is not configured.")
    return token, parts[3]


def load_state():
    token, store_id = _credentials()
    url = f"https://{store_id.lower()}.private.blob.vercel-storage.com/{STATE_PATH}?cache=0"
    request = Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(request, timeout=15) as response:
            etag = response.headers.get("ETag")
            state = json.loads(gzip.decompress(response.read()))
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise CloudStorageError("Unable to read private cloud history.") from exc
    if not etag or state.get("schema") != 1 or not state.get("database"):
        raise CloudStorageError("Cloud history is missing or has an unsupported format.")
    return state, etag


def save_state(state, etag=None):
    """Create once or replace exactly the version read; never blind-overwrite."""
    token, _ = _credentials()
    payload = gzip.compress(json.dumps(state, separators=(",", ":"), allow_nan=False).encode())
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "x-api-version": "12",
        "x-vercel-blob-access": "private",
        "x-content-type": "application/gzip",
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "1" if etag else "0",
        "x-cache-control-max-age": "60",
    }
    if etag:
        headers["x-if-match"] = etag
    url = "https://vercel.com/api/blob/?" + urlencode({"pathname": STATE_PATH})
    try:
        with urlopen(Request(url, data=payload, headers=headers, method="PUT"), timeout=15) as response:
            result = json.load(response)
    except HTTPError as exc:
        try:
            code = json.loads(exc.read()).get("error", {}).get("code")
        except (ValueError, AttributeError):
            code = None
        if exc.code == 412 or code == "precondition_failed":
            raise StateConflict("Another cloud request changed the state. Reload before retrying.") from exc
        raise CloudStorageError("Unable to save private cloud history.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise CloudStorageError("Unable to save private cloud history.") from exc
    if not result.get("etag"):
        raise CloudStorageError("Cloud storage did not confirm the saved version.")
    return result["etag"]


def database_backup(conn):
    """Use SQLite backup, including committed WAL rows, not a raw file copy."""
    with tempfile.TemporaryDirectory(prefix="cirqa-backup-") as folder:
        path = Path(folder) / "backup.db"
        target = sqlite3.connect(path)
        try:
            conn.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            target.close()
        return base64.b64encode(path.read_bytes()).decode("ascii")


@contextmanager
def open_snapshot(state):
    with tempfile.TemporaryDirectory(prefix="cirqa-cloud-") as folder:
        directory = Path(folder)
        path = directory / "garmin.db"
        path.write_bytes(base64.b64decode(state["database"], validate=True))
        tokens = directory / "tokens"
        tokens.mkdir()
        for name, value in state.get("tokens", {}).items():
            if name != "garmin_tokens.json":
                raise CloudStorageError("Unsupported Garmin token file in cloud history.")
            (tokens / name).write_bytes(base64.b64decode(value, validate=True))
        conn = store.connect_db(path)
        try:
            yield conn, directory
        finally:
            conn.close()


def initial_state(database_path, token_dir):
    conn = sqlite3.connect(f"file:{Path(database_path).as_posix()}?mode=ro", uri=True)
    try:
        backup = database_backup(conn)
    finally:
        conn.close()
    token_file = Path(token_dir) / "garmin_tokens.json"
    if not token_file.is_file():
        raise CloudStorageError("Run the local Garmin login before migrating tokens.")
    return {
        "schema": 1,
        "database": backup,
        "tokens": {token_file.name: base64.b64encode(token_file.read_bytes()).decode("ascii")},
        "sync": {"last_attempt": 0, "error": None},
        "details": {},
        "lease": None,
    }


def active_lease(state):
    lease = state.get("lease")
    return lease if lease and lease["until"] > time.time() else None


def sync_status(state):
    status = state.get("sync", {})
    lease = active_lease(state)
    expired = state.get("lease") and not lease and state["lease"]["kind"] == "sync"
    return {
        "ok": True,
        "running": bool(lease and lease["kind"] == "sync"),
        "busy": bool(lease and lease["kind"] != "sync"),
        "error": "The previous cloud refresh was interrupted. Stored history is preserved." if expired else status.get("error"),
        "cooldown_seconds": max(0, round(COOLDOWN - (time.time() - status.get("last_attempt", 0)))),
    }


def detail_response(conn, state, aid):
    result = activity_detail.get_detail(conn, aid)
    if result is None:
        return None
    lease = active_lease(state)
    status = state.get("details", {}).get(aid, {})
    expired = state.get("lease") and not lease and state["lease"].get("activity_id") == aid
    result["fetch"].update(
        running=bool(lease and lease.get("activity_id") == aid),
        busy=bool(lease and lease.get("activity_id") != aid),
        cooldown_seconds=max(result["fetch"]["cooldown_seconds"], max(0, round(COOLDOWN - (time.time() - status.get("last_attempt", 0))))),
    )
    if expired:
        result["fetch"]["error"] = "The activity refresh was interrupted. Cached detail is preserved."
    elif status.get("error"):
        result["fetch"]["error"] = status["error"]
    return result


def run_job(kind, aid=None):
    state, etag = load_state()
    with open_snapshot(state) as (conn, directory):
        if kind == "activity":
            detail = detail_response(conn, state, aid)
            if detail is None or not detail["fetch"]["supported"] or detail["fetch"]["cooldown_seconds"]:
                return state
            status = state.setdefault("details", {}).setdefault(aid, {})
        else:
            if sync_status(state)["cooldown_seconds"]:
                return state
            status = state.setdefault("sync", {})
        if active_lease(state):
            return state
        now = time.time()
        lease_id = secrets.token_hex(16)
        state["lease"] = {"id": lease_id, "kind": kind, "activity_id": aid, "until": now + LEASE_SECONDS}
        status.update(last_attempt=now, error=None)
        try:
            etag = save_state(state, etag)
        except StateConflict:
            return load_state()[0]
        command = [sys.executable, str(ROOT / "cloud_worker.py"), kind, str(directory)]
        if aid:
            command.append(aid)
        error = None
        try:
            result = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=220 if kind == "sync" else 180)
            if result.returncode:
                error = "Garmin refresh was incomplete. Stored readings are preserved; some endpoints may be unavailable or login may need renewal."
            result_path = directory / "result.json"
            if result_path.exists():
                error = json.loads(result_path.read_text()).get("error") or error
        except subprocess.TimeoutExpired:
            error = "Garmin refresh reached its time limit. Saved readings are preserved."
        except OSError:
            error = "Unable to start Garmin refresh. Stored readings are preserved."
        # The child is finished or killed before its committed database is backed up.
        state["database"] = database_backup(conn)
        token_file = directory / "tokens" / "garmin_tokens.json"
        state["tokens"] = {token_file.name: base64.b64encode(token_file.read_bytes()).decode("ascii")}
        status["error"] = error
        state["lease"] = None
        # A stale worker can never overwrite a successor's snapshot.
        save_state(state, etag)
        return state


def update_training(kind, payload, today):
    """Persist owner input atomically without overwriting a running Garmin job."""
    actions = {
        "profile": training.save_profile,
        "feedback": training.save_feedback,
        "checkin": lambda conn, data: training.save_checkin(conn, data, today),
        "plan": lambda conn, data: imported_plan.update(conn, data, today),
    }
    if kind not in actions:
        raise ValueError("Unsupported training update.")
    state, etag = load_state()
    if active_lease(state):
        raise StateConflict("Garmin is refreshing. Wait for it to finish, then save again; your form has not been saved.")
    with open_snapshot(state) as (conn, _):
        actions[kind](conn, payload)
        state["database"] = database_backup(conn)
    save_state(state, etag)
