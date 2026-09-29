from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.v1.dedupe.route import router as dedupe_router
from api.v1.estimate.route import router as estimate_router
from api.v1.graph.route import router as graph_router
from api.v1.intake.route import router as intake_router
from api.v1.judge.route import router as judge_router
from api.v1.retrieval.route import router as retrieval_router
from api.v1.review.route import router as review_router
from app.consolidation.tasks import app as consolidation_app


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Opened sync, not async: the resolve route is a sync def running in a worker thread, and a sync pool is the
    # one procrastinate's sync .defer() can use from there. See app/consolidation/tasks.py.
    consolidation_app.open()
    try:
        yield
    finally:
        consolidation_app.close()


app = FastAPI(title="Estimate Analysis Backend", lifespan=lifespan)
app.include_router(intake_router)
app.include_router(dedupe_router)
app.include_router(estimate_router)
app.include_router(graph_router)
app.include_router(retrieval_router)
app.include_router(judge_router)
app.include_router(review_router)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
