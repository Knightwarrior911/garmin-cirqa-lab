# CIRQA Watch

The Garmin screen CIRQA is missing: a configurable watch face, ordered glances and full native metric screens, with a local Windows server and owner-authenticated Vercel app. Synced Garmin measurements, optional effort feedback and a conservative planner—not Garmin firmware, live wrist streaming or a homemade recovery/strain score.

## Open locally

Double-click **CIRQA Dashboard** on the desktop. The launcher starts the local server if needed, opens your browser, and requests a background cloud refresh. Repeated launches reuse the same server.

Dashboard: http://127.0.0.1:8787

The page checks the local database every 15 seconds while visible. It requests Garmin cloud data every 30 minutes while visible, and on opening. A 30-minute cooldown prevents repeated refresh requests. **Sync now** follows the same cooldown. The scheduled daily sync remains independent of the browser. Closing the browser does not stop the local server; after restarting Windows, use the shortcut again.

## What “updated” means

CIRQA → Garmin Connect on iPhone → Garmin cloud → the local collector or authenticated cloud dashboard.

This is not direct live Bluetooth heart-rate streaming. Open Garmin Connect on your iPhone and finish syncing to upload new readings. The dashboard shows the last successful collector sync; each metric is dated. Partial-day totals are not compared against complete days. History may include other Garmin devices on the account.

If Garmin authentication expires, run `login.py` again in a terminal. Do not share passwords, MFA codes, or token files.

## Watch, glances and reports

- **Watch / Train / History** share a dark, instrument-style interface.
- **Today** replaces the redundant phone clock: date, HYROX countdown and four configurable metric fields with dedicated SVG icons. **Customize** pins/reorders glances and chooses the fields. Measurements retain their recording dates; only layout IDs are saved in browser storage.
- Open a glance for its dedicated **Overview / History** screen. Use the buttons or swipe horizontally; browser Back returns through visited screens.
- Native readiness dial and all supplied factor ratings, recovery time, training status, acute load, load ratio, VO₂ max and four-week load focus.
- Body Battery current/high/low, charged/drained points and a dated native intraday curve.
- Sleep duration/score, labeled Deep/Light/REM/Awake intervals, sleep recharge and restless moments. Awake time is not sleep.
- HRV overnight/weekly values and Garmin's balanced baseline band.
- Resting heart rate and daily stress summaries, plus recorded intraday heart-rate/stress charts—not live readings.
- Steps/goal, respiration, Pulse Ox, active/total calories, intensity minutes, skin-temperature deviation and naps when returned.
- Calendar-spaced 7/28/90-day history, missing-data gaps and accessible value tables. Dense daily detail loads on demand for the selected date.
- Last-run pace and recorded running weeks. **History** preserves All / Running / Strength filters, search and every saved activity.
- **Morning report / Evening report** summarize dated readings and today/tomorrow training context. These are CIRQA summaries, not native Garmin watch reports.

Readiness factor percentages are native factor ratings, not weights. Advanced running metrics remain unavailable unless Garmin supplies usable records; the capability audit did not return dated running tolerance, race predictions, endurance/hill scores or a usable lactate threshold. Running economy was not exposed by the audited client. No empty advanced endpoints were added to routine sync.

Unavailable readings stay unavailable—not zero. Unsupported metric panels do not fill the page. Existing activities, splits and manual training-log history remain in SQLite; the noisy coaching engine and manual log dashboard were removed. The JSON CLI can still read old logs.

## Activity details

Open a session from the homepage or http://127.0.0.1:8787/activities. Four key statistics stay up front; **More recorded statistics** expands the remaining native Garmin values.

- Aligned heart-rate, pace/speed, cadence, elevation, power and Body Battery charts appear only when those streams are supplied.
- Switch between elapsed time and recorded distance. Distance mode requires a usable, nondecreasing distance stream.
- Hover or tap for synchronized sample values. Section sliders zoom all charts together and show elapsed duration, recorded distance, elapsed pace and mean sampled heart rate.
- Pace uses an equal-speed axis: very slow GPS samples remain represented without flattening the moving portions. Exact pace remains available in the sample inspector. Zero speed has no finite pace.
- Garmin heart-rate zones, native laps/typed intervals and strength sets are shown when returned. A single lap is not classified as a workout interval.
- GPS recordings get a local route trace without external map tiles. Indoor recordings show an explicit unavailable state.
- Choose another session for side-by-side native statistics, or open the recording in Garmin Connect.

First opening downloads the detail with the existing Garmin session; later visits use saved history. **Refresh activity** has a 30-minute per-activity cooldown. Local jobs use the cross-process lock and are bounded to three minutes. Cloud jobs share an atomic storage lease with daily sync and run inside a bounded request; keep the page open until completion. Failures preserve cached data; stale optional sections are labeled.

Garmin may downsample its chart response. Section summaries use returned samples, not full-resolution FIT data, and mean sampled heart rate is not presented as Garmin's native activity average. No pace is inferred from heart rate, a treadmill activity name, or a manually entered title.

## Training, feedback and planning

Open **Train** from the bottom navigation, or https://garmin-cirqa-lab.vercel.app/training.

- Native activity load and aerobic/anaerobic Training Effect stay separate from Garmin acute load. Missing load stays unknown; partial totals disclose coverage.
- Compare the last seven or 28 completed days with the preceding equal period. Today is excluded. Metric means include coverage; changes require at least 75% recorded days in both periods. Descriptive insights do not infer causes or statistical significance.
- Optionally record session effort (0–10), soreness and notes. Session-RPE = activity duration in minutes × your effort; these units are not Garmin load. Clear fields and save to remove your values. Feedback survives later Garmin activity refreshes.
- **Today / This week / Race plan** are running-only. Strength programming stays in Ladder; recorded lifting still informs running demand. There are no strength-day, equipment or routine controls.
- Without an imported plan, first choose running days, available minutes, recent experience and your usual weekly kilometres. The unsaved race-date field starts at the owner's stated **25 October 2026**. Enter a comfortable outdoor pace (`min:sec/km`) or treadmill speed (`km/h`); a known tempo benchmark is optional. Blank benchmarks remain unknown. Saving a weekly baseline never creates recorded kilometres.
- Each day, complete the symptoms check-in. **I feel good** explicitly records no fatigue, soreness, pain or illness; the detailed dialog handles other answers. Today shows the run type, minutes, estimated kilometres and main-work pace/speed, followed by warm-up, work and cool-down targets. Switch outdoor/treadmill display without changing the underlying prescription.
- Without an imported plan, Policy 3 combines today's dated readiness, sleep, HRV, Body Battery, recovery and stress with actual runs this Monday–Sunday, recent demanding work and remaining known mileage. Recent Ladder/HIIT, yesterday's run, a quality run already recorded this week or incomplete running-distance coverage can replace quality/long work with easy running. Walking alone does not cancel a run; a meaningful run already recorded today prevents an automatic second session.
- Regular experience plus six recorded 20-minute runs spanning 14 days, or an explicitly supplied usual baseline of at least 8 km/week, is required before quality work. Easy pace comes from the owner's benchmark or at least two explicitly easy-rated/native-base runs; ordinary average pace is never treated as a tempo threshold. Quality work without a known tempo benchmark uses effort cues rather than fabricated numbers.
- Weekly volume maintains the supplied/recorded baseline rather than promising arbitrary increases. Specific preparation reduces the guide to 90%; taper to 60%, with shorter easy sessions, no catch-up kilometres and no training run the day before or on race day. These are disclosed product rules, not a validated individual race plan. Today's estimated distance is capped by remaining mileage only when recording coverage and pace permit that calculation.
- Pain/illness, substantial symptoms, rest days, stale readiness or scheduled Garmin work can prevent a prescription. Native readiness must be measured today within 12 hours. **Why this run today? / How targets are chosen** disclose reasons, sources and limits.
- Last-run average pace requires positive recorded distance and duration. A positive-duration treadmill recording with zero distance has **missing mileage**, not a confirmed zero-kilometre run. Correct/calibrate distance in Garmin Connect, then sync; the app does not infer it from an activity name. All running volume is in kilometres, never miles.
- Garmin calendar/plan availability is checked once daily for the current and next month. Accessible scheduled workouts are not verified watch Daily Suggested Workouts; empty results do not imply the watch has no suggestion. Failed checks retain the last schedule and show the error.
- **Start run guide** opens the selected prescription's steps with pace, treadmill speed and plan HR targets when supplied. Fixed durations use a foreground countdown; distance steps advance manually after the recorded distance. Unspecified recovery stays manual. For a duration range or unspecified duration, an optional timer is explicitly your choice—not a source-plan duration. Steps stop at zero and await manual advancement. Closing pauses. Finishing neither records an activity nor marks the plan complete. The guide does not control CIRQA, measure distance, stream HR/pace or provide background audio/notifications. Pain/illness and other blocking decisions remove the guide.

### Private imported plans

**My plan** opens the complete saved prescription. **This week** shows its own date window, which can differ from Monday–Sunday Garmin mileage. Original sessions, repeat/rest structure, pace/speed/HR ranges, taper entries and source notes remain visible. Personal plan data belongs only in the authenticated private snapshot, never public source, fixtures or browser storage. An imported plan does not require generic running setup.

Dates absent from the source stay unassigned. Choose **Use today** for an eligible current-week entry, or assign dates within that plan week; conflicting dates are rejected. An assigned session becomes today's plan automatically. Future sessions are intentions, not clearance. Recovery checks can block a session or offer a shorter alternative without editing the original. The generic single-quality-session quota and pre-race rest template do not overwrite an explicit imported prescription. Multiple hard sessions and recent strength work are disclosed risks, not permission to ignore symptoms.

**Mark complete** requires an explicit confirmation; linking a real Garmin activity is optional. Completion and reopening affect plan progress only, never native mileage, activity history or Garmin load. Guide use alone proves neither distance nor completion. Saved HR targets and maximum HR are source claims, not live measurements or independently validated zones.

**Refresh** in Train reads the stored snapshot; it does not request a Garmin sync. Use **Sync now** on Watch after syncing CIRQA to Garmin Connect. Training forms preserve unsaved edits across reads and dialog closes. Cloud saves persist in the private snapshot with conditional ETag writes; an active sync or concurrent update asks you to retry rather than overwrite newer data.

The one-time storage migration retains legacy running days, time budget, experience and race date, but drops the obsolete mixed/strength plan fields. It does not guess pace, weekly mileage or treadmill preference. Non-running legacy planner setups require new running setup. Native history and activity feedback remain intact.

## First installation

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python login.py
.venv\Scripts\python sync.py
powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1
powershell -ExecutionPolicy Bypass -File scripts\register_daily_sync.ps1
```

Login requires email/password and possibly MFA typed locally. Tokens live in `%USERPROFILE%\.garminconnect\`. The desktop shortcut targets the virtual environment's `pythonw.exe`, so no terminal stays visible.

For an initial refresh of historical metric mappings:

```powershell
.venv\Scripts\python sync.py --days 30 --force
```

Routine sync refreshes today/yesterday and skips older cached dates. Rich timelines begin with dates fetched by the updated collector; older daily summaries remain intact. Endpoint failures preserve previous values/groups and are recorded in `sync_log`; successful empty responses clear only their group. A partial sync is not marked successful. Concurrent CLI/scheduled/dashboard sync processes are serialized by a local file lock. No aggressive automatic retries.

## Vercel and iPhone

Production dashboard: **https://garmin-cirqa-lab.vercel.app**

The owner access code is saved locally in ignored `data/cloud-owner-access.txt`; never commit it or share it publicly.

`app.py` is the Flask entrypoint. Vercel's filesystem is temporary: `cloud_state.py` stores a compressed, **private** Blob containing a consistent SQLite backup, Garmin token file and job metadata. Reads reconstruct an isolated temporary database. Conditional ETag writes acquire a 330-second account-wide lease and prevent an old request from overwriting a newer snapshot. Daily sync is bounded to 220 seconds; activity detail to 180 seconds, within a 300-second function.

The cloud overview checks saved data once a minute while idle, more often during sync. It requests Garmin refresh on opening and every 30 minutes while visible. A daily cron runs at `02:30 UTC` (08:00 Asia/Kolkata; Hobby scheduling can be imprecise). Nothing depends on the PC remaining on after migration. The training workspace does not automatically trigger sync or poll over unsaved forms.

Required production environment variables:

| Variable | Purpose |
| --- | --- |
| `BLOB_READ_WRITE_TOKEN` | Read/write token for a **private** Vercel Blob store |
| `CIRQA_ORIGIN` | Exact production HTTPS origin, without a trailing slash |
| `CIRQA_ACCESS_HASH` | SHA-256 hex digest of a cryptographically random owner access code |
| `CIRQA_SESSION_SECRET` | Independent random signing secret, at least 32 characters |
| `CRON_SECRET` | Independent random bearer secret for the daily cron |
| `CIRQA_TIMEZONE` | Garmin day boundary, normally `Asia/Kolkata` |

Keep an administrative copy of the storage token in ignored `.env.cloud`. Initialize history **once**, before opening the deployment:

```powershell
py -3 scripts/cloud_admin.py init
```

Initialization refuses to overwrite an existing cloud snapshot. It backs up all local SQLite tables, including older activities, manual logs and cached details; it does not reconstruct history from only Garmin's latest activities. Local and cloud history are independent after migration.

If Garmin requires a new login, run `py -3 login.py`, then `py -3 scripts/cloud_admin.py tokens`. This replaces only the private token material and retains cloud history. Wait for any active cloud job to finish first.

Open the production URL in iPhone Safari, enter the **dashboard owner access code** (not the Garmin password), then Share → **Add to Home Screen** → Add. The manifest uses standalone display and same-origin PNG icons. There is no offline health-data cache or service worker. **Sign out** clears the owner session.

All health APIs require the signed owner cookie. Mutating requests require an exact allowed origin and the dashboard request header. The cron uses its separate bearer secret. Preview deployments must not receive production storage or owner secrets. `.vercelignore` and function exclusions keep local databases, tokens, `.env` files and backups out of deployment bundles.

## Development and diagnostics

```powershell
.venv\Scripts\python serve.py --no-open
.venv\Scripts\python query.py overview
.venv\Scripts\python query.py days 7
.venv\Scripts\python query.py coverage
.venv\Scripts\python query.py log 20
.venv\Scripts\python -m unittest test_imported_plan test_training test_cloud test_metrics test_activity_detail -v
```

API: `/api/health`, `/api/dashboard` (compact combined watch response), `/api/overview`, `/api/days`, `/api/day?date=YYYY-MM-DD` (full saved daily timelines), `/api/activities`, `/api/sync`, `/api/activity/<id>`. Day/activity GETs read saved detail only. Dashboard/day-list responses include timeline point counts rather than dense arrays. POST `/api/activity/<id>/fetch` requests native detail; POST `/api/sync` refreshes daily data. Both POST routes require `X-CIRQA-Request: 1`; cloud mode additionally requires owner authentication and an exact allowed origin. `/api/insights` and the log-write API were removed from the local server.

GET `/api/training?period=7|28` returns native load/comparisons, feedback, today's `recovery`, `running` week/baseline/race/dated race-plan/recent-runs context, nullable `imported_plan`, and the current `recommendation`. Recommendations retain nullable scalar targets and add source ranges, mixed-mode steps and the unchanged `planned_session` when applicable. POST JSON to `/api/training/profile`, `/api/training/feedback` or `/api/training/checkin` saves owner inputs. POST `/api/training/plan` accepts `install`, `schedule`, `select`, `complete` and `reopen`; plan requests are limited to 256 KiB, while other inputs retain the 4 KiB limit. Identical imports retain progress; replacement of a different existing plan is rejected. All writes use the same authentication/origin/request-header and conditional snapshot protections; validation failures leave earlier inputs intact. They never alter native Garmin scores.

The running profile schema is `race_date` (ISO date), `weekdays` (Monday=0), `minutes` (10–120), `experience` (`beginner|regular`), `surface` (`outdoor|treadmill`), nullable `easy_pace_s_per_km` and `tempo_pace_s_per_km` (120–1200), and nullable `weekly_km` (0–250). Pace is canonical seconds/km; the UI converts treadmill input. When both benchmarks exist, tempo must be faster than easy. Feedback and check-in schemas are unchanged.

## Privacy

The repository is public; private files are excluded by `.gitignore` and `.vercelignore`. Local mode keeps health data on this PC. Cloud mode stores health data, recorded GPS coordinates and refreshed Garmin tokens in private Vercel Blob storage, accessible only to the server. Never commit `data/`, `.env` files, Garmin exports or tokens. No chart or map assets are fetched from third parties. The local server remains loopback-only with Host validation; do not tunnel it or bind it to the LAN. Use the authenticated cloud entrypoint for internet access.

Garmin Connect access uses the unofficial `garminconnect` library and can change with Garmin's endpoints. Availability depends on device support, recording settings and uploads.
