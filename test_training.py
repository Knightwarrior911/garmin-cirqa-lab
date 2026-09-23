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
        self.profile = {"race_date": "2026-10-25", "weekdays": [1, 3, 5], "minutes": 40, "experience": "regular", "surface": "treadmill", "easy_pace_s_per_km": 420, "tempo_pace_s_per_km": 360, "weekly_km": 15}
        self.checkin = {"date": self.today, "fatigue": 1, "soreness": 1, "pain": False, "illness": False}

    def ready(self):
        training.save_profile(self.conn, self.profile)
        training.save_checkin(self.conn, self.checkin, self.today)
        store.upsert_day(self.conn, {"date": self.today, "training_readiness": 80, "readiness_updated_at": self.today + "T08:00:00", "sleep_seconds": 8 * 3600})

    def decision(self):
        return training.dashboard(self.conn, self.today, now_local=datetime.fromisoformat(self.today + "T10:00:00"))["recommendation"]

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

    def test_walking_does_not_cancel_run_but_recorded_run_prevents_second_session(self):
        self.ready()
        store.upsert_activity(self.conn, {"activity_id": "walk", "type": "walking", "start_local": self.today + " 09:00:00", "duration_s": 1800, "distance_m": 2000})
        session = self.decision()
        self.assertEqual(session["status"], "suggestion")
        self.assertLessEqual(session["minutes"], self.profile["minutes"])
        store.upsert_activity(self.conn, {"activity_id": "run", "type": "running", "start_local": self.today + " 10:00:00", "duration_s": 1200, "distance_m": 3000})
        self.assertEqual(self.decision()["status"], "rest")
        self.assertEqual(self.decision()["steps"], [])
        week = training.dashboard(self.conn, self.today)["running"]["week"]
        self.assertEqual((week["runs"], week["distance_km"]), (1, 3))

    def test_invalid_paces_and_feedback_preserve_saved_input(self):
        training.save_profile(self.conn, self.profile)
        with self.assertRaises(ValueError):
            training.save_profile(self.conn, dict(self.profile, tempo_pace_s_per_km=500))
        with self.assertRaises(ValueError):
            training.save_profile(self.conn, dict(self.profile, easy_pace_s_per_km=float("nan")))
        self.assertEqual(training.document(self.conn, "profile"), self.profile)
        with self.assertRaises(ValueError):
            training.save_feedback(self.conn, {"activity_id": "missing", "rpe": 4, "soreness": 2, "notes": ""})
        store.upsert_activity(self.conn, {"activity_id": "1"})
        with self.assertRaises(ValueError):
            training.save_feedback(self.conn, {"activity_id": "1", "rpe": float("nan"), "soreness": 2, "notes": ""})
        with self.assertRaises(ValueError):
            training.save_checkin(self.conn, dict(self.checkin, date="2026-09-21"), self.today)
        self.assertIsNone(training.document(self.conn, "checkin"))

    def test_stale_and_future_readiness_do_not_allow_a_run(self):
        self.ready()
        result = training.dashboard(self.conn, self.today, now_local=datetime(2026, 9, 22, 21))["recommendation"]
        self.assertEqual((result["status"], result["steps"]), ("caution", []))
        store.upsert_day(self.conn, {"date": self.today, "readiness_updated_at": self.today + "T11:00:00"})
        self.assertEqual(self.decision()["status"], "caution")

    def seed_running_base(self):
        for index, offset in enumerate((4, 7, 10, 13, 16, 19)):
            day = (date.fromisoformat(self.today) - timedelta(days=offset)).isoformat()
            store.upsert_activity(self.conn, {"activity_id": f"run-{index}", "type": "running", "start_local": day + " 08:00:00", "duration_s": 2100, "distance_m": 5000})

    def test_unclassified_average_pace_is_not_an_easy_or_tempo_benchmark(self):
        self.profile = dict(self.profile, easy_pace_s_per_km=None, tempo_pace_s_per_km=None, weekly_km=None)
        self.ready()
        self.seed_running_base()
        result = training.dashboard(self.conn, self.today)
        self.assertEqual(result["running"]["last_run"]["pace_s_per_km"], 420)
        self.assertIsNone(result["running"]["baseline"]["easy_pace_s_per_km"])
        self.assertIsNone(self.decision()["distance_km"])
        for aid in ("run-0", "run-1"):
            training.save_feedback(self.conn, {"activity_id": aid, "rpe": 3, "soreness": None, "notes": ""})
        baseline = training.dashboard(self.conn, self.today)["running"]["baseline"]
        self.assertEqual(baseline["easy_pace_s_per_km"], 420)
        self.assertIsNone(baseline["tempo_pace_s_per_km"])

    def test_tempo_targets_convert_to_treadmill_speed_and_account_for_all_steps(self):
        self.ready()
        result = self.decision()
        self.assertEqual(result["kind"], "tempo_run")
        self.assertEqual((result["pace_s_per_km"], result["speed_kmh"]), (360, 10))
        self.assertEqual(sum(s["minutes"] for s in result["steps"]), result["minutes"])
        self.assertAlmostEqual(sum(s["distance_km"] for s in result["steps"]), result["distance_km"], places=2)
        training.save_profile(self.conn, dict(self.profile, experience="beginner"))
        beginner = self.decision()
        self.assertEqual(beginner["kind"], "easy_run")
        self.assertLessEqual(beginner["minutes"], 20)

    def test_ladder_work_and_fatigue_reduce_running_instead_of_adding_strength(self):
        self.ready()
        self.assertEqual(self.decision()["kind"], "tempo_run")
        store.upsert_activity(self.conn, {"activity_id": "gym", "type": "strength_training", "start_local": "2026-09-21 18:00:00", "duration_s": 1800})
        self.assertEqual(self.decision()["kind"], "easy_run")
        training.save_checkin(self.conn, dict(self.checkin, soreness=4), self.today)
        self.assertEqual(self.decision()["kind"], "recovery_run")
        training.save_profile(self.conn, dict(self.profile, weekdays=[3, 5]))
        self.assertEqual(self.decision()["status"], "rest")

    def test_quality_already_this_week_is_not_repeated_after_two_day_window(self):
        self.today = "2026-09-24"
        self.profile = dict(self.profile, weekdays=[0, 1, 3, 5])
        self.checkin = dict(self.checkin, date=self.today)
        self.ready()
        self.assertEqual(self.decision()["kind"], "tempo_run")
        store.upsert_activity(self.conn, {"activity_id": "quality", "type": "running", "start_local": "2026-09-21 08:00:00", "duration_s": 1800, "distance_m": 5000, "effect_label": "TEMPO"})
        self.assertEqual(self.decision()["kind"], "easy_run")
        self.assertEqual(training.dashboard(self.conn, self.today)["running"]["week"]["quality_runs"], 1)

    def test_faster_work_cannot_overspend_remaining_weekly_distance(self):
        self.today = "2026-09-24"
        self.profile = dict(self.profile, weekdays=[0, 1, 3, 5], weekly_km=16)
        self.checkin = dict(self.checkin, date=self.today)
        self.ready()
        self.assertEqual(self.decision()["kind"], "tempo_run")
        store.upsert_activity(self.conn, {"activity_id": "previous", "type": "running", "start_local": "2026-09-21 08:00:00", "duration_s": 5000, "distance_m": 12400})
        session = self.decision()
        self.assertEqual(session["kind"], "easy_run")
        self.assertLessEqual(session["distance_km"], 3.6)
        store.upsert_activity(self.conn, {"activity_id": "previous", "distance_m": 16000})
        self.assertEqual(self.decision()["status"], "rest")

    def test_zero_treadmill_distance_is_missing_not_zero_weekly_exposure(self):
        self.ready()
        store.upsert_activity(self.conn, {"activity_id": "treadmill", "type": "treadmill_running", "start_local": "2026-09-21 08:00:00", "duration_s": 500, "distance_m": 0})
        result = training.dashboard(self.conn, self.today)["running"]
        self.assertEqual(result["week"]["runs"], 1)
        self.assertIsNone(result["week"]["distance_km"])
        self.assertIsNone(result["week"]["remaining_km"])
        self.assertIsNone(result["recent_runs"][0]["pace_s_per_km"])
        self.assertEqual(self.decision()["kind"], "easy_run")

    def test_race_week_tapers_then_prevents_pre_race_and_post_race_training(self):
        self.ready()
        training.save_profile(self.conn, dict(self.profile, race_date="2026-09-25"))
        taper = self.decision()
        self.assertEqual(taper["kind"], "easy_run")
        self.assertLessEqual(taper["minutes"], 15)
        training.save_checkin(self.conn, dict(self.checkin, soreness=4), self.today)
        self.assertEqual(self.decision()["kind"], "recovery_run")
        training.save_profile(self.conn, dict(self.profile, race_date="2026-09-23"))
        self.assertEqual(self.decision()["status"], "rest")
        training.save_profile(self.conn, dict(self.profile, race_date=self.today))
        self.assertEqual((self.decision()["status"], self.decision()["kind"]), ("rest", "race"))
        training.save_profile(self.conn, dict(self.profile, race_date="2026-09-21"))
        self.assertEqual(self.decision()["status"], "setup")
        self.assertEqual(training.dashboard(self.conn, self.today)["running"]["week"]["target_km"], 0)

    def test_legacy_running_setup_migrates_without_inventing_pace_or_losing_history(self):
        training.save_document(self.conn, "profile", {"goal": "hyrox", "sport": "running", "weekdays": [1,3,5], "minutes": 40, "experience": "regular", "equipment": "gym", "routine": [], "strength_days": [4], "race_date": "2026-10-25"})
        store.upsert_activity(self.conn, {"activity_id": "owned", "duration_s": 1800})
        training.save_feedback(self.conn, {"activity_id": "owned", "rpe": 4, "soreness": 1, "notes": "keep this"})
        store.upsert_day(self.conn, {"date": self.today, "sleep_seconds": 27000})
        self.conn.close()
        self.conn = store.connect_db(Path(self.folder.name) / "history.db")
        self.addCleanup(self.conn.close)
        result = training.dashboard(self.conn, self.today)
        self.assertEqual(result["profile"]["weekdays"], [1,3,5])
        self.assertNotIn("strength_days", result["profile"])
        self.assertIsNone(result["profile"]["easy_pace_s_per_km"])
        self.assertIsNone(result["profile"]["weekly_km"])
        self.assertEqual(result["activities"][0]["feedback"]["notes"], "keep this")
        self.assertEqual(result["recovery"]["sleep_hours"], 7.5)

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
