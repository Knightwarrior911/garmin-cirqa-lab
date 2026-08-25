# AGENTS.md — Setup Runbook for the AI Agent

You are setting up and operating a local Garmin CIRQA data pipeline on this Windows PC.
Follow the steps **in order**. Every command is idempotent unless marked otherwise.
The **only human input required in the entire setup** is Step 4: the device owner types
their Garmin email, password, and MFA code into the terminal when prompted. Nothing else
needs human action.

## Hard rules

- NEVER commit or push anything under `data/` or `.venv/` (already in `.gitignore`).
- NEVER write the owner's Garmin credentials into any file, command line, or log.
  Credentials are only entered interactively at the `login.py` prompt.
- NEVER print token file contents. Tokens live in `%USERPROFILE%\.garminconnect\`.
- Run every Python command from the repository root using the venv interpreter:
  `.venv\Scripts\python`. Do not use the system Python for app commands.
- If any step fails, consult Troubleshooting below before improvising.

## What this repo does

```
CIRQA (wrist) → Bluetooth → iPhone Garmin Connect → Garmin cloud
                                                       │
                              this PC: sync.py (pulls cloud data daily)
                                                       │
                                            data\garmin.db (SQLite, local)
                                                       │
                             serve.py → http://127.0.0.1:8787 dashboard
                             insights.py → rules that turn data into actions
```

- The device owner wears the CIRQA; their iPhone syncs it to Garmin's cloud.
- `sync.py` pulls that cloud data to a local SQLite DB: daily HRV, resting HR, sleep,
  stress, Body Battery, SpO2, steps, training readiness, activities, and per-km run splits.
- `serve.py` serves a private dashboard with an insight engine that produces concrete,
  numeric recommendations (pace fade, aerobic efficiency, load spikes, recovery coupling).
- Nothing leaves this machine. No Garmin credentials are stored in the repo.

## Step 0 — Verify prerequisites

```powershell
py -3 --version
```

Expected: `Python 3.10` or newer (3.11/3.12 ideal). If `py` is missing, try `python --version`
and substitute `python` for `py -3` everywhere below. If neither exists:

```powershell
winget install -e --id Python.Python.3.12
```

then open a NEW terminal and re-check. Also verify `git --version` (needed only to clone).

## Step 1 — Create the virtualenv

From the repository root:

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -r requirements.txt
```

Expected: installs `garminconnect`, `curl_cffi`, `fitdecode` without errors.

## Step 2 — Pipeline smoke test (no Garmin account needed)

```powershell
.venv\Scripts\python sync.py --demo
```

Expected output: `Demo data written: 30 days, 11 activities, 4 run split sets, 4 log entries.`

Then verify the API layer:

```powershell
.venv\Scripts\python serve.py --no-open --port 8787
# in a SECOND terminal:
curl http://127.0.0.1:8787/api/overview
curl http://127.0.0.1:8787/api/insights
```

Expected: JSON with `"ok": true`; insights list contains entries such as
`pace_fade`, `hr_drift`, `aerobic_efficiency`, `easy_gap`. Stop the server (Ctrl+C).

Then clear the demo rows so real data starts clean (a real sync also does this
automatically, but clearing now keeps things obvious):

```powershell
.venv\Scripts\python sync.py --clear-demo
```

## Step 3 — First sync (THE ONLY STEP REQUIRING THE OWNER)

The owner must be present to type credentials. Run:

```powershell
.venv\Scripts\python login.py
```

The script prompts for:
1. Garmin email
2. Garmin password (hidden input)
3. MFA one-time code (sent to their email/authenticator, only if MFA is enabled)

Expected: `Login OK.` plus today's step count. Tokens are saved to
`%USERPROFILE%\.garminconnect\` — future syncs never ask again.

Then backfill (default 30 days; the device already has ~4+ days of history):

```powershell
.venv\Scripts\python sync.py
```

Expected: `Synced N days (...), M activities, K new run split sets.` with N ≥ 4.

## Step 4 — Launch the dashboard

```powershell
.venv\Scripts\python serve.py
```

Opens `http://127.0.0.1:8787` in the default browser. Verify visually:
- "Today's guidance" card shows a directive with numeric reasons.
- "Insights" lists rules with real numbers (or an explicit not-enough-data notice).
- "Activities" shows the owner's runs; runs with splits show per-km bars + fade %.
- Training log accepts an entry (submit the form; the table and insights refresh).

## Step 5 — Daily automation (optional but recommended)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_sync.ps1
```

Registers a scheduled task `GarminCirqaSync` (daily 08:30). Verify:
`Get-ScheduledTask GarminCirqaSync`. Remove with
`Unregister-ScheduledTask -TaskName "GarminCirqaSync" -Confirm:$false`.

## Step 6 — Optional: local FIT files

If the owner copies `.FIT` files from the CIRQA (Garmin Connect iPhone app →
device settings → System → USB File Access) into `data\fit\`:

```powershell
.venv\Scripts\python import_fit.py
```

## Using the data (for you, the agent)

Answer the owner's questions by querying the store directly — print JSON:

```powershell
.venv\Scripts\python query.py overview      # coverage, last sync, latest day
.venv\Scripts\python query.py days 14       # last 14 days of metrics
.venv\Scripts\python query.py activities 10 # recent activities (runs include splits)
.venv\Scripts\python query.py insights      # full insight engine output
.venv\Scripts\python query.py log 20        # manual training log
```

When the owner asks "how am I doing / what should I change", run `query.py insights`
and ground your answer in its numbers. Do not invent metrics that are not in the store.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `login.py` asks for credentials again after working before | Tokens expired or were cleared — just log in again once. |
| MFA code rejected | Codes expire fast; request a fresh one and enter it immediately. |
| `sync.py` prints `! <date>: ...` lines | One endpoint failed for one day; the sync continues. Re-run `sync.py --force` later to backfill. |
| Garmin rate limiting / 429 errors | Wait 10+ minutes before the next sync; keep syncs to 1-2 per day. |
| Port 8787 busy | `serve.py --port 8790`. |
| `py` not found but `python` works | Use `python -m venv .venv` and `.venv\Scripts\python` everywhere. |
| Dashboard shows "Demo data" banner | Demo rows are present; run `sync.py --clear-demo` (real sync also removes them). |
| Insights section says not enough data | Expected before ~7 days of syncs; keep the daily task running. |

## Verification checklist (report results to the owner)

1. `py -3 --version` → version printed.
2. `pip install -r requirements.txt` → exit code 0.
3. `sync.py --demo` → demo counts line printed.
4. `/api/overview` and `/api/insights` → `"ok": true`.
5. `sync.py --clear-demo` → `Demo rows cleared: N` (N > 0).
6. `login.py` → `Login OK.`
7. `sync.py` → `Synced N days` with N ≥ 4.
8. Dashboard loads; guidance + insights render with real values.
