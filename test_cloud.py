"""Observable cloud access and durable snapshot boundaries; no real credentials."""

import base64
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import app as web
import cloud_state
import store


class CloudAccessTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "CIRQA_ORIGIN": "https://cirqa.example",
            "CIRQA_ACCESS_HASH": hashlib.sha256(b"owner-test-code").hexdigest(),
            "CRON_SECRET": "cron-test-secret",
        })
        self.env.start()
        self.config = patch.dict(web.app.config, SECRET_KEY="test-session-secret-that-is-long-enough", TESTING=True, SESSION_COOKIE_SECURE=True, SESSION_COOKIE_NAME="__Host-cirqa")
        self.config.start()
        self.client = web.app.test_client()
        self.root = "https://cirqa.example"

    def tearDown(self):
        self.config.stop()
        self.env.stop()

    def sign_in(self):
        return self.client.post("/login", base_url=self.root, headers={"Origin": self.root}, data={"password": "owner-test-code"})

    def test_health_routes_require_owner_before_reading_storage(self):
        with patch.object(cloud_state, "load_state", side_effect=AssertionError("Must not access storage")):
            for path in ("/api/dashboard", "/api/days", "/api/activities", "/api/activity/123"):
                response = self.client.get(path, base_url=self.root)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["Cache-Control"], "private, no-store")
            self.assertEqual(self.client.get("/", base_url=self.root).location, "/login")

    def test_owner_session_cookie_and_logout(self):
        response = self.sign_in()
        self.assertEqual(response.status_code, 303)
        cookie = response.headers["Set-Cookie"]
        for requirement in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
            self.assertIn(requirement, cookie)
        with self.client.get("/", base_url=self.root) as page:
            self.assertEqual(page.status_code, 200)
        self.assertEqual(self.client.post("/auth/logout", base_url=self.root, headers={"Origin": self.root, "X-CIRQA-Request": "1"}).status_code, 200)
        self.assertEqual(self.client.get("/api/dashboard", base_url=self.root).status_code, 401)

    def test_wrong_code_and_cross_origin_writes_are_rejected(self):
        wrong = self.client.post("/login", base_url=self.root, headers={"Origin": self.root}, data={"password": "wrong"})
        self.assertEqual(wrong.status_code, 401)
        self.sign_in()
        with patch.object(cloud_state, "run_job", side_effect=AssertionError("Must not run a job")):
            for headers in ({}, {"Origin": "https://other.example", "X-CIRQA-Request": "1"}, {"Origin": self.root}):
                self.assertEqual(self.client.post("/api/sync", base_url=self.root, headers=headers).status_code, 403)
            self.assertEqual(self.client.get("/api/cron", base_url=self.root).status_code, 401)

    def test_snapshot_response_contains_readings_not_private_tokens(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = store.connect_db(Path(folder) / "source.db")
            store.upsert_day(conn, {"date": "2026-09-22", "steps": 123, "resting_hr": None})
            state = {"schema": 1, "database": cloud_state.database_backup(conn), "tokens": {"garmin_tokens.json": base64.b64encode(b'{"secret":"never-send-to-browser"}').decode()}, "sync": {}, "lease": None}
            conn.close()
        self.sign_in()
        with patch.object(cloud_state, "load_state", return_value=(state, '"version"')):
            response = self.client.get("/api/dashboard", base_url=self.root)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["days"][0]["steps"], 123)
        self.assertIsNone(payload["days"][0]["resting_hr"])
        self.assertNotIn("tokens", payload)
        self.assertNotIn("database", payload)
        self.assertNotIn(state["tokens"]["garmin_tokens.json"], response.get_data(as_text=True))


class SnapshotTests(unittest.TestCase):
    def test_backup_preserves_committed_wal_rows_and_all_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            source = store.connect_db(Path(folder) / "source.db")
            store.upsert_day(source, {"date": "2026-09-22", "steps": 0})
            source.execute("INSERT INTO training_log(date,notes) VALUES(?,?)", ("2026-09-22", "retained history"))
            source.commit()
            state = {"database": cloud_state.database_backup(source), "tokens": {}}
            with cloud_state.open_snapshot(state) as (restored, _):
                self.assertEqual(store.get_day(restored, "2026-09-22")["steps"], 0)
                self.assertEqual(restored.execute("SELECT notes FROM training_log").fetchone()[0], "retained history")
            source.close()

    def test_expired_job_is_not_reported_as_running_or_successful(self):
        state = {"sync": {"last_attempt": time.time() - 400}, "lease": {"kind": "sync", "until": time.time() - 1}}
        result = cloud_state.sync_status(state)
        self.assertFalse(result["running"])
        self.assertIn("interrupted", result["error"])


if __name__ == "__main__":
    unittest.main()
