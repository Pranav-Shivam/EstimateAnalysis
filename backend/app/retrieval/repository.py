from sqlalchemy import select
from sqlalchemy.orm import Session

from app.retrieval.models import CommunitySummary


def get_summaries(session: Session, hashes: list[str]) -> dict[str, str]:
    if not hashes:
        return {}
    rows = session.execute(
        select(CommunitySummary.member_hash, CommunitySummary.summary).where(CommunitySummary.member_hash.in_(hashes))
    )
    return {member_hash: summary for member_hash, summary in rows}


def save_summary(session: Session, *, member_hash: str, summary: str, model: str) -> None:
    row = session.get(CommunitySummary, member_hash)
    if row is None:
        row = CommunitySummary(member_hash=member_hash)
        session.add(row)
    row.summary = summary
    row.model = model
    session.flush()
