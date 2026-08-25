"""Optional: import local .FIT activity files (e.g. from CIRQA USB File Access) into the store.

Usage:
    1. Copy .FIT files into  data/fit/
    2. .venv\\Scripts\\python import_fit.py

Each file is parsed with fitdecode; session + lap data become activities and splits.
Files already imported (by content hash) are skipped.
"""
import hashlib
import sys
from pathlib import Path

import store

FIT_DIR = store.DATA_DIR / "fit"
RUN_TYPES = {"running", "trail_running", "treadmill_running", "virtual_run", "track_running"}


def fit_time_to_iso(msg_value):
    try:
        return msg_value.utc.isoformat() if msg_value else None
    except Exception:
        return None


def import_file(conn, path):
    import fitdecode

    raw = path.read_bytes()
    content_hash = hashlib.sha1(raw).hexdigest()[:16]
    if conn.execute("SELECT 1 FROM activities WHERE activity_id=?", (f"fit-{content_hash}",)).fetchone():
        return None

    session = {}
    laps = []
    records_hr = []
    try:
        with path.open("rb") as f:
            for frame in fitdecode.FitReader(f):
                if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                    continue
                m = frame.name
                if m == "session":
                    session = {k: frame.get_value(k) for k in (
                        "sport", "sub_sport", "start_time", "total_timer_time",
                        "total_distance", "total_calories", "avg_heart_rate", "max_heart_rate")}
                elif m == "lap":
                    lap = {k: frame.get_value(k) for k in (
                        "total_timer_time", "total_distance", "avg_heart_rate")}
                    if lap.get("total_distance"):
                        laps.append(lap)
                elif m == "record":
                    hr = frame.get_value("heart_rate")
                    if hr:
                        records_hr.append(hr)
    except Exception as e:
        print(f"  ! {path.name}: {type(e).__name__}: {e}")
        return None

    if not session:
        return None
    sport = str(getattr(session.get("sport"), "value", session.get("sport")) or "unknown").lower()
    start_iso = fit_time_to_iso(session.get("start_time"))
    dist = session.get("total_distance")
    dur = session.get("total_timer_time")
    aid = f"fit-{content_hash}"
    store.upsert_activity(conn, {
        "activity_id": aid,
        "name": f"{sport.capitalize()} (FIT import)",
        "type": sport,
        "start_local": start_iso[:19].replace("T", " ") if start_iso else None,
        "start_iso": start_iso,
        "duration_s": float(dur) if dur else None,
        "distance_m": float(dist) if dist else None,
        "calories": session.get("total_calories"),
        "avg_hr": session.get("avg_heart_rate") or (round(sum(records_hr) / len(records_hr)) if records_hr else None),
        "max_hr": session.get("max_heart_rate") or (max(records_hr) if records_hr else None),
        "raw_json": None,
    }, source="fit")

    if laps and (sport in RUN_TYPES or (dist and dur)):
        splits = []
        for lap in laps:
            d, t = float(lap.get("total_distance") or 0), float(lap.get("total_timer_time") or 0)
            if not d or not t:
                continue
            splits.append({"distance_m": d, "duration_s": t,
                           "avg_hr": lap.get("avg_heart_rate"),
                           "pace_s_per_km": round(t / d * 1000.0, 1)})
        if len(splits) >= 2:
            store.replace_splits(conn, aid, splits)
    return aid


def main():
    if not FIT_DIR.exists():
        print(f"No {FIT_DIR} directory. Copy .FIT files there first "
              f"(CIRQA: Garmin Connect app > device settings > System > USB File Access).")
        return
    files = sorted(FIT_DIR.glob("*.fit"))
    if not files:
        print("No .fit files found in data/fit/.")
        return
    conn = store.connect_db()
    imported = 0
    for p in files:
        if import_file(conn, p):
            imported += 1
    print(f"Imported {imported} of {len(files)} FIT file(s). Skipped files were already imported or unreadable.")


if __name__ == "__main__":
    main()
