"""Runs the procrastinate worker that executes deferred consolidation jobs. A long-running process, started
manually (`python run_worker.py`), never by the test suite or by any request-serving process."""
from app.consolidation.tasks import app


def main() -> None:
    with app.open():
        app.run_worker()


if __name__ == "__main__":
    main()
