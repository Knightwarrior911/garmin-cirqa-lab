"""Protect native units, absent streams and previously cached detail."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import activity_detail as detail
import store


class ActivityDetailIntegrity(unittest.TestCase):
    base = {"activity_id": "123", "type": "walking", "source": "garmin"}

    def recording(self, rows):
        return {
            "summary": {
                "summaryDTO": {
                    "startTimeGMT": "2026-09-18T10:00:00.000",
                    "averageSpeed": 2,
                }
            },
            "details": {
                "metricDescriptors": [
                    {
                        "key": key,
                        "metricsIndex": i,
                        "unit": {"key": unit},
                        "factor": 1000,
                    }
                    for i, (key, unit) in enumerate(
                        [
                            ("sumElapsedDuration", "second"),
                            ("sumDistance", "meter"),
                            ("directHeartRate", "bpm"),
                            ("directSpeed", "mps"),
                            ("directDoubleCadence", "stepsPerMinute"),
                        ]
                    )
                ],
                "activityDetailMetrics": [{"metrics": row} for row in rows],
            },
        }

    def test_units_are_not_multiplied_and_stopped_pace_is_missing(self):
        result = detail.normalize(
            self.recording([[0, 0, 100, 2, 120], [10, 20, 0, 0, None]]), self.base
        )
        streams = {s["key"]: s["values"] for s in result["streams"]}
        self.assertEqual(streams["speed"], [500, None])
        self.assertEqual(streams["cadence"], [120, None])
        self.assertEqual(streams["hr"], [100, None])
        self.assertEqual(result["axis"][-1], {"time_s": 10, "distance_m": 20})

    def test_summary_speed_does_not_fabricate_a_chart(self):
        result = detail.normalize(
            self.recording([[0, 0, 100], [10, 0, None]]), self.base
        )
        self.assertFalse(result["supports_distance"])
        self.assertNotIn("speed", [s["key"] for s in result["streams"]])
        self.assertEqual(
            next(s["value"] for s in result["stats"] if s["key"] == "averageSpeed"), 500
        )

    def test_invalid_values_stay_missing_and_single_lap_is_not_an_interval(self):
        raw = self.recording(
            [[0, 0, float("nan"), None, None], [10, 5, float("inf"), -1, None]]
        )
        raw["splits"] = {"lapDTOs": [{"lapIndex": 1, "duration": 10, "distance": 5}]}
        result = detail.normalize(raw, self.base)
        self.assertEqual(result["intervals"], [])
        self.assertEqual(result["streams"], [])
        json.dumps(result, allow_nan=False)

    def test_failed_optional_fetch_preserves_cached_zones_but_fresh_empty_clears_them(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(store, "DB_PATH", Path(directory) / "test.db"),
        ):
            conn = store.connect_db()
            conn.execute(
                "INSERT INTO activities(activity_id,type,source) VALUES('123','walking','garmin')"
            )
            conn.commit()
            payload = detail.normalize(self.recording([[0, 0, 100, 2, 120]]), self.base)
            payload["zones"] = [
                {
                    "zone": 1,
                    "seconds": 20,
                    "low_bpm": 90,
                    "high_bpm": None,
                    "percent": 100,
                }
            ]
            detail.save_payload(conn, "123", payload)
            conn.close()

            class Garmin:
                def get_activity(self, aid):
                    return {"summaryDTO": {"duration": 20}}

                def get_activity_details(self, aid, **kwargs):
                    return {}

                def get_activity_splits(self, aid):
                    return {}

                def get_activity_typed_splits(self, aid):
                    return {}

                def get_activity_hr_in_timezones(self, aid):
                    raise OSError("endpoint unavailable")

            with patch("garmin_client.connect", return_value=Garmin()):
                detail.download("123")
            conn = store.connect_db()
            cached = detail.get_detail(conn, "123")["detail"]
            conn.close()
            self.assertEqual(cached["zones"], payload["zones"])
            self.assertIn("zones", cached["stale_sections"])
            with (
                patch("garmin_client.connect", return_value=Garmin()),
                patch.object(Garmin, "get_activity_hr_in_timezones", return_value=[]),
            ):
                detail.download("123")
            conn = store.connect_db()
            self.assertEqual(detail.get_detail(conn, "123")["detail"]["zones"], [])
            conn.close()


if __name__ == "__main__":
    unittest.main()
