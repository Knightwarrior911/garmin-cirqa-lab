"""Sync Garmin Connect data into the local SQLite database.

Real sync (requires login first):
    .venv\\Scripts\\python sync.py            # backfill last 30 days + activities + run splits
    .venv\\Scripts\\python sync.py --days 90   # deeper backfill
    .venv\\Scripts\\python sync.py --force     # refetch every day, ignore cache

Pipeline smoke test without a Garmin account:
    .venv\\Scripts\\python sync.py --demo      # seed ~30 days of clearly-marked demo data
    .venv\\Scripts\\python sync.py --clear-demo

Notes
- Today and yesterday are always refreshed (partial-day data).
- Demo rows are automatically removed the first time a real sync runs.
- Run splits (per-km pace/HR) are fetched for the 15 most recent run activities
  and power the run-analysis insights.
"""
import argparse
import json
import random
import sys
from datetime import date, timedelta

import store
from store import iso_days_back, now_iso

RUN_TYPES = {"running", "trail_running", "treadmill_running", "virtual_run", "track_running"}
SPLIT_FETCH_CAP = 15


def safe(garmin, name, *args):
    """Call a Garmin client method by name; missing methods or failures -> None.

    Resolving the attribute here (not at the call site) means an endpoint that
    does not exist in the installed garminconnect version can never abort a sync.
    """
    fn = getattr(garmin, name, None)
    if not callable(fn):
        return None
    try:
        return fn(*args)
    except Exception:
        return None


def _mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def fetch_day(garmin, d):
    """Fetch one day's health bundle. Each endpoint fails independently."""
    bundle = {k: None for k in ("date", "steps", "calories", "resting_hr", "stress_avg",
                                "body_battery_high", "body_battery_low", "spo2_avg",
                                "respiration_avg", "sleep_seconds", "sleep_score",
                                "hrv_last_night", "hrv_weekly_avg", "hrv_baseline_low",
                                "hrv_baseline_high", "training_readiness")}
    bundle["date"] = d
    stats = safe(garmin, "get_stats", d) or {}
    bundle["steps"] = stats.get("totalSteps")
    bundle["calories"] = stats.get("activeKilocalories") or stats.get("calories")
    bundle["resting_hr"] = stats.get("restingHeartRate")
    hrv = safe(garmin, "get_hrv_data", d)
    if isinstance(hrv, dict):
        # Canonical values live in hrvSummary; older responses expose them top-level.
        summary = hrv.get("hrvSummary") if isinstance(hrv.get("hrvSummary"), dict) else hrv
        base = summary.get("baseline") or {}
        bundle["hrv_last_night"] = summary.get("lastNightAvg")
        bundle["hrv_weekly_avg"] = summary.get("weeklyAvg")
        # Upstream baseline aliases: balancedLow/balancedUpper bound the balanced
        # band; lowUpper tops the low band. Fall back to low/high if ever present.
        bundle["hrv_baseline_low"] = base.get("balancedLow", base.get("low"))
        bundle["hrv_baseline_high"] = base.get("balancedUpper", base.get("high"))

    sleep = safe(garmin, "get_sleep_data", d) or {}
    dto = sleep.get("dailySleepDTO") or {}
    bundle["sleep_seconds"] = dto.get("sleepTimeSeconds")
    score = (dto.get("sleepScores") or {}).get("overall") or {}
    bundle["sleep_score"] = score.get("value")

    stress = safe(garmin, "get_stress_data", d)
    if isinstance(stress, dict):
        bundle["stress_avg"] = stress.get("avgStressLevel")
        if bundle["stress_avg"] is None and isinstance(stress.get("stressArray"), list):
            bundle["stress_avg"] = _mean([p.get("stress_level") for p in stress["stressArray"]
                                          if isinstance(p, dict)])

    bb = safe(garmin, "get_body_battery", d)
    if isinstance(bb, list) and bb:
        latest = bb[-1] or {}
        # highest/lowest are levels; charged/drained are deltas and must not
        # be stored as levels when the summary fields are absent.
        bundle["body_battery_high"] = latest.get("highest")
        bundle["body_battery_low"] = latest.get("lowest")

    spo2 = safe(garmin, "get_spo2_data", d)
    bundle["spo2_avg"] = extract_spo2(spo2)

    resp = safe(garmin, "get_respiration_data", d)
    if isinstance(resp, dict):
        bundle["respiration_avg"] = resp.get("avg") or resp.get("averageValue")

    tr = safe(garmin, "get_training_readiness", d)
    bundle["training_readiness"] = extract_readiness(tr)

    bundle["extracted_json"] = json.dumps({k: v for k, v in bundle.items() if k != "extracted_json"})
    return bundle


def extract_readiness(tr):
    """Training readiness arrives as a list, dict, or dict-wrapped list depending on endpoint."""
    if isinstance(tr, list) and tr:
        return (tr[0] or {}).get("score") if isinstance(tr[0], dict) else None
    if isinstance(tr, dict):
        if tr.get("score") is not None:
            return tr.get("score")
        for v in tr.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v[0].get("score")
    return None


def extract_spo2(spo2):
    if isinstance(spo2, dict):
        for key in ("average", "avgValue", "lastNightAvg"):
            if spo2.get(key) is not None:
                return spo2[key]
        readings = spo2.get("readings") or spo2.get("spo2Values") or []
        return _mean([r.get("value") for r in readings if isinstance(r, dict)]) or None
    if isinstance(spo2, list):
        return _mean([r.get("value") for r in spo2 if isinstance(r, dict)]) or None
    return None


def extract_activity(a):
    atype = a.get("activityType") or {}
    return {
        "activity_id": a.get("activityId"),
        "name": a.get("activityName"),
        "type": atype.get("typeKey"),
        "start_local": a.get("startTimeLocal"),
        "start_iso": a.get("startTimeGMT"),
        "duration_s": a.get("duration"),
        "distance_m": a.get("distance"),
        "calories": a.get("calories"),
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "raw_json": None,
    }


def fetch_splits(garmin, activity_id):
    """Per-split pace/HR for one activity. Shape varies; parse defensively."""
    raw = safe(garmin, "get_activity_split_summaries", activity_id)
    if not raw:
        return []
    if isinstance(raw, dict):
        raw = raw.get("splitSummaries") or raw.get("splits") or []
    splits = []
    for i, s in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(s, dict):
            continue
        dist = s.get("distance") or s.get("totalDistance")
        dur = s.get("duration") or s.get("totalDuration")
        if not dist or not dur:
            continue
        pace = (dur / dist) * 1000.0 if dist else None  # seconds per km
        splits.append({
            "distance_m": dist,
            "duration_s": dur,
            "avg_hr": s.get("averageHR") or s.get("hrAverage"),
            "pace_s_per_km": round(pace, 1) if pace else None,
        })
    return splits


def sync_real(garmin, conn, days, force, quiet):
    store.clear_demo(conn)  # demo rows never survive a real sync
    written = 0
    skipped = 0
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    for d in iso_days_back(days):
        existing = store.get_day(conn, d)
        if existing and not force and d not in (today, yesterday):
            skipped += 1
            continue
        try:
            bundle = fetch_day(garmin, d)
        except Exception as e:  # keep going; one bad day must not kill the backfill
            if not quiet:
                print(f"  ! {d}: {type(e).__name__}: {e}")
            continue
        store.upsert_day(conn, bundle, source="garmin")
        written += 1

    acts_written = 0
    try:
        acts = garmin.get_activities(0, 100) or []
    except Exception:
        acts = []
    run_ids = []
    for a in acts:
        if not isinstance(a, dict) or a.get("activityId") is None:
            continue
        extracted = extract_activity(a)
        store.upsert_activity(conn, extracted, source="garmin")
        acts_written += 1
        if (extracted.get("type") in RUN_TYPES or "run" in (extracted.get("name") or "").lower()):
            run_ids.append(extracted["activity_id"])

    splits_fetched = 0
    for aid in run_ids[:SPLIT_FETCH_CAP]:
        if store.has_splits(conn, aid):
            continue
        splits = fetch_splits(garmin, aid)
        if splits:
            store.replace_splits(conn, aid, splits)
            splits_fetched += 1

    store.log_sync(conn, "garmin", days, written, acts_written, ok=True)
    if not quiet:
        print(f"Synced {written} days ({skipped} cached), {acts_written} activities, "
              f"{splits_fetched} new run split sets.")
        print("Next:  .venv\\Scripts\\python serve.py")


def _demo_splits(rnd, base_pace_s, fade_s, hr_base):
    """5 x 1 km splits with realistic fatigue fade."""
    splits = []
    for i in range(5):
        pace = base_pace_s + fade_s * i + rnd.uniform(-3, 3)
        dist = 1000.0 + rnd.uniform(-8, 8)
        splits.append({
            "distance_m": dist,
            "duration_s": dist * pace / 1000.0,
            "avg_hr": hr_base + i * 2 + rnd.randint(-2, 2),
            "pace_s_per_km": round(pace, 1),
        })
    return splits


def seed_demo(conn, days, quiet):
    """Deterministic, clearly-marked demo dataset shaped so every insight rule can fire."""
    if store.has_real_data(conn):
        print("Real Garmin data exists; refusing to add demo rows. "
              "Use --clear-demo first if you really want demo data.")
        return
    rnd = random.Random(42)
    today = date.today()
    for i, d in enumerate(iso_days_back(days)):
        idx_from_end = days - 1 - i
        improving = idx_from_end / max(1, days - 1)  # 1.0 = oldest, 0.0 = today
        sleep_h = rnd.uniform(6.4, 8.4) - 0.35 * improving
        hrv = int(rnd.uniform(52, 60) + 6 * (1 - improving))
        rhr = int(rnd.uniform(49, 53) - 2 * (1 - improving))
        bb_high = int(rnd.uniform(78, 98) + 8 * (1 - improving))
        store.upsert_day(conn, {
            "date": d,
            "steps": int(rnd.uniform(6500, 14500)),
            "calories": int(rnd.uniform(550, 950)),
            "resting_hr": rhr,
            "stress_avg": round(rnd.uniform(24, 44) - 4 * (1 - improving), 0),
            "body_battery_high": bb_high,
            "body_battery_low": int(rnd.uniform(12, 30)),
            "spo2_avg": round(rnd.uniform(94.5, 97.5), 1),
            "respiration_avg": round(rnd.uniform(13.2, 15.4), 1),
            "sleep_seconds": int(sleep_h * 3600),
            "sleep_score": int(rnd.uniform(62, 88)),
            "hrv_last_night": hrv,
            "hrv_weekly_avg": round(hrv + rnd.uniform(-2, 2), 1),
            "hrv_baseline_low": hrv - 6,
            "hrv_baseline_high": hrv + 7,
            "training_readiness": int(rnd.uniform(58, 92) + 6 * (1 - improving)),
            "extracted_json": json.dumps({"demo": True}),
        }, source="demo")

    # Runs across 4 weeks: pace at the same HR improves ~5%; mild fade inside each run.
    run_days = [3, 10, 17, 24]
    for k, back in enumerate(run_days):
        d = (today - timedelta(days=back)).isoformat()
        base_pace = 335 + k * 9  # k=0 most recent (~5:43/km mean), oldest ~6:10/km
        aid = f"demo-run-{k}"
        start = f"{d} 07:{10 + k:02d}:00"
        store.upsert_activity(conn, {
            "activity_id": aid,
            "name": f"Easy run {k + 1}",
            "type": "running",
            "start_local": start,
            "start_iso": f"{d}T07:{10 + k:02d}:00.00",
            "duration_s": 5 * (base_pace + 8),
            "distance_m": 5000.0,
            "calories": 420 + k * 5,
            "avg_hr": 149 + k,
            "max_hr": 168 + k,
            "raw_json": json.dumps({"demo": True}),
        }, source="demo")
        store.replace_splits(conn, aid, _demo_splits(rnd, base_pace, 4, 148 + k))
    # Mixed sessions spread evenly across weeks (mostly easy intensity).
    for k, (back, name, atype, dur, avg_hr) in enumerate([
            (4, "Strength - lower body", "strength_training", 2700, 138),
            (6, "Row", "indoor_rowing", 1500, 128),
            (9, "HYROX circuit", "hiit", 3120, 149),
            (12, "Strength - upper body", "strength_training", 2400, 132),
            (13, "Easy spin", "cycling", 2400, 125),
            (16, "Recovery walk", "walking", 3600, 98),
            (20, "Recovery spin", "cycling", 1800, 118)]):
        d = (today - timedelta(days=back)).isoformat()
        store.upsert_activity(conn, {
            "activity_id": f"demo-x-{k}",
            "name": name,
            "type": atype,
            "start_local": f"{d} 18:30:00",
            "start_iso": f"{d}T18:30:00.00",
            "duration_s": dur,
            "distance_m": None,
            "calories": int(dur / 60 * rnd.uniform(7, 11)),
            "avg_hr": avg_hr,
            "max_hr": avg_hr + rnd.randint(18, 30),
            "raw_json": json.dumps({"demo": True}),
        }, source="demo")

    log_day = (today - timedelta(days=2)).isoformat()
    log_day2 = (today - timedelta(days=8)).isoformat()

    for e in [
        {"date": log_day, "session": "strength", "exercise": "Front squat", "sets": 4, "reps": 6,
         "load_kg": 82.5, "rpe": 9, "soreness": 6, "notes": "heavy lower body"},
        {"date": log_day, "session": "strength", "exercise": "Wall balls", "sets": 5, "reps": 20,
         "load_kg": 9, "rpe": 8, "soreness": 5, "notes": None},
        {"date": log_day2, "session": "strength", "exercise": "Deadlift", "sets": 5, "reps": 5,
         "load_kg": 120, "rpe": 9, "soreness": 7, "notes": "heavy lower body"},
        {"date": (today - timedelta(days=6)).isoformat(), "session": "run", "exercise": "5x1km",
         "sets": 5, "reps": 1, "load_kg": None, "rpe": 7, "soreness": 2, "notes": "controlled HR"},
    ]:
        store.add_log_entry(conn, e, source="demo")

    store.log_sync(conn, "demo", days, days, 11, ok=True)
    if not quiet:
        print(f"Demo data written: {days} days, 11 activities, 4 run split sets, 4 log entries.")
        print("This is synthetic data. A real sync removes it automatically, or run: "
              ".venv\\Scripts\\python sync.py --clear-demo")


def main():
    ap = argparse.ArgumentParser(description="Sync Garmin Connect data to local SQLite.")
    ap.add_argument("--days", type=int, default=30, help="days to backfill (default 30)")
    ap.add_argument("--force", action="store_true", help="refetch all days, ignoring cache")
    ap.add_argument("--demo", action="store_true", help="seed clearly-marked demo data (no account needed)")
    ap.add_argument("--clear-demo", action="store_true", help="remove demo rows")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    conn = store.connect_db()
    try:
        if args.clear_demo:
            n = store.clear_demo(conn)
            store.log_sync(conn, "clear-demo", 0, -n, 0, ok=True)
            print(f"Demo rows cleared: {n}")
            return
        if args.demo:
            seed_demo(conn, max(14, min(args.days, 90)), args.quiet)
            return
        from garmin_client import connect
        garmin = connect(interactive=not args.quiet)
        sync_real(garmin, conn, args.days, args.force, args.quiet)
    except KeyboardInterrupt:
        sys.exit("Interrupted.")
    except SystemExit:
        raise
    except Exception as e:
        store.log_sync(conn, "error", args.days, 0, 0, ok=False, error=f"{type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
