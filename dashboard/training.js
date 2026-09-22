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
    busy = false,
    expandedActivities = false;
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
    document.querySelectorAll("[data-period],#reload").forEach((button) => {
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

  function renderRecommendation() {
    const r = data.recommendation;
    $("recommendation").dataset.state = r.status;
    $("recommendation-title").textContent = r.title;
    $("decision-state").textContent =
      {
        setup: "Plan needed",
        checkin: "Check in",
        suggestion: "Your session",
        caution: "Take care",
        rest: "Recovery",
      }[r.status] || r.status;
    $("decision-state").className =
      `badge ${r.status === "caution" || r.status === "rest" ? r.status : ""}`;
    $("decision-source").textContent =
      `${r.source} · policy ${r.policy_version} · ${data.today}`;
    $("decision-target").textContent = r.target || r.reasons[0] || "";
    $("decision-demand").textContent = r.demand || "";
    $("demand-line").hidden = !r.demand;
    list("decision-reasons", r.reasons);
    list("decision-limits", r.limitations);
    $("decision-steps").innerHTML = r.steps
      .map(
        (s) =>
          `<li><strong>${escape(s.title)}${s.minutes == null ? "" : ` · ${number(s.minutes)} min`}</strong><p>${escape(s.detail)}</p></li>`,
      )
      .join("");
    $("decision-action").textContent =
      r.status === "setup"
        ? "Set up your week"
        : r.status === "checkin"
          ? "Complete today's check-in"
          : "Update today's check-in";
    $("decision-action").dataset.open =
      r.status === "setup" ? "profile-dialog" : "checkin-dialog";
    $("training-date").textContent = new Date(data.today + "T12:00:00")
      .toLocaleDateString(undefined, {
        weekday: "long",
        month: "short",
        day: "numeric",
      })
      .toUpperCase();
    $("goal-chip").textContent = data.profile
      ? {
          hyrox: "HYROX prep",
          endurance: "Endurance",
          strength: "Strength",
          general_fitness: "General fitness",
        }[data.profile.goal]
      : "HYROX focus";
  }

  function renderRunning() {
    const running = data.running;
    const run = running.last_run;
    const pace = run?.pace_s_per_km;
    const rounded =
      typeof pace === "number" && Number.isFinite(pace)
        ? Math.round(pace)
        : null;
    $("last-pace").textContent =
      rounded === null
        ? "—"
        : `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
    $("last-run-meta").textContent = run
      ? `${number(run.distance_m / 1000, 2)} km · ${run.date} · recorded average`
      : running.runs_28d
        ? "Run distance or duration is missing in Garmin."
        : "No recorded run with distance and duration";
    $("last-run-link").href = run
      ? `/activity?id=${encodeURIComponent(run.activity_id)}`
      : "/activities";
    $("last-run-link").firstChild.textContent = run
      ? "View run "
      : "Explore your runs ";
    $("running-count").textContent = number(running.runs_28d, 0);
    $("running-distance").textContent =
      running.distance_28d_m === null
        ? "—"
        : number(running.distance_28d_m / 1000, 1);
    $("week-note").textContent = running.note;
    $("week-plan").innerHTML =
      running.weekly_plan
        .map((day) => {
          const date = new Date(day.date + "T12:00:00");
          return `<article class="week-day${day.date === data.today ? " is-today" : ""}"><div class="week-date">${escape(date.toLocaleDateString(undefined, { weekday: "short" }))}<strong>${date.getDate()}</strong></div><div><h3>${escape(day.title)}</h3><p>${escape(day.detail)}</p><span class="kind">${escape(day.kind.replaceAll("_", " "))}</span></div></article>`;
        })
        .join("") ||
      '<p class="muted">Choose running and gym days to build your week.</p>';
  }

  function addMovement(move = {}) {
    const row = document.createElement("div");
    row.className = "routine-row";
    row.innerHTML = `<label>Movement<input data-field="name" maxlength="80" required value="${escape(move.name ?? "")}"></label><div class="numbers"><label>Sets<input data-field="sets" type="number" min="1" max="5" step="1" required value="${escape(move.sets ?? "")}"></label><label>Reps<input data-field="reps" type="number" min="1" max="30" step="1" required value="${escape(move.reps ?? "")}"></label><label>Added kg<input data-field="load_kg" type="number" min="0" max="300" step="0.1" required value="${escape(move.load_kg ?? "")}"></label></div><button type="button">Remove movement</button>`;
    row.querySelector("button").addEventListener("click", () => {
      row.remove();
      dirty.profile = true;
    });
    $("routine-rows").append(row);
  }
  function updateRoutineVisibility() {
    const strength = field("profile", "sport").value === "strength";
    $("routine-section").hidden = !strength;
    $("routine-rows")
      .querySelectorAll("input")
      .forEach((input) => {
        input.disabled = !strength;
      });
    $("strength-days").hidden = field("profile", "goal").value !== "hyrox";
  }
  function renderProfile() {
    if (dirty.profile) return;
    const p = data.profile;
    forms.profile.reset();
    $("routine-rows").replaceChildren();
    if (p) {
      for (const key of ["goal", "sport", "minutes", "experience", "equipment"])
        field("profile", key).value = p[key];
      forms.profile.querySelectorAll('[name="weekday"]').forEach((input) => {
        input.checked = p.weekdays.includes(Number(input.value));
      });
      p.routine.forEach(addMovement);
      field("profile", "race_date").value = p.race_date || "";
      forms.profile
        .querySelectorAll('[name="strength_day"]')
        .forEach((input) => {
          input.checked = (p.strength_days || []).includes(Number(input.value));
        });
    }
    updateRoutineVisibility();
  }
  function renderCheckin() {
    $("checkin-date").textContent =
      data.today +
      (data.checkin ? " · Check-in saved" : " · No check-in saved");
    $("checkin-summary").textContent = data.checkin
      ? "Checked in today · Tap to update"
      : "Check in before today's session";
    if (dirty.checkin) return;
    forms.checkin.reset();
    if (data.checkin)
      for (const key of ["fatigue", "soreness", "pain", "illness"])
        field("checkin", key).value = String(data.checkin[key]);
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
  function renderActivities() {
    if (!dirty.feedback) {
      const selected = field("feedback", "activity_id").value;
      $("feedback-activity").innerHTML =
        `<option value="">Choose a session</option>` +
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
    const visibleActivities = expandedActivities
      ? data.activities
      : data.activities.slice(0, 12);
    $("activity-list").innerHTML =
      visibleActivities
        .map(
          (a) =>
            `<article class="card"><p class="small muted">${escape(a.start_local || "Date unavailable")} · ${escape(a.type || "Type unavailable")}</p><h3><a href="/activity?id=${encodeURIComponent(a.activity_id)}">${escape(a.name || "Recorded activity")}</a></h3><div class="session-values"><p><span>Garmin load</span><strong>${number(a.training_load)}</strong></p><p><span>Your session-RPE load</span><strong>${number(a.rpe_load)}</strong></p><p><span>Aerobic effect / 5</span><strong>${number(a.aerobic_effect)}</strong></p><p><span>Anaerobic effect / 5</span><strong>${number(a.anaerobic_effect)}</strong></p></div><p class="small muted">${escape(a.effect_label ? a.effect_label.replaceAll("_", " ") : "Training benefit unavailable")}</p><p class="small">Your effort: ${number(a.feedback?.rpe)} · Post-session soreness: ${number(a.feedback?.soreness)}</p><button type="button" data-rate="${escape(a.activity_id)}">Rate this session</button></article>`,
        )
        .join("") || '<p class="muted">No recorded activities available.</p>';
    if (data.activities.length > 12) {
      const more = document.createElement("button");
      more.type = "button";
      more.textContent = expandedActivities
        ? "Show 12 recent sessions"
        : `Show all ${data.activities.length} sessions`;
      more.setAttribute("aria-expanded", String(expandedActivities));
      more.addEventListener("click", () => {
        expandedActivities = !expandedActivities;
        renderActivities();
      });
      $("activity-list").append(more);
    }
    $("activity-list")
      .querySelectorAll("[data-rate]")
      .forEach((button) =>
        button.addEventListener("click", () => {
          if (busy) return;
          if (
            dirty.feedback &&
            !confirm(
              "Discard unsaved session feedback and choose another activity?",
            )
          )
            return;
          dirty.feedback = false;
          field("feedback", "activity_id").value = button.dataset.rate;
          fillFeedback();
          $("feedback-dialog").showModal();
          field("feedback", "rpe").focus();
        }),
      );
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
  function render() {
    $("training-content").hidden = false;
    renderLoad();
    renderRecommendation();
    renderRunning();
    renderProfile();
    renderCheckin();
    renderActivities();
    renderNative();
  }

  for (const [kind, form] of Object.entries(forms))
    form.addEventListener("input", (event) => {
      if (kind !== "feedback" || event.target.name !== "activity_id")
        dirty[kind] = true;
    });
  field("profile", "sport").addEventListener("change", updateRoutineVisibility);
  field("profile", "goal").addEventListener("change", () => {
    const goal = field("profile", "goal").value;
    if (goal === "hyrox" || goal === "endurance")
      field("profile", "sport").value = "running";
    if (goal === "strength") field("profile", "sport").value = "strength";
    updateRoutineVisibility();
  });
  $("add-movement").addEventListener("click", () => {
    if ($("routine-rows").children.length >= 12) {
      error("A routine may contain up to 12 movements.");
      return;
    }
    dirty.profile = true;
    addMovement();
  });
  forms.profile.addEventListener("submit", (event) => {
    event.preventDefault();
    const sport = field("profile", "sport").value;
    const routine =
      sport === "strength"
        ? [...$("routine-rows").children].map((row) =>
            Object.fromEntries(
              [...row.querySelectorAll("[data-field]")].map((input) => [
                input.dataset.field,
                input.dataset.field === "name"
                  ? input.value
                  : Number(input.value),
              ]),
            ),
          )
        : [];
    save("profile", {
      goal: field("profile", "goal").value,
      sport,
      weekdays: [
        ...forms.profile.querySelectorAll('[name="weekday"]:checked'),
      ].map((input) => Number(input.value)),
      minutes: Number(field("profile", "minutes").value),
      experience: field("profile", "experience").value,
      equipment: field("profile", "equipment").value,
      routine,
      strength_days:
        field("profile", "goal").value === "hyrox"
          ? [
              ...forms.profile.querySelectorAll(
                '[name="strength_day"]:checked',
              ),
            ].map((input) => Number(input.value))
          : [],
      race_date: field("profile", "race_date").value || null,
    });
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
    if (Object.values(dirty).some(Boolean)) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  refresh();
})();
