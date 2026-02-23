"""FastAPI application entry point."""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from routers.analyze import router as analyze_router
from routers.questrade import router as questrade_router

app = FastAPI(
    title="Portfolio Risk Flamegraph",
    description="Fama-French 3-factor variance decomposition API",
    version="1.0.0",
)

# CORS — allow frontend to call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router)
app.include_router(questrade_router)


@app.get("/")
async def root():
    return {"status": "ok", "message": "Portfolio Risk Flamegraph API"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
