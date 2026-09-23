# Watch interface design

The Garmin Forerunner/fēnix interaction model is the reference: watch face → ordered glances → dedicated metric screens. This is an independent display for synced CIRQA/account data, not Garmin firmware or a live sensor connection. AMOLED-black surfaces, high-contrast numbers, restrained cyan/lime/purple accents, system fonts and inline SVG; no remote assets or copied Garmin branding.

## Hierarchy and navigation

- Persistent **Watch / Train / History** navigation on mobile and desktop. Login and activity details use the same dark palette.
- Watch shows phone time, four selectable complications and a direct training entry. Measurement dates remain separate from the clock.
- Default glances: readiness, training status, last run, running week, recovery, HRV, Body Battery and sleep. Pin/unpin, reorder and configure the four face fields in a native dialog. Only metric IDs and layout preferences enter local storage, never health values.
- Every glance opens its own Overview / History screen. Buttons, browser Back and horizontal swipes provide navigation. Historical values have 7/28/90-day controls and accessible tables.
- Morning/evening reports summarize latest dated readings and the planner's today/tomorrow context. Label them CIRQA summaries, not Garmin-generated reports. Future schedule entries are intentions, not recovery clearance.
- Desktop places the face beside glances and detail instruments beside supporting data; mobile stacks these without horizontal overflow. Avoid an endless feed of full-size charts.

## Native visualization

- Readiness uses Garmin's actual 0–100 score and native zones: poor 1–24, low 25–49, moderate 50–74, high 75–94 and prime 95–100. Six native factor ratings retain their supplied labels; factor percentages are not contribution weights and do not inherit the score's thresholds.
- HRV shows the recorded seven-day average, overnight value and supplied balanced baseline band. Do not invent a baseline or classify missing data.
- Body Battery shows its recorded level, high/low, charge/drain and native intraday series. Prefer the dense wellness series over sparse daily report points. Retain daily latest/high/low history.
- Sleep shows duration, score, native stage totals and actual stage intervals. Skin-temperature deviation, naps, sleep recharge and restless moments appear only when supplied. Preserve signed temperature deviations and valid zero values.
- Resting heart rate and daily average stress remain dated summaries; their separate intraday charts show recorded values and the last sample time, never live pulse/stress.
- Load focus uses native four-week categories and supplied target ranges. Missing advanced running metrics stay explicitly unavailable, rather than being inferred from ordinary activities.
- Historical charts use calendar-spaced dates and missing-day gaps. Native daily timelines break at invalid samples and gaps over 30 minutes. GMT inputs become explicit UTC instants; chart labels use phone-local time. Charts include units, provenance, dates and recorded-value tables.
- Large intraday arrays load on demand through the authenticated single-day API. The dashboard carries counts and compact summaries, not 90 days of dense sensor arrays. No health-data service worker or browser persistence.

## Freshness and interaction

Date every metric. Distinguish the last successful collector fetch from each reading's date/time. Recovery is a recorded value, not a live countdown. Show unavailable/error states without fabricating zero. Failed native endpoints retain previous groups; successful empty responses clear the relevant group.

Unchanged polling responses do not rebuild the screen. Preserve chart range, open value tables and focused date selection through relevant updates. Escape external strings before HTML insertion. Native dialogs provide focus containment and Escape dismissal. Verify narrow-screen overflow, date selection, range controls, customization persistence and browser Back on the real UI.

## Training

Train separates Today / Your week / Load & trends. Run / Strength / HYROX launchers lead to the existing decision or saved week; they never start a band recording. Preferences, symptoms and session feedback remain focused dialogs, preserving unsaved input across reads and closes. Nothing is saved until the owner submits it.

The optional phone workout guide snapshots an eligible timed recommendation. Large foreground countdown, pause/resume, next, reset and finish. Controlled repeats expose individual work/recovery segments. Steps stop at zero; the user advances manually. Closing pauses; leaving while running warns. No background audio/notifications, live HR/pace, CIRQA recording control or fabricated completed activity. A new blocked recommendation removes the guide. Symptoms remain a reason to stop, never something a timer can clear.

Native Garmin load, acute load and optional session-RPE retain independent units. Unknown load is not a rest day. Training reasons, coverage, policy limits and calendar provenance stay accessible; scheduled workouts are not relabeled watch Daily Suggested Workouts.

## Activity history and detail

History retains All / Running / Strength filters, search and average pace only when positive recorded distance and duration support it. Preserve all stored sessions, including short recordings.

Up to four primary native statistics, then expandable statistics and aligned recording charts. All panels share a time/distance axis, section selection and hover cursor. Pace uses an equal-speed scale with exact sample pace available. Nonnegative streams never have negative axes; missing samples and gaps over 30 seconds are disconnected.

Native zones, laps, typed intervals, strength sets and optional local GPS trace follow the charts. Comparisons use explicit units; pace and speed remain separate across sports. Partial download failures and missing streams remain visible. No invented interval classification, race pace or coaching.
