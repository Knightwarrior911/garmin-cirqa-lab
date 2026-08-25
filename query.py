"""Agent-friendly CLI over the local store. Prints JSON.

    .venv\\Scripts\\python query.py overview
    .venv\\Scripts\\python query.py days 14
    .venv\\Scripts\\python query.py activities 10
    .venv\\Scripts\\python query.py log 10
    .venv\\Scripts\\python query.py insights
    .venv\\Scripts\\python query.py coverage
"""
import json
import sys

import insights
import store


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "overview"
    arg = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
    conn = store.connect_db()
    if cmd == "overview":
        out = store.overview(conn)
    elif cmd == "days":
        out = [store.day_to_dict(r) for r in store.get_days(conn, arg or 14)]
    elif cmd == "activities":
        out = store.get_activities(conn, arg or 10)
    elif cmd == "log":
        out = store.get_log(conn, arg or 20)
    elif cmd == "insights":
        out = insights.generate(conn)
    elif cmd == "coverage":
        out = store.coverage(conn)
    else:
        sys.exit(f"Unknown command: {cmd}. Use overview|days|activities|log|insights|coverage")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
