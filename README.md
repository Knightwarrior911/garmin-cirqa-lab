# CIRQA Performance Lab

Local, private performance dashboard for a **Garmin CIRQA** (screenless 24/7 band)
paired with an iPhone, running on a **Windows PC**. Pulls your Garmin Connect cloud
data into a local SQLite database and turns it into **specific, numeric training
insights** — not just charts.

```
CIRQA → iPhone (Garmin Connect) → Garmin cloud
                                      │  sync.py pulls daily
                              data\garmin.db  (local SQLite)
                                      │
        serve.py → http://127.0.0.1:8787  (dashboard + insight engine)
```

## What it gives you

**Insights with numbers and actions**, computed by deterministic local rules
(`insights.py`) — no cloud AI, nothing leaves the machine:

- **Run analysis** — per-km splits from Garmin: pace fade within runs, HR drift,
  and aerobic-efficiency trend (pace at the same heart rate across weeks).
- **Load management** — acute vs chronic training-load ratio with spike warnings.
- **Recovery coupling** — how much your morning HRV drops after hard sessions,
  using the manual gym log.
- **Daily guidance** — a Green light / Steady / Recover directive with the exact
  HRV, resting-HR, and sleep numbers behind it.
- **Trend charts** for HRV, RHR, sleep, stress, Body Battery, SpO2, steps, readiness.
- **Training log** — the layer CIRQA cannot see (barbell loads, reps, RPE,
  soreness). Logged entries feed the recovery-coupling insights on the next refresh.

## Quick start (human version)

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python sync.py --demo     # optional: preview with synthetic data
.venv\Scripts\python login.py           # one-time: Garmin email + password + MFA
.venv\Scripts\python sync.py            # backfill ~30 days incl. run splits
.venv\Scripts\python serve.py           # dashboard on http://127.0.0.1:8787
```

## Handing this to an AI agent

Give the repo to any coding agent (Claude Code, Codex, Cursor, ...) and say:

> Read AGENTS.md and execute it.

`AGENTS.md` contains the complete ordered runbook — prerequisites, smoke tests,
the one interactive login, verification checklist, and troubleshooting. The only
human input ever required is the Garmin login in Step 3.

## Data collected

| Table | Contents |
|---|---|
| `days` | steps, calories, resting HR, stress avg, Body Battery high/low, SpO2, respiration, sleep seconds/score, HRV (last night + weekly + baseline), training readiness |
| `activities` | name, type, start, duration, distance, calories, avg/max HR |
| `splits` | per-km distance, duration, avg HR, pace for recent runs |
| `training_log` | your manual gym entries (date, session, exercise, sets/reps/load, RPE, soreness) |
| `sync_log` | sync history for diagnostics |

## Security & privacy

- Health data stays in `data\` — **gitignored, never committed or pushed**.
- Garmin credentials are never stored; only garth refresh tokens live in
  `%USERPROFILE%\.garminconnect\` on this machine. Treat that folder like a password.
- The dashboard binds to `127.0.0.1` only — not reachable from the network.
- Uses the unofficial `python-garminconnect` API; if Garmin changes endpoints,
  re-sync after updating the package (`pip install -U garminconnect`).

## Repo layout

```
AGENTS.md            agent runbook (start here when automating)
sync.py              Garmin cloud → SQLite collector (+ --demo smoke data)
insights.py          deterministic insight engine (13 rules)
serve.py             stdlib dashboard server, port 8787
query.py             JSON CLI: overview | days | activities | insights | log
store.py             SQLite schema + access layer
garmin_client.py     token-aware Garmin session helper
login.py             one-time interactive login
import_fit.py        optional local .FIT importer (data\fit\)
dashboard\index.html the UI
scripts\             optional Windows task-scheduler registration
```
