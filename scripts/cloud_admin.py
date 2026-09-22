"""Initialize cloud history or renew Garmin tokens without exposing their values.

Reads ignored .env.cloud from the project root, never prints credentials.
"""

import argparse
import base64
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cloud_state
from garmin_client import TOKEN_DIR
import store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "tokens"])
    args = parser.parse_args()
    env_path = ROOT / ".env.cloud"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)
    if args.action == "init":
        state = cloud_state.initial_state(store.DB_PATH, TOKEN_DIR)
        cloud_state.save_state(state)
        print("Private cloud history initialized from a consistent local SQLite backup.")
    else:
        state, etag = cloud_state.load_state()
        if cloud_state.active_lease(state):
            raise SystemExit("A cloud job is running. Wait for it to finish before updating tokens.")
        token_file = TOKEN_DIR / "garmin_tokens.json"
        state["tokens"] = {token_file.name: base64.b64encode(token_file.read_bytes()).decode("ascii")}
        state["sync"] = {"last_attempt": 0, "error": None}
        cloud_state.save_state(state, etag)
        print("Garmin tokens updated privately; cloud history preserved.")


if __name__ == "__main__":
    try:
        main()
    except cloud_state.CloudStorageError as error:
        raise SystemExit(str(error)) from None
