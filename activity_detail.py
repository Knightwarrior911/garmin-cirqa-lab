"""Native Garmin activity detail normalization and bounded, on-demand local caching."""

import json
import math
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import store

ROOT = Path(__file__).parent
COOLDOWN = 30 * 60
fetch_lock = threading.Lock()
active_id = None


def finite(value, low=None, high=None):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        return None
    if low is not None and value < low or high is not None and value > high:
        return None
    return value


def text(value):
    return value if isinstance(value, str) else None


def elapsed_timestamp(value):
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except (ValueError, AttributeError):
        return None


def pace(speed):
    return 1000 / speed if finite(speed, 0) and speed > 0 else None


SUMMARY_FIELDS = [
    ("duration", "Timer time", "s", "duration"),
    ("distance", "Distance", "m", "distance"),
    ("movingDuration", "Moving time", "s", "duration"),
    ("elapsedDuration", "Elapsed time", "s", "duration"),
    ("averageHR", "Average heart rate", "bpm", "number"),
    ("maxHR", "Maximum heart rate", "bpm", "number"),
    ("minHR", "Minimum heart rate", "bpm", "number"),
    ("calories", "Calories", "kcal", "number"),
    ("bmrCalories", "Resting calories", "kcal", "number"),
    ("trainingEffect", "Aerobic Training Effect", "/ 5", "decimal"),
    ("anaerobicTrainingEffect", "Anaerobic Training Effect", "/ 5", "decimal"),
    ("activityTrainingLoad", "Exercise load", "", "number"),
    ("averageRunCadence", "Average cadence", "steps/min", "number"),
    ("maxRunCadence", "Maximum cadence", "steps/min", "number"),
    ("averageBikeCadence", "Average cadence", "rpm", "number"),
    ("maxBikeCadence", "Maximum cadence", "rpm", "number"),
    ("averagePower", "Average power", "W", "number"),
    ("maxPower", "Maximum power", "W", "number"),
    ("elevationGain", "Ascent", "m", "number"),
    ("elevationLoss", "Descent", "m", "number"),
    ("steps", "Steps", "", "number"),
    ("moderateIntensityMinutes", "Moderate intensity", "min", "number"),
    ("vigorousIntensityMinutes", "Vigorous intensity", "min", "number"),
    ("differenceBodyBattery", "Body Battery change", "points", "signed"),
]


def normalize_splits(rows):
    result = []
    for lap in rows:
        if not isinstance(lap, dict):
            continue
        speed = finite(lap.get("averageSpeed"), 0)
        result.append(
            {
                "index": lap.get("lapIndex", lap.get("messageIndex", len(result) + 1)),
                "duration_s": finite(lap.get("duration"), 0),
                "distance_m": finite(lap.get("distance"), 0),
                "pace_s_km": pace(speed),
                "speed_kmh": speed * 3.6 if speed is not None else None,
                "avg_hr": finite(lap.get("averageHR"), 1),
                "max_hr": finite(lap.get("maxHR"), 1),
                "cadence": finite(lap.get("averageRunCadence"), 0),
                "intensity": text(lap.get("type")) or text(lap.get("intensityType")),
            }
        )
    return result


def normalize(raw, base):
    native = raw.get("summary") or {}
    summary = native.get("summaryDTO") or {}
    kind = (
        (native.get("activityTypeDTO") or {}).get("typeKey")
        or base.get("type")
        or "other"
    )
    running = "running" in kind or kind in ("trail_run", "virtual_run", "track_running")
    pace_sport = running or kind in ("walking", "hiking")
    stats = []
    for key, label, unit, fmt in SUMMARY_FIELDS:
        low = (
            None
            if fmt == "signed"
            else 1
            if key in ("averageHR", "maxHR", "minHR")
            else 0
        )
        value = finite(summary.get(key), low)
        if value is not None:
            stats.append(
                {
                    "key": key,
                    "label": label,
                    "value": value,
                    "unit": unit,
                    "format": fmt,
                }
            )
    for key, label in [
        ("averageSpeed", "Average"),
        ("averageMovingSpeed", "Moving"),
        ("maxSpeed", "Best" if pace_sport else "Maximum"),
    ]:
        value = finite(summary.get(key), 0)
        if value is not None and (not pace_sport or value > 0):
            stats.insert(
                2,
                {
                    "key": key,
                    "label": label + (" pace" if pace_sport else " speed"),
                    "value": pace(value) if pace_sport else value * 3.6,
                    "unit": "/km" if pace_sport else "km/h",
                    "format": "pace" if pace_sport else "decimal",
                },
            )
    detail = raw.get("details") or {}
    descriptors = {
        d.get("key"): d
        for d in (detail.get("metricDescriptors") or [])
        if isinstance(d, dict)
    }

    # Garmin chart values already use the descriptor's named units; its factor is not a multiplier.
    def channel(key, unit=None):
        descriptor = descriptors.get(key) or {}
        if unit and (descriptor.get("unit") or {}).get("key") not in unit:
            return None
        index = descriptor.get("metricsIndex")
        return index if isinstance(index, int) and index >= 0 else None

    def value(row, key, units=None, low=None, high=None):
        index = channel(key, units)
        return (
            finite(row[index], low, high)
            if index is not None and index < len(row)
            else None
        )

    rows = [
        r.get("metrics")
        for r in (detail.get("activityDetailMetrics") or [])
        if isinstance(r, dict) and isinstance(r.get("metrics"), list)
    ]
    start = elapsed_timestamp(summary.get("startTimeGMT"))
    timed = []
    for row in rows:
        t = value(row, "sumElapsedDuration", ("second",), 0)
        if t is None:
            timestamp = value(row, "directTimestamp", ("gmt",), 0)
            if timestamp is not None and start is not None:
                t = finite(timestamp / 1000 - start, 0)
        if t is not None:
            timed.append((t, row))
    timed.sort(key=lambda r: r[0])
    points = []
    for t, row in timed:
        point = {
            "time_s": round(t, 3),
            "distance_m": value(row, "sumDistance", ("meter",), 0),
        }
        points.append((point, row))
    specs = [
        ("hr", "Heart rate", "bpm", "number", [("directHeartRate", ("bpm",))], 1, None),
        (
            "speed",
            "Pace" if pace_sport else "Speed",
            "/km" if pace_sport else "km/h",
            "pace" if pace_sport else "decimal",
            [("directSpeed", ("mps",))],
            0,
            None,
        ),
        (
            "cadence",
            "Cadence",
            "steps/min" if pace_sport else "rpm",
            "number",
            [
                ("directDoubleCadence", ("stepsPerMinute",)),
                ("directRunCadence", ("stepsPerMinute",)),
                ("directBikeCadence", ("rpm",)),
            ],
            0,
            None,
        ),
        (
            "elevation",
            "Elevation",
            "m",
            "number",
            [("directCorrectedElevation", ("meter",)), ("directElevation", ("meter",))],
            None,
            None,
        ),
        (
            "power",
            "Power",
            "W",
            "number",
            [("directPower", ("watt", "watts"))],
            0,
            None,
        ),
        (
            "body_battery",
            "Body Battery",
            "/ 100",
            "number",
            [("directBodyBattery", ("dimensionless",))],
            0,
            100,
        ),
    ]
    streams = []
    for key, label, unit, fmt, channels, low, high in specs:
        selected = next(
            ((c, units) for c, units in channels if channel(c, units) is not None), None
        )
        if not selected:
            continue
        data = [value(row, *selected, low, high) for _, row in points]
        if key == "speed":
            data = [
                pace(v) if pace_sport else v * 3.6 if v is not None else None
                for v in data
            ]
        if any(v is not None for v in data):
            streams.append(
                {
                    "key": key,
                    "label": label,
                    "unit": unit,
                    "format": fmt,
                    "values": [round(v, 3) if v is not None else None for v in data],
                }
            )
    laps = normalize_splits((raw.get("splits") or {}).get("lapDTOs") or [])
    zones = []
    raw_zones = raw.get("zones") if isinstance(raw.get("zones"), list) else []
    for z in raw_zones:
        if not isinstance(z, dict):
            continue
        zone, seconds, lower = (
            finite(z.get("zoneNumber"), 1),
            finite(z.get("secsInZone"), 0),
            finite(z.get("zoneLowBoundary"), 1),
        )
        if zone is not None and seconds is not None and lower is not None:
            zones.append({"zone": zone, "seconds": seconds, "low_bpm": lower})
    zones.sort(key=lambda z: z["zone"])
    zone_total = sum(z["seconds"] for z in zones)
    for i, z in enumerate(zones):
        z["high_bpm"] = zones[i + 1]["low_bpm"] - 1 if i + 1 < len(zones) else None
        z["percent"] = z["seconds"] / zone_total * 100 if zone_total else 0
    route = []
    for p in (detail.get("geoPolylineDTO") or {}).get("polyline") or []:
        if not isinstance(p, dict) or p.get("valid") is False:
            continue
        lat, lon = finite(p.get("lat"), -90, 90), finite(p.get("lon"), -180, 180)
        if lat is not None and lon is not None:
            route.append([lat, lon])
    sets = []
    for e in (raw.get("sets") or {}).get("exerciseSets") or []:
        if not isinstance(e, dict):
            continue
        sets.append(
            {
                "type": text(e.get("setType")),
                "reps": finite(e.get("repetitionCount"), 0),
                "duration_s": finite(e.get("duration"), 0),
                "weight_kg": finite(e.get("weight"), 0) / 1000
                if finite(e.get("weight"), 0) is not None
                else None,
                "exercises": [
                    {"category": text(x.get("category")), "name": text(x.get("name"))}
                    for x in (e.get("exercises") or [])
                    if isinstance(x, dict)
                ],
            }
        )
    typed = raw.get("typed") or {}
    intervals = normalize_splits(
        typed.get("splits") or [] if isinstance(typed, dict) else typed
    )
    if not intervals:
        intervals = [
            dict(l)
            for l in laps
            if l["intensity"] and l["intensity"] not in ("ACTIVE", "UNKNOWN")
        ]
    unavailable = []
    if not streams:
        unavailable.append(
            "No supported chart streams were returned for this recording."
        )
    if pace_sport and not any(s["key"] == "speed" for s in streams):
        unavailable.append(
            "Garmin did not supply a usable pace stream. Pace is not estimated from heart rate or the activity name."
        )
    if not zones:
        unavailable.append("Garmin did not supply heart-rate zones for this recording.")
    if running and not intervals:
        unavailable.append(
            "No classified run/walk intervals were supplied. Recorded laps are shown below when available."
        )
    distance_axis = [p["distance_m"] for p, _ in points if p["distance_m"] is not None]
    supports_distance = (
        len(distance_axis) > 1
        and max(distance_axis) > 0
        and all(b >= a for a, b in zip(distance_axis, distance_axis[1:]))
    )
    return {
        "id": str(base["activity_id"]),
        "name": native.get("activityName") or base.get("name") or "Activity",
        "type": kind,
        "start_local": summary.get("startTimeLocal") or base.get("start_local"),
        "pace_sport": pace_sport,
        "stats": stats,
        "axis": [p for p, _ in points],
        "streams": streams,
        "supports_distance": supports_distance,
        "laps": laps,
        "zones": zones,
        "route": route,
        "sets": sets,
        "intervals": intervals,
        "unavailable": unavailable,
        "partial_sections": raw.get("partial_sections", []),
        "stale_sections": [],
        "reported_measurements": detail.get("measurementCount"),
        "returned_samples": len(points),
        "garmin_url": "https://connect.garmin.com/modern/activity/"
        + str(base["activity_id"])
        if base.get("source") == "garmin" and str(base["activity_id"]).isdigit()
        else None,
    }


def get_record(conn, aid):
    row = conn.execute(
        "SELECT * FROM activities WHERE activity_id=?", (aid,)
    ).fetchone()
    return dict(row) if row else None


def save_payload(conn, aid, payload):
    conn.execute(
        "INSERT INTO activity_details(activity_id,payload_json,fetched_at,attempted_at,error) VALUES(?,?,?,?,NULL) ON CONFLICT(activity_id) DO UPDATE SET payload_json=excluded.payload_json,fetched_at=excluded.fetched_at,attempted_at=excluded.attempted_at,error=NULL",
        (aid, json.dumps(payload, allow_nan=False), store.now_iso(), time.time()),
    )
    conn.commit()


def get_detail(conn, aid):
    base = get_record(conn, aid)
    if not base:
        return None
    row = conn.execute(
        "SELECT * FROM activity_details WHERE activity_id=?", (aid,)
    ).fetchone()
    return {
        "ok": True,
        "activity": base,
        "detail": json.loads(row["payload_json"])
        if row and row["payload_json"]
        else None,
        "fetched_at": row["fetched_at"] if row else None,
        "fetch": {
            "running": active_id == aid,
            "busy": active_id is not None and active_id != aid,
            "error": row["error"] if row else None,
            "cooldown_seconds": max(
                0, round(COOLDOWN - (time.time() - (row["attempted_at"] or 0)))
            )
            if row
            else 0,
            "supported": base["source"] == "garmin" and aid.isdigit(),
        },
    }


def worker(aid):
    global active_id
    error = None
    busy = False
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "activity_detail.py"), aid],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 2:
            busy = True
            error = "The daily Garmin sync is running. Try loading this activity again after it finishes."
        elif result.returncode:
            error = "Garmin activity download failed. Check your connection or Garmin login. Cached detail has been preserved."
    except (OSError, subprocess.TimeoutExpired):
        error = "Garmin activity download could not finish. Cached detail has been preserved."
    finally:
        try:
            conn = store.connect_db()
            if error:
                conn.execute(
                    "UPDATE activity_details SET error=?,attempted_at=? WHERE activity_id=?",
                    (error, 0 if busy else time.time(), aid),
                )
                conn.commit()
            conn.close()
        finally:
            active_id = None
            fetch_lock.release()


def request_detail(aid):
    global active_id
    conn = store.connect_db()
    try:
        state = get_detail(conn, aid)
        if (
            state is None
            or not state["fetch"]["supported"]
            or state["fetch"]["cooldown_seconds"]
            or state["fetch"]["running"]
        ):
            return state
        if not fetch_lock.acquire(blocking=False):
            state["fetch"]["busy"] = True
            return state
        try:
            conn.execute(
                "INSERT INTO activity_details(activity_id,attempted_at) VALUES(?,?) ON CONFLICT(activity_id) DO UPDATE SET attempted_at=excluded.attempted_at,error=NULL",
                (aid, time.time()),
            )
            conn.commit()
            active_id = aid
            threading.Thread(target=worker, args=(aid,), daemon=True).start()
        except Exception:
            active_id = None
            fetch_lock.release()
            raise
        return get_detail(conn, aid)
    finally:
        conn.close()


def download_into(conn, g, aid):
    """Download into a caller-owned database with an isolated Garmin session."""
    base = get_record(conn, aid)
    if not base or base["source"] != "garmin" or not aid.isdigit():
        raise ValueError("Activity is not a Garmin recording")
    raw = {
        "summary": g.get_activity(aid),
        "details": g.get_activity_details(aid, maxchart=4000, maxpoly=4000),
        "partial_sections": [],
    }
    methods = {
        "splits": "get_activity_splits",
        "zones": "get_activity_hr_in_timezones",
        "typed": "get_activity_typed_splits",
    }
    if base["type"] == "strength_training":
        methods["sets"] = "get_activity_exercise_sets"
    for section, method in methods.items():
        try:
            raw[section] = getattr(g, method)(aid)
        except Exception:
            raw["partial_sections"].append(section)
    if (
        not isinstance(raw["summary"], dict)
        or not isinstance(raw["details"], dict)
        or not isinstance(raw["summary"].get("summaryDTO"), dict)
        or raw["details"].get("pendingData")
    ):
        raise ValueError("Garmin detail is not ready")
    payload = normalize(raw, base)
    previous = get_detail(conn, aid)["detail"]
    if previous:
        section_fields = {
            "splits": ("laps",),
            "zones": ("zones",),
            "typed": ("intervals",),
            "sets": ("sets",),
        }
        for section in raw["partial_sections"]:
            for field in section_fields[section]:
                if previous.get(field):
                    payload[field] = previous[field]
                    payload["stale_sections"].append(field)
    save_payload(conn, aid, payload)


def download(aid):
    from garmin_client import connect

    conn = store.connect_db()
    try:
        download_into(conn, connect(interactive=False), aid)
    finally:
        conn.close()


if __name__ == "__main__":
    import msvcrt

    if len(sys.argv) != 2:
        sys.exit(1)
    store.DATA_DIR.mkdir(exist_ok=True)
    with (store.DATA_DIR / "sync.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            sys.exit(2)
        try:
            download(sys.argv[1])
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
