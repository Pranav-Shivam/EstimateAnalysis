import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.retrieval.snapshot import SNAPSHOT_FILE, export_snapshot, write_snapshot
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    session = make_session_factory(make_engine(Settings().database_url))()
    try:
        snapshot = export_snapshot(session)
    finally:
        session.close()
    path = DATA_DIR / SNAPSHOT_FILE
    write_snapshot(snapshot, path)
    print(
        f"wrote {len(snapshot['embeddings'])} embeddings and {len(snapshot['summaries'])} community summaries "
        f"to {path} ({path.stat().st_size / 1_000_000:.1f} MB)"
    )


if __name__ == "__main__":
    main()
