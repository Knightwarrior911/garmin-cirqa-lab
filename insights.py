"""Deterministic insight engine.

Turns collected Garmin data + the manual gym log into specific, numeric,
actionable guidance. No cloud, no LLM: every rule computes from the local
SQLite store and reports the numbers it used, or stays silent when there
is not enough data.

Called by serve.py (/api/insights) and query.py (`insights`).
"""
import statistics
from datetime import date, timedelta

import store

SEVERITY_ORDER = {"action": 0, "watch": 1, "info": 2}


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _pace_str(sec_per_km):
    if not sec_per_km:
        return "?"
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}"


def _hours(seconds):
    return seconds / 3600.0 if seconds else None


def _day_str(d):
    return d.isoformat()


def _activity_date(a):
    for key in ("start_iso", "start_local"):
        v = a.get(key)
        if v:
            return v[:10]
    return None


def _is_hard(a, log_hard_dates):
    return (a.get("avg_hr") or 0) >= 150 or (_activity_date(a) in log_hard_dates)


def build_guidance(conn):
    days = store.get_days(conn, 60)
    if len(days) < 5:
        return {
            "directive": "Collecting baseline",
            "headline": f"{len(days)} day(s) of data so far. Guidance and insights unlock at ~7 days.",
            "reasons": [],
            "confidence": "low",
        }
    latest = store.day_to_dict(days[-1])
    prior = days[:-1][-28:]
    hrv_base = _mean([d["hrv_last_night"] for d in prior]) or latest.get("hrv_last_night")
    rhr_base = _mean([d["resting_hr"] for d in prior])
    sleep7 = _mean([_hours(d["sleep_seconds"]) for d in days[-8:-1]])
    sleep_last = _hours(latest.get("sleep_seconds"))
    hrv_low = hrv_base and latest.get("hrv_last_night") and latest["hrv_last_night"] < hrv_base * 0.92
    rhr_high = rhr_base and latest.get("resting_hr") and latest["resting_hr"] >= rhr_base + 3
    sleep_poor = sleep_last is not None and (sleep7 and sleep_last < sleep7 - 1.0 or sleep_last < 6.5)

    y_date = _day_str(date.today() - timedelta(days=1))
    log = store.get_log(conn, 60)
    log_hard = {e["date"] for e in log if (e.get("rpe") or 0) >= 8}
    activities = store.get_activities(conn, 30)
    yesterday_hard = any(_activity_date(a) == y_date and _is_hard(a, log_hard) for a in activities)

    reasons = []
    if latest.get("hrv_last_night"):
        reasons.append(f"HRV {latest['hrv_last_night']} ms vs {round(hrv_base)} ms baseline"
                       + (" (suppressed)" if hrv_low else " (normal)"))
    if latest.get("resting_hr") and rhr_base:
        reasons.append(f"RHR {latest['resting_hr']} vs {round(rhr_base)} bpm baseline"
                       + (" (elevated)" if rhr_high else ""))
    if sleep_last:
        reasons.append(f"Sleep {sleep_last:.1f} h last night" + (" (short)" if sleep_poor else ""))
    if yesterday_hard:
        reasons.append("hard session yesterday")

    if hrv_low or rhr_high:
        return {"directive": "Recover today", "headline": "Keep it easy: aerobic or mobility only, protect sleep.",
                "reasons": reasons, "confidence": "medium"}
    if yesterday_hard and (sleep_poor or hrv_low):
        return {"directive": "Steady", "headline": "Quality is fine; keep volume controlled after yesterday's hard work.",
                "reasons": reasons, "confidence": "medium"}
    return {"directive": "Green light", "headline": "Recovery is holding. A quality session is a good trade today.",
            "reasons": reasons, "confidence": "high" if len(days) >= 14 else "medium"}


def rule_aerobic_efficiency(conn):
    runs = [r for r in store.runs_with_splits(conn, 15) if (r.get("distance_m") or 0) >= 3000]
    if len(runs) < 4:
        return None
    sessions = []
    hrs = []
    for r in runs:
        splits = store.get_splits(conn, r["activity_id"])
        if len(splits) < 3:
            continue
        dist = sum(s["distance_m"] or 0 for s in splits)
        dur = sum(s["duration_s"] or 0 for s in splits)
        hr = _mean([s.get("avg_hr") for s in splits])
        if not dist or not dur or not hr:
            continue
        sessions.append({"date": _activity_date(r), "pace": dur / dist * 1000.0, "hr": hr})
        hrs.append(hr)
    if len(sessions) < 4:
        return None
    med_hr = statistics.median(hrs)
    band = [s for s in sessions if abs(s["hr"] - med_hr) <= 6]
    if len(band) < 4:
        band = sessions
    band.sort(key=lambda s: s["date"])
    third = max(2, len(band) // 3)
    old, new = band[:third], band[-third:]
    old_pace, new_pace = _mean([s["pace"] for s in old]), _mean([s["pace"] for s in new])
    if not old_pace or not new_pace:
        return None
    pct = (old_pace - new_pace) / old_pace * 100.0
    conf = "high" if len(band) >= 8 else ("medium" if len(band) >= 6 else "low")
    if pct >= 1.5:
        return {"id": "aerobic_efficiency", "severity": "info", "confidence": conf,
                "title": f"Aerobic efficiency improving: {pct:.1f}% at the same heart rate",
                "finding": f"Pace at ~{round(med_hr)} bpm moved from {_pace_str(old_pace)} to "
                           f"{_pace_str(new_pace)} /km across {len(band)} runs.",
                "action": "Base is responding. Hold weekly volume steady and add one quality session per week; "
                          "do not raise volume and intensity in the same week."}
    if pct <= -1.5:
        return {"id": "aerobic_efficiency", "severity": "watch", "confidence": conf,
                "title": f"Aerobic efficiency declining: {abs(pct):.1f}% slower at the same heart rate",
                "finding": f"Pace at ~{round(med_hr)} bpm moved from {_pace_str(old_pace)} to "
                           f"{_pace_str(new_pace)} /km across {len(band)} runs.",
                "action": "Slower pace at the same HR usually means fatigue, not lost fitness. "
                          "Check sleep and resting-HR trend; keep everything easy for 5-7 days."}
    return None


def rule_pace_fade(conn):
    fades, worst = [], None
    runs = store.runs_with_splits(conn, 15)
    for r in runs:
        splits = store.get_splits(conn, r["activity_id"])
        if len(splits) < 3:
            continue
        first, last = splits[0].get("pace_s_per_km"), splits[-1].get("pace_s_per_km")
        if not first or not last:
            continue
        fade = (last - first) / first * 100.0
        fades.append(fade)
        if worst is None or fade > worst[0]:
            worst = (fade, r.get("name") or "run")
    if len(fades) < 2:
        return None
    avg = _mean(fades)
    if avg > 6:
        sev = "action"
    elif avg > 3:
        sev = "watch"
    else:
        return None
    return {"id": "pace_fade", "severity": sev,
            "confidence": "high" if len(fades) >= 4 else "low",
            "title": f"Pace fades {avg:.0f}% across your runs",
            "finding": f"First-to-last kilometre slowdown averages {avg:.0f}% over {len(fades)} runs "
                       f"(worst: {worst[0]:.0f}% on \"{worst[1]}\").",
            "action": "Strength endurance is the limiter. Add sled pushes/pulls, loaded carries, and finish "
                      "one easy run per week with 3 progressively faster kilometres."}


def rule_hr_drift(conn):
    drifts = []
    for r in store.runs_with_splits(conn, 15):
        splits = store.get_splits(conn, r["activity_id"])
        if len(splits) < 3:
            continue
        h0, h1 = splits[0].get("avg_hr"), splits[-1].get("avg_hr")
        if not h0 or not h1:
            continue
        drifts.append(h1 - h0)
    if len(drifts) < 2:
        return None
    avg = _mean(drifts)
    if avg < 8:
        return None
    return {"id": "hr_drift", "severity": "watch",
            "confidence": "high" if len(drifts) >= 4 else "low",
            "title": f"Heart rate drifts +{avg:.0f} bpm within runs",
            "finding": f"Split HR rises {avg:.0f} bpm from start to end at steady effort "
                       f"(mean of {len(drifts)} runs).",
            "action": "Classic aerobic-endurance signal. Keep ~80% of running genuinely easy and retest in 4 weeks."}


def _proxy_load(a):
    dur_min = (a.get("duration_s") or 0) / 60.0
    if not dur_min:
        return 0.0
    t = a.get("type") or ""
    factor = 1.0 if t in ("running", "hiit") else 0.8 if t == "strength_training" else 0.7
    if (a.get("avg_hr") or 0) >= 155:
        factor += 0.15
    return dur_min * factor


def rule_load_balance(conn, activities):
    today = date.today()
    def window_sum(start_off, end_off):
        lo, hi = today - timedelta(days=start_off), today - timedelta(days=end_off)
        return sum(_proxy_load(a) for a in activities
                   if (_ad := _activity_date(a)) and lo.isoformat() <= _ad <= hi.isoformat())
    acute = window_sum(6, 0)
    chronic_weeks = [window_sum(13, 7), window_sum(20, 14), window_sum(27, 21)]
    chronic = _mean(chronic_weeks)
    if not acute or not chronic:
        return None
    ratio = acute / chronic
    if ratio > 1.3:
        return {"id": "load_balance", "severity": "action", "confidence": "medium",
                "title": f"Training spike: load ratio {ratio:.2f}",
                "finding": f"This week's training load is {ratio:.2f}x your 3-week weekly average.",
                "action": "Spikes above ~1.3x raise injury risk. Cut volume 20-30% this week or "
                          "convert one hard session to easy aerobic."}
    if ratio < 0.7:
        return {"id": "load_balance", "severity": "info", "confidence": "medium",
                "title": f"Load is tapering: ratio {ratio:.2f}",
                "finding": f"This week's load is {ratio:.2f}x your 3-week weekly average.",
                "action": "Fine during recovery weeks. If unplanned, schedule your key sessions "
                          "for the next 7 days."}
    return None


def rule_intensity_mix(conn, activities, log_hard_dates):
    today = date.today()
    lo = (today - timedelta(days=27)).isoformat()
    recent = [a for a in activities if (_ad := _activity_date(a)) and _ad >= lo]
    if len(recent) < 6:
        return None
    hard = [a for a in recent if _is_hard(a, log_hard_dates)]
    share = len(hard) / len(recent)
    if share > 0.45:
        return {"id": "intensity_mix", "severity": "action", "confidence": "medium",
                "title": f"Too much time hard: {round(share * 100)}% of sessions",
                "finding": f"{len(hard)} of {len(recent)} sessions in the last 4 weeks were high intensity.",
                "action": "Cap hard sessions at ~2-3 per week. Convert the rest to easy aerobic "
                          "(nose-breathing pace, HR under ~145)."}
    if share < 0.1:
        return {"id": "intensity_mix", "severity": "info", "confidence": "medium",
                "title": "No high-intensity stimulus in 4 weeks",
                "finding": f"{len(hard)} of {len(recent)} sessions were high intensity.",
                "action": "Add one weekly quality session (intervals or HYROX circuit) to keep race pace available."}
    return None


def rule_recovery_coupling(conn, activities, log_hard_dates):
    days = {d["date"]: store.day_to_dict(d) for d in store.get_days(conn, 60)}
    hard_next, rest_next = [], []
    for dstr, row in days.items():
        hrv = row.get("hrv_last_night")
        if not hrv:
            continue
        try:
            prev = date.fromisoformat(dstr) - timedelta(days=1)
        except ValueError:
            continue
        prev_s = _day_str(prev)
        prev_hard = any(_activity_date(a) == prev_s and _is_hard(a, log_hard_dates) for a in activities) \
            or prev_s in log_hard_dates
        (hard_next if prev_hard else rest_next).append(hrv)
    if len(hard_next) < 3 or len(rest_next) < 3:
        return None
    h, r = _mean(hard_next), _mean(rest_next)
    if not h or not r:
        return None
    drop = (r - h) / r * 100.0
    if drop > 8:
        return {"id": "recovery_coupling", "severity": "watch", "confidence": "medium",
                "title": f"HRV drops {drop:.0f}% the day after hard sessions",
                "finding": f"Morning HRV averages {round(h)} ms after hard days vs {round(r)} ms after rest days "
                           f"({len(hard_next)} vs {len(rest_next)} mornings).",
                "action": "Place hard sessions after rest days, keep the day after truly easy, "
                          "and prioritize sleep on strength days."}
    return None


def rule_rhr_trend(conn):
    days = [store.day_to_dict(d) for d in store.get_days(conn, 60)]
    vals = [(d["date"], d["resting_hr"]) for d in days if d["resting_hr"] is not None]
    if len(vals) < 10:
        return None
    recent = [v for _, v in vals[-7:]]
    prior = [v for _, v in vals[-28:-7]]
    if len(prior) < 5:
        return None
    a, b = _mean(prior), _mean(recent)
    diff = b - a
    if diff >= 3:
        return {"id": "rhr_trend", "severity": "watch", "confidence": "high",
                "title": f"Resting HR up {diff:+.0f} bpm vs baseline",
                "finding": f"7-day average {b:.0f} bpm vs {a:.0f} bpm over the prior 3 weeks.",
                "action": "Elevated RHR signals fatigue or oncoming illness. Cap intensity for 2-3 days "
                          "and watch morning HRV."}
    if diff <= -3:
        return {"id": "rhr_trend", "severity": "info", "confidence": "high",
                "title": f"Resting HR improving: {diff:+.0f} bpm vs baseline",
                "finding": f"7-day average {b:.0f} bpm vs {a:.0f} bpm over the prior 3 weeks.",
                "action": "Aerobic fitness is trending the right way. Hold the current structure."}
    return None


def rule_hrv_trend(conn):
    days = [store.day_to_dict(d) for d in store.get_days(conn, 60)]
    vals = [(d["date"], d["hrv_last_night"]) for d in days if d["hrv_last_night"] is not None]
    if len(vals) < 10:
        return None
    recent = [v for _, v in vals[-7:]]
    prior = [v for _, v in vals[-28:-7]]
    if len(prior) < 5:
        return None
    a, b = _mean(prior), _mean(recent)
    if not a or not b:
        return None
    pct = (b - a) / a * 100.0
    if pct <= -10:
        return {"id": "hrv_trend", "severity": "watch", "confidence": "high",
                "title": f"HRV suppressed {abs(pct):.0f}% vs baseline",
                "finding": f"7-day average {round(b)} ms vs {round(a)} ms over the prior 3 weeks.",
                "action": "Sustained HRV suppression means recovery debt. Prioritize sleep, cut intensity "
                          "until HRV returns toward baseline."}
    if pct >= 10:
        return {"id": "hrv_trend", "severity": "info", "confidence": "high",
                "title": f"HRV trending up {pct:+.0f}%",
                "finding": f"7-day average {round(b)} ms vs {round(a)} ms over the prior 3 weeks.",
                "action": "Recovery capacity is expanding - a good window for progressive overload."}
    return None


def rule_sleep(conn):
    days = [store.day_to_dict(d) for d in store.get_days(conn, 30)]
    hours = [_hours(d.get("sleep_seconds")) for d in days[-8:-1]]
    hours = [h for h in hours if h]
    if len(hours) < 4:
        return None
    avg = _mean(hours)
    if avg < 7.0:
        debt_min = (8.0 - avg) * 60
        return {"id": "sleep_debt", "severity": "action", "confidence": "high",
                "title": f"Sleep debt: averaging {avg:.1f} h/night",
                "finding": f"7-night average is {debt_min:.0f} minutes below the 8-hour target.",
                "action": "Recovery adaptations (HRV, pace at HR) stall in sleep debt. Move bedtime 30-45 min "
                          "earlier for one week and re-check HRV."}
    sd = statistics.stdev(hours) if len(hours) >= 3 else 0
    if sd > 1.1:
        return {"id": "sleep_consistency", "severity": "watch", "confidence": "medium",
                "title": f"Irregular sleep: +/-{sd:.1f} h night to night",
                "finding": f"7-night average {avg:.1f} h but high variance.",
                "action": "Fix a consistent sleep window; irregular timing suppresses HRV even at normal duration."}
    return None


def rule_easy_gap(conn, activities):
    today = date.today()
    easy_dates = sorted((_activity_date(a) for a in activities
                         if (a.get("avg_hr") or 999) < 145 and (a.get("type") or "")
                         not in ("strength_training",)), reverse=True)
    if not easy_dates:
        return None
    try:
        gap = (today - date.fromisoformat(easy_dates[0])).days
    except ValueError:
        return None
    if gap > 4:
        return {"id": "easy_gap", "severity": "action", "confidence": "high",
                "title": f"No easy aerobic session for {gap} days",
                "finding": f"Last low-intensity aerobic work was {easy_dates[0]}.",
                "action": "Schedule 30-45 min at conversational pace (HR < 145) today or tomorrow; "
                          "easy volume is what makes hard days work."}
    return None


def rule_strength_freq(conn, activities):
    today = date.today()
    lo = (today - timedelta(days=13)).isoformat()
    dates = set()
    for e in store.get_log(conn, 60):
        if (e.get("session") or "").lower().startswith("strength") and e["date"] >= lo:
            dates.add(e["date"])
    for a in activities:
        if (a.get("type") == "strength_training" and (_ad := _activity_date(a)) and _ad >= lo):
            dates.add(_ad)
    n = len(dates)
    if n >= 3:
        return None
    sev = "info" if n > 0 else "action"
    hint = "" if n > 0 else " Log them in the Training Log tab so recovery coupling can be computed."
    return {"id": "strength_freq", "severity": sev, "confidence": "high",
            "title": f"Only {n} strength session(s) in 14 days",
            "finding": f"Detected {n} strength day(s) since {lo}." + hint,
            "action": "HYROX rewards 2-3 strength sessions weekly: lower-body push/pull, loaded carries, "
                      "and wall-ball volume."}


def rule_spo2(conn):
    days = [store.day_to_dict(d) for d in store.get_days(conn, 10)]
    lows = [(d["date"], d["spo2_avg"]) for d in days if d["spo2_avg"] is not None and d["spo2_avg"] < 93]
    if not lows:
        return None
    d, v = lows[-1]
    return {"id": "spo2_low", "severity": "info", "confidence": "low",
            "title": f"Low SpO2 night: {v:.0f}%",
            "finding": f"Average SpO2 dipped to {v:.1f}% on {d}.",
            "action": "Occasional dips are common. Repeated low nights: check for illness, congestion, "
                      "or alcohol before bed."}


def rule_run_volume_ramp(conn, activities):
    today = date.today()
    weeks = []
    for w in range(4):
        lo = (today - timedelta(days=7 * (w + 1))).isoformat()
        hi = (today - timedelta(days=7 * w)).isoformat()
        km = sum((a.get("distance_m") or 0) / 1000.0 for a in activities
                 if (_ad := _activity_date(a)) and lo <= _ad < hi and a.get("type") == "running")
        weeks.append(km)
    this_wk, prior = weeks[0], [w for w in weeks[1:] if w > 0]
    if not prior or this_wk <= 0:
        return None
    avg_prior = _mean(prior)
    ramp = this_wk / avg_prior
    if ramp > 1.3:
        return {"id": "run_ramp", "severity": "watch", "confidence": "medium",
                "title": f"Run volume ramping fast: {ramp:.1f}x",
                "finding": f"This week {this_wk:.1f} km vs {avg_prior:.1f} km weekly average of prior weeks.",
                "action": "Keep weekly run increases under ~10% beyond this week to protect tendons."}
    return None


def generate(conn):
    days = store.get_days(conn, 60)
    activities = store.get_activities(conn, 100)
    log = store.get_log(conn, 100)
    log_hard_dates = {e["date"] for e in log if (e.get("rpe") or 0) >= 8}

    insights = [
        rule_aerobic_efficiency(conn),
        rule_pace_fade(conn),
        rule_hr_drift(conn),
        rule_load_balance(conn, activities),
        rule_intensity_mix(conn, activities, log_hard_dates),
        rule_recovery_coupling(conn, activities, log_hard_dates),
        rule_rhr_trend(conn),
        rule_hrv_trend(conn),
        rule_sleep(conn),
        rule_easy_gap(conn, activities),
        rule_strength_freq(conn, activities),
        rule_spo2(conn),
        rule_run_volume_ramp(conn, activities),
    ]
    insights = [i for i in insights if i]
    insights.sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], i["id"]))
    return {"guidance": build_guidance(conn), "insights": insights[:8],
            "data_days": len(days), "generated_at": store.now_iso()}
