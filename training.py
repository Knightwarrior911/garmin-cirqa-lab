"""Transparent training context: native measurements, reported effort, disclosed rules.

No WHOOP-equivalent score, inferred muscle strain, or injury prediction. Planner
thresholds are conservative product rules, not clinically validated cut-offs.
"""

from datetime import date, datetime, timedelta
import json
import math
import os
from statistics import median
from zoneinfo import ZoneInfo

POLICY = "3"
RUN_TYPES = frozenset(("running", "treadmill_running", "trail_running", "indoor_running", "track_running", "virtual_run", "ultra_run"))
STRENGTH_TYPES = frozenset(("strength_training", "strength", "functional_strength_training", "crossfit", "hiit"))


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def object_fields(payload, fields):
    if not isinstance(payload, dict) or set(payload) != set(fields):
        raise ValueError("Supply exactly these fields: " + ", ".join(fields) + ".")


def bounded(value, low, high, name, integer=False):
    if not finite(value) or not low <= value <= high or (integer and int(value) != value):
        raise ValueError(f"{name} must be {'an integer' if integer else 'a number'} from {low} to {high}.")
    return int(value) if integer else value


def text(value, maximum, name, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f"{name} must be {'nonempty ' if required else ''}text, at most {maximum} characters.")
    return value.strip()


def document(conn, kind):
    row = conn.execute("SELECT value_json FROM training_documents WHERE kind=?", (kind,)).fetchone()
    return json.loads(row[0]) if row else None


def save_document(conn, kind, value):
    conn.execute(
        "INSERT INTO training_documents(kind,value_json,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(kind) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
        (kind, json.dumps(value, allow_nan=False), datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def save_profile(conn, payload):
    object_fields(payload, ("race_date", "weekdays", "minutes", "experience", "surface",
                            "easy_pace_s_per_km", "tempo_pace_s_per_km", "weekly_km"))
    try:
        if not isinstance(payload["race_date"], str) or date.fromisoformat(payload["race_date"]).isoformat() != payload["race_date"]:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Choose a valid race date.") from None
    weekdays = payload["weekdays"]
    if not isinstance(weekdays, list) or not 1 <= len(weekdays) <= 7:
        raise ValueError("Choose at least one running day.")
    weekdays = [bounded(day, 0, 6, "Running weekday", True) for day in weekdays]
    if len(set(weekdays)) != len(weekdays):
        raise ValueError("Running days must not repeat.")
    if payload["experience"] not in ("beginner", "regular") or payload["surface"] not in ("outdoor", "treadmill"):
        raise ValueError("Choose your running experience and surface.")
    minutes = bounded(payload["minutes"], 10, 120, "Time available per run", True)
    for key in ("easy_pace_s_per_km", "tempo_pace_s_per_km"):
        if payload[key] is not None:
            bounded(payload[key], 120, 1200, "Pace in seconds per kilometre")
    easy, tempo = payload["easy_pace_s_per_km"], payload["tempo_pace_s_per_km"]
    if tempo is not None and easy is not None and tempo >= easy:
        raise ValueError("A known tempo pace must be faster than your comfortable easy pace. Leave it blank if unknown.")
    if payload["weekly_km"] is not None:
        bounded(payload["weekly_km"], 0, 250, "Usual weekly kilometres")
    save_document(conn, "profile", dict(payload, weekdays=sorted(weekdays), minutes=minutes))


def save_feedback(conn, payload):
    object_fields(payload, ("activity_id", "rpe", "soreness", "notes"))
    aid = text(payload["activity_id"], 80, "Activity ID", True)
    if not conn.execute("SELECT 1 FROM activities WHERE activity_id=?", (aid,)).fetchone():
        raise ValueError("Choose a recorded activity.")
    rpe = None if payload["rpe"] is None else bounded(payload["rpe"], 0, 10, "Whole-session effort")
    soreness = None if payload["soreness"] is None else bounded(payload["soreness"], 0, 10, "Post-session soreness", True)
    notes = text(payload["notes"], 500, "Notes")
    conn.execute(
        "INSERT INTO session_feedback(activity_id,rpe,soreness,notes,updated_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(activity_id) DO UPDATE SET rpe=excluded.rpe,soreness=excluded.soreness,"
        "notes=excluded.notes,updated_at=excluded.updated_at",
        (aid, rpe, soreness, notes, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def save_checkin(conn, payload, today_iso):
    object_fields(payload, ("date", "fatigue", "soreness", "pain", "illness"))
    if payload["date"] != today_iso:
        raise ValueError("This check-in is not dated today. Reload the page before saving.")
    for key in ("fatigue", "soreness"):
        bounded(payload[key], 0, 10, key.title(), True)
    if not isinstance(payload["pain"], bool) or not isinstance(payload["illness"], bool):
        raise ValueError("Pain and illness must be explicit yes/no answers.")
    save_document(conn, "checkin", payload)


def activity_day(activity):
    # Garmin's local recording date is the authoritative grouping, not UTC midnight.
    stamp = activity.get("start_local")
    if not isinstance(stamp, str):
        return None
    try:
        return date.fromisoformat(stamp[:10]).isoformat()
    except ValueError:
        return None


def session_load(activity):
    feedback = activity.get("feedback") or {}
    duration, rpe = activity.get("duration_s"), feedback.get("rpe")
    if finite(duration) and duration > 0 and finite(rpe):
        return round(duration / 60 * rpe, 1)
    return None


def aggregate(activities):
    loads = [a["training_load"] for a in activities if finite(a.get("training_load"))]
    perceived = [a["rpe_load"] for a in activities if a.get("rpe_load") is not None]
    return {
        "load": round(sum(loads), 1) if loads else None,
        "known": len(loads), "total": len(activities),
        "rpe_load": round(sum(perceived), 1) if perceived else None, "rated": len(perceived),
    }


def run_records(activities, today):
    start = (today - timedelta(days=28)).isoformat()
    return [a for a in activities if a.get("type") in RUN_TYPES and activity_day(a)
            and start <= activity_day(a) <= today.isoformat()
            and finite(a.get("duration_s")) and a["duration_s"] > 0]


def run_distance(activity):
    value = activity.get("distance_m")
    # An elapsed treadmill recording with zero distance cannot establish mileage.
    return value / 1000 if finite(value) and value > 0 else None


def quality_run(activity):
    effort = (activity.get("feedback") or {}).get("rpe")
    label = str(activity.get("effect_label") or "").upper()
    return ((finite(effort) and effort >= 6)
            or (finite(activity.get("aerobic_effect")) and activity["aerobic_effect"] >= 3.5)
            or any(k in label for k in ("TEMPO", "THRESHOLD", "VO2", "ANAEROBIC")))


def running_baseline(profile, recent, today):
    p = profile or {}
    prior = [a for a in recent if activity_day(a) < today.isoformat() and a["duration_s"] >= 300]
    easy_runs = [a for a in prior if run_distance(a) is not None and (
        (finite((a.get("feedback") or {}).get("rpe")) and a["feedback"]["rpe"] <= 4)
        or str(a.get("effect_label") or "").upper() in ("BASE", "RECOVERY", "AEROBIC_BASE"))]
    easy = p.get("easy_pace_s_per_km")
    source = "Your comfortable running benchmark" if easy is not None else "No usable easy-pace benchmark"
    if easy is None and len(easy_runs) >= 2:
        easy = round(median(a["duration_s"] / run_distance(a) for a in easy_runs), 1)
        source = f"Median of {len(easy_runs)} recorded easy-rated runs"
    monday = today - timedelta(days=today.weekday())
    completed = [a for a in prior if activity_day(a) < monday.isoformat()]
    totals = {}
    for a in completed:
        if run_distance(a) is not None:
            d = date.fromisoformat(activity_day(a))
            week = (d - timedelta(days=d.weekday())).isoformat()
            totals[week] = totals.get(week, 0) + run_distance(a)
    weekly = p.get("weekly_km")
    weekly_source = "Your reported usual weekly kilometres" if weekly is not None else "Weekly baseline not established"
    # Exclude the partially observed earliest week in the 28-day lookback.
    complete_start = today - timedelta(days=28)
    complete_start += timedelta(days=(7 - complete_start.weekday()) % 7)
    complete_totals = [v for k, v in totals.items() if k >= complete_start.isoformat()]
    complete_runs = [a for a in completed if activity_day(a) >= complete_start.isoformat()]
    if len(complete_totals) >= 3 and all(run_distance(a) is not None for a in complete_runs):
        weekly = round(median(complete_totals), 1)
        weekly_source = f"Median of {len(complete_totals)} complete recorded running weeks"
    dates = sorted({activity_day(a) for a in prior if a["duration_s"] >= 1200})
    recorded_base = len(dates) >= 6 and (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days >= 14
    established = p.get("experience") == "regular" and (recorded_base or (finite(p.get("weekly_km")) and p["weekly_km"] >= 8))
    note = source + ". " + weekly_source + "."
    if easy is None:
        note += " Add the pace or treadmill speed at which you can comfortably talk; unclassified run averages are not used."
    return {"source": source, "easy_pace_s_per_km": easy, "tempo_pace_s_per_km": p.get("tempo_pace_s_per_km"),
            "weekly_km": weekly, "weekly_source": weekly_source, "established": established, "note": note}


def race_phase(day, race):
    remaining = (race - day).days
    return ("post_race" if remaining < 0 else "race" if remaining == 0 else
            "taper" if remaining <= 7 else "specific" if remaining <= 14 else "build" if remaining <= 28 else "base")


def planned_kind(profile, day, race, established):
    if day == race:
        return "race"
    if day > race or (race - day).days == 1 or not profile or day.weekday() not in profile["weekdays"]:
        return "rest"
    days = profile["weekdays"]
    phase = race_phase(day, race)
    if phase == "taper" or not established:
        return "easy_run"
    quality = next((d for d in days if (d - 1) % 7 not in days and (d + 1) % 7 not in days), None)
    if len(days) >= 3 and day.weekday() == quality and day.weekday() != days[-1]:
        return "interval_run" if phase == "specific" else "tempo_run"
    if len(days) >= 2 and day.weekday() == days[-1]:
        return "long_run"
    return "easy_run"


RUN_NAMES = {"easy_run": "Easy run", "recovery_run": "Recovery run", "tempo_run": "Tempo run",
             "interval_run": "Controlled intervals", "long_run": "Long easy run", "rest": "No run planned",
             "race": "HYROX race day"}
PHASE_NAMES = {"base": "Settle into your running week", "build": "Easy volume + controlled tempo",
               "specific": "HYROX running rhythm", "taper": "Freshen up for race day",
               "race": "Race day", "post_race": "Recover and choose your next race"}


def week_target(baseline, phase, profile):
    km = baseline["weekly_km"]
    if not finite(km) or km <= 0 or not profile:
        return None
    # Maintain, rather than invent, a volume increase in a short race build.
    factor = .6 if phase == "taper" else .9 if phase == "specific" else 0 if phase == "post_race" else 1
    if baseline["easy_pace_s_per_km"]:
        km = min(km, len(profile["weekdays"]) * profile["minutes"] * 60 / baseline["easy_pace_s_per_km"])
    return round(km * factor, 1)


def running_context(profile, activities, today):
    recent = run_records(activities, today)
    baseline = running_baseline(profile, recent, today)
    race = date.fromisoformat(profile["race_date"] if profile else "2026-10-25")
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    weekly = [a for a in recent if activity_day(a) >= monday.isoformat()]
    known = [run_distance(a) for a in weekly if run_distance(a) is not None]
    distance = round(sum(known), 2) if known or not weekly else None
    phase = race_phase(today, race)
    target = week_target(baseline, "post_race" if today > race else race_phase(min(monday + timedelta(days=3), race), race), profile)
    remaining = round(max(0, target - distance), 2) if target is not None and distance is not None and len(known) == len(weekly) else None
    recent_rows = [dict(a, pace_s_per_km=round(a["duration_s"] / run_distance(a), 1) if run_distance(a) is not None else None) for a in recent]
    last = next((a for a in recent_rows if a["pace_s_per_km"] is not None), None)
    if last:
        last = dict(last, date=activity_day(last))
    plan = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        recorded = [a for a in weekly if activity_day(a) == day.isoformat()]
        kind = planned_kind(profile, day, race, baseline["established"])
        detail = "Future intention; today's recovery can shorten or replace it."
        title = RUN_NAMES[kind]
        if recorded:
            kind, title = "completed", f"{len(recorded)} recorded run" + ("s" if len(recorded) != 1 else "")
            vals = [run_distance(a) for a in recorded if run_distance(a) is not None]
            detail = f"{sum(vals):.2f} km recorded · distance available for {len(vals)}/{len(recorded)} runs." if vals else "Recorded duration is available; running distance is missing."
        elif day < today:
            detail = "No run recorded. Do not make up missed mileage."
        elif not profile:
            title, detail = "Choose your running days", "Your strength plan stays in Ladder."
        plan.append({"date": day.isoformat(), "kind": kind, "title": title, "detail": detail})
    race_plan = []
    cursor = monday
    while cursor <= race and len(race_plan) < 53:
        end = min(cursor + timedelta(days=6), race)
        stage = race_phase(min(cursor + timedelta(days=3), race), race)
        race_plan.append({"start": cursor.isoformat(), "end": end.isoformat(), "phase": stage,
                          "title": PHASE_NAMES[stage], "target_km": week_target(baseline, stage, profile),
                          "detail": "Keep your established volume; at most one separated quality run." if stage in ("base", "build") else
                                    "Short controlled repeats, separated from demanding work; no extra mileage." if stage == "specific" else
                                    "Reduce running volume, keep runs easy, and rest the day before HYROX. No catch-up sessions."})
        if not baseline["established"] and stage in ("base", "build", "specific"):
            race_plan[-1].update(title="Establish easy running",
                                 detail="Keep runs short and conversational. Quality work needs an established running baseline; future dates do not establish one automatically.")
        cursor += timedelta(days=7)
    all_known = [run_distance(a) for a in recent if run_distance(a) is not None]
    return {"last_run": last, "runs_28d": len(recent), "distance_28d_m": sum(all_known) * 1000 if all_known or not recent else None,
            "weekly_plan": plan, "note": "Running only. Ladder handles strength. Recorded kilometres can be partial; future sessions are intentions, not recovery clearance.",
            "week": {"start": monday.isoformat(), "end": sunday.isoformat(), "runs": len(weekly), "distance_km": distance,
                     "known_distance_runs": len(known), "total_runs": len(weekly), "minutes": round(sum(a["duration_s"] for a in weekly) / 60, 1),
                     "quality_runs": sum(quality_run(a) for a in weekly), "target_km": target, "remaining_km": remaining},
            "baseline": baseline, "race": {"date": race.isoformat(), "days_left": (race - today).days,
                                          "weeks_left": max(0, math.ceil((race - today).days / 7)), "phase": phase},
            "race_plan": race_plan, "recent_runs": recent_rows}


def run_step(title, minutes, detail, pace):
    return {"title": title, "minutes": round(minutes, 2), "detail": detail, "pace_s_per_km": pace,
            "speed_kmh": round(3600 / pace, 1) if pace else None,
            "distance_km": round(minutes * 60 / pace, 3) if pace else None}


def running_session(kind, minutes, baseline):
    easy, tempo = baseline["easy_pace_s_per_km"], baseline["tempo_pace_s_per_km"]
    gentle = round(easy * 1.15, 1) if easy else None
    warm = min(5, minutes / 4)
    steps = [run_step("Warm up", warm, "Start gently. Walk or jog; the displayed speed is a starting guide, not a minimum.", gentle)]
    if kind == "interval_run":
        segments = []
        for i in range(1, 5):
            segments.extend([run_step(f"Repeat {i} · controlled", 2, "RPE 6/10; controlled, not a sprint.", tempo),
                             run_step(f"Repeat {i} · easy", 2, "Jog or walk until breathing settles.", gentle)])
        steps.append({"title": "4 × 2 min controlled / 2 min easy", "minutes": 16,
                      "detail": "Four controlled repeats, each followed by easy recovery.", "segments": segments,
                      "pace_s_per_km": tempo, "speed_kmh": round(3600 / tempo, 1) if tempo else None, "distance_km": None})
        steps.append(run_step("Cool down", minutes - warm - 16, "Easy jog or walk. Stop earlier if uncomfortable.", gentle))
    else:
        work_pace = tempo if kind == "tempo_run" else round(easy * 1.1, 1) if easy and kind == "recovery_run" else easy
        cue = "Comfortably hard, RPE 6/10. Short phrases, never gasping." if kind == "tempo_run" else "RPE 2–3/10; very relaxed, walk breaks welcome." if kind == "recovery_run" else "Conversational, RPE 3–4/10. Slow down if you cannot speak full sentences."
        steps.append(run_step(RUN_NAMES[kind], minutes - 2 * warm, cue, work_pace))
        steps.append(run_step("Cool down", warm, "Finish gently; no sprint finish.", gentle))
    return steps


def recommendation(profile, checkin, today, days, activities, native, now_local, running):
    result = {"status": "setup", "title": "Set up your running plan", "kind": "rest", "source": "CIRQA running guidance",
              "policy_version": POLICY, "reasons": [], "steps": [], "adjustments": [], "target": "", "demand": "",
              "minutes": None, "distance_km": None, "pace_s_per_km": None, "speed_kmh": None,
              "baseline_note": running["baseline"]["note"],
              "limitations": ["Starting targets, not Garmin Daily Suggested Workouts, a validated personalised race plan or medical clearance.",
                              "Paces come from your benchmarks or explicitly easy-rated runs. Slower warm-up/recovery targets are coaching estimates; adjust to effort.",
                              "Readiness 25/50, sleep 6h, Body Battery 25, recovery 24h and symptom 4/7 boundaries are conservative product rules, not validated individual cut-offs."]}
    def stop(status, title, reason):
        result.update(status=status, title=title, target=reason)
        result["reasons"].append(reason)
        return result
    if checkin and (checkin["pain"] or checkin["illness"]):
        return stop("rest", "No run today", "Pain or illness overrides your plan and every wearable score. Seek appropriate care for concerning symptoms.")
    if not profile:
        return stop("setup", result["title"], "Choose running days and your comfortable pace or treadmill speed. Ladder remains your strength plan.")
    remaining_days = running["race"]["days_left"]
    if remaining_days < 0:
        return stop("setup", "Your race date has passed", "Update the race date before starting another training block.")
    if remaining_days == 0:
        result["kind"] = "race"
        return stop("rest", "HYROX race day", "No extra training run today. Follow your established race strategy, event guidance and symptoms.")
    if any(a.get("type") in RUN_TYPES and activity_day(a) == today.isoformat() and finite(a.get("duration_s")) and a["duration_s"] >= 300 for a in activities):
        return stop("rest", "Your run is recorded", "Today's run counts. Review it in This week; no automatic second run or make-up mileage.")
    kind = planned_kind(profile, today, date.fromisoformat(profile["race_date"]), running["baseline"]["established"])
    if kind == "rest":
        return stop("rest", "No run planned today", "Keep your chosen non-running day." if remaining_days > 1 else "Rest your legs the day before HYROX; no last-minute fitness session.")
    if not checkin:
        return stop("checkin", "How do your legs feel today?", "Confirm your symptoms before the app turns today's plan into a run.")
    if max(checkin["fatigue"], checkin["soreness"]) >= 7:
        return stop("rest", "Recover today", "Reported fatigue or soreness is at least 7/10. Skip the run rather than chasing weekly kilometres.")
    if any(w.get("date") == today.isoformat() for w in native["workouts"]):
        return stop("caution", "Check today's Garmin workout", "A scheduled workout exists. Review it in Garmin Connect before adding a separate run.")
    row = next((d for d in days if d["date"] == today.isoformat()), {})
    stamp = row.get("readiness_updated_at")
    try:
        measured = datetime.fromisoformat(stamp)
        measured = measured.replace(tzinfo=now_local.tzinfo) if measured.tzinfo is None else measured.astimezone(now_local.tzinfo)
        fresh = measured.date() == today and 0 <= (now_local - measured).total_seconds() <= 43200
    except (ValueError, TypeError):
        fresh = False
    readiness = row.get("training_readiness")
    if not finite(readiness) or not fresh:
        return stop("caution", "Sync today's recovery first", "Sync CIRQA in Garmin Connect, then Sync now on Watch. Readiness must be from today and within 12 hours; missing is not recovered.")
    result["reasons"].append(f"Native readiness {readiness:g}/100, recorded {stamp}; no live recovery countdown is assumed.")
    if readiness < 25:
        return stop("rest", "Recovery instead of a run", "Native readiness is below 25. Do not chase the week's distance today.")
    week, baseline = running["week"], running["baseline"]
    if week["remaining_km"] is not None and week["remaining_km"] <= 0:
        return stop("rest", "This week's running guide is met", "No extra running is needed to fill a target. Keep recovery and your existing Ladder plan in view.")
    result["reasons"].append(f"This week: {week['runs']} recorded runs; {week['quality_runs']} identifiable quality runs. Distance coverage {week['known_distance_runs']}/{week['total_runs']}.")
    if not baseline["established"]:
        result["adjustments"].append("Start with easy running: an established recent running baseline has not been supplied or recorded.")
    prior = [a for a in run_records(activities, today) if activity_day(a) < today.isoformat() and a["duration_s"] >= 300]
    if baseline["established"] and finite(baseline["weekly_km"]) and baseline["easy_pace_s_per_km"]:
        duration_base = baseline["weekly_km"] * baseline["easy_pace_s_per_km"] / 60 / len(profile["weekdays"])
    else:
        duration_base = median(a["duration_s"] / 60 for a in prior) if prior else 20
    minutes = min(profile["minutes"], max(10, int(duration_base)))
    if kind == "long_run" and prior:
        minutes = min(profile["minutes"], max(minutes, int(max(a["duration_s"] for a in prior) / 60)))
    if not baseline["established"]:
        minutes = min(minutes, 20)
    recovery_flags = []
    quality_flags = []
    if readiness < 50: recovery_flags.append("readiness below 50")
    sleep = row.get("sleep_seconds")
    if finite(sleep) and sleep < 21600: recovery_flags.append("less than six hours' sleep")
    if sleep is None: quality_flags.append("sleep duration unavailable")
    if max(checkin["fatigue"], checkin["soreness"]) >= 4: recovery_flags.append("reported fatigue or sore legs")
    if finite(row.get("body_battery_current")) and row["body_battery_current"] < 25: recovery_flags.append("low recorded Body Battery")
    if str(row.get("hrv_status") or "").upper() in ("LOW", "UNBALANCED"): quality_flags.append("HRV outside your balanced range")
    if finite(row.get("recovery_time_hours")) and row["recovery_time_hours"] > 24: quality_flags.append("more than 24 recorded recovery hours")
    if finite(row.get("stress_avg")) and row["stress_avg"] > 50: quality_flags.append("elevated recorded daily stress")
    recent_work = [a for a in activities if activity_day(a) and (today - timedelta(days=2)).isoformat() <= activity_day(a) <= today.isoformat()]
    lifting = any(a.get("type") in STRENGTH_TYPES and finite(a.get("duration_s")) and a["duration_s"] >= 600 for a in recent_work)
    if lifting: quality_flags.append("recent recorded strength/HIIT work; Ladder already adds demand")
    if any(a.get("type") in RUN_TYPES and quality_run(a) for a in recent_work): quality_flags.append("a recent demanding run")
    if any(a.get("type") in RUN_TYPES and activity_day(a) == (today - timedelta(days=1)).isoformat() for a in recent_work): quality_flags.append("you ran yesterday")
    if week["quality_runs"]: quality_flags.append("this week's quality run is already recorded")
    if week["known_distance_runs"] < week["total_runs"]: quality_flags.append("this week's running distance is incomplete")
    original = kind
    if recovery_flags:
        kind, minutes = "recovery_run", min(minutes, 20)
        result["adjustments"].append("Short recovery option instead: " + "; ".join(recovery_flags) + ". Rest is also acceptable.")
    elif quality_flags and kind in ("tempo_run", "interval_run", "long_run"):
        kind, minutes = "easy_run", min(minutes, 30)
        result["adjustments"].append("Easy running replaces the planned session: " + "; ".join(quality_flags) + ".")
    elif quality_flags:
        result["reasons"].append("Keep it easy: " + "; ".join(quality_flags) + ".")
    if kind in ("tempo_run", "interval_run") and minutes < (26 if kind == "interval_run" else 25):
        kind = "easy_run"
        result["adjustments"].append("Your current duration budget is too short for a separated warm-up, quality work and cool-down.")
    if kind == "tempo_run": minutes = min(minutes, 25)
    if kind == "interval_run": minutes = 30 if minutes >= 30 else 26
    if remaining_days <= 7:
        kind = "recovery_run" if kind == "recovery_run" else "easy_run"
        minutes = min(minutes, 15 if remaining_days <= 3 else max(10, int(minutes * .65)))
        result["adjustments"].append("Race-week taper: reduce volume and avoid hard running. Do not make up missed sessions.")
    easy = baseline["easy_pace_s_per_km"]
    if week["remaining_km"] is not None and easy:
        budget_minutes = int(week["remaining_km"] * easy / 60)
        if budget_minutes < 10:
            return stop("rest", "No extra mileage to chase", "Less than a short easy session remains in this week's guide. Do not squeeze in a run just to hit a number.")
        if minutes > budget_minutes:
            kind, minutes = "easy_run", budget_minutes
            result["adjustments"].append("Shortened to stay within this week's remaining running guide.")
    steps = running_session(kind, minutes, baseline)
    flattened = [part for step in steps for part in step.get("segments", [step])]
    distance = round(sum(s["distance_km"] for s in flattened), 2) if all(s["distance_km"] is not None for s in flattened) else None
    if distance is not None and week["remaining_km"] is not None and distance > week["remaining_km"]:
        kind = "easy_run"
        steps = running_session(kind, minutes, baseline)
        distance = round(sum(s["distance_km"] for s in steps), 2)
        result["adjustments"].append("Easy running replaces faster work to keep the estimated distance within this week's remaining guide.")
    pace = baseline["tempo_pace_s_per_km"] if kind in ("tempo_run", "interval_run") else round(easy * 1.1, 1) if easy and kind == "recovery_run" else easy
    if kind in ("tempo_run", "interval_run") and pace is None:
        result["baseline_note"] += " Tempo pace is unknown: use the effort cue, or add your known tempo benchmark for numeric work-step targets."
    result["reasons"].append(f"Planned {RUN_NAMES[original].lower()} in the {running['race']['phase'].replace('_', ' ')} phase, {remaining_days} days before HYROX.")
    result.update(status="suggestion", kind=kind, title=RUN_NAMES[kind], minutes=minutes, steps=steps,
                  distance_km=distance, pace_s_per_km=pace, speed_kmh=round(3600 / pace, 1) if pace else None,
                  demand="Controlled · RPE 6/10 in work steps" if kind in ("tempo_run", "interval_run") else "Easy · conversational",
                  target="Follow the steps below. Pace and treadmill speed refer to the main work; estimated distance includes warm-up and cool-down.")
    return result


def dashboard(conn, today_iso, period=7, now_local=None):
    today = date.fromisoformat(today_iso)
    if now_local is None:
        now_local = datetime.now(ZoneInfo(os.environ.get("CIRQA_TIMEZONE", "Asia/Kolkata")))
    if period not in (7, 28):
        raise ValueError("Choose a 7 or 28 day comparison.")
    profile = document(conn, "profile")
    checkin = document(conn, "checkin")
    if checkin and checkin.get("date") != today_iso:
        checkin = None
    feedback = {r["activity_id"]: dict(r) for r in conn.execute("SELECT * FROM session_feedback")}
    activities = [dict(r) for r in conn.execute(
        "SELECT activity_id,name,type,start_local,duration_s,distance_m,training_load,aerobic_effect,anaerobic_effect,effect_label "
        "FROM activities ORDER BY start_local DESC"
    )]
    for activity in activities:
        activity["feedback"] = feedback.get(activity["activity_id"])
        activity["rpe_load"] = session_load(activity)
    first = today - timedelta(days=2 * period)
    days = [dict(r) for r in conn.execute("SELECT * FROM days WHERE date BETWEEN ? AND ? ORDER BY date", (first.isoformat(), today_iso))]
    grouped = {}
    for activity in activities:
        day = activity_day(activity)
        if day:
            grouped.setdefault(day, []).append(activity)
    daily = [{"date": (today - timedelta(days=offset)).isoformat(), **aggregate(grouped.get((today - timedelta(days=offset)).isoformat(), []))} for offset in range(period - 1, -1, -1)]
    acute = next((d for d in reversed(days) if finite(d.get("acute_load"))), None)
    comparisons = []
    current_start = (today - timedelta(days=period)).isoformat()
    previous_start = first.isoformat()
    for key, label, unit, divisor in (("sleep_seconds", "Mean sleep", "hours", 3600), ("resting_hr", "Mean resting heart rate", "bpm", 1), ("hrv_last_night", "Mean overnight HRV", "ms", 1), ("acute_load", "Mean native acute load", "Garmin units", 1)):
        current = [d[key] / divisor for d in days if current_start <= d["date"] < today_iso and finite(d.get(key))]
        previous = [d[key] / divisor for d in days if previous_start <= d["date"] < current_start and finite(d.get(key))]
        a, b = (round(sum(v) / len(v), 2) if v else None for v in (current, previous))
        sufficient = min(len(current), len(previous)) >= math.ceil(period * .75)
        comparisons.append({"key": key, "label": label, "unit": unit, "current": a, "previous": b, "current_count": len(current), "previous_count": len(previous), "expected": period,
                            "change": round(a - b, 2) if sufficient else None,
                            "note": "Adjacent completed periods; today excluded. Change requires at least 75% observed-day coverage in both periods (a display rule, not statistical significance)."})
    current_acts = [a for a in activities if activity_day(a) and current_start <= activity_day(a) < today_iso]
    previous_acts = [a for a in activities if activity_day(a) and previous_start <= activity_day(a) < current_start]
    ca, pa = aggregate(current_acts), aggregate(previous_acts)
    # Totals may be partial; no inferred rest days or change claim from uneven collection.
    comparisons.insert(0, {"key": "exercise_load", "label": "Recorded exercise load", "unit": "Garmin units", "current": ca["load"], "previous": pa["load"],
                           "current_count": len({activity_day(a) for a in current_acts if finite(a.get("training_load"))}),
                           "previous_count": len({activity_day(a) for a in previous_acts if finite(a.get("training_load"))}), "expected": period, "change": None,
                           "note": f"Current: {ca['known']}/{ca['total']} recorded activities have load; previous: {pa['known']}/{pa['total']}. Day counts are days with load-bearing records. These are recorded totals, not verified complete training exposure; missing days are not rest days."})
    insights = []
    for item in comparisons:
        if item["change"] is not None:
            direction = "higher" if item["change"] > 0 else "lower" if item["change"] < 0 else "unchanged"
            insights.append(f"{item['label']} is {direction}" + (f" by {abs(item['change']):g} {item['unit']}" if item["change"] else "") + f" across the last two completed {period}-day periods ({item['current_count']}/{period} vs {item['previous_count']}/{period} observed days). This is descriptive, not a causal or recovery conclusion.")
    if not insights:
        insights.append("There is not enough observed-day coverage in both completed periods to describe changes reliably. Missing readings have not been filled in.")
    native = {"checked_at": None, "last_success_at": None, "range_start": None, "range_end": None, "error": None, "workouts": [], "plans_count": None}
    native.update(document(conn, "native_workouts") or {})
    running = running_context(profile, activities, today)
    import imported_plan
    saved_plan = imported_plan.context(conn, today_iso)
    decision = imported_plan.apply(saved_plan, running, checkin, today, days, activities, native, now_local) if saved_plan else recommendation(profile, checkin, today, days, activities, native, now_local, running)
    for planned in running["weekly_plan"]:
        if planned["date"] == today_iso and planned["kind"] != "completed":
            planned.update(kind=decision["kind"], title=decision["title"], detail=decision["target"])
    recovery = next((d for d in days if d["date"] == today_iso), {})
    return {
        "ok": True, "today": today_iso, "period": period, "profile": profile, "checkin": checkin,
        "imported_plan": saved_plan,
        "recovery": {"date": recovery.get("date"), "readiness": recovery.get("training_readiness"),
                     "readiness_updated_at": recovery.get("readiness_updated_at"),
                     "sleep_hours": recovery["sleep_seconds"] / 3600 if finite(recovery.get("sleep_seconds")) else None,
                     "hrv_status": recovery.get("hrv_status"), "body_battery": recovery.get("body_battery_current"),
                     "recovery_hours": recovery.get("recovery_time_hours"), "stress": recovery.get("stress_avg")},
        "load": {"today": aggregate(grouped.get(today_iso, [])), "acute": {"value": acute["acute_load"] if acute else None, "date": acute["date"] if acute else None}, "daily": daily},
        "comparisons": comparisons, "insights": insights, "activities": activities[:100], "native": native,
        "running": running,
        "recommendation": decision,
    }
