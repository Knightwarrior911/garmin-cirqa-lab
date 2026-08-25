"""SQLite storage for Garmin CIRQA data: daily metrics, activities, run splits, training log."""
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "garmin.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS days (
  date TEXT PRIMARY KEY,
  steps INTEGER,
  calories INTEGER,
  resting_hr INTEGER,
  stress_avg REAL,
  body_battery_high INTEGER,
  body_battery_low INTEGER,
  spo2_avg REAL,
  respiration_avg REAL,
  sleep_seconds INTEGER,
  sleep_score INTEGER,
  sleep_deep_s INTEGER,
  sleep_rem_s INTEGER,
  sleep_light_s INTEGER,
  sleep_awake_s INTEGER,
  hrv_last_night INTEGER,
  hrv_weekly_avg REAL,
  hrv_baseline_low INTEGER,
  hrv_baseline_high INTEGER,
  training_readiness INTEGER,
  source TEXT NOT NULL DEFAULT 'garmin',
  extracted_json TEXT,
  fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS activities (
  activity_id TEXT PRIMARY KEY,
  name TEXT,
  type TEXT,
  start_local TEXT,
  start_iso TEXT,
  duration_s REAL,
  distance_m REAL,
  calories INTEGER,
  avg_hr INTEGER,
  max_hr INTEGER,
  elevation_m REAL,
  source TEXT NOT NULL DEFAULT 'garmin',
  raw_json TEXT
);
CREATE TABLE IF NOT EXISTS splits (
  activity_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  distance_m REAL,
  duration_s REAL,
  avg_hr INTEGER,
  pace_s_per_km REAL,
  PRIMARY KEY (activity_id, idx)
);
CREATE TABLE IF NOT EXISTS training_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  session TEXT,
  exercise TEXT,
  sets INTEGER,
  reps INTEGER,
  load_kg REAL,
  rpe REAL,
  soreness INTEGER,
  notes TEXT,
  created_at TEXT,
  source TEXT NOT NULL DEFAULT 'user'
);
CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT,
  finished_at TEXT,
  mode TEXT,
  days_requested INTEGER,
  days_written INTEGER,
  activities_written INTEGER,
  ok INTEGER,
  error TEXT
);
"""

DAY_COLUMNS = [
    "date", "steps", "calories", "resting_hr", "stress_avg",
    "body_battery_high", "body_battery_low", "spo2_avg", "respiration_avg",
    "sleep_seconds", "sleep_score", "sleep_deep_s", "sleep_rem_s", "sleep_light_s",
    "sleep_awake_s", "hrv_last_night", "hrv_weekly_avg",
    "hrv_baseline_low", "hrv_baseline_high", "training_readiness",
]


def connect_db():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def upsert_day(conn, values, source="garmin"):
    """values: dict keyed by DAY_COLUMNS (missing keys -> NULL)."""
    row = {k: values.get(k) for k in DAY_COLUMNS}
    conn.execute(
        f"INSERT OR REPLACE INTO days ({', '.join(DAY_COLUMNS)}, source, extracted_json, fetched_at) "
        f"VALUES ({', '.join('?' * len(DAY_COLUMNS))}, ?, ?, ?)",
        [row[k] for k in DAY_COLUMNS] + [source, values.get("extracted_json"), now_iso()],
    )
    conn.commit()


def get_day(conn, d):
    return conn.execute("SELECT * FROM days WHERE date=?", (d,)).fetchone()


def get_days(conn, n=90):
    """Most recent n days, ascending by date."""
    rows = conn.execute("SELECT * FROM days ORDER BY date DESC LIMIT ?", (int(n),)).fetchall()
    return list(reversed(rows))


def day_to_dict(row):
    if row is None:
        return None
    d = {k: row[k] for k in row.keys()}
    d["sleep_hours"] = round(d["sleep_seconds"] / 3600.0, 2) if d.get("sleep_seconds") else None
    return d


def upsert_activity(conn, a, source="garmin"):
    conn.execute(
        "INSERT OR REPLACE INTO activities (activity_id, name, type, start_local, start_iso, "
        "duration_s, distance_m, calories, avg_hr, max_hr, source, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(a.get("activity_id")), a.get("name"), a.get("type"), a.get("start_local"),
         a.get("start_iso"), a.get("duration_s"), a.get("distance_m"), a.get("calories"),
         a.get("avg_hr"), a.get("max_hr"), source, a.get("raw_json")),
    )
    conn.commit()


def get_activities(conn, limit=20):
    rows = conn.execute(
        "SELECT * FROM activities ORDER BY COALESCE(start_iso, start_local) DESC LIMIT ?", (int(limit),)
    ).fetchall()
    return [dict(r) for r in rows]


def activity_count(conn):
    return conn.execute("SELECT COUNT(*) c FROM activities").fetchone()["c"]


def upsert_activity(conn, a, source="garmin"):
    conn.execute(
        "INSERT OR REPLACE INTO activities (activity_id, name, type, start_local, start_iso, "
        "duration_s, distance_m, calories, avg_hr, max_hr, elevation_m, source, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(a.get("activity_id")), a.get("name"), a.get("type"), a.get("start_local"),
         a.get("start_iso"), a.get("duration_s"), a.get("distance_m"), a.get("calories"),
         a.get("avg_hr"), a.get("max_hr"), a.get("elevation_m"), source, a.get("raw_json")),
    )
    conn.commit()


def replace_splits(conn, activity_id, splits):
    conn.execute("DELETE FROM splits WHERE activity_id=?", (str(activity_id),))
    for i, s in enumerate(splits):
        conn.execute(
            "INSERT OR REPLACE INTO splits (activity_id, idx, distance_m, duration_s, avg_hr, pace_s_per_km) "
            "VALUES (?,?,?,?,?,?)",
            (str(activity_id), i, s.get("distance_m"), s.get("duration_s"),
             s.get("avg_hr"), s.get("pace_s_per_km")),
        )
    conn.commit()


def has_splits(conn, activity_id):
    return conn.execute("SELECT 1 FROM splits WHERE activity_id=? LIMIT 1", (str(activity_id),)).fetchone() is not None


def get_splits(conn, activity_id):
    rows = conn.execute(
        "SELECT * FROM splits WHERE activity_id=? ORDER BY idx", (str(activity_id),)
    ).fetchall()
    return [dict(r) for r in rows]


def runs_with_splits(conn, limit=15):
    """Recent run activities that have stored splits, ascending by start."""
    rows = conn.execute(
        "SELECT a.* FROM activities a JOIN splits s ON s.activity_id = a.activity_id "
        "GROUP BY a.activity_id ORDER BY COALESCE(a.start_iso, a.start_local) DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def add_log_entry(conn, e, source="user"):
    cur = conn.execute(
        "INSERT INTO training_log (date, session, exercise, sets, reps, load_kg, rpe, soreness, notes, created_at, source) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (e.get("date"), e.get("session"), e.get("exercise"), e.get("sets"), e.get("reps"),
         e.get("load_kg"), e.get("rpe"), e.get("soreness"), e.get("notes"), now_iso(), source),
    )
    conn.commit()
    return cur.lastrowid


def get_log(conn, limit=50):
    rows = conn.execute("SELECT * FROM training_log ORDER BY date DESC, id DESC LIMIT ?", (int(limit),)).fetchall()
    return [dict(r) for r in rows]


def log_count(conn):
    return conn.execute("SELECT COUNT(*) c FROM training_log").fetchone()["c"]


def log_sync(conn, mode, days_requested, days_written, activities_written, ok, error=None):
    conn.execute(
        "INSERT INTO sync_log (started_at, finished_at, mode, days_requested, days_written, "
        "activities_written, ok, error) VALUES (?,?,?,?,?,?,?,?)",
        (now_iso(), now_iso(), mode, days_requested, days_written, activities_written,
         1 if ok else 0, error),
    )
    conn.commit()


def last_sync(conn):
    row = conn.execute("SELECT finished_at, mode FROM sync_log WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def clear_demo(conn):
    cur_d = conn.execute("DELETE FROM days WHERE source='demo'")
    cur_a = conn.execute("DELETE FROM activities WHERE source='demo'")
    cur_l = conn.execute("DELETE FROM training_log WHERE source='demo'")
    conn.execute("DELETE FROM splits WHERE activity_id NOT IN (SELECT activity_id FROM activities)")
    conn.commit()
    return cur_d.rowcount + cur_a.rowcount + cur_l.rowcount


def has_real_data(conn):
    return conn.execute("SELECT 1 FROM days WHERE source='garmin' LIMIT 1").fetchone() is not None


def coverage(conn):
    """Per-metric non-null counts across the last 90 stored days."""
    rows = conn.execute(
        "SELECT COUNT(*) total, "
        "COUNT(resting_hr) resting_hr, COUNT(hrv_last_night) hrv, COUNT(sleep_seconds) sleep, "
        "COUNT(stress_avg) stress, COUNT(body_battery_high) body_battery, COUNT(spo2_avg) spo2, "
        "COUNT(training_readiness) readiness, COUNT(steps) steps "
        "FROM (SELECT * FROM days ORDER BY date DESC LIMIT 90)"
    ).fetchone()
    return dict(rows)


def overview(conn):
    rows = conn.execute("SELECT MIN(date) first_day, MAX(date) last_day, COUNT(*) n FROM days").fetchone()
    demo = conn.execute("SELECT 1 FROM days WHERE source='demo' LIMIT 1").fetchone() is not None
    latest = day_to_dict(conn.execute("SELECT * FROM days ORDER BY date DESC LIMIT 1").fetchone())
    return {
        "first_day": rows["first_day"],
        "last_day": rows["last_day"],
        "days": rows["n"],
        "demo": demo,
        "latest": latest,
        "last_sync": last_sync(conn),
        "activities": activity_count(conn),
        "log_entries": log_count(conn),
        "coverage": coverage(conn),
    }


def iso_days_back(n):
    return [(date.today() - timedelta(days=i)).isoformat() for i in range(int(n) - 1, -1, -1)]
