from fastapi import FastAPI
from app.api.cases import router as cases_router

app = FastAPI(
    title="ValueSims Case API",
    version="0.1"
)

app.include_router(cases_router)
