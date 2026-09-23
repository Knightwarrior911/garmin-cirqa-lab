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
const words = (v) => String(v || "").replaceAll("_", " ");
const valid = (v) => typeof v === "number" && Number.isFinite(v);
const num = (v, digits = 0) =>
  valid(v)
    ? v.toLocaleString(undefined, { maximumFractionDigits: digits })
    : "—";
function duration(v) {
  if (!valid(v)) return "—";
  const s = Math.round(v);
  return s >= 3600
    ? `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`
    : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function formatted(s) {
  if (!s || !valid(s.value)) return "—";
  if (s.format === "duration" || s.format === "pace") return duration(s.value);
  if (s.format === "distance") return num(s.value / 1000, 2);
  if (s.format === "signed") return (s.value > 0 ? "+" : "") + num(s.value);
  return num(s.value, s.format === "decimal" ? 1 : 0);
}
function unit(s) {
  return s.format === "distance" ? "km" : s.format === "duration" ? "" : s.unit;
}
function shown(s) {
  return `${formatted(s)}${unit(s) ? " " + unit(s) : ""}`;
}
function dateLabel(value) {
  return value
    ? String(value).replace("T", " ").slice(0, 16)
    : "Date unavailable";
}
const colors = [
  "#ff7387",
  "#5edfff",
  "#a3ff12",
  "#ffbb60",
  "#b09aff",
  "#80ddad",
];
let activities = [],
  current = null,
  axis = "time_s",
  enabled = new Set(),
  selection = [0, 1000],
  comparisonSequence = 0,
  cooldownTimer;
let sportFilter = "all";
const runTypes = new Set([
  "running",
  "treadmill_running",
  "trail_running",
  "indoor_running",
  "track_running",
  "virtual_run",
  "ultra_run",
]);
const strengthTypes = new Set([
  "strength_training",
  "strength",
  "functional_strength_training",
  "crossfit",
  "hiit",
]);
const isRun = (a) => runTypes.has(a.type);
const recordedPace = (a) =>
  isRun(a) &&
  valid(a.distance_m) &&
  a.distance_m > 0 &&
  valid(a.duration_s) &&
  a.duration_s > 0
    ? (a.duration_s * 1000) / a.distance_m
    : null;
const aid = new URLSearchParams(location.search).get("id");
async function request(url, post = false) {
  const r = await fetch(url, {
    method: post ? "POST" : "GET",
    headers: post ? { "X-CIRQA-Request": "1" } : {},
  });
  if (r.status === 401) {
    location.replace("/login");
    throw new Error("Sign in to continue");
  }
  const data = await r.json();
  if (!r.ok || !data.ok) throw new Error(data.error || "Request failed");
  return data;
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function loadDetail(
  id,
  notify,
  refresh = false,
  cancelled = () => false,
) {
  let result = await request(`/api/activity/${encodeURIComponent(id)}`);
  if (
    (!result.detail || refresh) &&
    result.fetch.supported &&
    !result.fetch.running &&
    !result.fetch.cooldown_seconds &&
    !result.fetch.busy
  ) {
    notify(
      "Downloading native Garmin streams… Keep this page open until the refresh finishes.",
    );
    result = await request(
      `/api/activity/${encodeURIComponent(id)}/fetch`,
      true,
    );
  }
  const until = Date.now() + 195000;
  while (result.fetch.running && !cancelled() && Date.now() < until) {
    notify(
      "Downloading native Garmin streams… Saved readings remain available while the refresh runs.",
    );
    await wait(1400);
    result = await request(`/api/activity/${encodeURIComponent(id)}`);
  }
  return result;
}
function activityOption(a) {
  return `<option value="${esc(a.activity_id)}">${esc(dateLabel(a.start_local || a.start_iso))} · ${esc(a.name || words(a.type) || "Activity")}</option>`;
}
function history() {
  const query = $("search").value.trim().toLowerCase();
  const rows = activities.filter(
    (a) =>
      (sportFilter === "all" ||
        (sportFilter === "running" ? isRun(a) : strengthTypes.has(a.type))) &&
      [a.name, a.type, a.start_local, a.start_iso]
        .join(" ")
        .replaceAll("_", " ")
        .toLowerCase()
        .includes(query),
  );
  $("history-count").textContent =
    `${rows.length} of ${activities.length} stored activities`;
  $("history-list").innerHTML =
    rows
      .map(
        (a) =>
          `<a class="history-row" href="/activity?id=${encodeURIComponent(a.activity_id)}"><div class="when"><small>${esc(dateLabel(a.start_local || a.start_iso))}</small></div><div class="session-name"><span class="sport-mark ${isRun(a) ? "running" : strengthTypes.has(a.type) ? "strength" : ""}" aria-hidden="true">${isRun(a) ? "↗" : strengthTypes.has(a.type) ? "+" : "•"}</span><span>${esc(a.name || words(a.type))}<small>${esc(words(a.type))} · ${duration(a.duration_s)}${valid(a.distance_m) ? " · " + num(a.distance_m / 1000, 2) + " km" : ""}</small></span></div><div class="right">${isRun(a) ? duration(recordedPace(a)) : duration(a.duration_s)}<small>${isRun(a) ? "/km · avg" : "duration"}</small></div><div class="right hr">${num(a.avg_hr)} <small>bpm</small></div></a>`,
      )
      .join("") || '<p class="empty">No matching activities.</p>';
}
function localSummary(a) {
  const fields = [
    ["duration_s", "duration", "Timer time", "s", "duration"],
    ["distance_m", "distance", "Distance", "m", "distance"],
    ["avg_hr", "averageHR", "Average heart rate", "bpm", "number"],
    ["max_hr", "maxHR", "Maximum heart rate", "bpm", "number"],
    ["calories", "calories", "Calories", "kcal", "number"],
  ];
  return {
    id: a.activity_id,
    name: a.name || words(a.type),
    type: a.type,
    start_local: a.start_local || a.start_iso,
    pace_sport: isRun(a),
    stats: fields
      .filter(([k]) => valid(a[k]))
      .map(([k, key, label, unit, format]) => ({
        key,
        label,
        unit,
        format,
        value: a[k],
      }))
      .concat(
        recordedPace(a) === null
          ? []
          : [
              {
                key: "averageSpeed",
                label: "Average recorded pace",
                unit: "/km",
                format: "pace",
                value: recordedPace(a),
              },
            ],
      ),
    streams: [],
    axis: [],
    laps: [],
    zones: [],
    route: [],
    sets: [],
    intervals: [],
    unavailable: ["Only the locally stored activity summary is available."],
    partial_sections: [],
    stale_sections: [],
  };
}
function fetchMessage(result) {
  const f = result.fetch;
  if (f.running)
    return "Activity download is still running. Reload this page shortly.";
  if (f.busy) return "Another activity is downloading. Retry when it finishes.";
  if (f.error) return f.error;
  if (!f.supported)
    return "This is a local import; Garmin cloud details are not available for it.";
  if (!result.detail && f.cooldown_seconds)
    return `Download is cooling down. Retry in ${Math.ceil(f.cooldown_seconds / 60)} minutes.`;
  return "";
}
function render(result) {
  current = result.detail || localSummary(result.activity);
  $("detail").hidden = false;
  $("title").textContent = current.name;
  document.title = current.name + " · CIRQA";
  $("kind").textContent = words(current.type);
  $("date").textContent = dateLabel(current.start_local);
  $("status").textContent = fetchMessage(result);
  $("garmin").hidden = !current.garmin_url;
  if (current.garmin_url) $("garmin").href = current.garmin_url;
  const priority = [
    ...(current.pace_sport
      ? ["averageSpeed", "distance", "duration", "averageHR"]
      : ["duration", "distance", "averageSpeed", "averageHR"]),
    "maxHR",
    "calories",
  ];
  const primary = priority
    .map((k) => current.stats.find((s) => s.key === k))
    .filter(Boolean)
    .slice(0, 4);
  const card = (s) =>
    `<div class="stat${s.format === "pace" ? " pace-stat" : ""}"><div class="note">${esc(s.label)}</div><div class="value">${esc(formatted(s))}<small>${esc(unit(s))}</small></div></div>`;
  $("stats").innerHTML = primary.map(card).join("");
  const extra = current.stats.filter((s) => !primary.includes(s));
  $("stats-more").innerHTML = extra.map(card).join("");
  $("more-summary").hidden = !extra.length;
  $("cache").textContent = result.fetched_at
    ? `Detail cached ${new Date(result.fetched_at).toLocaleString()}. Refresh is limited to once every 30 minutes.`
    : "No detailed recording cached yet.";
  $("refresh").disabled =
    !result.fetch.supported ||
    result.fetch.running ||
    result.fetch.cooldown_seconds > 0;
  $("refresh").textContent = result.detail
    ? "Refresh activity"
    : "Load activity details";
  $("refresh").title = result.fetch.cooldown_seconds
    ? `Available in ${Math.ceil(result.fetch.cooldown_seconds / 60)} minutes`
    : "Fetch native detail from Garmin";
  clearTimeout(cooldownTimer);
  if (
    result.fetch.supported &&
    !result.fetch.running &&
    result.fetch.cooldown_seconds
  )
    cooldownTimer = setTimeout(() => {
      $("refresh").disabled = false;
      $("refresh").title = "Fetch native detail from Garmin";
    }, result.fetch.cooldown_seconds * 1000);
  $("notices").innerHTML = [
    ...current.unavailable,
    ...(current.partial_sections.length
      ? [
          `Garmin could not return: ${current.partial_sections.join(", ")}. Other sections remain available.`,
        ]
      : []),
    ...(current.stale_sections?.length
      ? [
          `Previously cached ${current.stale_sections.join(", ")} retained; these sections were not refreshed.`,
        ]
      : []),
  ]
    .map((t) => `<p>${esc(t)}</p>`)
    .join("");
  enabled = new Set(current.streams.map((s) => s.key));
  selection = [0, 1000];
  axis = "time_s";
  $("section-start").value = 0;
  $("section-end").value = 1000;
  $("distance-axis").disabled = !current.supports_distance;
  $("distance-axis").title = current.supports_distance
    ? "Use recorded distance"
    : "No usable recorded distance stream";
  $("metric-toggles").innerHTML = current.streams
    .map(
      (s, i) =>
        `<label><input type="checkbox" checked data-metric="${esc(s.key)}"><span style="color:${colors[i % colors.length]}">${esc(s.label)}</span></label>`,
    )
    .join("");
  document.querySelectorAll("[data-metric]").forEach(
    (el) =>
      (el.onchange = () => {
        el.checked
          ? enabled.add(el.dataset.metric)
          : enabled.delete(el.dataset.metric);
        charts();
      }),
  );
  charts();
  zones();
  laps();
  route();
  sets();
  $("compare").innerHTML =
    '<option value="">Choose another session</option>' +
    activities
      .filter((a) => a.activity_id !== current.id)
      .sort(
        (a, b) =>
          Number(b.type === current.type) - Number(a.type === current.type),
      )
      .map(activityOption)
      .join("");
  $("comparison").innerHTML = "";
  $("compare-status").textContent = "";
  comparisonSequence++;
}
function charts() {
  $("time-axis").setAttribute("aria-pressed", axis === "time_s");
  $("distance-axis").setAttribute("aria-pressed", axis === "distance_m");
  $("sample").textContent = "Move over a chart to inspect one sample.";
  const usable = current.axis
    .map((p, i) => ({ i, x: p[axis] }))
    .filter((p) => valid(p.x));
  const dataStreams = current.streams.filter((s) => enabled.has(s.key));
  if (!usable.length || !dataStreams.length) {
    $("charts").innerHTML =
      '<p class="empty">' +
      (current.streams.length
        ? "Select a metric to show its chart."
        : "No chart data recorded or available.") +
      "</p>";
    $("segment-summary").textContent = "";
    $("sampling").textContent = "";
    return;
  }
  const first = usable[0].x,
    last = usable[usable.length - 1].x;
  const lo = first + ((last - first) * selection[0]) / 1000,
    hi = first + ((last - first) * selection[1]) / 1000;
  const selected = usable.filter((p) => p.x >= lo && p.x <= hi);
  const W = Math.max(280, $("charts").clientWidth),
    L = 60,
    R = 18,
    H = 154;
  const x = (v) => L + ((v - lo) / (hi - lo || 1)) * (W - L - R);
  const tick = (v) =>
    axis === "time_s" ? duration(v) : num(v / 1000, 2) + " km";
  let markup = "";
  dataStreams.forEach((s, panel) => {
    // Equal speed intervals keep near-stationary GPS samples from flattening pace.
    // All finite samples retain their exact values in the inspector.
    const coordinate = s.format === "pace" ? (v) => 1000 / v : (v) => v;
    const ys = selected
      .map((p) => s.values[p.i])
      .filter(valid)
      .map(coordinate);
    const top = panel * H + 29,
      bottom = panel * H + 123;
    let ymin = ys.length ? Math.min(...ys) : 0,
      ymax = ys.length ? Math.max(...ys) : 1;
    const pad = (ymax - ymin) * 0.08 || 1;
    ymin = s.key === "elevation" ? ymin - pad : Math.max(0, ymin - pad);
    ymax = s.key === "body_battery" ? Math.min(100, ymax + pad) : ymax + pad;
    const y = (v) =>
      bottom - ((v - ymin) / (ymax - ymin || 1)) * (bottom - top);
    const color = colors[current.streams.indexOf(s) % colors.length];
    markup += `<text x="${L}" y="${panel * H + 16}" style="fill:${color};font-weight:600">${esc(s.label)} · ${esc(s.unit)}${s.format === "pace" ? " · equal-speed scale" : ""}</text>`;
    for (let j = 0; j < 3; j++) {
      const v = ymin + ((ymax - ymin) * j) / 2,
        py = y(v);
      const label =
        s.format === "pace"
          ? v > 0
            ? duration(1000 / v)
            : "Stopped"
          : num(v, 1);
      markup += `<line x1="${L}" x2="${W - R}" y1="${py}" y2="${py}" stroke="#29313c"/><text x="${L - 8}" y="${py + 4}" text-anchor="end">${esc(label)}</text>`;
    }
    let d = "",
      connected = false,
      previous = null;
    for (const p of selected) {
      const v = s.values[p.i];
      if (!valid(v)) {
        connected = false;
        continue;
      }
      const gap =
        previous !== null &&
        current.axis[p.i].time_s - current.axis[previous].time_s > 30;
      d +=
        (connected && !gap ? "L" : "M") +
        x(p.x).toFixed(2) +
        "," +
        y(coordinate(v)).toFixed(2);
      connected = true;
      previous = p.i;
    }
    markup += `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.7" vector-effect="non-scaling-stroke"/>`;
    const ticks = W < 500 ? 2 : 4;
    for (let j = 0; j <= ticks; j++) {
      const v = lo + ((hi - lo) * j) / ticks;
      markup += `<text x="${x(v)}" y="${panel * H + 145}" text-anchor="${j === 0 ? "start" : j === ticks ? "end" : "middle"}">${esc(tick(v))}</text>`;
    }
  });
  $("charts").innerHTML =
    `<svg viewBox="0 0 ${W} ${dataStreams.length * H}" role="img" aria-label="Aligned activity charts by ${axis === "time_s" ? "elapsed time" : "recorded distance"}">${markup}<line id="crosshair" x1="0" x2="0" y1="22" y2="${dataStreams.length * H - 25}" stroke="#a0adbf" stroke-dasharray="3 3" visibility="hidden"/></svg>`;
  const svg = $("charts").querySelector("svg");
  svg.onpointermove = (event) => {
    const rect = svg.getBoundingClientRect(),
      pixel = ((event.clientX - rect.left) / rect.width) * W,
      target = lo + ((pixel - L) / (W - L - R)) * (hi - lo);
    if (!selected.length) return;
    let a = 0,
      b = selected.length - 1;
    while (a < b) {
      const m = Math.floor((a + b) / 2);
      if (selected[m].x < target) a = m + 1;
      else b = m;
    }
    const pick =
      a > 0 &&
      Math.abs(selected[a - 1].x - target) < Math.abs(selected[a].x - target)
        ? selected[a - 1]
        : selected[a];
    const cursor = $("crosshair");
    cursor.setAttribute("x1", x(pick.x));
    cursor.setAttribute("x2", x(pick.x));
    cursor.setAttribute("visibility", "visible");
    $("sample").innerHTML =
      `<span><b>${esc(tick(pick.x))}</b></span>` +
      dataStreams
        .map(
          (s) =>
            `<span>${esc(s.label)} <b>${esc(shown({ ...s, value: s.values[pick.i] }))}</b></span>`,
        )
        .join("");
  };
  const begin = selected[0],
    end = selected.at(-1);
  let summary = `Selected ${tick(lo)} – ${tick(hi)} · ${selected.length} returned samples`;
  if (begin && end) {
    const seconds = current.axis[end.i].time_s - current.axis[begin.i].time_s;
    summary += ` · elapsed ${duration(seconds)}`;
    const d0 = current.axis[begin.i].distance_m,
      d1 = current.axis[end.i].distance_m;
    if (valid(d0) && valid(d1) && d1 > d0)
      summary += ` · ${num((d1 - d0) / 1000, 2)} km · elapsed pace ${duration((seconds / (d1 - d0)) * 1000)}/km`;
    const hr = current.streams.find((s) => s.key === "hr");
    if (hr) {
      const values = selected.map((p) => hr.values[p.i]).filter(valid);
      if (values.length)
        summary += ` · mean sampled HR ${num(values.reduce((a, b) => a + b, 0) / values.length)} bpm`;
    }
  }
  $("segment-summary").textContent = summary;
  $("sampling").textContent =
    `${current.returned_samples ?? current.axis.length} Garmin chart samples returned. Streams may be downsampled; section statistics use returned samples, not full-resolution FIT data. Time axis includes pauses. Gaps over 30 seconds are not connected.`;
}
window.addEventListener("resize", () => {
  if (current) charts();
});
function zones() {
  const total = current.zones.reduce((a, z) => a + z.seconds, 0);
  $("zones").innerHTML = current.zones.length
    ? current.zones
        .map(
          (z, i) =>
            `<div class="zone"><div>Zone ${num(z.zone)}<small>${num(z.low_bpm)}${z.high_bpm ? "–" + num(z.high_bpm) : "+"} bpm</small></div><div class="bar"><i style="width:${z.percent}%;background:${colors[(i + 1) % colors.length]}"></i></div><div class="amount">${duration(z.seconds)}<small>${num(z.percent, 1)}%</small></div></div>`,
        )
        .join("") +
      `<p class="note">${duration(total)} in supplied zones. Percentages exclude unclassified time.</p>`
    : '<p class="empty">No Garmin heart-rate zones supplied.</p>';
}
function lapTable(rows) {
  return `<table><thead><tr><th>Lap</th><th>Time</th><th>Distance</th><th>${current.pace_sport ? "Pace /km" : "Speed km/h"}</th><th>Avg HR</th><th>Max HR</th><th>Cadence</th></tr></thead><tbody>${rows.map((l) => `<tr><td>${esc(l.index)}${l.intensity ? " · " + esc(words(l.intensity)) : ""}</td><td>${duration(l.duration_s)}</td><td>${valid(l.distance_m) ? num(l.distance_m / 1000, 2) + " km" : "—"}</td><td>${current.pace_sport ? duration(l.pace_s_km) : num(l.speed_kmh, 1)}</td><td>${num(l.avg_hr)}</td><td>${num(l.max_hr)}</td><td>${num(l.cadence)}</td></tr>`).join("")}</tbody></table>`;
}
function laps() {
  $("laps").innerHTML = current.laps.length
    ? lapTable(current.laps)
    : '<p class="empty">No recorded laps supplied.</p>';
  $("intervals").innerHTML = current.intervals.length
    ? `<h2 style="margin-top:24px">Classified intervals</h2><div class="table-wrap">${lapTable(current.intervals)}</div>`
    : "";
}
function route() {
  const points = current.route;
  if (points.length < 2) {
    $("route").innerHTML =
      '<p class="empty">No GPS route supplied for this recording.</p>';
    return;
  }
  const latitude = points.reduce((a, p) => a + p[0], 0) / points.length;
  const projected = points.map((p) => [
    p[1] * Math.cos((latitude * Math.PI) / 180),
    -p[0],
  ]);
  const xs = projected.map((p) => p[0]),
    ys = projected.map((p) => p[1]);
  const minx = Math.min(...xs),
    maxx = Math.max(...xs),
    miny = Math.min(...ys),
    maxy = Math.max(...ys),
    scale = Math.min(400 / (maxx - minx || 1e-9), 160 / (maxy - miny || 1e-9));
  const coords = projected.map((p) => [
    230 + (p[0] - (minx + maxx) / 2) * scale,
    100 + (p[1] - (miny + maxy) / 2) * scale,
  ]);
  $("route").innerHTML =
    `<svg viewBox="0 0 460 200" role="img" aria-label="Recorded GPS route trace"><polyline points="${coords.map((p) => p.map((n) => n.toFixed(2)).join(",")).join(" ")}" fill="none" stroke="#a3ff12" stroke-width="2"/><circle cx="${coords[0][0]}" cy="${coords[0][1]}" r="4" fill="#a3ff12"/><circle cx="${coords.at(-1)[0]}" cy="${coords.at(-1)[1]}" r="4" fill="#ff7387"/></svg><p class="note">Green: start · Red: finish · North up · Trace only, no map tiles.</p>`;
}
function sets() {
  $("sets-section").hidden =
    current.type !== "strength_training" && !current.sets.length;
  $("sets").innerHTML = current.sets.length
    ? `<table><thead><tr><th>Set</th><th>Exercise</th><th>Reps</th><th>Weight</th><th>Time</th></tr></thead><tbody>${current.sets.map((s, i) => `<tr><td>${i + 1} · ${esc(words(s.type))}</td><td>${esc(s.exercises.map((x) => words(x.name || x.category)).join(", ") || "Not supplied")}</td><td>${num(s.reps)}</td><td>${valid(s.weight_kg) ? num(s.weight_kg, 2) + " kg" : "—"}</td><td>${duration(s.duration_s)}</td></tr>`).join("")}</tbody></table>`
    : '<p class="empty">Garmin supplied no exercise sets or repetitions for this recording. Heart rate and duration remain available above.</p>';
}
$("browse").onchange = () => {
  if ($("browse").value)
    location.href = "/activity?id=" + encodeURIComponent($("browse").value);
};
$("search").oninput = history;
document.querySelectorAll("[data-sport]").forEach((button) =>
  button.addEventListener("click", () => {
    sportFilter = button.dataset.sport;
    document
      .querySelectorAll("[data-sport]")
      .forEach((item) =>
        item.setAttribute("aria-pressed", String(item === button)),
      );
    history();
  }),
);
$("time-axis").onclick = () => {
  axis = "time_s";
  charts();
};
$("distance-axis").onclick = () => {
  axis = "distance_m";
  charts();
};
$("section-start").oninput = () => {
  selection[0] = Math.min(Number($("section-start").value), selection[1] - 1);
  $("section-start").value = selection[0];
  charts();
};
$("section-end").oninput = () => {
  selection[1] = Math.max(Number($("section-end").value), selection[0] + 1);
  $("section-end").value = selection[1];
  charts();
};
$("reset").onclick = () => {
  selection = [0, 1000];
  $("section-start").value = 0;
  $("section-end").value = 1000;
  charts();
};
$("refresh").onclick = async () => {
  $("refresh").disabled = true;
  clearTimeout(cooldownTimer);
  $("refresh").textContent = "Downloading…";
  try {
    render(await loadDetail(aid, (t) => ($("status").textContent = t), true));
  } catch (e) {
    $("status").textContent = e.message;
    $("refresh").disabled = false;
  }
};
$("compare").onchange = async () => {
  const id = $("compare").value,
    sequence = ++comparisonSequence;
  $("comparison").innerHTML = "";
  $("compare-status").textContent = "";
  if (!id) return;
  try {
    const result = await loadDetail(
      id,
      (t) => {
        if (sequence === comparisonSequence)
          $("compare-status").textContent = t;
      },
      false,
      () => sequence !== comparisonSequence,
    );
    if (sequence !== comparisonSequence) return;
    const other = result.detail || localSummary(result.activity);
    $("compare-status").textContent =
      fetchMessage(result) ||
      (other.type !== current.type
        ? "Different activity types — interpret comparisons in context."
        : "Same activity type. Values are not adjusted for terrain, weather or pauses.");
    const identity = (s) => s.key + ":" + s.format;
    const keys = [...new Set([...current.stats, ...other.stats].map(identity))];
    $("comparison").innerHTML =
      `<table><thead><tr><th>Metric</th><th>${esc(current.name)}<br><small>${esc(dateLabel(current.start_local))}</small></th><th><a href="/activity?id=${encodeURIComponent(other.id)}">${esc(other.name)} →</a><small>${esc(dateLabel(other.start_local))}</small></th></tr></thead><tbody>${keys
        .map((k) => {
          const a = current.stats.find((s) => identity(s) === k),
            b = other.stats.find((s) => identity(s) === k);
          return `<tr><td>${esc((a || b).label)}</td><td>${a ? esc(shown(a)) : "—"}</td><td>${b ? esc(shown(b)) : "—"}</td></tr>`;
        })
        .join("")}</tbody></table>`;
  } catch (e) {
    if (sequence === comparisonSequence)
      $("compare-status").textContent = e.message;
  }
};
(async () => {
  try {
    const data = await request("/api/activities?limit=1000");
    activities = data.activities;
    $("browse").innerHTML =
      '<option value="">Choose a recorded activity</option>' +
      activities.map(activityOption).join("");
    if (!aid) {
      $("history").hidden = false;
      document.querySelector(".browser").hidden = true;
      $("status").textContent = "";
      history();
      return;
    }
    $("browse").value = aid;
    render(await loadDetail(aid, (t) => ($("status").textContent = t)));
  } catch (e) {
    $("status").textContent = e.message;
  }
})();
