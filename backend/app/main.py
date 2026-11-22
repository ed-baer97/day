"""FastAPI entrypoint — Цифровой след LPG."""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import require_admin, require_principal
from app.config import get_settings
from app.domain.errors import DomainError
from app.routers import (
    auth,
    balance,
    batches,
    cashiers,
    events,
    ingest,
    map as map_router,
    owners,
    public,
    shelly,
    shifts,
    station_owners,
    stations,
    tanks,
    trucks,
)
from app.schemas.common import HealthOut
from app.services.boot import import_state_if_empty, restore_memory_state, run_migrations
from app.services.shelly_link import shelly_poller


@asynccontextmanager
async def lifespan(_app: FastAPI):
    testing = (
        "PYTEST_CURRENT_TEST" in os.environ
        or os.environ.get("TESTING") == "true"
        or os.environ.get("AUTH_DISABLED") == "true"
    )
    if not testing:
        settings = get_settings()
        if settings.use_postgres:
            run_migrations()
            import_state_if_empty()
        else:
            restore_memory_state()
        shelly_poller.start()
    try:
        yield
    finally:
        if not testing:
            shelly_poller.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Device-Token"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if not request.url.path.startswith(f"{settings.api_prefix}/public"):
            response.headers["Cache-Control"] = "no-store"
        return response

    prefix = settings.api_prefix
    admin_guard = [Depends(require_admin)]
    # Станции, резервуары, кассиры и смены: проверка прав внутри роутеров.
    app.include_router(stations.router, prefix=prefix, dependencies=[Depends(require_principal)])
    app.include_router(tanks.router, prefix=prefix, dependencies=[Depends(require_principal)])
    app.include_router(cashiers.router, prefix=prefix, dependencies=[Depends(require_principal)])
    app.include_router(shifts.router, prefix=prefix, dependencies=[Depends(require_principal)])
    app.include_router(shelly.router, prefix=prefix, dependencies=admin_guard)
    app.include_router(station_owners.router, prefix=prefix, dependencies=admin_guard)
    app.include_router(owners.router, prefix=prefix, dependencies=admin_guard)
    app.include_router(trucks.router, prefix=prefix, dependencies=admin_guard)
    app.include_router(batches.router, prefix=prefix, dependencies=admin_guard)
    app.include_router(balance.router, prefix=prefix, dependencies=admin_guard)
    app.include_router(events.router, prefix=prefix, dependencies=admin_guard)
    app.include_router(map_router.router, prefix=prefix, dependencies=admin_guard)
    app.include_router(ingest.router, prefix=prefix)
    app.include_router(public.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)

    @app.get("/health", response_model=HealthOut, tags=["health"])
    def health() -> HealthOut:
        return HealthOut(status="ok", service=settings.app_name, version=settings.app_version)

    return app


app = create_app()
