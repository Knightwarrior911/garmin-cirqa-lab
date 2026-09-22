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

POLICY = "1"


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
    object_fields(payload, ("goal", "sport", "weekdays", "minutes", "experience", "equipment", "routine"))
    for key, options in {
        "goal": ("general_fitness", "endurance", "strength"),
        "sport": ("walking", "running", "cycling", "strength"),
        "experience": ("beginner", "regular"),
        "equipment": ("none", "bike", "gym"),
    }.items():
        if payload[key] not in options:
            raise ValueError(f"Choose a supported {key}.")
    weekdays = payload["weekdays"]
    if not isinstance(weekdays, list) or not 1 <= len(weekdays) <= 7:
        raise ValueError("Choose one to seven training days.")
    weekdays = [bounded(day, 0, 6, "Weekday", True) for day in weekdays]
    if len(set(weekdays)) != len(weekdays):
        raise ValueError("Training days must not repeat.")
    minutes = bounded(payload["minutes"], 10, 120, "Available minutes", True)
    if (payload["goal"] == "strength") != (payload["sport"] == "strength"):
        raise ValueError("Choose strength as both the goal and activity, or choose a cardio activity for a fitness/endurance goal.")
    if payload["sport"] == "cycling" and payload["equipment"] != "bike":
        raise ValueError("Cycling requires access to a bike.")
    routine = payload["routine"]
    if not isinstance(routine, list) or len(routine) > 12:
        raise ValueError("A routine may contain up to 12 movements.")
    if payload["sport"] == "strength" and not routine:
        raise ValueError("Enter an established strength routine; CIRQA does not guess exercises or weights.")
    if payload["sport"] != "strength" and routine:
        raise ValueError("Clear the strength routine for a cardio profile.")
    cleaned = []
    for move in routine:
        object_fields(move, ("name", "sets", "reps", "load_kg"))
        load = bounded(move["load_kg"], 0, 300, "Resistance in kg")
        if load and payload["equipment"] != "gym":
            raise ValueError("A weighted routine requires gym/weights equipment.")
        cleaned.append({
            "name": text(move["name"], 80, "Movement", True),
            "sets": bounded(move["sets"], 1, 5, "Sets", True),
            "reps": bounded(move["reps"], 1, 30, "Repetitions", True), "load_kg": load,
        })
    save_document(conn, "profile", dict(payload, weekdays=sorted(weekdays), minutes=minutes, routine=cleaned))


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


def recommendation(profile, checkin, today, days, activities, native, now_local):
    result = {
        "status": "setup", "title": "Set your goal and available training days",
        "source": "CIRQA rules", "policy_version": POLICY, "reasons": [], "steps": [],
        "limitations": [
            "Conservative planning aid, not Garmin Daily Suggested Workouts or medical clearance.",
            "This policy does not prescribe maximal efforts, predict injury, or automatically increase your workload.",
        ],
    }

    def decision(status, title, reason):
        result.update(status=status, title=title)
        result["reasons"].append(reason)
        return result

    if checkin and (checkin["pain"] or checkin["illness"]):
        result["limitations"].append("Do not use a wearable score to override pain or illness; seek appropriate care for concerning symptoms.")
        return decision("rest", "No workout prescription today", "Your current check-in reports pain or illness.")
    if not profile:
        return decision("setup", result["title"], "Your goal, routine and practical constraints have not been saved.")
    if not checkin:
        return decision("checkin", "Complete today's check-in", "Yesterday's fatigue or soreness is not assumed to describe today.")
    if max(checkin["fatigue"], checkin["soreness"]) >= 7:
        return decision("rest", "Defer demanding exercise today", "You reported fatigue or soreness of 7/10 or higher. This is a conservative product threshold, not a validated physiological cut-off.")
    if today.weekday() not in profile["weekdays"]:
        return decision("rest", "Keep your planned rest day", "Today is outside your chosen training days. Good readiness does not override your plan.")
    if any(activity_day(a) == today.isoformat() for a in activities):
        return decision("rest", "Your recorded activity counts today", "An activity is already recorded today. CIRQA does not automatically add a second session; review the recorded load and your existing plan.")
    scheduled = [w for w in native["workouts"] if w.get("date") == today.isoformat()]
    if scheduled:
        return decision("caution", "Review your Garmin calendar workout", "A Garmin calendar workout exists for today. Check its current instructions in Garmin Connect rather than layering a CIRQA session on top.")
    row = next((d for d in days if d["date"] == today.isoformat()), None)
    readiness = row.get("training_readiness") if row else None
    stamp = row.get("readiness_updated_at") if row else None
    try:
        measured = datetime.fromisoformat(stamp)
        measured = measured.replace(tzinfo=now_local.tzinfo) if measured.tzinfo is None else measured.astimezone(now_local.tzinfo)
        age_hours = (now_local - measured).total_seconds() / 3600
        fresh = measured.date() == today and 0 <= age_hours <= 12
    except (ValueError, TypeError):
        fresh = False
    if not finite(readiness) or not fresh:
        result["limitations"].append("Sync Garmin Connect and the dashboard. Missing or old readiness is not treated as recovery. The 12-hour freshness limit is a conservative product rule.")
        return decision("caution", "Today's recovery context is incomplete", "No native training-readiness measurement from today and within the preceding 12 hours is available. No structured session is prescribed.")
    result["reasons"].append(f"Garmin readiness: {readiness:g}/100, measured {stamp}. It is context, not an exercise clearance.")
    if readiness < 25:
        return decision("rest", "Keep today low demand", "Garmin readiness is below 25. CIRQA conservatively defers structured training rather than setting a target strain.")
    sleep = row.get("sleep_seconds")
    modifiers = []
    if readiness < 50:
        modifiers.append("readiness below 50")
    if finite(sleep) and sleep < 6 * 3600:
        modifiers.append("recorded sleep below six hours")
    if max(checkin["fatigue"], checkin["soreness"]) >= 4:
        modifiers.append("reported fatigue or soreness at least 4/10")
    if sleep is None:
        result["limitations"].append("No sleep duration is recorded for today; sleep adequacy is unknown.")
    recovery = row.get("recovery_time_hours")
    if finite(recovery) and recovery > 0:
        result["limitations"].append(f"Garmin reported {recovery:g} hours of recovery at the readiness update. This is not a live countdown or a prohibition on all movement.")
    result["limitations"].append("Readiness 25/50, sleep six hours and check-in 4/7 cut-offs are disclosed conservative rules, not validated personal thresholds.")
    sport = profile["sport"]
    result["reasons"].append(f"Goal: {profile['goal'].replace('_', ' ')}. Today is a chosen training day; available time is {profile['minutes']} minutes.")
    if sport == "strength":
        if modifiers:
            return decision("caution", "Defer the saved strength routine", "Recovery modifiers: " + ", ".join(modifiers) + ". No substitute weights or muscle-strain estimates are invented.")
        if today.weekday() in profile["weekdays"] and (today.weekday() - 1) % 7 in profile["weekdays"]:
            return decision("caution", "Separate repeats of this strength routine", "The same routine is scheduled on consecutive days. Adjust your training days or follow an individually designed split instead.")
        result["steps"] = [{"title": "Warm up", "minutes": None, "detail": "Use your established movement-specific warm-up; do not rush it to fit the time budget."}]
        for move in profile["routine"]:
            resistance = f"{move['load_kg']:g} kg as you entered" if move["load_kg"] else "bodyweight / no added resistance"
            result["steps"].append({"title": move["name"], "minutes": None, "detail": f"Your saved routine: {move['sets']} sets × {move['reps']} repetitions, {resistance}. Use your usual rests; stop for pain or form breakdown."})
        result["limitations"].append(f"These are your supplied prescriptions, not AI-selected weights. Stop at your {profile['minutes']}-minute budget rather than rushing unfinished sets. Exercise order and individual suitability are not validated by CIRQA.")
        return decision("suggestion", "Repeat your established strength routine", "No progression is applied. Your saved movements, sets, repetitions and resistance are preserved.")
    groups = {"walking": {"walking", "casual_walking"}, "running": {"running", "treadmill_running", "trail_running", "indoor_running"}, "cycling": {"cycling", "indoor_cycling", "road_biking", "mountain_biking"}}
    recent = [a["duration_s"] / 60 for a in activities if a.get("type") in groups[sport]
              and activity_day(a) and (today - timedelta(days=28)).isoformat() <= activity_day(a) < today.isoformat()
              and finite(a.get("duration_s")) and a["duration_s"] >= 60]
    minutes = profile["minutes"]
    if recent:
        minutes = min(minutes, max(1, int(median(recent))))
        result["reasons"].append(f"Duration is capped at the median of {len(recent)} recorded same-sport sessions in the preceding 28 days, not increased automatically.")
    else:
        minutes = min(minutes, 20)
        result["limitations"].append("No same-sport duration baseline in the preceding 28 days. A 20-minute maximum is a conservative introductory cap, not a fitness estimate; stop sooner if needed.")
    if profile["experience"] == "beginner":
        minutes = min(minutes, 20)
        result["reasons"].append("Beginner sessions are capped at 20 minutes under this policy.")
    if modifiers:
        minutes = min(minutes, 20)
        result["reasons"].append("Short, easy option only because of " + ", ".join(modifiers) + ". Rest is an acceptable alternative.")
    warm = min(5, minutes // 4) if minutes >= 4 else round(minutes / 4, 1)
    main = round(minutes - 2 * warm, 1)
    descriptions = {
        "walking": "Comfortable walking, able to converse normally. Do not chase a heart-rate target.",
        "running": "Conversational running with walk breaks whenever needed. No pace or heart-rate target is inferred.",
        "cycling": "Easy cycling on your available bike, at an effort that permits normal conversation; no invented watts or heart-rate zones.",
    }
    result["steps"] = [
        {"title": "Ease in", "minutes": warm, "detail": "Start more gently than the main segment."},
        {"title": "Easy " + sport, "minutes": main, "detail": descriptions[sport]},
        {"title": "Ease out", "minutes": warm, "detail": "Gradually reduce effort; end earlier if uncomfortable."},
    ]
    if profile["goal"] == "endurance":
        result["limitations"].append("This is aerobic-base maintenance, not a race-specific or progressive interval plan. No race goal, threshold pace or power has been inferred.")
    result["limitations"].append("Recorded duration is exposure, not proof of tolerance. Reported pain/illness overrides the suggestion; stop if symptoms develop.")
    return decision("suggestion", f"{minutes} minutes of easy {sport}", "The session is chosen from your goal and schedule; readiness only moderates it. No score target must be reached.")


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
        "SELECT activity_id,name,type,start_local,duration_s,training_load,aerobic_effect,anaerobic_effect,effect_label "
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
    return {
        "ok": True, "today": today_iso, "period": period, "profile": profile, "checkin": checkin,
        "load": {"today": aggregate(grouped.get(today_iso, [])), "acute": {"value": acute["acute_load"] if acute else None, "date": acute["date"] if acute else None}, "daily": daily},
        "comparisons": comparisons, "insights": insights, "activities": activities[:100], "native": native,
        "recommendation": recommendation(profile, checkin, today, days, activities, native, now_local),
    }
