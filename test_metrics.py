"""Regression checks for unavailable readings and preserving data on endpoint failure."""

import sqlite3
import unittest

import store
import sync


class EmptyGarmin:
    def get_body_battery(self, d):
        return [
            {
                "date": d,
                "bodyBatteryValuesArray": None,
                "bodyBatteryValueDescriptorDTOList": None,
            }
        ]

    def __getattr__(self, name):
        return lambda d: {}


class MetricIntegrity(unittest.TestCase):
    def test_null_battery_arrays_are_unavailable_not_zero(self):
        values, failures = sync.fetch_day(EmptyGarmin(), "2026-09-18")
        self.assertIsNone(values["body_battery_current"])
        self.assertEqual(failures, [])

    def test_failed_endpoint_preserves_previous_reading_but_returned_null_clears_it(
        self,
    ):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(store.SCHEMA)
        try:
            store.upsert_day(
                db, {"date": "2026-09-18", "steps": 123, "sleep_score": 81}
            )
            store.upsert_day(db, {"date": "2026-09-18", "steps": 0})
            self.assertEqual(store.get_day(db, "2026-09-18")["sleep_score"], 81)
            self.assertEqual(store.get_day(db, "2026-09-18")["steps"], 0)
            store.upsert_day(db, {"date": "2026-09-18", "sleep_score": None})
            self.assertIsNone(store.get_day(db, "2026-09-18")["sleep_score"])
        finally:
            db.close()

    def test_negative_sentinel_is_not_a_stress_measurement(self):
        g = EmptyGarmin()
        g.get_stats = lambda d: {
            "averageStressLevel": -1,
            "activeKilocalories": 0,
            "totalKilocalories": 800,
        }
        v, _ = sync.fetch_day(g, "2026-09-18")
        self.assertIsNone(v["stress_avg"])
        self.assertEqual(v["active_calories"], 0)
        self.assertEqual(v["total_calories"], 800)

    def test_native_timeline_gaps_zero_and_descriptor_order(self):
        g = EmptyGarmin()
        g.get_body_battery = lambda d: [{
            "date": d, "charged": 0, "drained": 8,
            "bodyBatteryValueDescriptorDTOList": [
                {"bodyBatteryValueDescriptorKey": "timestamp", "bodyBatteryValueDescriptorIndex": 1},
                {"bodyBatteryValueDescriptorKey": "bodyBatteryLevel", "bodyBatteryValueDescriptorIndex": 0},
            ],
            "bodyBatteryValuesArray": [[50, 1790015400000], [-1, 1790015520000], [0, 1790015640000]]
        }]
        values, failures = sync.fetch_day(g, "2026-09-22")
        self.assertEqual(failures, [])
        timeline = values["watch"]["body_battery"]
        self.assertEqual([p["value"] for p in timeline["points"]], [50, None, 0])
        self.assertEqual(timeline["charged"], 0)
        self.assertEqual(values["body_battery_current"], 0)

    def test_failed_native_group_preserves_history_but_empty_clears(self):
        db = store.connect_db(":memory:")
        try:
            store.upsert_day(db, {"date": "2026-09-22", "watch": {
                "body_battery": {"points": [{"time": "2026-09-22T00:00:00+00:00", "value": 42}]},
                "readiness_factors": [{"key": "sleepScoreFactor", "value": 80}]
            }})
            g = EmptyGarmin()
            def failed(d):
                raise ConnectionError("offline")
            g.get_body_battery = failed
            values, _ = sync.fetch_day(g, "2026-09-22")
            store.upsert_day(db, values)
            actual = store.day_to_dict(store.get_day(db, "2026-09-22"), detail=True)["watch"]
            self.assertEqual(actual["body_battery"]["points"][0]["value"], 42)
            self.assertEqual(actual["readiness_factors"], [])
            g.get_body_battery = lambda d: []
            values, _ = sync.fetch_day(g, "2026-09-22")
            store.upsert_day(db, values)
            self.assertEqual(store.day_to_dict(store.get_day(db, "2026-09-22"), detail=True)["watch"]["body_battery"]["points"], [])
        finally:
            db.close()

    def test_sleep_intervals_keep_utc_and_signed_temperature(self):
        result = sync.sleep_watch({
            "avgSkinTempDeviationC": -0.2,
            "sleepLevels": [
                {"startGMT": "2026-09-21T22:00:00.0", "endGMT": "2026-09-21T22:15:00.0", "activityLevel": 0},
                {"startGMT": "bad", "endGMT": "bad", "activityLevel": 1},
            ]
        })
        self.assertEqual(result["sleep"]["points"], [{
            "start": "2026-09-21T22:00:00+00:00", "end": "2026-09-21T22:15:00+00:00", "stage": "Deep"
        }])
        self.assertEqual(result["sleep_metrics"][0]["value"], -0.2)

    def test_dense_timeline_uses_level_column_and_preserves_measurement_gaps(self):
        g = EmptyGarmin()
        g.get_stress_data = lambda d: {
            "stressValuesArray": [[1000, -1], [2000, 0]],
            "bodyBatteryValuesArray": [[1000, "MEASURED", 42, 3]],
            "bodyBatteryValueDescriptorsDTOList": [
                {"bodyBatteryValueDescriptorKey": "timestamp", "bodyBatteryValueDescriptorIndex": 0},
                {"bodyBatteryValueDescriptorKey": "bodyBatteryLevel", "bodyBatteryValueDescriptorIndex": 2},
            ],
        }
        g.get_heart_rates = lambda d: {"heartRateValues": [[1000, 0], [2000, 61]]}
        values, _ = sync.fetch_day(g, "2026-09-22")
        watch = values["watch"]
        self.assertEqual(watch["body_battery_timeline"]["points"][0]["value"], 42)
        self.assertEqual([p["value"] for p in watch["stress"]["points"]], [None, 0])
        self.assertEqual([p["value"] for p in watch["heart_rate"]["points"]], [None, 61])


if __name__ == "__main__":
    unittest.main()
