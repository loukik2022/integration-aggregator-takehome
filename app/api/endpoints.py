"""HTTP request handlers implementing the integration aggregator endpoints."""

import logging
import secrets
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from app.models import (
    AsyncAcceptedResponse,
    AsyncStatusResponse,
    CallbackResponse,
    ConnectResponse,
    ProviderRegisterRequest,
    ProviderRegisterResponse,
    RequestStatus,
)
from app.openbao import OpenBaoClient, OpenBaoError
from app.store import ProviderStore, RequestStore, StateStore
from app.worker import WorkerPool

logger = logging.getLogger("integration_aggregator.api")
router = APIRouter()


# Dependency injection helpers
def get_openbao(request: Request) -> OpenBaoClient:
    return request.app.state.openbao_client


def get_state_store(request: Request) -> StateStore:
    return request.app.state.state_store


def get_request_store(request: Request) -> RequestStore:
    return request.app.state.request_store


def get_provider_store(request: Request) -> ProviderStore:
    return request.app.state.provider_store


def get_worker_pool(request: Request) -> WorkerPool:
    return request.app.state.worker_pool


@router.post(
    "/providers",
    response_model=ProviderRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new OAuth/OIDC provider",
)
async def register_provider(
    body: ProviderRegisterRequest,
    openbao: OpenBaoClient = Depends(get_openbao),
    provider_store: ProviderStore = Depends(get_provider_store),
):
    """Register an OAuth provider with OpenBao and cache metadata in memory."""
    try:
        await openbao.configure_server(
            name=body.name,
            provider=body.provider,
            client_id=body.client_id,
            client_secret=body.client_secret,
            provider_options=body.provider_options,
        )
    except OpenBaoError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenBao registration failed: {str(exc)}",
        )

    # Store provider metadata in memory (excluding secret)
    await provider_store.register(
        body.name,
        {
            "name": body.name,
            "provider": body.provider,
            "client_id": body.client_id,
            "scopes": body.scopes,
        },
    )

    logger.info("Provider registered successfully: %s (%s)", body.name, body.provider)
    return ProviderRegisterResponse(name=body.name, status="registered")


@router.post(
    "/providers/{provider}/users/{user}/connect",
    response_model=ConnectResponse,
    summary="Initiate OAuth authorization connection for a user",
)
async def connect_user(
    provider: str,
    user: str,
    request: Request,
    redirect_uri: Optional[str] = Query(default=None, description="Optional custom redirect URI"),
    openbao: OpenBaoClient = Depends(get_openbao),
    state_store: StateStore = Depends(get_state_store),
    provider_store: ProviderStore = Depends(get_provider_store),
):
    """Generate state, store transient mapping, and obtain provider authorization URL."""
    provider_data = await provider_store.get(provider)
    scopes = provider_data.get("scopes") if provider_data else None

    # Generate cryptographically secure random state
    state = secrets.token_urlsafe(32)
    await state_store.save(state, provider, user)

    # Use explicit redirect_uri or construct from request base URL
    effective_redirect = redirect_uri or f"{str(request.base_url).rstrip('/')}/callback"

    try:
        auth_url = await openbao.get_auth_code_url(
            server=provider,
            state=state,
            scopes=scopes,
            redirect_url=effective_redirect,
        )
    except OpenBaoError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to generate authorization URL: {str(exc)}",
        )

    logger.info("Initiated connection for user '%s' on provider '%s'", user, provider)
    return ConnectResponse(auth_url=auth_url, state=state)


@router.get(
    "/callback",
    response_model=CallbackResponse,
    summary="OAuth callback receiving authorization code and state",
)
async def oauth_callback(
    code: str = Query(..., description="Authorization code from provider"),
    state: str = Query(..., description="OAuth state parameter"),
    openbao: OpenBaoClient = Depends(get_openbao),
    state_store: StateStore = Depends(get_state_store),
):
    """Validate state from memory and exchange authorization code via OpenBao."""
    state_record = await state_store.pop(state)
    if not state_record:
        logger.warning("Callback received invalid or expired state")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state parameter",
        )

    provider = state_record.provider
    user = state_record.user
    cred_name = f"{provider}_{user}"

    try:
        await openbao.exchange_code(server=provider, cred_name=cred_name, code=code)
    except OpenBaoError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Code exchange failed in OpenBao: {str(exc)}",
        )

    logger.info("Successfully connected user '%s' to provider '%s'", user, provider)
    return CallbackResponse(status="connected", provider=provider, user=user)


@router.get(
    "/requests/{request_id}",
    response_model=AsyncStatusResponse,
    summary="Poll status/result of an async token retrieval request",
)
async def get_request_status(
    request_id: str,
    request_store: RequestStore = Depends(get_request_store),
):
    """Check whether async token retrieval has completed, failed, or is still pending."""
    record = await request_store.get(request_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found or expired",
        )

    return AsyncStatusResponse(
        request_id=record.request_id,
        status=record.status,
        access_token=record.access_token,
        token_type=record.token_type,
        expires_at=record.expires_at,
        error=record.error,
    )


@router.get(
    "/{provider}/{user}",
    response_model=AsyncAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retrieve access token asynchronously (returns 202 with Location header)",
)
async def retrieve_token_async(
    provider: str,
    user: str,
    response: Response,
    request_store: RequestStore = Depends(get_request_store),
    worker_pool: WorkerPool = Depends(get_worker_pool),
):
    """Enqueue token retrieval request to background worker and return 202 Accepted immediately."""
    request_id = str(uuid.uuid4())
    location = f"/requests/{request_id}"

    # Set HTTP Location header per RFC 7231
    response.headers["Location"] = location

    # Persist pending record in memory and dispatch to worker queue
    await request_store.create(request_id, provider, user)
    await worker_pool.enqueue(request_id, provider, user)

    logger.info("Enqueued async token request %s for %s/%s", request_id, provider, user)
    return AsyncAcceptedResponse(
        request_id=request_id,
        status=RequestStatus.PENDING.value,
        location=location,
    )
