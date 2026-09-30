import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.retrieval.snapshot import SNAPSHOT_FILE, read_snapshot, restore_snapshot
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    snapshot = read_snapshot(DATA_DIR / SNAPSHOT_FILE)
    session = make_session_factory(make_engine(Settings().database_url))()
    try:
        summary = restore_snapshot(session, snapshot)
        session.commit()
    finally:
        session.close()
    print(f"restored {summary.embeddings} embeddings and {summary.summaries} community summaries; no API was called")


if __name__ == "__main__":
    main()
