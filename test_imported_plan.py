"""Synthetic plan fixtures only: no owner photo, health targets or private dates."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cloud_state
import imported_plan
import store
import training


def sample_plan():
    def step(title, mode, minutes=None, duration=None, km=None):
        return {"title": title, "mode": mode, "minutes": minutes, "minutes_range": duration, "distance_km": km,
                "pace_range_s_per_km": [600, 660] if mode != "manual" else None,
                "speed_range_kmh": [5.5, 6] if mode != "manual" else None, "hr_range_bpm": None, "detail": "Synthetic instruction"}
    def session(sid, kind, steps, day=None):
        return {"id": sid, "title": "Synthetic " + sid, "kind": kind, "date": day, "summary": "Synthetic session",
                "pace_range_s_per_km": [600, 660], "speed_range_kmh": [5.5, 6], "hr_range_bpm": None,
                "steps": steps, "notes": []}
    return {"id": "synthetic-plan", "title": "Synthetic test block", "start_date": "2030-04-08", "race_date": "2030-04-14",
            "source": "Synthetic test fixture", "notes": [], "max_hr": None, "hr_guide": [],
            "goal": {"pace_range_s_per_km": None, "speed_range_kmh": None, "notes": []},
            "weeks": [{"id": "first", "title": "Test week", "start": "2030-04-08", "end": "2030-04-14", "sessions": [
                session("mixed", "interval_run", [step("Distance", "distance", km=1.2), step("Full recovery", "manual"), step("Range", "manual", duration=[4, 6])]),
                session("recovery", "recovery_run", [step("Easy", "timed", minutes=12)]),
                session("shakeout", "recovery_run", [step("Shakeout", "timed", minutes=12)], "2030-04-13"),
                session("race", "race", [], "2030-04-14")]}]}


class ImportedPlanTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.conn = store.connect_db(Path(self.folder.name) / "test.db")
        self.addCleanup(self.conn.close)
        self.today = "2030-04-09"
        self.plan = sample_plan()
        self.action("install", plan=self.plan)

    def action(self, action, **values):
        imported_plan.update(self.conn, dict(action=action, **values), self.today)

    def ready(self):
        training.save_checkin(self.conn, {"date": self.today, "fatigue": 0, "soreness": 0, "pain": False, "illness": False}, self.today)
        store.upsert_day(self.conn, {"date": self.today, "training_readiness": 80, "readiness_updated_at": self.today + "T08:00:00", "sleep_seconds": 28800, "hrv_status": "BALANCED"})

    def response(self):
        return training.dashboard(self.conn, self.today, now_local=datetime.fromisoformat(self.today + "T10:00:00"))

    def test_distance_and_unknown_recovery_never_become_fabricated_timers(self):
        self.ready()
        self.action("select", session_id="mixed", date=self.today)
        result = self.response()
        self.assertIsNone(result["profile"])
        r = result["recommendation"]
        self.assertEqual(r["status"], "suggestion")
        self.assertEqual(r["steps"][0]["distance_km"], 1.2)
        self.assertIsNone(r["steps"][0]["minutes"])
        self.assertIsNone(r["steps"][1]["minutes"])
        self.assertEqual(r["steps"][2]["minutes_range"], [4, 6])
        self.assertIsNone(r["minutes"])
        self.assertIsNone(r["distance_km"])
        self.assertEqual(r["pace_range_s_per_km"], [600, 660])

    def test_week_boundaries_and_date_collisions_preserve_schedule(self):
        self.action("schedule", session_id="mixed", date=self.today)
        saved = training.document(self.conn, imported_plan.KIND)
        with self.assertRaises(ValueError):
            self.action("schedule", session_id="recovery", date=self.today)
        with self.assertRaises(ValueError):
            self.action("schedule", session_id="mixed", date="2030-04-15")
        self.assertEqual(training.document(self.conn, imported_plan.KIND), saved)
        self.today = "2030-04-07"
        with self.assertRaises(ValueError):
            self.action("select", session_id="mixed", date=self.today)
        self.assertEqual(self.response()["recommendation"]["status"], "plan")

    def test_completion_is_explicit_and_does_not_manufacture_native_mileage(self):
        store.upsert_activity(self.conn, {"activity_id": "actual", "type": "running", "start_local": self.today + " 08:00:00", "duration_s": 900, "distance_m": 1200})
        self.action("complete", session_id="mixed", activity_id="actual")
        result = self.response()
        self.assertEqual(result["running"]["week"]["distance_km"], 1.2)
        self.assertEqual(len(result["activities"]), 1)
        self.assertEqual(result["imported_plan"]["completed"]["mixed"]["activity_id"], "actual")
        with self.assertRaises(ValueError):
            self.action("complete", session_id="recovery", activity_id="actual")
        self.action("reopen", session_id="mixed")
        self.assertNotIn("mixed", self.response()["imported_plan"]["completed"])
        self.assertEqual(self.response()["running"]["week"]["distance_km"], 1.2)

    def test_identical_import_preserves_dates_and_owner_confirmed_progress(self):
        self.action("schedule", session_id="mixed", date=self.today)
        self.action("complete", session_id="mixed", activity_id=None)
        before = training.document(self.conn, imported_plan.KIND)
        self.action("install", plan=deepcopy(self.plan))
        self.assertEqual(training.document(self.conn, imported_plan.KIND), before)
        changed = deepcopy(self.plan)
        changed["weeks"][0]["sessions"][0]["steps"][0]["distance_km"] = 9
        with self.assertRaises(ValueError):
            self.action("install", plan=changed)
        self.assertEqual(training.document(self.conn, imported_plan.KIND), before)
        self.assertEqual(self.response()["running"]["week"]["distance_km"], 0)

    def test_symptoms_block_guide_but_preserve_original_prescription(self):
        self.ready()
        self.action("select", session_id="mixed", date=self.today)
        original = deepcopy(self.plan["weeks"][0]["sessions"][0])
        checkin = training.document(self.conn, "checkin")
        training.save_checkin(self.conn, dict(checkin, pain=True), self.today)
        result = self.response()["recommendation"]
        self.assertEqual((result["status"], result["steps"]), ("rest", []))
        self.assertEqual(result["planned_session"], original)
        training.save_checkin(self.conn, dict(checkin, soreness=5), self.today)
        result = self.response()["recommendation"]
        self.assertEqual(result["kind"], "recovery_run")
        self.assertEqual(result["planned_session"], original)
        self.assertEqual(training.document(self.conn, imported_plan.KIND)["plan"], self.plan)
        self.assertEqual(training.document(self.conn, imported_plan.KIND)["completed"], {})

    def test_imported_shakeout_is_not_replaced_by_generic_pre_race_rest(self):
        self.today = "2030-04-13"
        self.ready()
        result = self.response()["recommendation"]
        self.assertEqual(result["status"], "suggestion")
        self.assertEqual(result["plan_session_id"], "shakeout")
        self.assertEqual(result["minutes"], 12)

    def test_prior_week_quality_does_not_apply_generic_single_quality_quota(self):
        self.today = "2030-04-12"
        self.ready()
        store.upsert_activity(self.conn, {"activity_id": "earlier", "type": "running", "start_local": "2030-04-08 08:00:00", "duration_s": 900, "distance_m": 1200, "effect_label": "TEMPO"})
        self.action("select", session_id="mixed", date=self.today)
        self.assertEqual(self.response()["recommendation"]["kind"], "interval_run")
        self.assertIsNone(self.response()["running"]["week"]["target_km"])

    def test_stale_readiness_and_completed_sessions_cannot_start_again(self):
        self.ready()
        self.action("select", session_id="mixed", date=self.today)
        store.upsert_day(self.conn, {"date": self.today, "readiness_updated_at": "2030-04-08T22:00:00"})
        self.assertEqual(self.response()["recommendation"]["status"], "caution")
        self.action("complete", session_id="mixed", activity_id=None)
        self.assertEqual(self.response()["recommendation"]["status"], "rest")
        with self.assertRaises(ValueError):
            self.action("select", session_id="mixed", date=self.today)

    def test_future_completion_and_nonfinite_plan_targets_are_rejected(self):
        with self.assertRaises(ValueError):
            self.action("complete", session_id="shakeout", activity_id=None)
        bad = deepcopy(self.plan)
        bad["weeks"][0]["sessions"][0]["pace_range_s_per_km"] = [600, float("nan")]
        with self.assertRaises(ValueError):
            imported_plan.validate(bad)
        self.assertEqual(training.document(self.conn, imported_plan.KIND)["plan"], self.plan)
        with self.assertRaises(ValueError):
            self.action([])

    def test_active_cloud_sync_cannot_be_overwritten_by_plan_progress(self):
        state = {"schema": 1, "database": cloud_state.database_backup(self.conn), "tokens": {}, "lease": {"until": time.time() + 60}}
        with patch.object(cloud_state, "load_state", return_value=(state, '"v1"')):
            with self.assertRaises(cloud_state.StateConflict):
                cloud_state.update_training("plan", {"action": "complete", "session_id": "mixed", "activity_id": None}, self.today)
        self.assertEqual(training.document(self.conn, imported_plan.KIND)["completed"], {})


if __name__ == "__main__":
    unittest.main()
