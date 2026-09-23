"""Private owner-authored plans: source targets, explicit scheduling and reported progress."""
from datetime import date, datetime, timedelta
import math
import re

import training

KIND = "imported_plan"
KINDS = {"easy_run", "recovery_run", "tempo_run", "interval_run", "compromised_run", "long_run", "rest", "race"}
HARD = {"tempo_run", "interval_run", "compromised_run"}


def iso(value):
    if not isinstance(value, str):
        raise ValueError("Use an ISO calendar date.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Use an ISO calendar date.") from None
    if parsed.isoformat() != value:
        raise ValueError("Use an ISO calendar date.")
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("Plan and session IDs must be short letters, digits, hyphens or underscores.")


def strings(values):
    if not isinstance(values, list) or len(values) > 30:
        raise ValueError("Supply a bounded list of notes.")
    for value in values:
        training.text(value, 2000, "Note")


def target(value, low, high, label):
    if value is None:
        return
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must be a two-value range or null.")
    for number in value:
        training.bounded(number, low, high, label)
    if value[0] > value[1]:
        raise ValueError(f"{label} range must be in ascending numeric order.")


def targets(item):
    target(item["pace_range_s_per_km"], 120, 1200, "Pace")
    target(item["speed_range_kmh"], 1, 40, "Treadmill speed")
    target(item["hr_range_bpm"], 30, 250, "Heart rate")


def validate(plan):
    training.object_fields(plan, ("id", "title", "start_date", "race_date", "source", "notes", "max_hr", "hr_guide", "goal", "weeks"))
    identifier(plan["id"])
    training.text(plan["title"], 200, "Plan title", True)
    training.text(plan["source"], 200, "Source", True)
    start, end = iso(plan["start_date"]), iso(plan["race_date"])
    if not 0 <= (date.fromisoformat(end) - date.fromisoformat(start)).days <= 366:
        raise ValueError("A plan must end on its race date within one year of its start.")
    strings(plan["notes"])
    if plan["max_hr"] is not None:
        training.bounded(plan["max_hr"], 50, 250, "Reported maximum HR")
    if not isinstance(plan["hr_guide"], list) or len(plan["hr_guide"]) > 12:
        raise ValueError("Supply at most twelve heart-rate guide entries.")
    for entry in plan["hr_guide"]:
        training.object_fields(entry, ("label", "bpm"))
        training.text(entry["label"], 100, "HR label", True)
        target(entry["bpm"], 30, 250, "HR guide")
        if entry["bpm"] is None:
            raise ValueError("An HR guide entry needs a range.")
    goal = plan["goal"]
    training.object_fields(goal, ("pace_range_s_per_km", "speed_range_kmh", "notes"))
    target(goal["pace_range_s_per_km"], 120, 1200, "Goal pace")
    target(goal["speed_range_kmh"], 1, 40, "Goal speed")
    strings(goal["notes"])
    if not isinstance(plan["weeks"], list) or not 1 <= len(plan["weeks"]) <= 53:
        raise ValueError("Supply dated plan weeks.")
    week_ids, session_ids, scheduled = set(), set(), set()
    previous_end = None
    count = 0
    for week in plan["weeks"]:
        training.object_fields(week, ("id", "title", "start", "end", "sessions"))
        identifier(week["id"])
        if week["id"] in week_ids:
            raise ValueError("Week IDs must be unique.")
        week_ids.add(week["id"])
        training.text(week["title"], 160, "Week title", True)
        ws, we = iso(week["start"]), iso(week["end"])
        if not start <= ws <= we <= end or (date.fromisoformat(we) - date.fromisoformat(ws)).days > 6 or (previous_end and ws <= previous_end):
            raise ValueError("Weeks must be ordered, non-overlapping and within the plan dates.")
        previous_end = we
        if not isinstance(week["sessions"], list) or not 1 <= len(week["sessions"]) <= 14:
            raise ValueError("Supply one to fourteen entries per week.")
        for session in week["sessions"]:
            count += 1
            training.object_fields(session, ("id", "title", "kind", "date", "summary", "pace_range_s_per_km", "speed_range_kmh", "hr_range_bpm", "steps", "notes"))
            identifier(session["id"])
            if session["id"] in session_ids:
                raise ValueError("Session IDs must be unique across the plan.")
            session_ids.add(session["id"])
            training.text(session["title"], 200, "Session title", True)
            training.text(session["summary"], 1000, "Session summary", True)
            if not isinstance(session["kind"], str) or session["kind"] not in KINDS:
                raise ValueError("Unsupported running session kind.")
            if session["date"] is not None:
                day = iso(session["date"])
                if not ws <= day <= we or day in scheduled or (session["kind"] == "race" and day != end):
                    raise ValueError("Session dates must be unique, inside their week; race stays on race day.")
                scheduled.add(day)
            targets(session)
            strings(session["notes"])
            if not isinstance(session["steps"], list) or len(session["steps"]) > 80 or (session["kind"] not in ("rest", "race") and not session["steps"]):
                raise ValueError("Running sessions need one to eighty steps.")
            for step in session["steps"]:
                training.object_fields(step, ("title", "mode", "minutes", "minutes_range", "distance_km", "pace_range_s_per_km", "speed_range_kmh", "hr_range_bpm", "detail"))
                training.text(step["title"], 200, "Step title", True)
                training.text(step["detail"], 2000, "Step detail")
                targets(step)
                target(step["minutes_range"], .1, 240, "Duration")
                if step["minutes"] is not None:
                    training.bounded(step["minutes"], .1, 240, "Step minutes")
                if step["distance_km"] is not None:
                    training.bounded(step["distance_km"], .01, 100, "Step kilometres")
                if step["mode"] == "timed":
                    valid = step["minutes"] is not None and step["minutes_range"] is None and step["distance_km"] is None
                elif step["mode"] == "distance":
                    valid = step["distance_km"] is not None and step["minutes"] is None and step["minutes_range"] is None
                elif step["mode"] == "manual":
                    valid = step["minutes"] is None and step["distance_km"] is None
                else:
                    valid = False
                if not valid:
                    raise ValueError("Step mode must match its supplied duration or distance; unknown values stay null.")
    if count > 160:
        raise ValueError("A plan can contain at most 160 sessions.")
    return plan


def entries(state):
    return [(week, session) for week in state["plan"]["weeks"] for session in week["sessions"]]


def scheduled_date(state, session):
    return state["dates"].get(session["id"], session["date"])


def update(conn, payload, today):
    if not isinstance(payload, dict):
        raise ValueError("Supply a plan action.")
    action = payload.get("action")
    fields = {"install": ("action", "plan"), "schedule": ("action", "session_id", "date"),
              "select": ("action", "session_id", "date"), "complete": ("action", "session_id", "activity_id"),
              "reopen": ("action", "session_id")}
    if not isinstance(action, str) or action not in fields:
        raise ValueError("Unsupported plan action.")
    training.object_fields(payload, fields[action])
    state = training.document(conn, KIND)
    if action == "install":
        plan = validate(payload["plan"])
        if state:
            if state["plan"] != plan:
                raise ValueError("A different plan is already saved. It has not been replaced or its progress discarded.")
            return
        training.save_document(conn, KIND, {"plan": plan, "dates": {}, "completed": {}, "selection": None})
        return
    if not state:
        raise ValueError("No imported plan is saved.")
    match = next(((w, s) for w, s in entries(state) if s["id"] == payload["session_id"]), None)
    if not match:
        raise ValueError("Session not found in the saved plan.")
    week, session = match
    sid = session["id"]
    if action == "schedule":
        chosen = payload["date"]
        if chosen is not None:
            chosen = iso(chosen)
            if not week["start"] <= chosen <= week["end"] or (session["kind"] == "race" and chosen != state["plan"]["race_date"]):
                raise ValueError("Choose a date inside this session's week; race stays on race day.")
        effective = chosen if chosen is not None else session["date"]
        if effective and any(s["id"] != sid and scheduled_date(state, s) == effective for _, s in entries(state)):
            raise ValueError("Another plan entry already occupies that day. Move it first; the app does not schedule double sessions.")
        if chosen is None:
            state["dates"].pop(sid, None)
        else:
            state["dates"][sid] = chosen
        if state["selection"] and state["selection"]["session_id"] == sid:
            state["selection"] = None
    elif action == "select":
        if payload["date"] != today or not week["start"] <= today <= week["end"] or sid in state["completed"]:
            raise ValueError("Choose an incomplete session from the current plan week for today.")
        if scheduled_date(state, session) not in (None, today):
            raise ValueError("This session is assigned to another day. Change its date before using it today.")
        if any(s["id"] != sid and scheduled_date(state, s) == today for _, s in entries(state)):
            raise ValueError("Another entry is assigned today. Change its date before selecting a different session.")
        state["selection"] = {"date": today, "session_id": sid}
    elif action == "complete":
        planned = scheduled_date(state, session)
        if week["start"] > today or (planned and planned > today):
            raise ValueError("Future sessions cannot be marked complete.")
        aid = payload["activity_id"]
        if aid is not None:
            training.text(aid, 100, "Activity ID", True)
            row = conn.execute("SELECT start_local FROM activities WHERE activity_id=?", (aid,)).fetchone()
            day = training.activity_day(dict(row)) if row else None
            if not day or not week["start"] <= day <= min(week["end"], today):
                raise ValueError("Link a recorded activity from this plan week, not a future or unrelated date.")
            if any(k != sid and value["activity_id"] == aid for k, value in state["completed"].items()):
                raise ValueError("That activity is already linked to another completed session.")
        state["completed"][sid] = {"date": today, "activity_id": aid}
    else:
        state["completed"].pop(sid, None)
    training.save_document(conn, KIND, state)


def context(conn, today):
    state = training.document(conn, KIND)
    if state is None:
        return None
    return dict(state, current_week_id=next((w["id"] for w in state["plan"]["weeks"] if w["start"] <= today <= w["end"]), None))


def selected(state, today):
    selection = state["selection"]
    if selection and selection["date"] == today:
        return next((s for _, s in entries(state) if s["id"] == selection["session_id"]), None)
    return next((s for _, s in entries(state) if scheduled_date(state, s) == today), None)


def totals(steps):
    exact = all(s["minutes"] is not None for s in steps)
    ranges = [([s["minutes"], s["minutes"]] if s["minutes"] is not None else s["minutes_range"]) for s in steps]
    # Distance steps, unspecified rests and station/jog distances prevent fabricated whole-session totals.
    minutes = round(sum(s["minutes"] for s in steps), 2) if steps and exact else None
    minutes_range = [round(sum(r[i] for r in ranges), 2) for i in (0, 1)] if steps and not exact and all(r is not None for r in ranges) else None
    return minutes, minutes_range


def apply(state, running, checkin, today, days, activities, native, now):
    plan = state["plan"]
    day = today.isoformat()
    race = date.fromisoformat(plan["race_date"])
    running["race"] = {"date": plan["race_date"], "days_left": (race - today).days,
                       "weeks_left": max(0, math.ceil((race - today).days / 7)), "phase": "owner_plan"}
    running["week"].update(target_km=None, remaining_km=None)
    running["note"] = "Garmin mileage below is Monday–Sunday. Your imported plan uses its own dated weeks; completion checkmarks never create kilometres."
    for item in running["weekly_plan"]:
        if item["kind"] != "completed":
            assigned = next((s for _, s in entries(state) if scheduled_date(state, s) == item["date"]), None)
            item.update(kind=assigned["kind"] if assigned else "rest", title=assigned["title"] if assigned else "No plan session assigned",
                        detail=assigned["summary"] if assigned else "Choose a session from the matching plan week; missed sessions are not automatic catch-up work.")
    session = selected(state, day)
    result = {"status": "plan", "title": "Choose today's plan session", "kind": "rest", "source": "Your imported plan",
              "policy_version": "owner-plan-1", "reasons": [], "steps": [], "adjustments": [], "target": "Open your plan week and choose Use today, or assign a date.", "demand": "",
              "minutes": None, "minutes_range": None, "distance_km": None, "pace_s_per_km": None, "speed_kmh": None,
              "pace_range_s_per_km": None, "speed_range_kmh": None, "hr_range_bpm": None,
              "planned_session": session, "plan_session_id": session["id"] if session else None,
              "baseline_note": "Targets are supplied by your plan, not inferred Garmin fitness or measured threshold. Original targets remain unchanged when today's guidance differs.",
              "limitations": ["Your supplied HR ranges and maximum HR are not validated personal zones or medical clearance.",
                              "Several hard sessions plus Ladder can accumulate fatigue. Do not chase pace or HR through pain or poor recovery.",
                              "Unknown warm-up, recovery, station and stride details remain unspecified. Distance steps require manual advancement; no live distance is measured."]}
    def stop(status, title, reason):
        result.update(status=status, title=title, target=reason)
        result["reasons"].append(reason)
        return result
    if checkin and (checkin["pain"] or checkin["illness"]):
        return stop("rest", "No run today", "Pain or illness overrides the plan. Seek appropriate care for concerning symptoms; the original session remains available to review.")
    if day < plan["start_date"]:
        return stop("plan", "Your plan starts " + date.fromisoformat(plan["start_date"]).strftime("%d %b"), "Your full board is saved. Assign session dates in Race plan; no extra workout has been invented before the start.")
    if day > plan["race_date"]:
        return stop("rest", "Your race block is complete", "Review your saved plan and progress. No automatic repeat or catch-up block is prescribed.")
    if not session:
        return result
    if session["id"] in state["completed"]:
        return stop("rest", "Plan session marked complete", "Your owner-confirmed progress is saved separately from Garmin's recorded activity and kilometres.")
    if session["kind"] in ("rest", "race"):
        result["kind"] = session["kind"]
        return stop("rest", session["title"], session["summary"] + ". Review the original plan and race notes below; no extra training run is prescribed.")
    if any(a.get("type") in training.RUN_TYPES and training.activity_day(a) == day and training.finite(a.get("duration_s")) and a["duration_s"] >= 300 for a in activities):
        return stop("rest", "Your run is recorded", "No automatic second run. Link the actual recording when marking the corresponding plan session complete.")
    if not checkin:
        return stop("checkin", "How do your legs feel today?", "Your planned session is shown below. Confirm today's symptoms before opening its workout guide.")
    if max(checkin["fatigue"], checkin["soreness"]) >= 7:
        return stop("rest", "Recover today", "Fatigue or soreness is at least 7/10. Defer the plan session rather than making up training.")
    if any(w.get("date") == day for w in native["workouts"]):
        return stop("caution", "Review today's Garmin workout", "A native scheduled workout also exists. Review it before adding this plan session.")
    row = next((d for d in days if d["date"] == day), {})
    stamp = row.get("readiness_updated_at")
    try:
        measured = datetime.fromisoformat(stamp)
        measured = measured.replace(tzinfo=now.tzinfo) if measured.tzinfo is None else measured.astimezone(now.tzinfo)
        fresh = measured.date() == today and 0 <= (now - measured).total_seconds() <= 43200
    except (TypeError, ValueError):
        fresh = False
    readiness = row.get("training_readiness")
    if not training.finite(readiness) or not fresh:
        return stop("caution", "Sync today's recovery first", "Readiness must be dated today and within twelve hours. You can still inspect your original plan; missing readings are not recovery clearance.")
    if readiness < 25:
        return stop("rest", "Recovery instead of the planned run", "Native readiness is below 25. Keep the plan for review, not as a mileage debt.")
    result["reasons"].append(f"Native readiness {readiness:g}/100, recorded {stamp}.")
    missing = [label for key, label in (("hrv_status", "HRV"), ("body_battery_current", "Body Battery"),
                                       ("recovery_time_hours", "recovery time"), ("stress_avg", "stress")) if row.get(key) is None]
    if missing:
        result["limitations"].append("Today's native " + ", ".join(missing) + " is unavailable; these are not assumed normal.")
    concerns = []
    if readiness < 50: concerns.append("readiness below 50")
    if max(checkin["fatigue"], checkin["soreness"]) >= 4: concerns.append("reported fatigue or soreness")
    if training.finite(row.get("sleep_seconds")) and row["sleep_seconds"] < 21600: concerns.append("less than six hours' sleep")
    if training.finite(row.get("body_battery_current")) and row["body_battery_current"] < 25: concerns.append("low recorded Body Battery")
    recent = [a for a in activities if training.activity_day(a) and (today - timedelta(days=2)).isoformat() <= training.activity_day(a) <= day]
    demanding = session["kind"] in HARD or session["kind"] == "long_run"
    if demanding:
        if row.get("sleep_seconds") is None: concerns.append("sleep duration missing")
        if str(row.get("hrv_status") or "").upper() in ("LOW", "UNBALANCED"): concerns.append("HRV outside your balanced range")
        if training.finite(row.get("recovery_time_hours")) and row["recovery_time_hours"] > 24: concerns.append("more than 24 recorded recovery hours")
        if training.finite(row.get("stress_avg")) and row["stress_avg"] > 50: concerns.append("elevated recorded stress")
        if any(a.get("type") in training.STRENGTH_TYPES and training.finite(a.get("duration_s")) and a["duration_s"] >= 600 for a in recent): concerns.append("recent strength/HIIT or Ladder work")
        if any(a.get("type") in training.RUN_TYPES and training.quality_run(a) for a in recent): concerns.append("recent demanding running")
        if any(a.get("type") in training.RUN_TYPES and training.activity_day(a) == (today - timedelta(days=1)).isoformat() for a in recent): concerns.append("you ran yesterday")
        if any(s["kind"] in HARD and s["id"] in state["completed"] and
               (today - timedelta(days=2)).isoformat() <= state["completed"][s["id"]]["date"] <= day
               for _, s in entries(state)):
            concerns.append("a recently confirmed hard plan session; confirmation date is not a verified recording timestamp")
    completed_hard = sum(s["kind"] in HARD and s["id"] in state["completed"] for w, s in entries(state) if w["id"] == state["current_week_id"])
    result["reasons"].append(f"This plan week: {completed_hard} hard sessions marked complete. Garmin calendar week: {running['week']['runs']} runs, {running['week']['quality_runs']} identifiable demanding runs. These are different records, not summed exposure.")
    if completed_hard >= 2 or running["week"]["quality_runs"] >= 2:
        result["reasons"].append("Multiple demanding sessions are already reported or recorded this week. Preserve separation and review cumulative fatigue; the imported plan is not replaced by a generic weekly quota.")
    if running["week"]["known_distance_runs"] < running["week"]["total_runs"]:
        result["limitations"].append("Recorded running distance is incomplete. No remaining-mileage quota is inferred.")
    if concerns:
        result["adjustments"].append("Recovery guidance differs from the original plan: " + "; ".join(concerns) + ". The plan itself has not been edited or completed.")
        recovery = next((s for _, s in entries(state) if s["kind"] == "recovery_run" and s["pace_range_s_per_km"]), None)
        if not recovery:
            return stop("caution", "Defer the demanding session", "Recovery concerns need review. Rest is acceptable; no replacement pace has been invented.")
        step = {"title": "Optional short recovery run", "mode": "timed", "minutes": 15, "minutes_range": None,
                "distance_km": None, "pace_range_s_per_km": recovery["pace_range_s_per_km"], "speed_range_kmh": recovery["speed_range_kmh"],
                "hr_range_bpm": None, "detail": "App adjustment, not the original session. Use easy conversational effort; rest instead if needed. Do not chase a heart-rate number."}
        result.update(status="suggestion", title="Recovery option instead", kind="recovery_run", source="CIRQA recovery adjustment to your plan", minutes=15,
                      steps=[step], pace_range_s_per_km=step["pace_range_s_per_km"], speed_range_kmh=step["speed_range_kmh"],
                      target="Optional 15-minute easy recovery using your plan's recovery pace range. This does not complete the original workout.")
        return result
    minutes, minutes_range = totals(session["steps"])
    result.update(status="suggestion", title=session["title"], kind=session["kind"], steps=session["steps"], minutes=minutes, minutes_range=minutes_range,
                  pace_range_s_per_km=session["pace_range_s_per_km"], speed_range_kmh=session["speed_range_kmh"], hr_range_bpm=session["hr_range_bpm"],
                  target=session["summary"] + ". Follow the original step targets; distance and unspecified-duration steps advance manually.")
    result["reasons"].append("Selected from your saved plan, not the generic one-quality-session weekly template. Your supplied targets are not proof of current fitness.")
    return result
