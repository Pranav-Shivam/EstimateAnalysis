from fastapi import FastAPI

from api.v1.intake.route import router as intake_router

app = FastAPI(title="Estimate Analysis Backend")
app.include_router(intake_router)
