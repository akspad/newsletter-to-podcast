"""Configurable daily scheduling without exposing source configuration."""
from datetime import datetime, timezone
import os
import sys

from config import Settings
import storage


def scheduled_run_due(state, now, runs_per_day):
    """Allow one successful scheduled run per evenly spaced UTC window."""
    last = state.get("last_scheduled_run")
    if not last:
        return True

    def window(value):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        seconds = value.hour * 3600 + value.minute * 60 + value.second
        return value.date(), seconds * runs_per_day // 86400

    return window(now) > window(datetime.fromisoformat(last))


def main():
    try:
        settings = Settings.from_env()
        due = (os.environ.get("GITHUB_EVENT_NAME") != "schedule" or
               scheduled_run_due(storage.load(settings), datetime.now(timezone.utc), settings.runs_per_day))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"due={'true' if due else 'false'}\n")
        print("Podcast run is due." if due else "Scheduling window already completed; skipping generation.")
        return 0
    except Exception as error:
        print(f"Schedule check failed ({type(error).__name__}); existing output was left unchanged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
