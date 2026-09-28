from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.graph.schemas import CommunityStats
from app.retrieval.repository import get_summaries, save_summary
from core.llm.openai_summary_client import SUMMARY_MODEL, SUMMARY_SYSTEM

# Communities smaller than this are not worth a paid summary; their statistics already say everything.
MIN_SUMMARY_SIZE = 3
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class SummaryRun:
    generated: int
    cached: int
    skipped_small: int


def build_summary_prompt(stats: CommunityStats) -> str:
    return (
        f"Community of {stats.size} SKUs.\n"
        f"Product families: {', '.join(stats.families) or 'none'}\n"
        f"Dominant pricing category: {stats.dominant_category} ({stats.dominant_category_share:.0%} of members)\n"
        f"Discontinued SKUs: {stats.discontinued_count}\n"
        f"SKUs with required parts: {stats.requirement_count}\n"
        f"Member names ({len(stats.member_names)} shown): {'; '.join(stats.member_names)}\n"
    )


def pending_summaries(session: Session, stats_list: list[CommunityStats]) -> list[CommunityStats]:
    candidates = [s for s in stats_list if s.size >= MIN_SUMMARY_SIZE]
    cached = get_summaries(session, [s.member_hash for s in candidates])
    return [s for s in candidates if s.member_hash not in cached]


def estimate_input_tokens(pending: list[CommunityStats]) -> int:
    return sum((len(SUMMARY_SYSTEM) + len(build_summary_prompt(s))) // CHARS_PER_TOKEN for s in pending)


def summarize_communities(
    session: Session, summarizer, stats_list: list[CommunityStats], on_saved: Callable[[], None],
) -> SummaryRun:
    """Summarize only the communities with no cached summary. `on_saved` runs after each save so the caller can
    commit: a failure part-way must not throw away summaries that were already paid for."""
    pending = pending_summaries(session, stats_list)
    for stats in pending:
        text = summarizer.summarize(build_summary_prompt(stats))
        save_summary(session, member_hash=stats.member_hash, summary=text, model=SUMMARY_MODEL)
        on_saved()
    eligible = sum(1 for s in stats_list if s.size >= MIN_SUMMARY_SIZE)
    return SummaryRun(generated=len(pending), cached=eligible - len(pending), skipped_small=len(stats_list) - eligible)


def run_summary_job(
    session: Session, stats_list: list[CommunityStats], summarizer_factory: Callable[[], object], *,
    yes: bool, out: Callable[[str], None], on_saved: Callable[[], None],
) -> SummaryRun | None:
    """A dry run unless `yes`: report the plan and cost estimate, and only then build the paid client."""
    pending = pending_summaries(session, stats_list)
    out(
        f"{len(pending)} communities need a summary; estimated {estimate_input_tokens(pending)} input tokens "
        f"with model {SUMMARY_MODEL}"
    )
    if not yes:
        out("dry run: pass --yes to call the API")
        return None
    if not pending:
        return summarize_communities(session, None, stats_list, on_saved)
    run = summarize_communities(session, summarizer_factory(), stats_list, on_saved)
    out(f"generated {run.generated}, reused {run.cached} cached, skipped {run.skipped_small} small")
    return run
