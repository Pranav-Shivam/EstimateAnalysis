import pytest

from app.graph.helper import member_hash
from app.graph.schemas import CommunityStats
from app.retrieval.repository import get_summaries, save_summary
from app.retrieval.summarizer import (
    MIN_SUMMARY_SIZE, build_summary_prompt, estimate_input_tokens, pending_summaries, run_summary_job,
    summarize_communities,
)
from core.llm.openai_summary_client import SUMMARY_MODEL, SummaryError
from tests.graph_support import FakeSummarizer


def _stats(tag, size=4, community_id=1):
    ids = [f"SKU-SUM-{tag}{i}" for i in range(size)]
    return CommunityStats(
        community_id=community_id, size=size, families=(f"Family {tag}",), dominant_category="Cat-S",
        dominant_category_share=0.75, discontinued_count=1, requirement_count=2, example_sku_ids=tuple(ids[:5]),
        member_names=tuple(f"name {i}" for i in ids), member_hash=member_hash(ids),
    )


def test_prompt_contains_the_statistics_and_member_names():
    prompt = build_summary_prompt(_stats("A"))

    assert "4 SKUs" in prompt
    assert "Family A" in prompt
    assert "Cat-S" in prompt and "75%" in prompt
    assert "Discontinued SKUs: 1" in prompt and "required parts: 2" in prompt
    assert "name SKU-SUM-A0" in prompt


def test_pending_skips_small_communities_and_cached_ones(db_session):
    cached, fresh, small = _stats("C"), _stats("F"), _stats("S", size=MIN_SUMMARY_SIZE - 1)
    save_summary(db_session, member_hash=cached.member_hash, summary="already", model=SUMMARY_MODEL)

    pending = pending_summaries(db_session, [cached, fresh, small])

    assert [s.member_hash for s in pending] == [fresh.member_hash]


def test_summarize_saves_each_summary_and_reports_counts(db_session):
    fresh, cached, small = _stats("F"), _stats("C"), _stats("S", size=MIN_SUMMARY_SIZE - 1)
    save_summary(db_session, member_hash=cached.member_hash, summary="already", model=SUMMARY_MODEL)
    summarizer, saved = FakeSummarizer(), []

    run = summarize_communities(db_session, summarizer, [fresh, cached, small], on_saved=lambda: saved.append(1))

    assert (run.generated, run.cached, run.skipped_small) == (1, 1, 1)
    assert len(summarizer.prompts) == 1 and len(saved) == 1
    assert get_summaries(db_session, [fresh.member_hash]) == {fresh.member_hash: "Fake summary number 1."}


def test_on_saved_runs_only_after_its_summary_is_already_saved(db_session):
    """`on_saved` is the caller's commit boundary. If it fired before the row was flushed, a failure on a later
    community would lose a summary that looked already paid for. Prove the ordering by having `on_saved`
    read back, through the same session, the summary for the community that was just processed."""
    pending, seen = [_stats("A"), _stats("B", community_id=2)], []

    def on_saved():
        stats = pending[len(seen)]
        seen.append(get_summaries(db_session, [stats.member_hash]).get(stats.member_hash))

    summarize_communities(db_session, FakeSummarizer(), pending, on_saved=on_saved)

    assert seen == ["Fake summary number 1.", "Fake summary number 2."]


def test_a_second_run_makes_no_calls(db_session):
    stats = [_stats("A"), _stats("B", community_id=2)]
    summarizer = FakeSummarizer()
    summarize_communities(db_session, summarizer, stats, on_saved=lambda: None)

    again = summarize_communities(db_session, summarizer, stats, on_saved=lambda: None)

    assert len(summarizer.prompts) == 2
    assert (again.generated, again.cached) == (0, 2)


def test_a_relabeled_community_reuses_its_cached_summary(db_session):
    first = _stats("R", community_id=1)
    relabeled = _stats("R", community_id=99)
    summarizer = FakeSummarizer()
    summarize_communities(db_session, summarizer, [first], on_saved=lambda: None)

    summarize_communities(db_session, summarizer, [relabeled], on_saved=lambda: None)

    assert len(summarizer.prompts) == 1


def test_only_new_communities_are_sent_to_the_model(db_session):
    old, new = _stats("O"), _stats("N", community_id=2)
    summarizer = FakeSummarizer()
    summarize_communities(db_session, summarizer, [old], on_saved=lambda: None)

    summarize_communities(db_session, summarizer, [old, new], on_saved=lambda: None)

    assert len(summarizer.prompts) == 2
    assert "Family N" in summarizer.prompts[1]


def test_a_model_failure_keeps_the_summaries_already_saved(db_session):
    first, second = _stats("A"), _stats("B", community_id=2)

    class FailsOnSecond:
        def __init__(self):
            self.calls = 0

        def summarize(self, prompt):
            self.calls += 1
            if self.calls == 2:
                raise SummaryError("boom")
            return "first summary"

    saved = []
    with pytest.raises(SummaryError):
        summarize_communities(db_session, FailsOnSecond(), [first, second], on_saved=lambda: saved.append(1))

    assert saved == [1]
    assert list(get_summaries(db_session, [first.member_hash, second.member_hash])) == [first.member_hash]


def test_estimate_input_tokens_grows_with_the_pending_list(db_session):
    one = estimate_input_tokens([_stats("A")])
    two = estimate_input_tokens([_stats("A"), _stats("B")])

    assert 0 < one < two
    assert estimate_input_tokens([]) == 0


def test_a_dry_run_reports_the_plan_and_never_builds_the_client(db_session):
    stats = [_stats("A"), _stats("B", community_id=2)]
    lines, built = [], []

    result = run_summary_job(
        db_session, stats, lambda: built.append(1) or FakeSummarizer(), yes=False, out=lines.append,
        on_saved=lambda: None,
    )

    assert result is None and built == []
    text = "\n".join(lines)
    assert "2 communities need a summary" in text
    assert SUMMARY_MODEL in text
    assert "dry run" in text and "--yes" in text


def test_the_job_with_yes_builds_the_client_and_summarizes(db_session):
    stats = [_stats("A")]
    summarizer, lines = FakeSummarizer(), []

    result = run_summary_job(
        db_session, stats, lambda: summarizer, yes=True, out=lines.append, on_saved=lambda: None,
    )

    assert result.generated == 1 and len(summarizer.prompts) == 1
    assert any("generated 1" in line for line in lines)


def test_the_job_with_nothing_pending_makes_no_client(db_session):
    stats = [_stats("A")]
    save_summary(db_session, member_hash=stats[0].member_hash, summary="done", model=SUMMARY_MODEL)
    built = []

    result = run_summary_job(
        db_session, stats, lambda: built.append(1) or FakeSummarizer(), yes=True, out=lambda line: None,
        on_saved=lambda: None,
    )

    assert built == [] and result.generated == 0
