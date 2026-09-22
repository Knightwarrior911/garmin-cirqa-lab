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


if __name__ == "__main__":
    unittest.main()
