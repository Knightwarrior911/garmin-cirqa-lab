"""Shared Garmin Connect session helper (garminconnect 0.3.x native client).

Tokens are stored by the library under ~/.garminconnect on this machine only.
Credentials are never written to disk or this repository.

Verified against garminconnect 0.3.2:
- Garmin.login(tokenstore) loads existing tokens AND persists new ones after
  a fresh login. There is no separate dump call.
- MFA-protected accounts REQUIRE a prompt_mfa callable; without one the login
  raises "MFA Required but no prompt_mfa mechanism supplied" (client.py).
  We wire it to a terminal prompt so the owner can type the code they receive.
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
    print("Credentials are used only for this login; only session tokens are stored.")
    email = input("Garmin email: ").strip()
    password = getpass("Garmin password: ")
    garmin = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: input("Garmin MFA code (sent to your email/authenticator): ").strip(),
    )
    garmin.login(str(TOKEN_DIR))
    print(f"Login complete. Tokens saved to {TOKEN_DIR}")
    return garmin
