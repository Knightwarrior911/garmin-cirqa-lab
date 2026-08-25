"""One-time interactive Garmin login. Stores tokens under ~/.garminconnect.

Run from the repository root:
    .venv\\Scripts\\python login.py
"""
from datetime import date

from garmin_client import connect


def main():
    garmin = connect()
    today = date.today().isoformat()
    steps = None
    try:
        stats = garmin.get_stats(today) or {}
        steps = stats.get("totalSteps")
    except Exception:
        pass
    print("Login OK.")
    print(f"Today's steps so far: {steps if steps is not None else 'n/a (no data yet today)'}")
    print("Next:  .venv\\Scripts\\python sync.py")


if __name__ == "__main__":
    main()
