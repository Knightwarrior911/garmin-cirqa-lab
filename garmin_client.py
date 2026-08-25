"""Shared Garmin Connect session helper (garminconnect 0.3.x API).

Tokens are stored by the library under ~/.garminconnect on this machine only.
Credentials are never written to disk or this repository.

Verified against garminconnect 0.3.2: Garmin.login(tokenstore) both loads
existing tokens AND persists new ones after a fresh login (including the
interactive MFA prompt). There is no separate dump call in this version.
"""
import sys
from getpass import getpass
from pathlib import Path

TOKEN_DIR = Path.home() / ".garminconnect"


def connect(interactive=True):
    """Return a logged-in garminconnect.Garmin instance."""
    try:
        from garminconnect import Garmin
    except ImportError:
        sys.exit(
            "garminconnect is not installed.\n"
            "Run:  .venv\\Scripts\\python -m pip install -r requirements.txt"
        )

    garmin = Garmin()
    try:
        garmin.login(str(TOKEN_DIR))  # resumes from stored tokens when present
        return garmin
    except Exception:
        if not interactive:
            sys.exit("No valid Garmin session. Run:  .venv\\Scripts\\python login.py")

    print("Garmin login required (tokens missing or expired).")
    print("Credentials are used only for this login; only garth tokens are stored.")
    email = input("Garmin email: ").strip()
    password = getpass("Garmin password: ")
    garmin = Garmin(email=email, password=password)
    garmin.login(str(TOKEN_DIR))  # prompts for the MFA code on the terminal when enabled; persists tokens
    print(f"Login complete. Tokens saved to {TOKEN_DIR}")
    return garmin
