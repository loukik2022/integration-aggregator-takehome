"""Main entrypoint for the Integration Aggregator FastAPI service."""

from contextlib import asynccontextmanager
import time
from fastapi import FastAPI, Request
from app.api.endpoints import router as api_router
from app.config import settings
from app.logging_config import setup_logging
from app.openbao import OpenBaoClient
from app.store import ProviderStore, RequestStore, StateStore
from app.worker import WorkerPool

logger = setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for application startup and shutdown."""
    logger.info("Initializing Integration Aggregator service...")

    openbao_client = OpenBaoClient(
        base_url=settings.openbao_addr,
        token=settings.openbao_token,
        mount_path=settings.openbao_mount_path,
        timeout=settings.openbao_timeout,
    )
    state_store = StateStore(ttl_seconds=settings.state_ttl_seconds)
    request_store = RequestStore(ttl_seconds=settings.request_ttl_seconds)
    provider_store = ProviderStore()

    worker_pool = WorkerPool(
        openbao_client=openbao_client,
        request_store=request_store,
        state_store=state_store,
        concurrency=settings.worker_concurrency,
    )

    app.state.openbao_client = openbao_client
    app.state.state_store = state_store
    app.state.request_store = request_store
    app.state.provider_store = provider_store
    app.state.worker_pool = worker_pool

    await worker_pool.start()
    logger.info("Integration Aggregator service ready on port %d", settings.port)

    yield

    logger.info("Shutting down Integration Aggregator...")
    await worker_pool.stop()
    await openbao_client.close()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Integration Aggregator",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ready"}


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Sanitized request/response logging middleware."""
    start_time = time.time()
    safe_path = request.url.path
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(
        "%s %s -> %d (%.2f ms)",
        request.method,
        safe_path,
        response.status_code,
        duration * 1000,
    )
    return response


app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
