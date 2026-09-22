"""Unit tests for in-memory stores (StateStore, RequestStore, ProviderStore)."""

import asyncio
import pytest
from app.models import RequestStatus
from app.store import ProviderStore, RequestStore, StateStore


@pytest.mark.asyncio
async def test_state_store_lifecycle():
    store = StateStore(ttl_seconds=1)

    # Save state
    await store.save("state-123", "github", "user-1")

    # Retrieve state (consuming it)
    record = await store.pop("state-123")
    assert record is not None
    assert record.state == "state-123"
    assert record.provider == "github"
    assert record.user == "user-1"

    # State cannot be reused (one-time use CSRF protection)
    second_pop = await store.pop("state-123")
    assert second_pop is None


@pytest.mark.asyncio
async def test_state_store_expiration():
    # TTL of 0 seconds means immediately expired
    store = StateStore(ttl_seconds=0)
    await store.save("state-expired", "github", "user-1")
    await asyncio.sleep(0.01)

    record = await store.pop("state-expired")
    assert record is None

    cleaned = await store.cleanup_expired()
    assert cleaned == 0  # pop already deleted it or cleanup removes it


@pytest.mark.asyncio
async def test_request_store_lifecycle():
    store = RequestStore(ttl_seconds=10)

    # Create request
    record = await store.create("req-abc", "github", "alice")
    assert record.request_id == "req-abc"
    assert record.status == RequestStatus.PENDING

    # Read pending
    fetched = await store.get("req-abc")
    assert fetched is not None
    assert fetched.status == RequestStatus.PENDING

    # Mark completed
    success = await store.mark_completed(
        "req-abc",
        access_token="gho_mocktoken123",
        token_type="Bearer",
        expires_at="2026-10-01T00:00:00Z",
    )
    assert success is True

    completed = await store.get("req-abc")
    assert completed.status == RequestStatus.COMPLETED
    assert completed.access_token == "gho_mocktoken123"
    assert completed.token_type == "Bearer"


@pytest.mark.asyncio
async def test_request_store_mark_failed():
    store = RequestStore(ttl_seconds=10)
    await store.create("req-fail", "github", "bob")
    await store.mark_failed("req-fail", "Network error")

    record = await store.get("req-fail")
    assert record.status == RequestStatus.FAILED
    assert record.error == "Network error"


@pytest.mark.asyncio
async def test_provider_store():
    store = ProviderStore()
    assert not await store.has("google")

    await store.register("google", {"provider": "google", "client_id": "gid123"})
    assert await store.has("google")

    data = await store.get("google")
    assert data["client_id"] == "gid123"
