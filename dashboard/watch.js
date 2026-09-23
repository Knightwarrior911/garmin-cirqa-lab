"use strict";
const $ = (id) => document.getElementById(id);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const numeric = (v) => typeof v === "number" && Number.isFinite(v);
const valid = (v) => numeric(v) && v >= 0;
const num = (v, d = 0) =>
  numeric(v) ? v.toLocaleString(undefined, { maximumFractionDigits: d }) : "—";
const hours = (s) =>
  valid(s)
    ? `${Math.floor(Math.round(s / 60) / 60)}h ${Math.round(s / 60) % 60}m`
    : "—";
const words = (v) =>
  typeof v === "string"
    ? v
        .toLowerCase()
        .replace(/_\d+$/, "")
        .replace(/_/g, " ")
        .replace(/^./, (c) => c.toUpperCase())
    : "";
const dateLabel = (d) =>
  d
    ? new Date(d.slice(0, 10) + "T12:00:00").toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
      })
    : "Date unavailable";
const timeLabel = (t) =>
  new Date(t).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
let days = [],
  overview = {},
  activities = [],
  range = 7,
  refreshing = false,
  syncPending = false,
  hosting = "local",
  lastLoaded = 0,
  lastStatus = {},
  dataSignature = "";
let trainingData = null,
  trainingLoaded = 0,
  trainingLoading = false,
  draft = null,
  detailDate = "";
const RUN_TYPES = new Set([
  "running",
  "treadmill_running",
  "trail_running",
  "indoor_running",
  "track_running",
  "virtual_run",
  "ultra_run",
]);
const DEFINITIONS = [
  {
    id: "readiness",
    title: "Training readiness",
    field: "training_readiness",
    unit: "/100",
    color: "#a3ff12",
    status: "training_readiness_level",
    info: "Garmin readiness combines sleep, recovery, HRV, acute load and recent sleep/stress history. This is a dated snapshot, not a live assessment.",
  },
  {
    id: "status",
    title: "Training status",
    field: "training_status",
    unit: "",
    color: "#a3ff12",
    text: true,
    info: "Garmin’s classification of your training. Load, VO₂ max and HRV below retain their own measurement dates.",
  },
  { id: "last-run", title: "Last run", color: "#5edfff", unit: "/km" },
  { id: "running-week", title: "Running week", color: "#5edfff", unit: "km" },
  {
    id: "recovery",
    title: "Recovery time",
    field: "recovery_time_hours",
    unit: "h",
    color: "#ffbb60",
    info: "Garmin’s recorded recovery time before the next hard workout. This is not a live countdown or an instruction to avoid all movement.",
  },
  {
    id: "hrv",
    title: "HRV status",
    field: "hrv_weekly_avg",
    unit: "ms",
    color: "#b09aff",
    status: "hrv_status",
    info: "Seven-day average overnight HRV, compared with Garmin’s personal baseline. Overnight readings are shown separately.",
  },
  {
    id: "body-battery",
    title: "Body Battery",
    field: "body_battery_current",
    unit: "/100",
    color: "#5edfff",
    info: "Garmin’s recorded energy estimate. Intraday points are shown only when returned; long gaps are not joined.",
  },
  {
    id: "sleep",
    title: "Sleep",
    field: "sleep_seconds",
    unit: "",
    color: "#b09aff",
    duration: true,
    info: "Recorded time asleep and sleep stages. Awake time is separate. Timeline times use this phone’s time zone.",
  },
  {
    id: "heart-rate",
    title: "Resting heart rate",
    field: "resting_hr",
    unit: "bpm",
    color: "#ff7387",
    info: "Daily resting heart rate from Garmin, not your live pulse.",
  },
  {
    id: "stress",
    title: "Stress",
    field: "stress_avg",
    unit: "/100",
    color: "#ffbb60",
    info: "Garmin’s daily average stress. Missing readings are not interpreted as low stress.",
  },
  {
    id: "steps",
    title: "Steps",
    field: "steps",
    unit: "steps",
    color: "#a3ff12",
    info: "Recorded daily steps. The goal comes from the same dated Garmin record.",
  },
  {
    id: "vo2",
    title: "VO₂ max",
    field: "vo2_max",
    unit: "ml/kg/min",
    color: "#5edfff",
    info: "Garmin’s dated VO₂ max estimate. No estimate is created by this app.",
  },
  {
    id: "acute-load",
    title: "Acute load",
    field: "acute_load",
    unit: "Garmin load",
    color: "#a3ff12",
    info: "Native Garmin acute load. This is not the same as a sum of activity load or session-RPE.",
  },
  {
    id: "load-ratio",
    title: "Load ratio",
    field: "load_ratio",
    unit: "×",
    color: "#a3ff12",
    info: "Garmin’s acute-to-chronic workload ratio, displayed without inventing a personal safe range.",
  },
  {
    id: "respiration",
    title: "Respiration",
    field: "respiration_avg",
    unit: "brpm",
    color: "#5edfff",
    info: "Average waking respiration from Garmin, not a live breathing measurement.",
  },
  {
    id: "pulse-ox",
    title: "Pulse Ox",
    field: "spo2_avg",
    unit: "%",
    color: "#5edfff",
    info: "A native recorded average, when available. This is not a medical diagnostic reading.",
  },
  {
    id: "calories",
    title: "Active calories",
    field: "active_calories",
    unit: "kcal",
    color: "#ffbb60",
    info: "Active energy expenditure estimated by Garmin. Total calories are shown separately.",
  },
  {
    id: "intensity",
    title: "Intensity minutes",
    field: "intensity_minutes",
    unit: "min",
    color: "#ffbb60",
    info: "Daily Garmin intensity minutes; vigorous minutes count twice.",
  },
  {
    id: "skin-temperature",
    title: "Skin temperature",
    field: "skin_temperature",
    extra: true,
    unit: "°C",
    color: "#ffbb60",
    info: "Garmin’s overnight skin-temperature deviation, not body temperature or a diagnosis.",
  },
  {
    id: "naps",
    title: "Naps",
    field: "nap_seconds",
    extra: true,
    unit: "",
    duration: true,
    color: "#b09aff",
    info: "Native recorded nap duration. Missing data does not establish that no nap occurred.",
  },
];
const DEFAULT_PINS = [
  "readiness",
  "status",
  "last-run",
  "running-week",
  "recovery",
  "hrv",
  "body-battery",
  "sleep",
];
const DEFAULT_FACE = ["readiness", "body-battery", "recovery", "steps"];
const PREF_KEY = "cirqa.watch.layout.v1";
const defaults = () => ({
  face: [...DEFAULT_FACE],
  pins: [...DEFAULT_PINS],
  order: DEFINITIONS.map((d) => d.id),
});
const definition = (id) => DEFINITIONS.find((d) => d.id === id);
let prefs = defaults();
try {
  const p = JSON.parse(localStorage.getItem(PREF_KEY));
  if (
    p &&
    Array.isArray(p.face) &&
    p.face.length === 4 &&
    p.face.every(definition) &&
    Array.isArray(p.pins) &&
    Array.isArray(p.order)
  ) {
    prefs = {
      face: p.face,
      pins: [...new Set(p.pins.filter(definition))],
      order: [
        ...new Set([
          ...p.order.filter(definition),
          ...DEFINITIONS.map((d) => d.id),
        ]),
      ],
    };
  }
} catch {}
const raw = (d, def) =>
  def.extra
    ? d?.watch?.metrics?.find((m) => m.key === def.field)?.value
    : d?.[def.field];
const recordedValue = (v, def) =>
  def.text ? typeof v === "string" && v.length > 0 : numeric(v);
const metricDay = (def) =>
  days.findLast((d) => recordedValue(raw(d, def), def));
const stamp = (d) =>
  d
    ? `${dateLabel(d.date)}${d.date === overview.today ? " · today" : ""}`
    : "Not in synced data";
const runs = () =>
  activities.filter(
    (a) =>
      RUN_TYPES.has(a.type) &&
      String(a.start_local || a.start_iso || "").slice(0, 10) <=
        (overview.today || "9999"),
  );
const pace = (a) =>
  valid(a?.distance_m) &&
  a.distance_m > 0 &&
  valid(a.duration_s) &&
  a.duration_s > 0
    ? (a.duration_s * 1000) / a.distance_m
    : null;
const paceText = (p) =>
  valid(p)
    ? `${Math.floor(Math.round(p) / 60)}:${String(Math.round(p) % 60).padStart(2, "0")}`
    : "—";
function weekRuns() {
  const end = overview.today || new Date().toISOString().slice(0, 10);
  const t = new Date(end + "T12:00:00Z");
  const start = new Date(t.getTime() - ((t.getUTCDay() + 6) % 7) * 86400000)
    .toISOString()
    .slice(0, 10);
  return {
    start,
    end,
    items: runs().filter(
      (a) => (a.start_local || a.start_iso || "").slice(0, 10) >= start,
    ),
  };
}
function summary(def) {
  if (def.id === "last-run") {
    const a = runs()[0];
    return {
      value: paceText(pace(a)),
      unit: "/km",
      sub: a
        ? `${dateLabel(a.start_local || a.start_iso)} · ${a.name || "Run"}`
        : "No recorded run",
      date: a ? (a.start_local || a.start_iso).slice(0, 10) : null,
      text: false,
    };
  }
  if (def.id === "running-week") {
    const w = weekRuns(),
      known = w.items.filter((a) => valid(a.distance_m) && a.distance_m > 0);
    return {
      value:
        w.items.length && !known.length
          ? "—"
          : num(known.reduce((s, a) => s + a.distance_m, 0) / 1000, 1),
      unit: "km",
      sub: `${w.items.length} runs · Monday–Sunday`,
      date: w.end,
      text: false,
    };
  }
  const d = metricDay(def),
    v = raw(d, def);
  return {
    value: def.text
      ? words(v) || "—"
      : def.duration
        ? hours(v)
        : num(
            v,
            [
              "load_ratio",
              "recovery_time_hours",
              "vo2_max",
              "respiration_avg",
              "skin_temperature",
            ].includes(def.field)
              ? 1
              : 0,
          ),
    unit: def.unit,
    sub: def.status && d?.[def.status] ? words(d[def.status]) : stamp(d),
    date: d?.date,
    text: !!def.text,
    day: d,
    number: v,
  };
}
function icon(id) {
  const p = {
    readiness:
      "M12 3v3m-8 6h3m10 0h3M6 6l2 2m8 0 2-2M5 19a9 9 0 1 1 14 0M12 12l4-4",
    status: "M4 19V11m5 8V6m5 13V9m5 10V3",
    sleep: "M19 15A8 8 0 0 1 9 5 8 8 0 1 0 19 15Z",
    "body-battery": "M9 2h6v3h4v16H5V5h4M13 8l-4 6h4l-2 5 6-8h-4z",
    hrv: "M2 12h4l3-7 4 14 3-9 2 2h4",
    "heart-rate": "M12 20S2 14 2 8c0-5 7-6 10-1 3-5 10-4 10 1 0 6-10 12-10 12Z",
    steps:
      "M8 3c-2 0-3 3-3 6s1 4 3 4 3-1 3-4-1-6-3-6Zm-3 13h6v5H5ZM17 3h-3v5h3m1 3c-2 0-3 3-3 6s1 4 3 4 3-1 3-4-1-6-3-6Z",
    recovery: "M12 4a8 8 0 1 1-7 4M3 3v6h6m3-2v6l3 2",
    "last-run":
      "M15 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM3 13l5-4 4 1 3 4h5M12 10l-3 6-5 5m5-5 5 1 2 4",
    "running-week":
      "M5 5h14v16H5ZM8 2v6m8-6v6M5 10h14M8 14h2m4 0h2m-8 4h2m4 0h2",
    stress:
      "M12 2c4 4 7 7 7 11a7 7 0 0 1-14 0c0-2 1-4 3-6l1 5 3-10ZM9 17l2-3 2 2 2-3",
    vo2: "M11 3v7l-3-3C4 9 2 13 3 18c1 4 7 3 8 0V9m2-6v7l3-3c4 2 6 6 5 11-1 4-7 3-8 0V9",
    respiration:
      "M11 3v7l-3-3C4 9 2 13 3 18c1 4 7 3 8 0V9m2-6v7l3-3c4 2 6 6 5 11-1 4-7 3-8 0V9",
    "pulse-ox":
      "M12 2S5 10 5 15a7 7 0 0 0 14 0c0-5-7-13-7-13ZM9 17l6-6m-6 1h.01M15 17h.01",
    calories:
      "M13 2c1 6-5 7-3 11l3-3c6 4 7 10 1 12C3 23 2 13 6 8l1 5C10 10 8 6 13 2Z",
    intensity: "M12 2 4 14h7l-1 8 10-13h-7z",
    "skin-temperature":
      "M10 14V5a2 2 0 0 1 4 0v9a5 5 0 1 1-4 0Zm2-6v9m5-11h3m-3 4h3",
    naps: "M17 15A7 7 0 0 1 9 5a7 7 0 1 0 8 10ZM16 3h5l-5 5h5",
    "acute-load": "M3 18h3v-5h4V9h4V5h4V2M3 22h18",
    "load-ratio": "M12 3v18M3 7h18M6 7l-4 8h8L6 7Zm12 0-4 8h8l-4-8Z",
  };
  return `<span class="metric-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="${p[id] || p.hrv}"/></svg></span>`;
}
function readinessColor(v) {
  return !numeric(v)
    ? "#98a4b5"
    : v >= 95
      ? "#bd83ff"
      : v >= 75
        ? "#5edfff"
        : v >= 50
          ? "#a3ff12"
          : v >= 25
            ? "#ffbb60"
            : "#ff7387";
}
function metricColor(def, s) {
  return def.id === "readiness" ? readinessColor(s.number) : def.color;
}
function complication(id) {
  const def = definition(id),
    s = summary(def);
  return `<a class="complication" href="#metric/${id}/overview" style="--accent:${metricColor(def, s)}"><span class="comp-heading">${icon(id)}<span class="label">${esc(def.title)}</span></span><strong class="comp-value ${s.text ? "text-value" : ""}">${esc(s.value)}<small>${esc(s.unit)}</small></strong>${def.unit === "/100" && valid(s.number) ? `<div class="comp-meter"><i style="width:${Math.min(100, s.number)}%"></i></div>` : ""}<span class="stamp">${esc(s.date ? dateLabel(s.date) : "Not recorded")}</span></a>`;
}
function glance(id) {
  const def = definition(id),
    s = summary(def);
  return `<a class="glance" href="#metric/${id}/overview" style="--accent:${metricColor(def, s)}">${icon(id)}<div><div class="glance-title">${esc(def.title)}</div><div class="glance-sub">${esc(s.sub)}</div>${def.unit === "/100" && valid(s.number) ? `<div class="glance-rail"><i style="width:${Math.min(100, s.number)}%"></i></div>` : ""}</div><div class="glance-value ${s.text ? "text-value" : ""}">${esc(s.value)}<small>${esc(s.unit)}</small></div></a>`;
}
function home() {
  const next = trainingData?.recommendation;
  const race = trainingData?.running?.race;
  const raceDate = race?.date || "2026-10-25";
  const daysLeft = overview.today
    ? Math.round(
        (Date.parse(raceDate + "T12:00:00Z") -
          Date.parse(overview.today + "T12:00:00Z")) /
          86400000,
      )
    : null;
  return `<div class="watch-home"><section><div class="watch-face"><div class="today-face-head"><div><p class="eyebrow">${dateLabel(overview.today)}</p><h1 tabindex="-1">Today</h1></div><span class="today-emblem">${icon("last-run")}</span></div><a class="race-ribbon" href="/training"><span>HYROX · ${dateLabel(raceDate)}</span><strong>${daysLeft === null ? "Your running plan" : daysLeft > 0 ? daysLeft + " days to go" : daysLeft === 0 ? "Race day" : "Update race date"} <span aria-hidden="true">›</span></strong></a><div class="complications">${prefs.face.map(complication).join("")}</div><a class="next-session" href="/training">${icon("last-run")}<div><strong>${esc(next?.title || "Open today's run")}</strong><small>Running only · Strength stays in Ladder</small></div><span class="arrow">↗</span></a></div><div class="report-links"><a href="#report/morning">Morning report<span>SLEEP · RECOVERY · TODAY</span></a><a href="#report/evening">Evening report<span>YOUR DAY · TOMORROW</span></a></div><p class="muted">Your native Garmin readings, with their recording dates. Open Train for today's run.</p></section><section aria-label="Garmin glances"><div class="section-head"><h2>Glances</h2><button type="button" data-customize>EDIT</button></div>${
    prefs.order
      .filter((id) => prefs.pins.includes(id))
      .map(glance)
      .join("") ||
    '<p class="empty">No pinned glances. Use Edit to choose yours.</p>'
  }<details class="advanced"><summary>All metrics & availability</summary><div class="metric-links">${DEFINITIONS.filter(
    (d) => !prefs.pins.includes(d.id),
  )
    .map(
      (d) =>
        `<a href="#metric/${d.id}/overview"><span>${esc(d.title)}</span><strong>${esc(summary(d).value)}</strong></a>`,
    )
    .join(
      "",
    )}</div><p>Advanced running metrics were checked against your account. No usable dated running economy, running tolerance, hill/endurance score, race prediction or lactate-threshold record was returned during the capability audit. These are not reconstructed from ordinary averages. Accessory and device support can differ.</p><p>Garmin calendar workouts are not verified watch Daily Suggested Workouts. Live wrist data, device recording controls, Garmin Pay and satellite functions are not provided by this web app.</p></details></section></div>`;
}
function dial(value, def) {
  const readiness = def.id === "readiness";
  const segments = readiness
    ? [
        [0, 24, "#ff7387"],
        [25, 49, "#ffbb60"],
        [50, 74, "#a3ff12"],
        [75, 94, "#5edfff"],
        [95, 100, "#bd83ff"],
      ]
    : [[0, 100, def.color]];
  const r = 106,
    c = 2 * Math.PI * r,
    arc = c * 0.78,
    start = 129.6;
  return `<div class="dial"><svg viewBox="0 0 240 240" aria-hidden="true">${segments.map(([lo, hi, color]) => `<circle cx="120" cy="120" r="${r}" fill="none" stroke="${color}" stroke-width="7" stroke-dasharray="${Math.max(1, ((hi - lo) / 100) * arc - 3)} ${c}" transform="rotate(${start + (lo / 100) * 280.8} 120 120)"/>`).join("")}${valid(value) ? `<circle cx="120" cy="120" r="97" fill="none" stroke="#fff" stroke-width="11" stroke-dasharray="3 ${2 * Math.PI * 97}" transform="rotate(${start + (Math.min(100, value) / 100) * 280.8} 120 120)"/>` : ""}</svg><div class="dial-center"><div class="dial-label">${esc(def.title)}</div><div class="metric-big">${num(value)}</div><div class="dial-unit">OUT OF 100</div></div></div>`;
}
const stat = (label, value, unit = "") =>
  `<div class="stat"><span>${esc(label)}</span><strong>${esc(value)} <small>${esc(unit)}</small></strong></div>`;
function related(ids) {
  return `<div class="metric-links">${ids
    .map((id) => {
      const d = definition(id),
        s = summary(d);
      return `<a href="#metric/${id}/overview" style="--accent:${metricColor(d, s)}"><span>${esc(d.title)}<small class="stamp"> · ${esc(s.date ? dateLabel(s.date) : "Not recorded")}</small></span><strong>${esc(s.value)} ${esc(s.unit)}</strong></a>`;
    })
    .join("")}</div>`;
}
function calendarRows(field, def) {
  const end = overview.today || days.at(-1)?.date;
  if (!end) return [];
  const start = Date.parse(end + "T12:00:00Z") - (range - 1) * 86400000;
  const map = new Map(days.map((d) => [d.date, d]));
  return Array.from({ length: range }, (_, i) => {
    const date = new Date(start + i * 86400000).toISOString().slice(0, 10),
      d = map.get(date);
    return { date, value: def ? raw(d, def) : d?.[field] };
  });
}
function historyChart(
  def,
  field = def.field,
  title = def.title,
  unit = def.unit,
) {
  const rows = calendarRows(field, field === def.field ? def : null),
    observed = rows.filter((r) => numeric(r.value));
  if (def.text)
    return valueTable(
      rows.filter((r) => typeof r.value === "string"),
      unit,
      true,
    );
  if (!observed.length)
    return `<p class="empty">No readings in these ${range} days.</p>`;
  const duration = def.duration && field === def.field;
  const vals = observed.map((r) => (duration ? r.value / 3600 : r.value));
  const fixed = unit === "/100";
  const low = fixed || Math.min(...vals) >= 0 ? 0 : Math.min(...vals) * 1.2;
  const high = fixed ? 100 : Math.max(low + 1, ...vals) * 1.1;
  const X = (i) => 38 + (i * 404) / Math.max(1, range - 1),
    Y = (v) => 150 - ((v - low) / (high - low)) * 124;
  let svg = "",
    prev = null;
  [low, (low + high) / 2, high].forEach(
    (v) =>
      (svg += `<path d="M38 ${Y(v)}H442" stroke="#29313c"/><text x="30" y="${Y(v) + 4}" text-anchor="end">${num(v, 1)}</text>`),
  );
  const last = rows.findLastIndex((r) => numeric(r.value));
  rows.forEach((row, i) => {
    if (!numeric(row.value)) {
      prev = null;
      return;
    }
    const v = duration ? row.value / 3600 : row.value;
    const tip = `${dateLabel(row.date)}: ${duration ? hours(row.value) : num(row.value, 1)} ${duration ? "" : unit}`;
    if (prev !== null)
      svg += `<path d="M${X(prev.i)} ${Y(prev.v)}L${X(i)} ${Y(v)}" fill="none" stroke="${def.color}" stroke-width="2"/>`;
    svg += `<circle cx="${X(i)}" cy="${Y(v)}" r="3" fill="${def.color}"><title>${esc(tip)}</title></circle>`;
    if (range === 7 || i === last)
      svg += `<text class="data-label" x="${X(i)}" y="${Math.max(13, Y(v) - 8)}" text-anchor="middle">${num(v, 1)}</text>`;
    prev = { i, v };
  });
  [0, Math.floor((range - 1) / 2), range - 1].forEach(
    (i) =>
      (svg += `<text x="${X(i)}" y="178" text-anchor="middle">${dateLabel(rows[i].date)}</text>`),
  );
  return `<div class="chart"><h3>${esc(title)} · ${duration ? "hours" : esc(unit)}</h3><p class="stamp">${observed.length}/${range} days recorded · Gaps remain gaps</p><svg viewBox="0 0 480 190" role="img" aria-label="${esc(title)} over ${range} days">${svg}</svg><details id="recorded-values"><summary>Recorded values</summary>${valueTable(rows, unit, false, duration)}</details></div>`;
}
function valueTable(rows, unit, text = false, duration = false) {
  return `<div class="table-scroll"><table><thead><tr><th>Date</th><th>Recorded value</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${dateLabel(r.date)}</td><td>${text ? esc(words(r.value)) : duration ? hours(r.value) : num(r.value, 1)} ${esc(unit)}</td></tr>`).join("")}</tbody></table></div>`;
}
const dayDetails = new Map();
function nativeKey(def, day) {
  if (def.id === "body-battery")
    return day?.watch?.body_battery_timeline?.point_count
      ? "body_battery_timeline"
      : "body_battery";
  return { sleep: "sleep", "heart-rate": "heart_rate", stress: "stress" }[
    def.id
  ];
}
function nativeCount(day, def) {
  const group = day?.watch?.[nativeKey(def, day)];
  return group?.point_count || group?.points?.length || 0;
}
function detailDay(day) {
  return dayDetails.get(day?.date)?.day || day;
}
async function refreshDay(day) {
  if (!day || dayDetails.has(day.date)) return;
  const entry = { day: null, error: null };
  dayDetails.set(day.date, entry);
  try {
    entry.day = (
      await get(`/api/day?date=${encodeURIComponent(day.date)}`)
    ).day;
  } catch (e) {
    entry.error = e.message;
  }
  if (dayDetails.get(day.date) === entry && route().page === "metric") render();
}
function detailNotice(day) {
  const entry = dayDetails.get(day?.date);
  if (entry?.error)
    return `<p class="empty">${esc(entry.error)} <button type="button" data-retry-day="${esc(day.date)}">Retry detail</button></p>`;
  if (entry && !entry.day)
    return '<p class="muted" role="status">Loading recorded detail…</p>';
  return '<p class="empty">No intraday points stored for this date. Sync now to collect native detail; older daily summaries remain intact.</p>';
}
function intradayTimeline(day, def, title, unit, fixed = false) {
  const p = detailDay(day)?.watch?.[nativeKey(def, day)]?.points || [];
  if (!p.length) return detailNotice(day);
  const observed = p.filter((r) => valid(r.value));
  if (!observed.length)
    return '<p class="empty">Garmin returned no usable measurements in this recorded series.</p>';
  const start = Date.parse(p[0].time),
    end = Date.parse(p.at(-1).time);
  const high = fixed
    ? 100
    : Math.ceil(Math.max(...observed.map((r) => r.value)) / 20) * 20;
  const X = (t) =>
    35 + ((Date.parse(t) - start) / Math.max(1, end - start)) * 405;
  const Y = (v) => 150 - (v / Math.max(1, high)) * 120;
  let prev = null,
    path = "",
    dots = "";
  for (const row of p) {
    if (!valid(row.value)) {
      prev = null;
      continue;
    }
    const connected =
      prev && Date.parse(row.time) - Date.parse(prev.time) <= 1800000;
    path += `${connected ? "L" : "M"}${X(row.time).toFixed(2)} ${Y(row.value).toFixed(2)}`;
    if (!connected)
      dots += `<circle cx="${X(row.time)}" cy="${Y(row.value)}" r="2" fill="${def.color}"/>`;
    prev = row;
  }
  const last = observed.at(-1);
  return `<div class="chart"><h3>${esc(title)} · ${dateLabel(day.date)}</h3><p class="stamp">Last recorded ${num(last.value)} ${esc(unit)} · ${timeLabel(last.time)} · not live</p><svg viewBox="0 0 480 190" role="img" aria-label="${esc(title)}; missing readings and gaps above thirty minutes are disconnected"><path d="M35 30V150H440" stroke="#29313c" fill="none"/><path d="${path}" stroke="${def.color}" stroke-width="2" fill="none"/>${dots}<circle cx="${X(last.time)}" cy="${Y(last.value)}" r="3" fill="${def.color}"/><text x="28" y="34" text-anchor="end">${high}</text><text x="28" y="154" text-anchor="end">0</text><text x="35" y="177">${timeLabel(p[0].time)}</text><text x="440" y="177" text-anchor="end">${timeLabel(p.at(-1).time)}</text></svg><p class="stamp">Phone-local times · Gaps over 30 minutes are not joined.</p><details id="intraday-values"><summary>Recorded points (${p.length})</summary><div class="table-scroll"><table><thead><tr><th>Time</th><th>${esc(unit || "Value")}</th></tr></thead><tbody>${p.map((v) => `<tr><td>${timeLabel(v.time)}</td><td>${num(v.value)}</td></tr>`).join("")}</tbody></table></div></details></div>`;
}
const SLEEP_STAGES = [
  ["Deep", "sleep_deep_s", "#647eff"],
  ["Light", "sleep_light_s", "#5edfff"],
  ["REM", "sleep_rem_s", "#ba8cff"],
  ["Awake", "sleep_awake_s", "#ffb961"],
];
function sleepTimeline(d) {
  const p = detailDay(d)?.watch?.sleep?.points || [];
  if (!p.length) return detailNotice(d);
  const start = Math.min(...p.map((r) => Date.parse(r.start))),
    end = Math.max(...p.map((r) => Date.parse(r.end)));
  let svg = "";
  for (const row of p) {
    const stage = SLEEP_STAGES.findIndex((s) => s[0] === row.stage);
    if (stage < 0) continue;
    const x = 45 + ((Date.parse(row.start) - start) / (end - start)) * 385,
      w = ((Date.parse(row.end) - Date.parse(row.start)) / (end - start)) * 385;
    svg += `<rect x="${x}" y="${20 + stage * 26}" width="${Math.max(0.5, w)}" height="19" fill="${SLEEP_STAGES[stage][2]}"><title>${esc(row.stage)} ${timeLabel(row.start)}–${timeLabel(row.end)}</title></rect>`;
  }
  SLEEP_STAGES.forEach(
    ([name], i) =>
      (svg += `<text x="39" y="${33 + i * 26}" text-anchor="end">${name}</text>`),
  );
  svg += `<text x="45" y="147">${timeLabel(new Date(start).toISOString())}</text><text x="430" y="147" text-anchor="end">${timeLabel(new Date(end).toISOString())}</text>`;
  return `<div class="chart"><h3>Sleep stages · ${dateLabel(d.date)}</h3><svg viewBox="0 0 480 160" role="img" aria-label="Native sleep-stage intervals">${svg}</svg><details id="sleep-values"><summary>Recorded intervals (${p.length})</summary><div class="table-scroll"><table><tbody>${p.map((r) => `<tr><td>${timeLabel(r.start)}–${timeLabel(r.end)}</td><td>${esc(r.stage)}</td></tr>`).join("")}</tbody></table></div></details></div>`;
}
function nativeDateSelect(def) {
  const available = days.filter((d) => nativeCount(d, def));
  if (!available.length) return "";
  return `<label class="muted">Recorded detail date<select id="detail-date">${[
    ...available,
  ]
    .reverse()
    .map(
      (d) =>
        `<option value="${d.date}" ${d.date === detailDate ? "selected" : ""}>${dateLabel(d.date)}</option>`,
    )
    .join("")}</select></label>`;
}
function factorRows(d) {
  const factors = d?.watch?.readiness_factors || [];
  return factors.length
    ? `<h3>Readiness factors</h3>${factors.map((f) => `<div class="factor" style="--accent:#5edfff"><div class="factor-head"><span>${esc(f.label)}</span><strong>${esc(words(f.status) || "Not recorded")}</strong></div>${numeric(f.value) ? `<div class="factor-rail"><i style="width:${Math.max(0, Math.min(100, f.value))}%"></i></div><small>Garmin factor rating ${num(f.value)}/100</small>` : ""}</div>`).join("")}<p class="detail-copy">These are native factor ratings, not percentage weights or a score calculated by CIRQA.</p>`
    : '<p class="empty">Factor detail has not been stored for this reading. Sync to retrieve available native factors.</p>';
}
function loadFocus(d) {
  const f = d?.watch?.load_focus || [];
  return f.length
    ? `<div class="chart"><h3>Native load focus · ${dateLabel(d.date)}</h3><p class="stamp">Garmin’s four-week distribution and target bands</p>${f
        .map((v, i) => {
          const max = Math.max(1, v.value, v.max || 0);
          return `<div class="factor" style="--accent:${["#5edfff", "#ffbb60", "#bd83ff"][i]}"><div class="factor-head"><span>${esc(v.label)}</span><strong>${num(v.value)}</strong></div><div class="factor-rail"><i style="width:${(v.value / max) * 100}%"></i></div><small>Native target ${num(v.min)}–${num(v.max)} · Garmin load units</small></div>`;
        })
        .join("")}</div>`
    : '<p class="muted">No native load-focus breakdown stored for this date.</p>';
}
function baselineBand(d) {
  const low = d?.hrv_baseline_low,
    high = d?.hrv_baseline_high,
    value = d?.hrv_weekly_avg;
  if (!valid(low) || !valid(high) || high <= low) return "";
  const start = Math.min(low * 0.5, valid(value) ? value : low),
    end = Math.max(high * 1.5, valid(value) ? value : high);
  const position = (v) => ((v - start) / (end - start)) * 100;
  return `<div class="baseline"><p class="stamp">GARMIN BALANCED BASELINE</p><div class="baseline-rail"><span style="left:${position(low)}%;width:${position(high) - position(low)}%"></span>${valid(value) ? `<i style="left:${position(value)}%" aria-label="Seven-day average ${value} milliseconds"></i>` : ""}</div><p class="stamp">${num(low)}–${num(high)} ms native band · ${num(value)} ms weekly average</p></div>`;
}
function activityRows(items) {
  return items.length
    ? items
        .map(
          (a) =>
            `<a class="activity-row" href="/activity?id=${encodeURIComponent(a.activity_id)}"><div>${esc(a.name || words(a.type) || "Activity")}<span>${dateLabel(a.start_local || a.start_iso)} · ${num(valid(a.duration_s) ? a.duration_s / 60 : null)} min · ${valid(a.distance_m) && (!RUN_TYPES.has(a.type) || a.distance_m > 0) ? num(a.distance_m / 1000, 2) + " km" : "Distance unavailable"}</span></div><b>${RUN_TYPES.has(a.type) ? paceText(pace(a)) + " /km" : num(a.avg_hr) + " bpm"}</b></a>`,
        )
        .join("")
    : '<p class="empty">No recorded activities in this view.</p>';
}
function runDetail(def, history) {
  if (def.id === "running-week") {
    if (history) {
      const weeks = new Map();
      for (const a of runs()) {
        const day = new Date(
          (a.start_local || a.start_iso).slice(0, 10) + "T12:00:00",
        );
        day.setDate(day.getDate() - ((day.getDay() + 6) % 7));
        const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
        if (!weeks.has(key)) weeks.set(key, []);
        weeks.get(key).push(a);
      }
      return `<h3>Recorded running weeks</h3><p class="detail-copy">Monday starts. Only synced activities count; this is not running tolerance or a complete account of unrecorded training.</p>${
        weeks.size
          ? `<div class="table-scroll"><table><thead><tr><th>Week</th><th>Runs</th><th>Recorded km</th><th>Distance coverage</th></tr></thead><tbody>${[
              ...weeks,
            ]
              .sort(([a], [b]) => b.localeCompare(a))
              .map(([day, items]) => {
                const known = items.filter(
                  (a) => valid(a.distance_m) && a.distance_m > 0,
                );
                return `<tr><td>${dateLabel(day)}</td><td>${items.length}</td><td>${known.length ? num(known.reduce((sum, a) => sum + a.distance_m, 0) / 1000, 1) : "—"}</td><td>${known.length}/${items.length} runs</td></tr>`;
              })
              .join("")}</tbody></table></div>`
          : '<p class="empty">No recorded runs.</p>'
      }`;
    }
    const w = weekRuns(),
      distance = w.items.filter((a) => valid(a.distance_m) && a.distance_m > 0),
      total = distance.reduce((s, a) => s + a.distance_m, 0);
    return `<div class="instrument"><p class="eyebrow">${dateLabel(w.start)}–${dateLabel(w.end)} · MONDAY START</p><div class="metric-big">${w.items.length && !distance.length ? "—" : num(total / 1000, 1)} <small>km</small></div><p class="classification">${w.items.length} recorded runs</p><p class="detail-copy">Recorded distance, not running tolerance or a weekly mileage prescription. ${distance.length}/${w.items.length} runs have a usable distance value.</p></div>${activityRows(w.items)}<a class="next-session" href="/training">Open your running week →</a>`;
  }
  const a = runs()[0];
  return `<div class="instrument"><p class="eyebrow">RECORDED AVERAGE PACE</p><div class="metric-big">${paceText(pace(a))} <small>/km</small></div><p class="classification">${esc(a?.name || "No recorded run")}</p><p class="stamp">${a ? dateLabel(a.start_local || a.start_iso) : "Record a run in Garmin Connect"}</p></div>${a ? `<div class="stats">${stat("Distance", valid(a.distance_m) && a.distance_m > 0 ? num(a.distance_m / 1000, 2) : "—", "km")}${stat("Duration", num(valid(a.duration_s) ? a.duration_s / 60 : null, 1), "min")}${stat("Average heart rate", num(a.avg_hr), "bpm")}${stat("Native load", num(a.training_load))}</div><p class="detail-copy">Average pace requires positive recorded distance and duration. Treadmill names are not used to guess distance.</p><a class="next-session" href="/activity?id=${encodeURIComponent(a.activity_id)}">Open recording, laps & zones →</a>` : ""}${history ? activityRows(runs()) : ""}`;
}
function details(def, view) {
  const s = summary(def);
  let d = s.day;
  const isHistory = view === "history";
  const available = days.filter((r) => nativeCount(r, def));
  if (available.length && !available.some((r) => r.date === detailDate))
    detailDate = available.at(-1).date;
  const timelineDay = available.find((r) => r.date === detailDate);
  if (!isHistory && timelineDay) refreshDay(timelineDay);
  let body = "";
  if (!def.field) body = runDetail(def, isHistory);
  else if (isHistory) {
    body = `<div class="ranges" aria-label="History range">${[7, 28, 90].map((n) => `<button type="button" data-range="${n}" aria-pressed="${range === n}">${n} days</button>`).join("")}</div>${
      def.text
        ? valueTable(
            calendarRows(def.field, def).filter(
              (r) => typeof r.value === "string",
            ),
            "",
            true,
          )
        : historyChart(def)
    }${def.id === "hrv" ? historyChart({ ...def, extra: false }, "hrv_last_night", "Overnight HRV", "ms") : ""}`;
    if (def.id === "body-battery")
      body +=
        historyChart(def, "body_battery_high", "Daily high", "/100") +
        historyChart(def, "body_battery_low", "Daily low", "/100");
    if (def.id === "sleep")
      body += historyChart(
        { ...def, duration: false },
        "sleep_score",
        "Sleep score",
        "/100",
      );
    if (def.id === "calories")
      body += historyChart(def, "total_calories", "Total calories", "kcal");
  } else {
    let right = "",
      below = "";
    if (def.id === "readiness") {
      right = factorRows(d);
      below = related(["recovery", "hrv", "acute-load", "sleep"]);
    } else if (def.id === "status") {
      right = related(["vo2", "acute-load", "load-ratio", "hrv", "recovery"]);
      below = loadFocus(days.findLast((r) => r.watch?.load_focus?.length));
    } else if (def.id === "hrv") {
      right = `<div class="stats">${stat("Last night", num(d?.hrv_last_night), "ms")}${stat("Seven-day average", num(d?.hrv_weekly_avg), "ms")}${stat("Baseline low", num(d?.hrv_baseline_low), "ms")}${stat("Baseline high", num(d?.hrv_baseline_high), "ms")}</div><p class="muted">Garmin’s personal baseline · ${esc(stamp(d))}</p>`;
      right += baselineBand(d);
      below = historyChart(
        { ...def, extra: false },
        "hrv_last_night",
        "Overnight HRV",
        "ms",
      );
    } else if (def.id === "body-battery") {
      right = `<div class="stats">${stat("Daily high", num(d?.body_battery_high))}${stat("Daily low", num(d?.body_battery_low))}${stat("Charged", num(d?.watch?.body_battery?.charged), "points")}${stat("Drained", num(d?.watch?.body_battery?.drained), "points")}</div>`;
      below =
        nativeDateSelect(def) +
        intradayTimeline(
          timelineDay || d,
          def,
          "Recorded Body Battery",
          "points",
          true,
        );
    } else if (def.id === "sleep") {
      right = `<div class="stats">${stat("Sleep score", num(d?.sleep_score), "/100")}${SLEEP_STAGES.map(([name, key]) => stat(name, hours(d?.[key]))).join("")}</div>`;
      below =
        nativeDateSelect(def) +
        sleepTimeline(timelineDay || d) +
        related(["skin-temperature", "naps", "hrv"]);
      const metrics = (timelineDay || d)?.watch?.metrics || [];
      below += `<div class="stats">${stat("Sleep recharge", num(metrics.find((m) => m.key === "sleep_battery_gain")?.value), "points")}${stat("Restless moments", num(metrics.find((m) => m.key === "restless_moments")?.value))}</div>`;
    } else if (["heart-rate", "stress"].includes(def.id)) {
      right = historyChart(def);
      below =
        nativeDateSelect(def) +
        intradayTimeline(
          timelineDay || d,
          def,
          def.id === "heart-rate" ? "Recorded heart rate" : "Recorded stress",
          def.id === "heart-rate" ? "bpm" : "/100",
          def.id === "stress",
        );
    } else if (def.id === "steps") {
      right = `<div class="stats">${stat("Garmin goal", num(d?.steps_goal), "steps")}${stat("Goal progress", valid(d?.steps_goal) && d.steps_goal > 0 ? num((s.number / d.steps_goal) * 100) : "—", "%")}</div>`;
    } else if (def.id === "calories") {
      right = `<div class="stats">${stat("Active", num(d?.active_calories), "kcal")}${stat("Total", num(d?.total_calories), "kcal")}</div>`;
    } else if (def.id === "acute-load") {
      right = related(["status", "load-ratio", "recovery"]);
      below = loadFocus(days.findLast((r) => r.watch?.load_focus?.length));
    }
    if (!right) right = historyChart(def);
    const nativeMessage =
      def.id === "readiness" ? words(d?.watch?.readiness_message) : "";
    body = `<div class="detail-grid"><section class="instrument">${["readiness", "body-battery"].includes(def.id) ? dial(s.number, def) : `<p class="eyebrow">${def.id === "hrv" ? "SEVEN-DAY OVERNIGHT AVERAGE" : esc(def.title)}</p><div class="metric-big ${def.text ? "text-value" : ""}">${esc(s.value)} <small>${esc(s.unit)}</small></div>`}${def.status && !def.text ? `<div class="classification">${esc(words(d?.[def.status]) || "Status not recorded")}</div>` : ""}${nativeMessage ? `<p class="muted">${esc(nativeMessage)}</p>` : ""}<p class="stamp">${esc(stamp(d))}${d?.readiness_updated_at && def.id === "readiness" ? " · " + esc(d.readiness_updated_at.slice(11, 16)) : ""}</p><p class="detail-copy">${esc(def.info || "Native Garmin measurement.")}</p>${!d ? '<p class="empty">No reading returned in the stored history. Check device support, recording settings and Garmin Connect sync. Missing does not mean zero.</p>' : ""}</section><section>${right}</section></div>${below}`;
  }
  return `<div class="detail" style="--accent:${metricColor(def, s)}"><div class="detail-head"><a class="back" href="#watch" aria-label="Back to watch">‹</a><h1 tabindex="-1">${esc(def.title)}</h1></div><div class="detail-nav" aria-label="Metric pages"><button type="button" data-view="overview" aria-pressed="${!isHistory}">Overview</button><button type="button" data-view="history" aria-pressed="${isHistory}">History</button></div><div id="metric-pages">${body}</div><p class="muted">Swipe left/right between Overview and History, or use the buttons above.</p></div>`;
}
function report(kind) {
  const morning = kind === "morning";
  const ids = morning
    ? ["sleep", "hrv", "readiness", "recovery"]
    : ["body-battery", "steps", "calories", "intensity"];
  const items = ids
    .map((id, i) => {
      const def = definition(id),
        s = summary(def);
      return `<a class="report-item" href="#metric/${id}/overview" style="--accent:${metricColor(def, s)}"><span class="report-number">0${i + 1}</span><div><h2>${esc(def.title)}</h2><div class="report-value">${esc(s.value)} <small>${esc(s.unit)}</small></div><p>${esc(s.sub)}</p><span class="stamp">${esc(s.date ? dateLabel(s.date) : "Not recorded")}</span></div></a>`;
    })
    .join("");
  let session =
    trainingData?.profile || trainingData?.imported_plan
      ? "Check tomorrow's updated running decision in Train."
      : "Open Train to set up your running week.";
  let heading = morning ? "Today’s run" : "Tomorrow’s running intention";
  if (morning && trainingData?.recommendation)
    session =
      trainingData.recommendation.title +
      " — " +
      (trainingData.recommendation.target ||
        "See Train for reasons and limits.");
  if (!morning && trainingData?.running?.weekly_plan) {
    const tomorrow = new Date(
      Date.parse((overview.today || trainingData.today) + "T12:00:00Z") +
        86400000,
    )
      .toISOString()
      .slice(0, 10);
    const p = trainingData.running.weekly_plan.find((p) => p.date === tomorrow);
    if (p) session = p.title + " · " + p.detail;
  }
  return `<div class="detail-head"><a class="back" href="#watch" aria-label="Back to watch">‹</a><span class="eyebrow">CIRQA DAILY REPORT</span></div><section class="report-header"><h1 tabindex="-1">${morning ? "Morning" : "Evening"} report</h1><p class="muted">${dateLabel(overview.today)} · A summary of your latest recorded data, not a Garmin-generated watch report.</p></section><div class="report-list">${items}<a class="report-item" href="/training"><span class="report-number">05</span><div><h2>${heading}</h2><p>${esc(session)}</p><p class="stamp">CIRQA guidance. Future schedule entries are intentions, not recovery clearance.</p></div></a>${!morning ? `<div class="report-item"><span class="report-number">06</span><div><h2>Recorded activity</h2>${activityRows(activities.filter((a) => (a.start_local || a.start_iso || "").slice(0, 10) === overview.today))}</div></div>` : ""}</div><div class="report-switch"><a class="primary" style="display:inline-block;padding:13px 18px;border-radius:9px;font-size:13px" href="#report/${morning ? "evening" : "morning"}">${morning ? "Evening" : "Morning"} report →</a></div>`;
}
function route() {
  const p = location.hash.slice(1).split("/");
  return { page: p[0] || "watch", id: p[1], view: p[2] || "overview" };
}
function render() {
  const focusedId = $("content").contains(document.activeElement)
    ? document.activeElement.id
    : null;
  const opened = Array.from(
    document.querySelectorAll("#content details[open][id]"),
  ).map((e) => e.id);
  const r = route();
  $("content").innerHTML =
    r.page === "metric" && definition(r.id)
      ? details(definition(r.id), r.view)
      : r.page === "report" && ["morning", "evening"].includes(r.id)
        ? report(r.id)
        : home();
  opened.forEach((id) => {
    if ($(id)) $(id).open = true;
  });
  if (focusedId) $(focusedId)?.focus({ preventScroll: true });
  refreshTraining();
}
async function refreshTraining() {
  if (trainingLoading || Date.now() - trainingLoaded < 60000) return;
  trainingLoading = true;
  try {
    trainingData = await get("/api/training?period=7");
    trainingLoaded = Date.now();
    const r = route();
    if (r.page === "watch" || r.page === "report") render();
  } catch {
    trainingLoaded = Date.now();
  } finally {
    trainingLoading = false;
  }
}
function settings() {
  draft = structuredClone(prefs);
  drawSettings();
  $("custom-message").textContent = "";
  $("custom-dialog").showModal();
}
function drawSettings() {
  const options = (selected) =>
    DEFINITIONS.map(
      (d) =>
        `<option value="${d.id}" ${selected === d.id ? "selected" : ""}>${esc(d.title)}</option>`,
    ).join("");
  $("face-fields").innerHTML = draft.face
    .map(
      (id, i) =>
        `<label>Position ${i + 1}<select data-face="${i}">${options(id)}</select></label>`,
    )
    .join("");
  $("glance-settings").innerHTML = draft.order
    .map(
      (id, i) =>
        `<div class="setting-row"><label><input type="checkbox" data-pin="${id}" ${draft.pins.includes(id) ? "checked" : ""}>${esc(definition(id).title)}</label><button type="button" data-move="${id}" data-direction="-1" ${i === 0 ? "disabled" : ""} aria-label="Move ${esc(definition(id).title)} up">↑</button><button type="button" data-move="${id}" data-direction="1" ${i === draft.order.length - 1 ? "disabled" : ""} aria-label="Move ${esc(definition(id).title)} down">↓</button></div>`,
    )
    .join("");
}
$("customize").onclick = settings;
$("custom-close").onclick = () => $("custom-dialog").close();
$("custom-reset").onclick = () => {
  draft = defaults();
  drawSettings();
};
$("custom-form").addEventListener("change", (e) => {
  if (e.target.matches("[data-face]"))
    draft.face[Number(e.target.dataset.face)] = e.target.value;
  if (e.target.matches("[data-pin]")) {
    const id = e.target.dataset.pin;
    draft.pins = e.target.checked
      ? [...new Set([...draft.pins, id])]
      : draft.pins.filter((v) => v !== id);
  }
});
$("custom-form").addEventListener("click", (e) => {
  const b = e.target.closest("[data-move]");
  if (!b) return;
  const i = draft.order.indexOf(b.dataset.move),
    j = i + Number(b.dataset.direction);
  if (j < 0 || j >= draft.order.length) return;
  [draft.order[i], draft.order[j]] = [draft.order[j], draft.order[i]];
  drawSettings();
  const moved = $("glance-settings").querySelector(
    `[data-move="${b.dataset.move}"][data-direction="${b.dataset.direction}"]`,
  );
  (moved?.disabled
    ? $("glance-settings").querySelector(
        `[data-move="${b.dataset.move}"]:not(:disabled)`,
      )
    : moved
  )?.focus();
});
$("custom-form").onsubmit = (e) => {
  e.preventDefault();
  prefs = structuredClone(draft);
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify(prefs));
    $("custom-dialog").close();
  } catch {
    $("custom-message").textContent =
      "Applied for this tab. Browser storage is unavailable; this layout cannot survive a reload.";
  }
  render();
};
$("content").addEventListener("click", (e) => {
  const retry = e.target.closest("[data-retry-day]");
  if (retry) {
    dayDetails.delete(retry.dataset.retryDay);
    render();
  }
  if (e.target.closest("[data-customize]")) settings();
  const b = e.target.closest("[data-view]");
  if (b) {
    const r = route();
    location.hash = `metric/${r.id}/${b.dataset.view}`;
  }
  const n = e.target.closest("[data-range]");
  if (n) {
    range = Number(n.dataset.range);
    render();
    $("content").querySelector(`[data-range="${range}"]`)?.focus();
  }
});
$("content").addEventListener("change", (e) => {
  if (e.target.id === "detail-date") {
    detailDate = e.target.value;
    render();
    $("detail-date")?.focus();
  }
});
let touchStart = null;
$("content").addEventListener(
  "touchstart",
  (e) => {
    if (
      route().page === "metric" &&
      !e.target.closest("select,button,a,table,details")
    )
      touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    else touchStart = null;
  },
  { passive: true },
);
$("content").addEventListener(
  "touchend",
  (e) => {
    if (!touchStart) return;
    const dx = e.changedTouches[0].clientX - touchStart.x,
      dy = e.changedTouches[0].clientY - touchStart.y;
    touchStart = null;
    const r = route();
    if (
      Math.abs(dx) > 65 &&
      Math.abs(dx) > Math.abs(dy) * 1.5 &&
      r.page === "metric"
    )
      location.hash = `metric/${r.id}/${dx < 0 ? "history" : "overview"}`;
  },
  { passive: true },
);
window.addEventListener("hashchange", () => {
  detailDate = "";
  render();
  window.scrollTo(0, 0);
  document.querySelector("h1")?.focus({ preventScroll: true });
});

async function get(url, options) {
  const r = await fetch(url, options);
  if (r.status === 401) {
    location.replace("/login");
    throw Error("Sign in to continue");
  }
  const data = await r.json();
  if (!r.ok || data.ok === false) throw Error(data.error || "Request failed");
  return data;
}
function syncStatus(s) {
  lastStatus = s;
  const running = syncPending || !!s.running;
  $("refresh").disabled = running || !!s.busy;
  $("refresh").textContent = running
    ? "Syncing…"
    : s.busy
      ? "Activity syncing…"
      : "Sync now";
  const t = overview.last_sync?.finished_at;
  $("syncStatus").textContent = running
    ? "Updating from Garmin Connect…"
    : t
      ? `Synced ${new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}`
      : "Not synced yet";
  if (s.error) {
    $("error").hidden = false;
    $("error").textContent = s.error;
  }
}
async function load() {
  if (refreshing) return;
  refreshing = true;
  try {
    const data = await get("/api/dashboard");
    const signature = JSON.stringify([
      data.overview,
      data.days,
      data.activities,
    ]);
    overview = data.overview;
    days = data.days;
    activities = data.activities;
    hosting = data.hosting;
    lastLoaded = Date.now();
    $("error").hidden = true;
    if (signature !== dataSignature) {
      dataSignature = signature;
      dayDetails.clear();
      render();
    }
    syncStatus(data.sync);
    return true;
  } catch (e) {
    $("error").hidden = false;
    $("error").textContent =
      `Unable to update the dashboard: ${e.message}. Existing data has not been deleted.`;
    return false;
  } finally {
    refreshing = false;
  }
}
async function sync() {
  if (syncPending || lastStatus.running || lastStatus.busy) return;
  syncPending = true;
  syncStatus(lastStatus);
  try {
    const s = await get("/api/sync", {
      method: "POST",
      headers: { "X-CIRQA-Request": "1" },
    });
    syncPending = false;
    await load();
    syncStatus(s);
    if (s.cooldown_seconds && !s.running) {
      $("syncStatus").textContent =
        `Next cloud refresh available in ${Math.ceil(s.cooldown_seconds / 60)} min`;
    }
  } catch (e) {
    $("error").hidden = false;
    $("error").textContent = e.message;
  } finally {
    syncPending = false;
    syncStatus(lastStatus);
  }
}
$("refresh").onclick = sync;
load().then((loaded) => {
  if (loaded) sync();
});
setInterval(() => {
  if (
    !document.hidden &&
    (hosting !== "cloud" ||
      syncPending ||
      lastStatus.running ||
      Date.now() - lastLoaded >= 60000)
  )
    load();
}, 15000);
setInterval(
  () => {
    if (!document.hidden) sync();
  },
  30 * 60 * 1000,
);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden)
    load().then((loaded) => {
      if (loaded) sync();
    });
});
