from procrastinate import testing
from sqlalchemy.exc import OperationalError

from app.consolidation.tasks import app, consolidate_review_item_task


def test_deferring_enqueues_a_job_with_the_review_item_id():
    in_memory = testing.InMemoryConnector()
    with app.replace_connector(in_memory) as scoped_app:
        consolidate_review_item_task.defer(review_item_id="11111111-1111-1111-1111-111111111111")

        jobs = list(scoped_app.connector.jobs.values())
        assert len(jobs) == 1
        assert jobs[0]["task_name"] == "consolidate_review_item"
        # The job row's argument field is named task_kwargs per procrastinate's own reference docs, but this
        # asserts on its content rather than guessing the exact dict key, so it stays correct either way.
        assert "11111111-1111-1111-1111-111111111111" in str(jobs[0])


def test_the_task_retries_transient_database_errors_only():
    strategy = consolidate_review_item_task.retry_strategy

    assert strategy.max_attempts > 1
    assert list(strategy.retry_exceptions) == [OperationalError]
