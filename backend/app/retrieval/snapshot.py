import gzip
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.reference_data.models import Sku
from app.retrieval.models import CommunitySummary, SkuEmbedding
from app.retrieval.repository import save_embeddings, save_summary

SNAPSHOT_FILE = "llm_snapshot.json.gz"


class SnapshotMismatch(Exception):
    pass


@dataclass(frozen=True)
class RestoreSummary:
    embeddings: int
    summaries: int


def export_snapshot(session: Session) -> dict:
    """Everything that cost an LLM call to produce, so a new machine can load it instead of paying again."""
    embeddings = session.execute(
        select(SkuEmbedding.sku_id, SkuEmbedding.model, SkuEmbedding.embedding).order_by(SkuEmbedding.sku_id)
    )
    summaries = session.execute(
        select(CommunitySummary.member_hash, CommunitySummary.model, CommunitySummary.summary)
        .order_by(CommunitySummary.member_hash)
    )
    return {
        "embeddings": [
            {"sku_id": sku_id, "model": model, "embedding": [float(x) for x in vector]}
            for sku_id, model, vector in embeddings
        ],
        "summaries": [
            {"member_hash": member_hash, "model": model, "summary": summary}
            for member_hash, model, summary in summaries
        ],
    }


def restore_snapshot(session: Session, snapshot: dict) -> RestoreSummary:
    """Idempotent. Refuses a snapshot whose SKUs are not all loaded: it was exported from a different catalog, and
    embeddings attached to the wrong products would make vector search quietly wrong."""
    known = set(session.scalars(select(Sku.sku_id)))
    missing = sorted({row["sku_id"] for row in snapshot["embeddings"]} - known)
    if missing:
        raise SnapshotMismatch(
            f"{len(missing)} embedded SKUs are not in the database (first: {missing[0]}); "
            "run load_data.py first, and check the snapshot matches this catalog"
        )
    by_model: dict[str, list[tuple[str, list[float]]]] = {}
    for row in snapshot["embeddings"]:
        by_model.setdefault(row["model"], []).append((row["sku_id"], row["embedding"]))
    for model, items in by_model.items():
        save_embeddings(session, model, items)
    for row in snapshot["summaries"]:
        save_summary(session, member_hash=row["member_hash"], summary=row["summary"], model=row["model"])
    return RestoreSummary(embeddings=len(snapshot["embeddings"]), summaries=len(snapshot["summaries"]))


def write_snapshot(snapshot: dict, path: Path) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(snapshot, handle, separators=(",", ":"))


def read_snapshot(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)
