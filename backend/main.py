from fastapi import FastAPI

from api.v1.dedupe.route import router as dedupe_router
from api.v1.estimate.route import router as estimate_router
from api.v1.intake.route import router as intake_router

app = FastAPI(title="Estimate Analysis Backend")
app.include_router(intake_router)
app.include_router(dedupe_router)
app.include_router(estimate_router)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
