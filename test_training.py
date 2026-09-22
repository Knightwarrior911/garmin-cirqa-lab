"""Protect missing-data semantics, user ownership and conservative planning decisions."""

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cloud_state
import store
import sync
import training


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.conn = store.connect_db(Path(self.folder.name) / "history.db")
        self.addCleanup(self.conn.close)
        self.today = "2026-09-22"
        self.profile = {"goal": "endurance", "sport": "running", "weekdays": [1, 3, 5], "minutes": 40, "experience": "regular", "equipment": "none", "routine": []}
        self.checkin = {"date": self.today, "fatigue": 1, "soreness": 1, "pain": False, "illness": False}

    def ready(self):
        training.save_profile(self.conn, self.profile)
        training.save_checkin(self.conn, self.checkin, self.today)
        store.upsert_day(self.conn, {"date": self.today, "training_readiness": 80, "readiness_updated_at": self.today + "T08:00:00", "sleep_seconds": 8 * 3600})

    def decision(self):
        return training.dashboard(self.conn, self.today, now_local=datetime(2026, 9, 22, 10))["recommendation"]

    def test_zero_load_and_zero_effort_are_not_missing(self):
        store.upsert_activity(self.conn, {"activity_id": "1", "start_local": self.today + " 09:00:00", "duration_s": 1800, "training_load": 0})
        store.upsert_activity(self.conn, {"activity_id": "2", "start_local": self.today + " 10:00:00", "duration_s": 1800})
        training.save_feedback(self.conn, {"activity_id": "1", "rpe": 0, "soreness": 0, "notes": ""})
        result = training.dashboard(self.conn, self.today)
        self.assertEqual(result["load"]["today"], {"load": 0, "known": 1, "total": 2, "rpe_load": 0, "rated": 1})
        self.assertIsNone(result["load"]["daily"][0]["load"])

    def test_feedback_survives_sync_updates_and_can_be_cleared(self):
        store.upsert_activity(self.conn, {"activity_id": "1", "duration_s": 1200, "training_load": 10})
        payload = {"activity_id": "1", "rpe": 6, "soreness": 2, "notes": "whole session"}
        training.save_feedback(self.conn, payload)
        store.upsert_activity(self.conn, {"activity_id": "1", "duration_s": 1800})
        activity = training.dashboard(self.conn, self.today)["activities"][0]
        self.assertEqual(activity["training_load"], 10)
        self.assertEqual(activity["rpe_load"], 180)
        training.save_feedback(self.conn, dict(payload, rpe=None, soreness=None, notes=""))
        self.assertIsNone(training.dashboard(self.conn, self.today)["activities"][0]["rpe_load"])

    def test_period_comparison_excludes_today_and_requires_coverage(self):
        today = date.fromisoformat(self.today)
        for offset in range(1, 15):
            store.upsert_day(self.conn, {"date": (today - timedelta(days=offset)).isoformat(), "sleep_seconds": (7 if offset <= 7 else 8) * 3600})
        store.upsert_day(self.conn, {"date": self.today, "sleep_seconds": 100 * 3600})
        metric = next(c for c in training.dashboard(self.conn, self.today)["comparisons"] if c["key"] == "sleep_seconds")
        self.assertEqual((metric["current"], metric["previous"], metric["change"]), (7, 8, -1))
        self.conn.execute("DELETE FROM days WHERE date < ?", ((today - timedelta(days=9)).isoformat(),))
        self.conn.commit()
        metric = next(c for c in training.dashboard(self.conn, self.today)["comparisons"] if c["key"] == "sleep_seconds")
        self.assertIsNone(metric["change"])

    def test_pain_rest_days_and_stale_readiness_override_suggestion(self):
        self.ready()
        self.assertEqual(self.decision()["status"], "suggestion")
        training.save_checkin(self.conn, dict(self.checkin, pain=True), self.today)
        self.assertEqual(self.decision()["status"], "rest")
        training.save_checkin(self.conn, self.checkin, self.today)
        training.save_profile(self.conn, dict(self.profile, weekdays=[0]))
        self.assertEqual(self.decision()["status"], "rest")
        training.save_profile(self.conn, self.profile)
        store.upsert_day(self.conn, {"date": self.today, "readiness_updated_at": "2026-09-21T23:59:00"})
        self.assertEqual(self.decision()["status"], "caution")
        self.assertEqual(self.decision()["steps"], [])

    def test_recent_same_sport_duration_caps_plan_and_today_prevents_second_session(self):
        self.ready()
        for aid, minutes in (("1", 24), ("2", 30)):
            store.upsert_activity(self.conn, {"activity_id": aid, "type": "running", "start_local": "2026-09-20 10:00:00", "duration_s": minutes * 60})
        store.upsert_activity(self.conn, {"activity_id": "3", "type": "cycling", "start_local": "2026-09-20 10:00:00", "duration_s": 120 * 60})
        self.assertEqual(sum(s["minutes"] for s in self.decision()["steps"]), 27)
        store.upsert_activity(self.conn, {"activity_id": "4", "type": "running", "start_local": self.today + " 10:00:00", "duration_s": 1200})
        self.assertEqual(self.decision()["status"], "rest")
        self.assertEqual(self.decision()["steps"], [])

    def test_invalid_feedback_and_impossible_equipment_do_not_replace_saved_input(self):
        training.save_profile(self.conn, self.profile)
        with self.assertRaises(ValueError):
            training.save_profile(self.conn, dict(self.profile, sport="cycling", equipment="none"))
        self.assertEqual(training.document(self.conn, "profile")["sport"], "running")
        with self.assertRaises(ValueError):
            training.save_feedback(self.conn, {"activity_id": "missing", "rpe": 4, "soreness": 2, "notes": ""})
        store.upsert_activity(self.conn, {"activity_id": "1"})
        with self.assertRaises(ValueError):
            training.save_feedback(self.conn, {"activity_id": "1", "rpe": float("nan"), "soreness": 2, "notes": ""})
        with self.assertRaises(ValueError):
            training.save_checkin(self.conn, dict(self.checkin, date="2026-09-21"), self.today)
        self.assertIsNone(training.document(self.conn, "checkin"))

    def test_same_day_old_readiness_and_unspecified_strength_load_are_not_prescriptions(self):
        self.ready()
        stale = training.dashboard(self.conn, self.today, now_local=datetime(2026, 9, 22, 21))["recommendation"]
        self.assertEqual(stale["status"], "caution")
        self.assertEqual(stale["steps"], [])
        strength = dict(self.profile, goal="strength", sport="strength", equipment="gym", routine=[])
        with self.assertRaises(ValueError):
            training.save_profile(self.conn, strength)
        strength["routine"] = [{"name": "Established squat", "sets": 2, "reps": 8, "load_kg": 20}]
        training.save_profile(self.conn, strength)
        self.assertEqual(self.decision()["status"], "suggestion")
        training.save_checkin(self.conn, dict(self.checkin, soreness=4), self.today)
        self.assertEqual(self.decision()["status"], "caution")
        self.assertEqual(self.decision()["steps"], [])

    def seed_running_base(self):
        for index, offset in enumerate((4, 7, 10, 13, 16, 19)):
            day = (date.fromisoformat(self.today) - timedelta(days=offset)).isoformat()
            store.upsert_activity(self.conn, {"activity_id": f"run-{index}", "type": "running", "start_local": day + " 08:00:00", "duration_s": 2100, "distance_m": 5000})

    def test_hyrox_quality_run_requires_established_base_and_respects_race_week(self):
        self.profile = dict(self.profile, goal="hyrox", equipment="gym", strength_days=[4], race_date=None)
        self.ready()
        self.assertEqual(self.decision()["kind"], "easy_run")
        self.seed_running_base()
        session = self.decision()
        self.assertEqual(session["kind"], "controlled_run")
        self.assertEqual(sum(step["minutes"] for step in session["steps"]), 30)
        training.save_profile(self.conn, dict(self.profile, race_date="2026-09-25"))
        self.assertEqual(self.decision()["kind"], "easy_run")

    def test_recent_lifting_downgrades_quality_and_gym_day_obeys_checkin(self):
        self.profile = dict(self.profile, goal="hyrox", equipment="gym", strength_days=[4])
        self.ready()
        self.seed_running_base()
        self.assertEqual(self.decision()["kind"], "controlled_run")
        store.upsert_activity(self.conn, {"activity_id": "gym", "type": "strength_training", "start_local": "2026-09-21 18:00:00", "duration_s": 1800})
        self.assertEqual(self.decision()["kind"], "easy_run")
        training.save_profile(self.conn, dict(self.profile, weekdays=[3, 5], strength_days=[1]))
        session = self.decision()
        self.assertEqual(session["kind"], "strength")
        self.assertEqual(sum(step["minutes"] for step in session["steps"]), 40)
        training.save_checkin(self.conn, dict(self.checkin, soreness=4), self.today)
        self.assertEqual(self.decision()["status"], "caution")
        self.assertEqual(self.decision()["steps"], [])

    def test_pace_uses_actual_distance_and_week_keeps_gym_separate(self):
        self.profile = dict(self.profile, goal="hyrox", equipment="gym", strength_days=[4])
        self.ready()
        self.seed_running_base()
        store.upsert_activity(self.conn, {"activity_id": "zero-distance", "type": "running", "start_local": "2026-09-21 08:00:00", "duration_s": 500, "distance_m": 0})
        context = training.dashboard(self.conn, self.today)["running"]
        self.assertEqual(context["last_run"]["pace_s_per_km"], 420)
        self.assertEqual(context["distance_28d_m"], 30000)
        by_date = {day["date"]: day for day in context["weekly_plan"]}
        self.assertEqual(by_date["2026-09-25"]["kind"], "strength")
        self.assertEqual(by_date["2026-09-23"]["kind"], "rest")
        with self.assertRaises(ValueError):
            training.save_profile(self.conn, dict(self.profile, strength_days=[1]))
        self.assertEqual(training.document(self.conn, "profile")["strength_days"], [4])

    def test_native_calendar_failure_retains_previous_schedule(self):
        previous = {"checked_at": "2000-01-01", "last_success_at": "2000-01-01", "workouts": [{"id": "1", "date": self.today, "name": "Saved workout"}]}
        training.save_document(self.conn, "native_workouts", previous)
        class Unavailable:
            def get_scheduled_workouts(self, *args):
                raise RuntimeError("remote unavailable")
        sync.sync_native_workouts(Unavailable(), self.conn)
        result = training.document(self.conn, "native_workouts")
        self.assertEqual(result["workouts"], previous["workouts"])
        self.assertEqual(result["last_success_at"], previous["last_success_at"])
        self.assertIsNotNone(result["error"])

    def test_running_cloud_job_rejects_owner_update(self):
        state = {"schema": 1, "database": cloud_state.database_backup(self.conn), "tokens": {}, "lease": {"until": time.time() + 30}}
        with patch.object(cloud_state, "load_state", return_value=(state, '"version1"')):
            with self.assertRaises(cloud_state.StateConflict):
                cloud_state.update_training("profile", self.profile, self.today)
        self.assertIsNone(training.document(self.conn, "profile"))


if __name__ == "__main__":
    unittest.main()
