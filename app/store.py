"""In-memory storage for transient OAuth states and async request jobs."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from app.models import AsyncRequestRecord, OAuthStateRecord, RequestStatus


class StateStore:
    """Stores transient OAuth state tokens for CSRF protection and callback mapping."""

    def __init__(self, ttl_seconds: int = 600):
        self._states: Dict[str, OAuthStateRecord] = {}
        self._lock = asyncio.Lock()
        self._ttl_seconds = ttl_seconds

    async def save(self, state: str, provider: str, user: str) -> None:
        """Store a new state associated with provider and user."""
        async with self._lock:
            self._states[state] = OAuthStateRecord(
                state=state,
                provider=provider,
                user=user,
                created_at=datetime.now(timezone.utc),
            )

    async def pop(self, state: str) -> Optional[OAuthStateRecord]:
        """Validate, retrieve, and immediately invalidate state (one-time use)."""
        async with self._lock:
            record = self._states.pop(state, None)
            if not record:
                return None
            # Check expiration
            if datetime.now(timezone.utc) - record.created_at > timedelta(seconds=self._ttl_seconds):
                return None
            return record

    async def cleanup_expired(self) -> int:
        """Remove states exceeding TTL."""
        now = datetime.now(timezone.utc)
        threshold = timedelta(seconds=self._ttl_seconds)
        async with self._lock:
            expired = [k for k, v in self._states.items() if now - v.created_at > threshold]
            for k in expired:
                del self._states[k]
            return len(expired)


class RequestStore:
    """Stores status and results of asynchronous token retrieval requests."""

    def __init__(self, ttl_seconds: int = 600):
        self._requests: Dict[str, AsyncRequestRecord] = {}
        self._lock = asyncio.Lock()
        self._ttl_seconds = ttl_seconds

    async def create(self, request_id: str, provider: str, user: str) -> AsyncRequestRecord:
        """Create a new pending async request record."""
        record = AsyncRequestRecord(
            request_id=request_id,
            provider=provider,
            user=user,
            status=RequestStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        async with self._lock:
            self._requests[request_id] = record
        return record

    async def get(self, request_id: str) -> Optional[AsyncRequestRecord]:
        """Fetch request record by ID."""
        async with self._lock:
            return self._requests.get(request_id)

    async def mark_completed(
        self,
        request_id: str,
        access_token: str,
        token_type: str = "Bearer",
        expires_at: Optional[str] = None,
    ) -> bool:
        """Mark request as completed with retrieved token."""
        async with self._lock:
            record = self._requests.get(request_id)
            if not record:
                return False
            record.status = RequestStatus.COMPLETED
            record.access_token = access_token
            record.token_type = token_type
            record.expires_at = expires_at
            record.completed_at = datetime.now(timezone.utc)
            return True

    async def mark_failed(self, request_id: str, error: str) -> bool:
        """Mark request as failed with error message."""
        async with self._lock:
            record = self._requests.get(request_id)
            if not record:
                return False
            record.status = RequestStatus.FAILED
            record.error = error
            record.completed_at = datetime.now(timezone.utc)
            return True

    async def cleanup_expired(self) -> int:
        """Remove requests exceeding TTL."""
        now = datetime.now(timezone.utc)
        threshold = timedelta(seconds=self._ttl_seconds)
        async with self._lock:
            expired = [k for k, v in self._requests.items() if now - v.created_at > threshold]
            for k in expired:
                del self._requests[k]
            return len(expired)


class ProviderStore:
    """In-memory registry of configured providers."""

    def __init__(self):
        self._providers: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def register(self, name: str, data: Dict[str, Any]) -> None:
        """Register provider in memory."""
        async with self._lock:
            self._providers[name] = data

    async def get(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieve provider details."""
        async with self._lock:
            return self._providers.get(name)

    async def has(self, name: str) -> bool:
        """Check if provider exists."""
        async with self._lock:
            return name in self._providers
