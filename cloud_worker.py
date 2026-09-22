"""Bounded subprocess entrypoint used only with a private request workspace."""

import json
import os
from pathlib import Path
import sys
import time

import activity_detail
from garmin_client import connect
import store
import sync


def run(kind, directory, aid=None):
    if hasattr(time, "tzset"):
        os.environ["TZ"] = os.environ.get("CIRQA_TIMEZONE", "Asia/Kolkata")
        time.tzset()
    conn = store.connect_db(directory / "garmin.db")
    error = None
    try:
        garmin = connect(interactive=False, token_dir=directory / "tokens")
        if kind == "sync":
            if not sync.sync_real(garmin, conn, 2, quiet=True):
                error = "Garmin returned some incomplete daily endpoints. Available readings were saved; missing readings were not replaced."
        elif kind == "activity" and aid and aid.isdigit():
            activity_detail.download_into(conn, garmin, aid)
        else:
            raise ValueError("Unsupported cloud job")
    except SystemExit:
        error = "The Garmin session needs renewal. Run login.py locally and securely update the cloud token snapshot. Stored history is preserved."
    except Exception:
        error = "Garmin refresh failed. Cached data is preserved; check the Garmin session or try again later."
    finally:
        conn.close()
        (directory / "result.json").write_text(json.dumps({"error": error}), encoding="utf-8")
    return 1 if error else 0


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(2)
    raise SystemExit(run(sys.argv[1], Path(sys.argv[2]), sys.argv[3] if len(sys.argv) == 4 else None))
