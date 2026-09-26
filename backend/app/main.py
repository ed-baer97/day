"""FastAPI entrypoint — Цифровой след LPG."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.routers import balance, batches, events, ingest, map as map_router, stations, trucks
from app.schemas.common import HealthOut


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = settings.api_prefix
    app.include_router(stations.router, prefix=prefix)
    app.include_router(trucks.router, prefix=prefix)
    app.include_router(batches.router, prefix=prefix)
    app.include_router(balance.router, prefix=prefix)
    app.include_router(events.router, prefix=prefix)
    app.include_router(ingest.router, prefix=prefix)
    app.include_router(map_router.router, prefix=prefix)

    @app.get("/health", response_model=HealthOut, tags=["health"])
    def health() -> HealthOut:
        return HealthOut(status="ok", service=settings.app_name, version=__version__)

    return app


app = create_app()
