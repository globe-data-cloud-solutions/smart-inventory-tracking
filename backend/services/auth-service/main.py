from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import auth


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


app = FastAPI(title="SMART Auth Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "auth"}
