"""FastAPI application — AI Portfolio Architect."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from portfolio_architect.db.pool import create_pool, close_pool
from portfolio_architect.db.migrations import run_migrations
from api.routers import projects, documents, research, criteria, artifacts, discrepancy, screening, ingest, export, workbench


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await create_pool()
    await run_migrations(pool)
    yield
    await close_pool()


app = FastAPI(
    title="AI Portfolio Architect",
    description=(
        "Stateful research workbench that transforms unstructured text into verified "
        "portfolio definitions with inclusion/exclusion criteria. "
        "Powered by Nebius AI Cloud."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten for production; open for local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(research.router)
app.include_router(criteria.router)
app.include_router(artifacts.router)
app.include_router(discrepancy.router)
app.include_router(screening.router)
app.include_router(ingest.router)
app.include_router(export.router)
app.include_router(workbench.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "AI Portfolio Architect"}
