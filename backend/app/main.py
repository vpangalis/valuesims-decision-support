from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.cases import router as cases_router

app = FastAPI(
    title="ValueSims Case API",
    version="0.1"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cases_router)
