"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const forms = {
    profile: $("profile-form"),
    checkin: $("checkin-form"),
    feedback: $("feedback-form"),
  };
  const dirty = { profile: false, checkin: false, feedback: false };
  let data = null,
    period = 7,
    busy = false;
  const escape = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const number = (value, digits = 1) =>
    typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString(undefined, { maximumFractionDigits: digits })
      : "Unavailable";
  const field = (kind, name) => forms[kind].elements.namedItem(name);
  const list = (id, items) => {
    $(id).innerHTML = items.map((item) => `<li>${escape(item)}</li>`).join("");
  };
  const shiftDate = (day, offset) => {
    const d = new Date(`${day}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + offset);
    return d.toISOString().slice(0, 10);
  };
  const guide = {
    key: "",
    steps: [],
    index: 0,
    remaining: 0,
    deadline: 0,
    running: false,
    finished: false,
    durations: {},
  };
  const guideTime = () =>
    guide.running ? Math.max(0, guide.deadline - Date.now()) : guide.remaining;
  const guideMinutes = () =>
    guide.durations[guide.index] ?? guide.steps[guide.index]?.minutes;
  function drawGuide() {
    const step = guide.steps[guide.index];
    if (!step) return;
    const timed = finite(guideMinutes()),
      seconds = Math.ceil(guideTime() / 1000);
    $("guide-target").textContent = guide.finished ? "" : targetText(step);
    $("guide-clock").classList.toggle("manual-step", !timed);
    $("guide-clock").textContent = guide.finished
      ? "Done"
      : timed
        ? `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`
        : step.distance_km
          ? `${fmt(step.distance_km < 1 ? step.distance_km * 1000 : step.distance_km)} ${step.distance_km < 1 ? "m" : "km"}`
          : step.minutes_range
            ? rangeText(step.minutes_range) + " min"
            : "Manual";
    $("guide-progress").textContent =
      `STEP ${guide.index + 1} OF ${guide.steps.length}`;
    $("guide-step").textContent = guide.finished
      ? "Guide finished"
      : step.title;
    $("guide-detail").textContent = guide.finished
      ? "No activity or plan completion was created. Finish your CIRQA recording, sync Garmin Connect, then confirm the session you actually completed."
      : step.detail;
    const state = guide.finished
      ? "Finished"
      : guide.running
        ? "Running"
        : !timed
          ? "Manual step · Next when done"
          : seconds === 0
            ? "Step complete · Next when ready"
            : "Paused · Start when ready";
    if ($("guide-state").textContent !== state)
      $("guide-state").textContent = state;
    $("guide-toggle").hidden = !timed;
    $("guide-toggle").textContent = guide.running
      ? "Pause"
      : seconds === 0
        ? "Restart step"
        : "Start / resume";
    $("guide-toggle").disabled = guide.finished;
    $("guide-next").disabled = guide.finished;
    $("guide-next").textContent =
      guide.index === guide.steps.length - 1 ? "Finish guide" : "Next step";
    $("guide-duration-options").hidden =
      guide.finished ||
      finite(step.minutes) ||
      step.mode !== "manual" ||
      guide.running;
    $("guide-duration").min = step.minutes_range?.[0] ?? 0.1;
    $("guide-duration").max = step.minutes_range?.[1] ?? 240;
    $("guide-duration").placeholder = step.minutes_range
      ? rangeText(step.minutes_range)
      : "Your choice; not specified";
  }
  function pauseGuide() {
    guide.remaining = guideTime();
    guide.running = false;
    drawGuide();
  }
  function resetGuide() {
    guide.running = false;
    guide.finished = false;
    guide.index = 0;
    guide.durations = {};
    guide.remaining = (guide.steps[0]?.minutes || 0) * 60000;
    $("guide-duration").value = "";
    $("guide-duration-error").textContent = "";
    drawGuide();
  }
  function updateGuide() {
    const r = data.recommendation,
      steps =
        r.status === "suggestion"
          ? r.steps.flatMap((s) => s.segments || [s])
          : [];
    const eligible =
      steps.length > 0 &&
      steps.every(
        (s) =>
          (finite(s.minutes) && s.minutes > 0) ||
          (s.mode === "distance" &&
            finite(s.distance_km) &&
            s.distance_km > 0) ||
          s.mode === "manual",
      );
    $("guide-open").hidden = !eligible;
    const key = JSON.stringify([data.today, r.title, eligible ? steps : []]);
    if (key !== guide.key) {
      guide.key = key;
      guide.steps = eligible ? steps : [];
      resetGuide();
      if ($("guide-dialog").open) $("guide-dialog").close();
    }
    $("guide-title").textContent = r.title;
  }
  $("guide-open").onclick = () => {
    if (!guide.steps.length) return;
    drawGuide();
    $("guide-dialog").showModal();
  };
  $("guide-close").onclick = () => {
    pauseGuide();
    $("guide-dialog").close();
  };
  $("guide-dialog").addEventListener("cancel", pauseGuide);
  $("guide-dialog").addEventListener("close", pauseGuide);
  $("guide-toggle").onclick = () => {
    if (!finite(guideMinutes())) return;
    if (guide.running) pauseGuide();
    else {
      if (guide.remaining <= 0) guide.remaining = guideMinutes() * 60000;
      guide.deadline = Date.now() + guide.remaining;
      guide.running = true;
      drawGuide();
    }
  };
  $("guide-next").onclick = () => {
    guide.running = false;
    if (guide.index === guide.steps.length - 1) {
      guide.finished = true;
      guide.remaining = 0;
    } else {
      guide.index++;
      guide.remaining = (guideMinutes() || 0) * 60000;
    }
    $("guide-duration").value = "";
    $("guide-duration-error").textContent = "";
    drawGuide();
  };
  $("guide-apply-duration").onclick = () => {
    const step = guide.steps[guide.index],
      value = Number($("guide-duration").value),
      lo = step.minutes_range?.[0] ?? 0.1,
      hi = step.minutes_range?.[1] ?? 240;
    if (!finite(value) || value < lo || value > hi) {
      $("guide-duration-error").textContent =
        `Choose ${lo}–${hi} minutes. The original plan remains unchanged.`;
      return;
    }
    guide.durations[guide.index] = value;
    guide.remaining = value * 60000;
    guide.running = false;
    $("guide-duration-error").textContent =
      "Your optional timer is set; it is not an added source-plan duration.";
    drawGuide();
  };
  $("guide-reset").onclick = resetGuide;
  function tickGuide() {
    if (!guide.running) return;
    if (guideTime() === 0) {
      guide.remaining = 0;
      guide.running = false;
    }
    drawGuide();
  }
  setInterval(tickGuide, 500);
  document.addEventListener("visibilitychange", tickGuide);

  async function request(path, payload) {
    const options = { credentials: "same-origin", cache: "no-store" };
    if (payload !== undefined)
      Object.assign(options, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CIRQA-Request": "1" },
        body: JSON.stringify(payload),
      });
    const response = await fetch(path, options);
    if (response.status === 401) {
      location.assign("/login");
      throw new Error("Sign in to continue.");
    }
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error(
        "The server did not return dashboard data. Your form has not been cleared.",
      );
    }
    if (!response.ok || !result.ok)
      throw new Error(result.error || "Unable to complete this request.");
    return result;
  }

  function lock(on) {
    busy = on;
    Object.values(forms).forEach((form) => {
      form.querySelector("fieldset").disabled = on;
    });
    document
      .querySelectorAll(
        "[data-period],#reload,#feeling-good,[data-plan-action],[data-board-date],#plan-complete-form fieldset",
      )
      .forEach((button) => {
        button.disabled = on;
      });
  }
  function error(message) {
    $("error").textContent = message;
    $("error").hidden = !message;
  }
  async function load(message = "Saved data refreshed.") {
    data = await request(`/api/training?period=${period}`);
    render();
    $("message").textContent = message;
  }
  async function refresh() {
    if (busy) return;
    lock(true);
    error("");
    try {
      await load();
    } catch (e) {
      error(e.message);
      $("message").textContent = "Unable to refresh saved data.";
    } finally {
      lock(false);
    }
  }
  async function save(kind, payload) {
    if (busy) return;
    const result = forms[kind].querySelector(".form-result");
    lock(true);
    error("");
    $("message").textContent = "Saving privately…";
    result.textContent = "Saving…";
    result.dataset.error = "false";
    let saved = false;
    try {
      await request(`/api/training/${kind}`, payload);
      saved = true;
      dirty[kind] = false;
      await load("Saved. Your training is up to date.");
      result.textContent = "";
      forms[kind].closest("dialog").close();
    } catch (e) {
      const message =
        (saved
          ? "Saved, but the updated view could not be loaded. "
          : "Not saved. ") + e.message;
      error(message);
      result.textContent = message;
      result.dataset.error = "true";
      $("message").textContent = saved
        ? "Refresh to see your saved changes."
        : "Your entries are preserved.";
    } finally {
      lock(false);
    }
  }

  function renderLoad() {
    const today = data.load.today;
    $("today-load").textContent =
      today.load === null ? "—" : number(today.load);
    $("today-load").setAttribute("aria-label", number(today.load));
    $("load-coverage").textContent =
      `${today.known}/${today.total} recorded activities have load · ${data.today}` +
      (today.known < today.total ? " · Partial total" : "");
    $("acute-load").textContent =
      data.load.acute.value === null ? "—" : number(data.load.acute.value);
    $("acute-load").setAttribute("aria-label", number(data.load.acute.value));
    $("acute-date").textContent = data.load.acute.date
      ? `Measurement date: ${data.load.acute.date}`
      : "No recorded acute load.";
    $("rpe-load").textContent =
      today.rpe_load === null ? "—" : number(today.rpe_load);
    $("rpe-load").setAttribute("aria-label", number(today.rpe_load));
    $("rpe-coverage").textContent =
      `${today.rated}/${today.total} recorded sessions have both effort and a usable duration today.`;
    const days = data.load.daily,
      maximum = Math.max(1, ...days.map((d) => d.load ?? 0));
    $("load-chart").innerHTML = days
      .map((d, i) => {
        const unknown = d.load === null;
        const label = `${d.date}: ${number(d.load)} Garmin units; ${d.known}/${d.total} activities have load`;
        return `<div class="day-bar ${unknown ? "unknown" : d.known < d.total ? "partial" : ""}" role="img" aria-label="${escape(label)}" title="${escape(label)}"><div class="bar" style="height:${unknown ? 4 : Math.max(1, (d.load / maximum) * 100)}%"></div>${days.length <= 7 || i === 0 || i === days.length - 1 || i % 7 === 0 ? `<small>${escape(d.date.slice(5))}</small>` : ""}</div>`;
      })
      .join("");
    $("load-table").innerHTML = days
      .map(
        (d) =>
          `<tr><td>${escape(d.date)}</td><td>${number(d.load)}</td><td>${d.known}/${d.total}</td><td>${number(d.rpe_load)} · ${d.rated} rated</td></tr>`,
      )
      .join("");
    document
      .querySelectorAll("[data-period]")
      .forEach((button) =>
        button.setAttribute(
          "aria-pressed",
          String(Number(button.dataset.period) === period),
        ),
      );
    $("comparison-dates").textContent =
      `${shiftDate(data.today, -period)} – ${shiftDate(data.today, -1)} versus ${shiftDate(data.today, -2 * period)} – ${shiftDate(data.today, -period - 1)}. Today is excluded.`;
    $("comparisons").innerHTML = data.comparisons
      .map(
        (c) =>
          `<article class="card"><h3>${escape(c.label)}</h3><p class="small muted">${escape(c.unit)}</p><div class="comparison-values"><div><strong>${number(c.current)}</strong><span>Recent · ${c.current_count}/${c.expected} days</span></div><div><strong>${number(c.previous)}</strong><span>Previous · ${c.previous_count}/${c.expected} days</span></div></div><p class="small">${c.change === null ? "No change conclusion" : `Observed difference: ${c.change > 0 ? "+" : ""}${number(c.change)} ${escape(c.unit)}`}</p><p class="small muted">${escape(c.note)}</p></article>`,
      )
      .join("");
    list("insights", data.insights);
  }

  function fillFeedback() {
    const activity = data.activities.find(
      (a) => a.activity_id === field("feedback", "activity_id").value,
    );
    const f = activity?.feedback;
    for (const key of ["rpe", "soreness", "notes"])
      field("feedback", key).value = f?.[key] ?? "";
    previewEffort();
  }
  function previewEffort() {
    const a = data?.activities.find(
      (item) => item.activity_id === field("feedback", "activity_id").value,
    );
    const raw = field("feedback", "rpe").value;
    const rpe = Number(raw);
    $("effort-preview").textContent =
      a &&
      typeof a.duration_s === "number" &&
      a.duration_s > 0 &&
      raw !== "" &&
      Number.isFinite(rpe) &&
      rpe >= 0 &&
      rpe <= 10
        ? `${number(a.duration_s / 60)} recorded minutes × ${number(rpe)} RPE = ${number((a.duration_s / 60) * rpe)} session-RPE units. Recording duration is used consistently; it is not a muscle-strain measurement.`
        : "No session-RPE load without a usable recorded duration and an explicit effort rating. Blank means unknown, not zero.";
  }
  function renderNative() {
    const n = data.native;
    const fresh = !n.error && n.last_success_at?.slice(0, 10) === data.today;
    $("native-status").textContent = n.checked_at
      ? `Last attempted: ${n.checked_at}. Last successful: ${n.last_success_at || "unavailable"}. ${n.range_start || "Unknown"} – ${n.range_end || "unknown"}. Plan-list entries: ${n.plans_count ?? "unknown"}. ${fresh ? "Checked today." : "Not confirmed current."}${n.error ? " " + n.error : ""}`
      : "Calendar has not been checked yet. A Garmin sync checks the current and next calendar month, at most once a day.";
    const upcoming = n.workouts.filter((w) => w.date >= data.today);
    $("native-workouts").innerHTML =
      upcoming
        .map(
          (w) =>
            `<article class="native-item"><p class="small muted">${escape(w.date)} · Garmin scheduled workout${fresh ? "" : " · cached, not confirmed current"}</p><h3>${escape(w.name)}</h3>${w.description ? `<p class="small">${escape(w.description)}</p>` : ""}</article>`,
        )
        .join("") ||
      `<p>${n.last_success_at ? "No upcoming scheduled workout in the last returned calendar snapshot." : "No verified schedule is available."}</p>`;
  }

  let displaySurface = null,
    profileSurface = "outdoor";
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const fmt = (value, digits = 1) =>
    finite(value) ? number(value, digits) : "—";
  const pace = (value) => {
    if (!finite(value) || value <= 0) return "—";
    const s = Math.round(value);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  const dateLabel = (d) =>
    d
      ? new Date(d + "T12:00:00").toLocaleDateString(undefined, {
          day: "numeric",
          month: "short",
        })
      : "Not recorded";
  function svg(kind) {
    const shapes = {
      run: "M15 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM3 13l5-4 4 1 3 4h5M12 10l-3 6-5 5m5-5 5 1 2 4",
      treadmill:
        "M3 18h17a2 2 0 0 1 0 4H3a2 2 0 0 1 0-4Zm15 0-2-12h5M9 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm0 5-3 5h5l3 4M8 12l-4 5m5-9 4 3h4",
      rest: "M19 15A8 8 0 0 1 9 5 8 8 0 1 0 19 15Z",
      readiness: "M4 18a9 9 0 1 1 16 0M12 13l5-6M8 21h8",
      sleep: "M19 15A8 8 0 0 1 9 5 8 8 0 1 0 19 15Z",
      hrv: "M2 12h4l3-7 4 14 3-9 2 2h4",
      battery: "M9 2h6v3h4v16H5V5h4M13 8l-4 6h4l-2 5 6-8h-4z",
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${shapes[kind] || shapes.run}"/></svg>`;
  }
  function targetText(s) {
    if (
      s.pace_range_s_per_km ||
      s.speed_range_kmh ||
      s.hr_range_bpm ||
      s.mode
    ) {
      const parts = [];
      if (s.pace_range_s_per_km)
        parts.push(rangeText(s.pace_range_s_per_km, pace) + " min/km");
      if (s.speed_range_kmh) parts.push(rangeText(s.speed_range_kmh) + " km/h");
      if (s.hr_range_bpm)
        parts.push(rangeText(s.hr_range_bpm) + " bpm · plan target");
      return parts.join(" · ") || "No numeric pace / HR specified in the plan";
    }
    if (s.segments)
      return s.segments
        .slice(0, 2)
        .map((part, i) => {
          const value = !finite(part.pace_s_per_km)
            ? "by effort"
            : displaySurface === "treadmill"
              ? `${fmt(part.speed_kmh)} km/h`
              : `${pace(part.pace_s_per_km)} min/km`;
          return `${i ? "Easy" : "Work"} ${value}`;
        })
        .join(" · ");
    const p = s.pace_s_per_km,
      speed = s.speed_kmh;
    if (!finite(p)) return "By effort · numeric pace not established";
    const main =
      displaySurface === "treadmill"
        ? `${fmt(speed)} km/h · ${pace(p)} min/km`
        : `${pace(p)} min/km · ${fmt(speed)} km/h`;
    return (
      main + (finite(s.distance_km) ? ` · ≈ ${fmt(s.distance_km, 2)} km` : "")
    );
  }
  function stat(label, value, unit = "") {
    return `<div><span>${escape(label)}</span><strong>${escape(value)} <small>${escape(unit)}</small></strong></div>`;
  }
  function renderRecommendation() {
    const r = data.recommendation,
      indoors = displaySurface === "treadmill";
    const imported = !!data.imported_plan;
    $("first-use").hidden = !!data.profile || imported;
    $("recommendation").hidden = !data.profile && !imported;
    $("today-panel").classList.toggle(
      "needs-setup",
      !data.profile && !imported,
    );
    $("recommendation").dataset.state = r.status;
    $("recommendation-title").textContent = r.title;
    $("decision-state").textContent =
      {
        setup: "Setup",
        checkin: "Check in",
        suggestion: "Today's suggestion",
        rest: "Recovery",
        caution: "Needs attention",
        plan: "Your saved plan",
      }[r.status] || r.status;
    $("session-icon").innerHTML = svg(
      r.status === "rest" ? "rest" : indoors ? "treadmill" : "run",
    );
    $("decision-target").textContent = r.target || "";
    $("session-metrics").hidden = r.status !== "suggestion";
    $("session-metrics").innerHTML =
      stat("Total time", fmt(r.minutes, 0), "min") +
      stat(
        "Estimated distance",
        finite(r.distance_km) ? "≈ " + fmt(r.distance_km, 2) : "—",
        "km",
      ) +
      stat(
        "Main work",
        indoors ? fmt(r.speed_kmh) : pace(r.pace_s_per_km),
        indoors ? "km/h" : "min/km",
      );
    $("session-metrics").classList.toggle("has-ranges", imported);
    if (imported) {
      const known = r.steps.filter((s) => finite(s.distance_km));
      $("session-metrics").innerHTML =
        stat(
          "Duration",
          finite(r.minutes)
            ? fmt(r.minutes)
            : r.minutes_range
              ? rangeText(r.minutes_range)
              : "Mixed",
          finite(r.minutes) || r.minutes_range ? "min" : "distance + recovery",
        ) +
        stat(
          "Specified run distance",
          known.length
            ? fmt(
                known.reduce((n, s) => n + s.distance_km, 0),
                2,
              )
            : "—",
          "km · work only",
        ) +
        stat(
          "Main work",
          indoors
            ? rangeText(r.speed_range_kmh)
            : rangeText(r.pace_range_s_per_km, pace),
          indoors ? "km/h" : "min/km",
        ) +
        stat(
          "Plan HR target",
          rangeText(r.hr_range_bpm),
          "bpm · not a live reading",
        );
    }
    $("surface-toggle").hidden = r.status !== "suggestion";
    document
      .querySelectorAll("[data-surface]")
      .forEach((b) =>
        b.setAttribute(
          "aria-pressed",
          String(b.dataset.surface === displaySurface),
        ),
      );
    $("target-note").innerHTML =
      r.status !== "suggestion"
        ? ""
        : imported
          ? "Your plan's ranges stay ranges. Unspecified distances or durations stay unknown; do not chase an HR target through poor recovery."
          : finite(r.pace_s_per_km)
            ? `${indoors ? "Treadmill settings" : "Pace targets"} are starting guides. Follow the effort cue, not the number at all costs.`
            : 'Pace/speed is not established. <button type="button" class="text-button" data-open="profile-dialog">Add your running benchmark</button> for numeric targets; you can still follow the effort and duration.';
    $("adjustments").hidden = !r.adjustments.length;
    $("adjustments").innerHTML = r.adjustments
      .map((a) => `<p>${escape(a)}</p>`)
      .join("");
    $("decision-steps").innerHTML = r.steps
      .map(
        (s, i) =>
          `<li><span class="step-number">${i + 1}</span><div><strong>${escape(s.title)} <span>${escape(stepDurationText(s))}</span></strong><p class="step-target">${escape(targetText(s))}</p><p>${escape(s.detail)}</p>${
            s.segments
              ? `<details><summary>Work / recovery targets</summary>${s.segments
                  .slice(0, 2)
                  .map(
                    (x) =>
                      `<p><b>${escape(x.title.replace("Repeat 1 · ", ""))}</b> · ${fmt(x.minutes)} min · ${escape(targetText(x))}</p>`,
                  )
                  .join("")}</details>`
              : ""
          }</div></li>`,
      )
      .join("");
    $("decision-action").textContent =
      r.status === "setup" ? "Set up running" : "Edit running setup";
    $("decision-action").hidden = !data.profile || imported;
    $("decision-action").dataset.open = "profile-dialog";
    $("quick-checkin").hidden = imported ? !r.planned_session : !data.profile;
    $("checkin-summary").textContent = data.checkin
      ? "Today's check-in is saved. Update it if anything changes."
      : "One quick check before your run.";
    $("feeling-good").hidden = !!data.checkin;
    list("decision-reasons", r.reasons);
    list("decision-limits", r.limitations);
    $("baseline-note").textContent = r.baseline_note;
    $("decision-source").textContent =
      `${r.source} · policy ${r.policy_version} · ${data.today}`;
    $("training-date").textContent = new Date(
      data.today + "T12:00:00",
    ).toLocaleDateString(undefined, {
      weekday: "long",
      day: "numeric",
      month: "short",
    });
    const race = data.running.race;
    $("race-countdown").innerHTML =
      `<span>HYROX · ${dateLabel(race.date)}</span><strong>${race.days_left > 0 ? race.days_left + "<small> days to go</small>" : race.days_left === 0 ? "Race day" : "Update race date"}</strong>`;
    document
      .querySelectorAll('[data-open="profile-dialog"]')
      .forEach((b) => (b.hidden = imported));
    $("board-nav").hidden = !imported;
    $("today-plan-link").hidden = !imported;
    $("original-plan").hidden = !r.planned_session;
    $("original-plan-content").innerHTML = r.planned_session
      ? boardSession(null, r.planned_session, false)
      : "";
    $("decision-steps").before($("guide-open"));
  }
  function weekStats() {
    const w = data.running.week;
    if (data.imported_plan)
      return `<div class="volume-number">${fmt(w.distance_km, 2)} <small>km recorded</small></div><p>${w.runs} recorded runs · ${fmt(w.minutes)} min</p><p class="small muted">${dateLabel(w.start)}–${dateLabel(w.end)} · Monday–Sunday<br>Distance available for ${w.known_distance_runs}/${w.total_runs} runs${w.known_distance_runs < w.total_runs ? " · partial mileage" : ""}.</p><p class="small muted">Plan progress is separate. Checkmarks, stations and timer steps do not add Garmin kilometres.</p>`;
    return `<div class="volume-number">${fmt(w.distance_km, 2)} <small>km recorded</small></div><p>${w.runs} run${w.runs === 1 ? "" : "s"} · ${fmt(w.minutes)} min · ${w.quality_runs} identifiable quality run${w.quality_runs === 1 ? "" : "s"}</p><p class="small muted">${dateLabel(w.start)}–${dateLabel(w.end)} · Distance available for ${w.known_distance_runs}/${w.total_runs} runs.</p>${finite(w.target_km) ? `<p class="small">Weekly guide: ${fmt(w.target_km)} km · ${escape(data.running.baseline.weekly_source)}</p>${finite(w.distance_km) && w.target_km > 0 && w.known_distance_runs === w.total_runs ? `<div class="volume-rail"><i style="width:${Math.min(100, (w.distance_km / w.target_km) * 100)}%"></i></div>` : ""}<p class="small muted">${finite(w.remaining_km) ? fmt(w.remaining_km) + " km remaining in the guide—not a quota to chase." : "Remaining distance is unknown because recordings are incomplete."}</p>` : '<p class="small muted">No weekly distance guide yet. Add your usual weekly kilometres in setup if Garmin is missing your history.</p>'}`;
  }
  function renderRunning() {
    const running = data.running;
    $("week-glance").innerHTML = weekStats();
    $("week-totals").innerHTML = weekStats();
    $("week-note").textContent = running.note;
    $("week-plan").innerHTML = running.weekly_plan
      .map(
        (d) =>
          `<article class="week-day${d.date === data.today ? " is-today" : ""}"><div class="week-date"><span>${new Date(d.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" })}</span><strong>${Number(d.date.slice(8))}</strong></div><div><h3>${escape(d.title)}</h3><p>${escape(d.detail)}</p></div><span class="week-symbol">${d.kind === "completed" ? "✓" : svg(d.kind === "rest" ? "rest" : "run")}</span></article>`,
      )
      .join("");
    $("recent-runs").innerHTML =
      running.recent_runs
        .map(
          (a) =>
            `<a class="run-row" href="/activity?id=${encodeURIComponent(a.activity_id)}"><span class="run-icon">${svg("run")}</span><div><strong>${escape(a.name || "Run")}</strong><p>${dateLabel(a.start_local.slice(0, 10))} · ${fmt(a.duration_s / 60)} min</p><small>${a.distance_m > 0 ? fmt(a.distance_m / 1000, 2) + " km" : "Distance missing in Garmin"}</small></div><b>${pace(a.pace_s_per_km)}<small>min/km</small></b></a>`,
        )
        .join("") ||
      '<p class="muted">No running recordings in the last 28 days. Record a run on CIRQA and sync through Garmin Connect.</p>';
    const race = running.race;
    $("race-intro").textContent =
      `${dateLabel(race.date)} · ${race.days_left > 0 ? race.weeks_left + " weeks to go" : race.days_left === 0 ? "Race day" : "Race date passed"}. Build around familiar running, then taper. Today decides the actual session from your recovery and recorded week.`;
    $("race-plan").innerHTML =
      running.race_plan
        .map(
          (w, i) =>
            `<article class="race-week"><div class="week-index">${String(i + 1).padStart(2, "0")}</div><div><p class="eyebrow">${dateLabel(w.start)}–${dateLabel(w.end)}</p><h3>${escape(w.title)}</h3><p>${escape(w.detail)}</p><strong>${finite(w.target_km) ? fmt(w.target_km) + " km weekly guide" : "Weekly volume not established"}</strong></div></article>`,
        )
        .join("") ||
      '<p class="muted">Choose your next race date in setup.</p>';
    const rec = data.recovery || {};
    $("recovery-metrics").innerHTML =
      [
        ["readiness", "readiness", "Readiness", fmt(rec.readiness, 0), "/100"],
        ["sleep", "sleep", "Sleep", fmt(rec.sleep_hours), "h"],
        [
          "hrv",
          "hrv",
          "HRV",
          String(rec.hrv_status || "Unavailable")
            .toLowerCase()
            .replaceAll("_", " "),
          "",
        ],
        [
          "battery",
          "body-battery",
          "Body Battery",
          fmt(rec.body_battery, 0),
          "/100",
        ],
      ]
        .map(
          ([icon, id, label, value, unit]) =>
            `<a class="recovery-row" href="/#metric/${id}/overview">${svg(icon)}<span>${label}</span><strong>${escape(value)} <small>${unit}</small></strong></a>`,
        )
        .join("") +
      `<p class="small muted">${rec.date ? dateLabel(rec.date) : "No reading today"} · recorded recovery ${fmt(rec.recovery_hours)} h, not a live countdown.</p>`;
    renderBoard();
  }
  const boardDateDrafts = new Map();
  let completionSession = null;
  function rangeText(values, format = (value) => fmt(value, 2)) {
    if (!Array.isArray(values)) return "—";
    return values[0] === values[1]
      ? format(values[0])
      : `${format(values[0])}–${format(values[1])}`;
  }
  function stepDurationText(step) {
    if (finite(step.minutes)) return `${fmt(step.minutes, 2)} min`;
    if (step.minutes_range)
      return `${rangeText(step.minutes_range)} min · choose`;
    if (finite(step.distance_km))
      return step.distance_km < 1
        ? `${fmt(step.distance_km * 1000)} m`
        : `${fmt(step.distance_km)} km`;
    return "Manual";
  }
  function boardEntries() {
    return data.imported_plan.plan.weeks.flatMap((week) =>
      week.sessions.map((session) => ({ week, session })),
    );
  }
  function boardDate(session) {
    return data.imported_plan.dates[session.id] ?? session.date;
  }
  function boardSession(week, session, controls = true) {
    const state = data.imported_plan,
      done = state.completed[session.id],
      assigned = boardDate(session);
    const current = week && week.start <= data.today && data.today <= week.end;
    const canSelect =
      current &&
      !done &&
      (!assigned || assigned === data.today) &&
      !["rest", "race"].includes(session.kind);
    const canComplete =
      week && week.start <= data.today && (!assigned || assigned <= data.today);
    const value = boardDateDrafts.has(session.id)
      ? boardDateDrafts.get(session.id)
      : assigned || "";
    return `<article class="board-session${done ? " is-complete" : ""}" data-board-session="${escape(session.id)}">
      <div class="board-session-heading"><h3>${escape(session.title)}</h3><span class="board-status">${done ? "Done" : assigned ? escape(dateLabel(assigned)) : "Unscheduled"}</span></div>
      <p class="board-prescription">${escape(session.summary)}</p>
      <p class="board-targets">${escape(targetText(session))}</p>
      <details class="board-step-details"><summary>All steps & source notes</summary><ol class="board-steps">${session.steps.map((s) => `<li><strong>${escape(s.title)}</strong><span>${escape(stepDurationText(s))}</span><p>${escape(targetText(s))}</p>${s.detail ? `<p class="small muted">${escape(s.detail)}</p>` : ""}</li>`).join("")}</ol>${session.notes.map((n) => `<p class="small muted">${escape(n)}</p>`).join("")}</details>
      ${done ? `<p class="small muted">Owner-confirmed ${escape(dateLabel(done.date))}. ${done.activity_id ? `<a href="/activity?id=${encodeURIComponent(done.activity_id)}">Linked Garmin recording</a>` : "No recording linked; no kilometres added."}</p>` : ""}
      ${
        controls
          ? `<div class="board-actions">${canSelect ? `<button type="button" class="primary" data-plan-action="select" data-session="${escape(session.id)}">Use today</button>` : ""}${done ? `<button type="button" data-plan-action="reopen" data-session="${escape(session.id)}">Reopen</button>` : canComplete ? `<button type="button" data-plan-action="complete" data-session="${escape(session.id)}">Mark complete</button>` : ""}</div>
      ${!done && session.kind !== "race" ? `<div class="board-date"><label>Assign date within ${escape(dateLabel(week.start))}–${escape(dateLabel(week.end))}<input type="date" data-board-date="${escape(session.id)}" min="${escape(week.start)}" max="${escape(week.end)}" value="${escape(value)}"></label><button type="button" data-plan-action="schedule" data-session="${escape(session.id)}">Save date</button></div><p class="small muted">Leave blank to keep the board's original date or leave an undated session unscheduled.</p>` : ""}`
          : ""
      }
    </article>`;
  }
  function renderBoard() {
    const state = data.imported_plan;
    $("board-week-section").hidden = !state;
    $("week-heading").textContent = state
      ? "Garmin recorded week"
      : "Your running week";
    $("week-plan").hidden = !!state;
    if (!state) return;
    const plan = state.plan,
      all = boardEntries(),
      done = Object.keys(state.completed).length;
    const week =
      plan.weeks.find((w) => w.id === state.current_week_id) ||
      plan.weeks.find((w) => w.start > data.today) ||
      plan.weeks.at(-1);
    $("board-week-title").textContent =
      (week.id === state.current_week_id
        ? "Your plan week"
        : "Next / latest plan week") + ` · ${week.title}`;
    $("board-week-note").textContent =
      `${dateLabel(week.start)}–${dateLabel(week.end)}. Select a session for Today or assign dates. ${done}/${all.length} plan entries marked complete; not Garmin mileage.`;
    $("board-week-sessions").innerHTML = week.sessions
      .map((s) => boardSession(week, s))
      .join("");
    $("race-intro").textContent =
      `${plan.title} · ${dateLabel(plan.start_date)}–${dateLabel(plan.race_date)} · ${all.length} entries · ${done} completed. Saved privately from ${plan.source}.`;
    $("race-plan").innerHTML =
      plan.weeks
        .map(
          (w) =>
            `<details class="board-week" data-board-week="${escape(w.id)}" ${w.id === week.id ? "open" : ""}><summary><span>${escape(w.title)} · ${dateLabel(w.start)}–${dateLabel(w.end)}</span><small>${w.sessions.filter((s) => state.completed[s.id]).length}/${w.sessions.length} done</small></summary>${w.sessions.map((s) => boardSession(w, s)).join("")}</details>`,
        )
        .join("") +
      `<section class="board-guide"><h3>Race goals · from your plan</h3><p class="board-targets">${rangeText(plan.goal.pace_range_s_per_km, pace)} min/km · ${rangeText(plan.goal.speed_range_kmh)} km/h</p>${plan.goal.notes.map((n) => `<p>${escape(n)}</p>`).join("")}<h3>HR guide · owner supplied</h3><p class="small muted">${plan.max_hr === null ? "Maximum HR not supplied." : `Reported max HR ${fmt(plan.max_hr, 0)} bpm.`} Not measured or validated by this app.</p><table><tbody>${plan.hr_guide.map((h) => `<tr><th>${escape(h.label)}</th><td>${rangeText(h.bpm)} bpm</td></tr>`).join("")}</tbody></table><details><summary>Source, assumptions & recovery notes</summary>${plan.notes.map((n) => `<p class="small muted">${escape(n)}</p>`).join("")}</details></section>`;
    $("week-note").textContent = data.running.note;
  }
  async function planAction(payload) {
    if (busy) return false;
    lock(true);
    error("");
    $("plan-complete-error").textContent = "";
    $("message").textContent = "Saving your private plan…";
    let saved = false;
    try {
      await request("/api/training/plan", payload);
      saved = true;
      if (payload.action === "schedule")
        boardDateDrafts.delete(payload.session_id);
      await load(
        "Plan updated. Garmin recordings and kilometres are unchanged.",
      );
      return true;
    } catch (e) {
      const message =
        (saved ? "Saved, but refresh failed. " : "Not saved. ") + e.message;
      error(message);
      $("plan-complete-error").textContent = message;
      $("message").textContent = "Your entries are preserved.";
      return false;
    } finally {
      lock(false);
    }
  }
  function showCompletion(sid) {
    const found = boardEntries().find((x) => x.session.id === sid);
    if (!found) return;
    completionSession = sid;
    $("plan-complete-session").textContent = found.session.title;
    $("plan-complete-error").textContent = "";
    const used = new Set(
      Object.values(data.imported_plan.completed)
        .map((c) => c.activity_id)
        .filter(Boolean),
    );
    const activities = data.activities.filter(
      (a) =>
        a.start_local &&
        a.start_local.slice(0, 10) >= found.week.start &&
        a.start_local.slice(0, 10) <= found.week.end &&
        a.start_local.slice(0, 10) <= data.today &&
        !used.has(a.activity_id),
    );
    $("plan-complete-activity").innerHTML =
      '<option value="">No recording linked · owner-confirmed only</option>' +
      activities
        .map(
          (a) =>
            `<option value="${escape(a.activity_id)}">${escape(dateLabel(a.start_local.slice(0, 10)) + " · " + (a.name || a.type || "Activity"))}</option>`,
        )
        .join("");
    $("plan-complete-dialog").showModal();
  }
  document.addEventListener("input", (event) => {
    const id = event.target.dataset.boardDate;
    if (id) boardDateDrafts.set(id, event.target.value);
  });
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-plan-action]");
    if (!button || busy) return;
    const action = button.dataset.planAction,
      sid = button.dataset.session;
    if (action === "complete") {
      showCompletion(sid);
      return;
    }
    const payload = { action, session_id: sid };
    if (action === "select") payload.date = data.today;
    if (action === "schedule")
      payload.date =
        button.closest(".board-session").querySelector("[data-board-date]")
          .value || null;
    if (await planAction(payload)) {
      if (action === "select") {
        selectView($("today-tab"));
        window.scrollTo(0, 0);
        $("today-tab").focus();
      }
    }
  });
  $("plan-complete-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (
      await planAction({
        action: "complete",
        session_id: completionSession,
        activity_id: $("plan-complete-activity").value || null,
      })
    )
      $("plan-complete-dialog").close();
  });
  $("board-nav").onclick = () => {
    selectView($("race-tab"));
    $("race-tab").focus();
    window.scrollTo(0, 0);
  };
  $("today-plan-link").onclick = () => {
    selectView(
      data.imported_plan.current_week_id ? $("week-tab") : $("race-tab"),
    );
    window.scrollTo(0, 0);
  };
  function parseTarget(value, surface) {
    value = value.trim();
    if (!value) return null;
    if (surface === "treadmill") {
      const n = Number(value);
      if (!Number.isFinite(n) || n <= 0)
        throw Error("Enter a positive treadmill speed in km/h.");
      return 3600 / n;
    }
    const match = value.match(/^(\d{1,2}):([0-5]\d)$/);
    if (!match)
      throw Error(
        "Enter pace as minutes:seconds per kilometre, for example 7:00.",
      );
    return Number(match[1]) * 60 + Number(match[2]);
  }
  const targetInput = (value, surface) =>
    value === null || value === undefined
      ? ""
      : surface === "treadmill"
        ? (3600 / value).toFixed(2).replace(/\.?0+$/, "")
        : pace(value);
  function targetLabels() {
    const indoors = field("profile", "surface").value === "treadmill";
    $("easy-input-label").textContent = indoors
      ? "Comfortable treadmill speed (km/h)"
      : "Easy pace (min:sec per km)";
    $("tempo-input-label").textContent = indoors
      ? "Known tempo treadmill speed (km/h)"
      : "Known tempo pace (min:sec per km)";
    for (const key of ["easy_target", "tempo_target"]) {
      field("profile", key).inputMode = indoors ? "decimal" : "text";
      field("profile", key).placeholder = indoors ? "e.g. 8.5" : "e.g. 7:00";
    }
  }
  function renderProfile() {
    if (dirty.profile) return;
    forms.profile.reset();
    const p = data.profile;
    profileSurface = p?.surface || "outdoor";
    field("profile", "surface").value = profileSurface;
    if (p) {
      for (const k of ["race_date", "minutes", "experience", "weekly_km"])
        field("profile", k).value = p[k] ?? "";
      forms.profile
        .querySelectorAll('[name="weekday"]')
        .forEach((e) => (e.checked = p.weekdays.includes(Number(e.value))));
    }
    field("profile", "easy_target").value = targetInput(
      p?.easy_pace_s_per_km,
      profileSurface,
    );
    field("profile", "tempo_target").value = targetInput(
      p?.tempo_pace_s_per_km,
      profileSurface,
    );
    targetLabels();
  }
  function renderCheckin() {
    $("checkin-date").textContent =
      data.today +
      (data.checkin ? " · Check-in saved" : " · No check-in saved");
    if (dirty.checkin) return;
    forms.checkin.reset();
    if (data.checkin)
      for (const k of ["fatigue", "soreness", "pain", "illness"])
        field("checkin", k).value = String(data.checkin[k]);
  }
  function renderFeedback() {
    if (dirty.feedback) return;
    const selected = field("feedback", "activity_id").value;
    $("feedback-activity").innerHTML =
      '<option value="">Choose a recorded session</option>' +
      data.activities
        .map(
          (a) =>
            `<option value="${escape(a.activity_id)}">${escape((a.start_local || "Undated") + " · " + (a.name || a.type || "Activity"))}</option>`,
        )
        .join("");
    field("feedback", "activity_id").value = data.activities.some(
      (a) => a.activity_id === selected,
    )
      ? selected
      : "";
    fillFeedback();
  }
  function render() {
    if (displaySurface === null)
      displaySurface = data.profile?.surface || "outdoor";
    $("training-content").hidden = false;
    renderRecommendation();
    renderRunning();
    renderProfile();
    renderCheckin();
    renderFeedback();
    renderLoad();
    renderNative();
    updateGuide();
  }
  for (const [kind, form] of Object.entries(forms))
    form.addEventListener("input", (event) => {
      if (kind !== "feedback" || event.target.name !== "activity_id")
        dirty[kind] = true;
    });
  field("profile", "surface").addEventListener("change", () => {
    const next = field("profile", "surface").value;
    try {
      const easy = parseTarget(
          field("profile", "easy_target").value,
          profileSurface,
        ),
        tempo = parseTarget(
          field("profile", "tempo_target").value,
          profileSurface,
        );
      field("profile", "easy_target").value = targetInput(easy, next);
      field("profile", "tempo_target").value = targetInput(tempo, next);
      profileSurface = next;
      targetLabels();
    } catch (e) {
      field("profile", "surface").value = profileSurface;
      forms.profile.querySelector(".form-result").textContent = e.message;
    }
  });
  forms.profile.addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      const surface = field("profile", "surface").value;
      const payload = {
        race_date: field("profile", "race_date").value,
        weekdays: [
          ...forms.profile.querySelectorAll('[name="weekday"]:checked'),
        ].map((e) => Number(e.value)),
        minutes: Number(field("profile", "minutes").value),
        experience: field("profile", "experience").value,
        surface,
        easy_pace_s_per_km: parseTarget(
          field("profile", "easy_target").value,
          surface,
        ),
        tempo_pace_s_per_km: parseTarget(
          field("profile", "tempo_target").value,
          surface,
        ),
        weekly_km:
          field("profile", "weekly_km").value === ""
            ? null
            : Number(field("profile", "weekly_km").value),
      };
      displaySurface = surface;
      save("profile", payload);
    } catch (e) {
      forms.profile.querySelector(".form-result").textContent = e.message;
    }
  });
  forms.checkin.addEventListener("submit", (event) => {
    event.preventDefault();
    save("checkin", {
      date: data.today,
      fatigue: Number(field("checkin", "fatigue").value),
      soreness: Number(field("checkin", "soreness").value),
      pain: field("checkin", "pain").value === "true",
      illness: field("checkin", "illness").value === "true",
    });
  });
  $("feeling-good").onclick = () =>
    save("checkin", {
      date: data.today,
      fatigue: 0,
      soreness: 0,
      pain: false,
      illness: false,
    });
  document.querySelectorAll("[data-surface]").forEach(
    (b) =>
      (b.onclick = () => {
        displaySurface = b.dataset.surface;
        renderRecommendation();
      }),
  );
  $("open-week").onclick = () => {
    selectView($("week-tab"));
    $("week-tab").focus();
    window.scrollTo(0, 0);
  };
  let selectedFeedback = "";
  field("feedback", "activity_id").addEventListener("focus", () => {
    selectedFeedback = field("feedback", "activity_id").value;
  });
  field("feedback", "activity_id").addEventListener("change", () => {
    if (
      dirty.feedback &&
      !confirm("Discard unsaved session feedback and choose another activity?")
    ) {
      field("feedback", "activity_id").value = selectedFeedback;
      return;
    }
    dirty.feedback = false;
    fillFeedback();
    selectedFeedback = field("feedback", "activity_id").value;
  });
  field("feedback", "rpe").addEventListener("input", previewEffort);
  forms.feedback.addEventListener("submit", (event) => {
    event.preventDefault();
    const optional = (name) =>
      field("feedback", name).value === ""
        ? null
        : Number(field("feedback", name).value);
    save("feedback", {
      activity_id: field("feedback", "activity_id").value,
      rpe: optional("rpe"),
      soreness: optional("soreness"),
      notes: field("feedback", "notes").value,
    });
  });
  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-open]");
    if (opener && !busy) $(opener.dataset.open).showModal();
    const closer = event.target.closest("[data-close]");
    if (closer) closer.closest("dialog").close();
  });
  function selectView(button) {
    document.querySelectorAll("[data-view]").forEach((tab) => {
      const selected = tab === button;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      $(tab.dataset.view + "-panel").hidden = !selected;
    });
  }
  document.querySelectorAll("[data-view]").forEach((button, index, buttons) => {
    button.addEventListener("click", () => selectView(button));
    button.addEventListener("keydown", (event) => {
      const positions = {
        ArrowRight: (index + 1) % buttons.length,
        ArrowLeft: (index + buttons.length - 1) % buttons.length,
        Home: 0,
        End: buttons.length - 1,
      };
      if (!(event.key in positions)) return;
      event.preventDefault();
      const next = buttons[positions[event.key]];
      selectView(next);
      next.focus();
    });
  });
  $("reload").addEventListener("click", refresh);
  document.querySelectorAll("[data-period]").forEach((button) =>
    button.addEventListener("click", () => {
      if (!busy) {
        period = Number(button.dataset.period);
        refresh();
      }
    }),
  );
  window.addEventListener("beforeunload", (event) => {
    if (
      Object.values(dirty).some(Boolean) ||
      guide.running ||
      boardDateDrafts.size
    ) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  refresh();
})();
