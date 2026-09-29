"""Runs the procrastinate worker that executes deferred consolidation jobs. A long-running process, started
manually (`python scripts/run_worker.py` from backend/, where .env lives), never by the test suite or by any
request-serving process."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.consolidation.tasks import run_worker


def main() -> None:
    run_worker()


if __name__ == "__main__":
    main()
