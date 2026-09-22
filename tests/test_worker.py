"""Unit tests for background worker pool."""

import asyncio
from unittest.mock import AsyncMock
import pytest
from app.models import RequestStatus
from app.openbao import OpenBaoNotFoundError
from app.store import RequestStore, StateStore
from app.worker import WorkerPool


@pytest.mark.asyncio
async def test_worker_pool_fulfills_job():
    mock_openbao = AsyncMock()
    mock_openbao.get_credential.return_value = {
        "access_token": "token-12345",
        "type": "Bearer",
        "expire_time": "2026-10-10T10:00:00Z",
    }
    request_store = RequestStore()
    state_store = StateStore()

    worker_pool = WorkerPool(
        openbao_client=mock_openbao,
        request_store=request_store,
        state_store=state_store,
        concurrency=1,
    )
    await worker_pool.start()

    # Create request and enqueue
    req_id = "test-job-1"
    await request_store.create(req_id, "github", "alice")
    await worker_pool.enqueue(req_id, "github", "alice")

    # Wait for queue to drain
    await worker_pool.queue.join()

    record = await request_store.get(req_id)
    assert record.status == RequestStatus.COMPLETED
    assert record.access_token == "token-12345"

    await worker_pool.stop()


@pytest.mark.asyncio
async def test_worker_pool_handles_not_found():
    mock_openbao = AsyncMock()
    mock_openbao.get_credential.side_effect = OpenBaoNotFoundError("not found")
    request_store = RequestStore()
    state_store = StateStore()

    worker_pool = WorkerPool(
        openbao_client=mock_openbao,
        request_store=request_store,
        state_store=state_store,
        concurrency=1,
    )
    await worker_pool.start()

    req_id = "test-job-fail"
    await request_store.create(req_id, "github", "bob")
    await worker_pool.enqueue(req_id, "github", "bob")

    await worker_pool.queue.join()

    record = await request_store.get(req_id)
    assert record.status == RequestStatus.FAILED
    assert "not connected" in record.error.lower()

    await worker_pool.stop()
