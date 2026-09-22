"""Collect Garmin Connect measurements. No locally invented recovery scores.

sync.py --days 30 --force backfills updated mappings. Normal sync refreshes two days.
"""

import argparse
import json
import math
import sys
from datetime import date, timedelta

import store


def number(value, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if (
        not math.isfinite(value)
        or value < 0
        or (maximum is not None and value > maximum)
    ):
        return None
    return value


def choose_record(payload, d, primary_key=None):
    records = payload if isinstance(payload, list) else [payload]
    records = [
        r for r in records if isinstance(r, dict) and r.get("calendarDate", d) == d
    ]
    if primary_key:
        primary = [r for r in records if r.get(primary_key) is True]
        if primary:
            records = primary
    return max(
        records,
        key=lambda r: str(r.get("timestampLocal") or r.get("timestamp") or ""),
        default={},
    )


def fetch_day(garmin, d):
    values = {"date": d}
    errors = []

    def call(name):
        try:
            return getattr(garmin, name)(d)
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}")
            return None

    stats = call("get_stats")
    if isinstance(stats, dict):
        for field, key in {
            "steps": "totalSteps",
            "steps_goal": "dailyStepGoal",
            "active_calories": "activeKilocalories",
            "total_calories": "totalKilocalories",
            "resting_hr": "restingHeartRate",
            "stress_avg": "averageStressLevel",
            "body_battery_high": "bodyBatteryHighestValue",
            "body_battery_low": "bodyBatteryLowestValue",
        }.items():
            values[field] = number(stats.get(key))
        values["calories"] = values["active_calories"]
        moderate, vigorous = (
            number(stats.get("moderateIntensityMinutes")),
            number(stats.get("vigorousIntensityMinutes")),
        )
        values["intensity_minutes"] = (
            moderate + 2 * vigorous
            if moderate is not None and vigorous is not None
            else None
        )
    hrv = call("get_hrv_data")
    if isinstance(hrv, dict):
        summary = hrv.get("hrvSummary") or {}
        baseline = summary.get("baseline") or {}
        for field, key in [
            ("hrv_last_night", "lastNightAvg"),
            ("hrv_weekly_avg", "weeklyAvg"),
        ]:
            values[field] = number(summary.get(key))
        values["hrv_baseline_low"] = number(baseline.get("balancedLow"))
        values["hrv_baseline_high"] = number(baseline.get("balancedUpper"))
        values["hrv_status"] = (
            summary.get("status")
            if summary.get("status") not in (None, "NONE", "UNKNOWN")
            else None
        )
    sleep = call("get_sleep_data")
    if isinstance(sleep, dict):
        dto = sleep.get("dailySleepDTO") or {}
        for field, key in [
            ("sleep_seconds", "sleepTimeSeconds"),
            ("sleep_deep_s", "deepSleepSeconds"),
            ("sleep_rem_s", "remSleepSeconds"),
            ("sleep_light_s", "lightSleepSeconds"),
            ("sleep_awake_s", "awakeSleepSeconds"),
        ]:
            values[field] = number(dto.get(key))
        values["sleep_score"] = number(
            ((dto.get("sleepScores") or {}).get("overall") or {}).get("value"), 100
        )
    battery = call("get_body_battery")
    if isinstance(battery, list):
        entry = next(
            (b for b in battery if isinstance(b, dict) and b.get("date") == d), {}
        )
        descriptors = {
            v.get("bodyBatteryValueDescriptorKey"): v.get(
                "bodyBatteryValueDescriptorIndex"
            )
            for v in (entry.get("bodyBatteryValueDescriptorDTOList") or [])
            if isinstance(v, dict)
        }
        idx = descriptors.get("bodyBatteryLevel", 1)
        readings = [
            r
            for r in (entry.get("bodyBatteryValuesArray") or [])
            if isinstance(r, list) and len(r) > idx and number(r[idx], 100) is not None
        ]
        if readings:
            readings.sort(key=lambda r: r[0])
            levels = [r[idx] for r in readings]
            values["body_battery_current"] = levels[-1]
            values["body_battery_high"] = max(levels)
            values["body_battery_low"] = min(levels)
            values["body_battery_updated_at"] = entry.get("endTimestampLocal")
        else:
            values["body_battery_current"] = None
    spo2 = call("get_spo2_data")
    if isinstance(spo2, dict):
        values["spo2_avg"] = number(spo2.get("averageSpO2"), 100)
    respiration = call("get_respiration_data")
    if isinstance(respiration, dict):
        values["respiration_avg"] = number(respiration.get("avgWakingRespirationValue"))
    readiness = call("get_training_readiness")
    if readiness is not None:
        r = choose_record(readiness, d, "primaryActivityTracker")
        values["training_readiness"] = number(r.get("score"), 100)
        values["training_readiness_level"] = r.get("level")
        values["readiness_updated_at"] = r.get("timestampLocal")
        recovery = number(r.get("recoveryTime"))
        values["recovery_time_hours"] = (
            round(recovery / 60, 2) if recovery is not None else None
        )
        values["acute_load"] = number(r.get("acuteLoad"))
    status = call("get_training_status")
    if isinstance(status, dict):
        records = (
            (status.get("mostRecentTrainingStatus") or {}).get(
                "latestTrainingStatusData"
            )
            or {}
        ).values()
        t = choose_record(list(records), d, "primaryTrainingDevice")
        phrase = t.get("trainingStatusFeedbackPhrase")
        # Garmin's phrase is exposed verbatim, not interpreted as a medical recommendation.
        values["training_status"] = (
            phrase if phrase and not phrase.startswith("NO_STATUS") else None
        )
        load = t.get("acuteTrainingLoadDTO") or {}
        values["load_ratio"] = number(load.get("dailyAcuteChronicWorkloadRatio"))
        if number(load.get("dailyTrainingLoadAcute")) is not None:
            values["acute_load"] = load["dailyTrainingLoadAcute"]
        vo2 = (status.get("mostRecentVO2Max") or {}).get("generic") or {}
        # Never misdate Garmin's most-recent (possibly old) measurement as today's.
        values["vo2_max"] = (
            number(vo2.get("vo2MaxPreciseValue"))
            if vo2.get("calendarDate") == d
            else None
        )
    values["extracted_json"] = json.dumps(values)
    return values, errors


def extract_activity(a):
    return {
        "activity_id": a.get("activityId"),
        "name": a.get("activityName"),
        "type": (a.get("activityType") or {}).get("typeKey"),
        "start_local": a.get("startTimeLocal"),
        "start_iso": a.get("startTimeGMT"),
        "duration_s": number(a.get("duration")),
        "distance_m": number(a.get("distance")),
        "calories": number(a.get("calories")),
        "avg_hr": number(a.get("averageHR")),
        "max_hr": number(a.get("maxHR")),
        "elevation_m": number(a.get("elevationGain")),
    }


def sync_real(garmin, conn, days, force=False, quiet=False):
    written, acts_written, errors = 0, 0, []
    for d in store.iso_days_back(days):
        if (
            store.get_day(conn, d)
            and not force
            and d < (date.today() - timedelta(days=1)).isoformat()
        ):
            continue
        values, failures = fetch_day(garmin, d)
        errors.extend(f"{d} {e}" for e in failures)
        if len(values) > 2:
            # Missing keys mean a failed endpoint: preserve those existing values.
            store.upsert_day(conn, values, source="garmin")
            written += 1
    try:
        for a in garmin.get_activities(0, 100) or []:
            if isinstance(a, dict) and a.get("activityId") is not None:
                store.upsert_activity(conn, extract_activity(a), source="garmin")
                acts_written += 1
    except Exception as exc:
        errors.append(f"get_activities: {type(exc).__name__}")
    store.log_sync(
        conn,
        "garmin",
        days,
        written,
        acts_written,
        ok=not errors,
        error="; ".join(errors) or None,
    )
    if not quiet:
        print(
            f"Synced {written} days, {acts_written} activities; {len(errors)} endpoint errors."
        )
        for e in errors:
            print(e)
    return not errors


def main():
    import msvcrt

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    if not 1 <= args.days <= 365:
        ap.error("--days must be between 1 and 365")
    from garmin_client import connect

    store.DATA_DIR.mkdir(exist_ok=True)
    with (store.DATA_DIR / "sync.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("A Garmin sync is already running.")
            sys.exit(2)
        try:
            conn = store.connect_db()
            try:
                garmin = connect(interactive=not args.quiet)
                success = sync_real(garmin, conn, args.days, args.force, args.quiet)
            finally:
                conn.close()
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
