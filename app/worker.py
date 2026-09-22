"""Background worker pool for asynchronous token retrieval.

Fulfills GET /{provider}/{user} requests without blocking the HTTP handler inline.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional
from app.openbao import OpenBaoClient, OpenBaoNotFoundError
from app.store import RequestStore, StateStore

logger = logging.getLogger("integration_aggregator.worker")


@dataclass
class AsyncJob:
    """Represents a queued token retrieval job."""

    request_id: str
    provider: str
    user: str


class WorkerPool:
    """Manages an in-memory queue and concurrent worker tasks."""

    def __init__(
        self,
        openbao_client: OpenBaoClient,
        request_store: RequestStore,
        state_store: StateStore,
        concurrency: int = 5,
        cleanup_interval_seconds: int = 60,
    ):
        self.openbao_client = openbao_client
        self.request_store = request_store
        self.state_store = state_store
        self.concurrency = concurrency
        self.cleanup_interval = cleanup_interval_seconds

        self.queue: asyncio.Queue[AsyncJob] = asyncio.Queue()
        self._tasks: List[asyncio.Task] = []
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start worker and cleanup background tasks."""
        if self._running:
            return
        self._running = True
        for i in range(self.concurrency):
            task = asyncio.create_task(self._worker_loop(i))
            self._tasks.append(task)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Worker pool started with %d workers", self.concurrency)

    async def stop(self) -> None:
        """Cancel and await termination of all background tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._cleanup_task:
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
        self._tasks.clear()
        logger.info("Worker pool shut down cleanly")

    async def enqueue(self, request_id: str, provider: str, user: str) -> None:
        """Enqueue an async token retrieval request."""
        job = AsyncJob(request_id=request_id, provider=provider, user=user)
        await self.queue.put(job)

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker task processing jobs from the in-memory queue."""
        while self._running:
            try:
                job = await self.queue.get()
            except asyncio.CancelledError:
                break

            try:
                cred_name = f"{job.provider}_{job.user}"
                data = await self.openbao_client.get_credential(cred_name)
                await self.request_store.mark_completed(
                    request_id=job.request_id,
                    access_token=data.get("access_token", ""),
                    token_type=data.get("type", "Bearer"),
                    expires_at=data.get("expire_time"),
                )
            except OpenBaoNotFoundError:
                await self.request_store.mark_failed(
                    job.request_id,
                    "User not connected or credential not found in OpenBao",
                )
            except Exception as exc:
                logger.error("Error fulfilling request %s: %s", job.request_id, exc)
                await self.request_store.mark_failed(
                    job.request_id,
                    f"Token retrieval error: {str(exc)}",
                )
            finally:
                self.queue.task_done()

    async def _cleanup_loop(self) -> None:
        """Periodically cleans up expired records from in-memory stores."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                states_cleaned = await self.state_store.cleanup_expired()
                requests_cleaned = await self.request_store.cleanup_expired()
                if states_cleaned or requests_cleaned:
                    logger.debug(
                        "Evicted expired entries: %d states, %d requests",
                        states_cleaned,
                        requests_cleaned,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Cleanup loop error: %s", exc)
