"""End-to-end integration tests for FastAPI HTTP routes."""

import pytest
from httpx import ASGITransport, AsyncClient
import respx
from app.main import app, lifespan


@pytest.fixture
async def client():
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


@pytest.mark.asyncio
async def test_probes(client: AsyncClient):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


@pytest.mark.asyncio
@respx.mock
async def test_register_provider(client: AsyncClient):
    # Mock OpenBao endpoint
    respx.post("http://openbao:8200/v1/oauth2/servers/github").respond(status_code=204)

    payload = {
        "name": "github",
        "provider": "github",
        "client_id": "test_client_id",
        "client_secret": "super_secret_val",
        "scopes": ["read:user", "repo"],
    }
    resp = await client.post("/providers", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "github"
    assert data["status"] == "registered"
    # Ensure client_secret is NEVER returned in response
    assert "super_secret_val" not in resp.text
    assert "client_secret" not in data


@pytest.mark.asyncio
@respx.mock
async def test_connect_user(client: AsyncClient):
    # Mock OpenBao auth-code-url
    respx.post("http://openbao:8200/v1/oauth2/auth-code-url").respond(
        status_code=200,
        json={"data": {"url": "https://github.com/login/oauth/authorize?client_id=cid"}},
    )

    resp = await client.post("/providers/github/users/alice/connect")
    assert resp.status_code == 200
    data = resp.json()
    assert "auth_url" in data
    assert "state" in data
    assert len(data["state"]) > 10


@pytest.mark.asyncio
@respx.mock
async def test_callback_flow(client: AsyncClient):
    # 1. Start connect to generate a valid state
    respx.post("http://openbao:8200/v1/oauth2/auth-code-url").respond(
        status_code=200,
        json={"data": {"url": "https://github.com/login/oauth/authorize?client_id=cid"}},
    )
    connect_resp = await client.post("/providers/github/users/bob/connect")
    state = connect_resp.json()["state"]

    # 2. Mock OpenBao code exchange
    respx.post("http://openbao:8200/v1/oauth2/creds/github_bob").respond(status_code=204)

    # 3. Call callback with valid state and code
    cb_resp = await client.get(f"/callback?code=mock_code_123&state={state}")
    assert cb_resp.status_code == 200
    assert cb_resp.json() == {
        "status": "connected",
        "provider": "github",
        "user": "bob",
    }
    # Authorization code must not be exposed in response body
    assert "mock_code_123" not in cb_resp.text

    # 4. State can only be used once: second callback must fail
    second_cb = await client.get(f"/callback?code=mock_code_123&state={state}")
    assert second_cb.status_code == 400


@pytest.mark.asyncio
@respx.mock
async def test_retrieve_token_async_flow(client: AsyncClient):
    # Mock OpenBao credential read
    respx.get("http://openbao:8200/v1/oauth2/creds/github_charlie").respond(
        status_code=200,
        json={
            "data": {
                "access_token": "gho_secret_access_token",
                "server": "github",
                "type": "Bearer",
                "expire_time": "2026-12-31T23:59:59Z",
            }
        },
    )

    # 1. Request token (must return 202 Accepted with Location header)
    resp = await client.get("/github/charlie")
    assert resp.status_code == 202
    assert "Location" in resp.headers

    data = resp.json()
    assert data["status"] == "pending"
    request_id = data["request_id"]
    location = resp.headers["Location"]
    assert location == f"/requests/{request_id}"

    # 2. Wait a moment for worker task to fulfill
    # Poll GET /requests/{id}
    import asyncio
    for _ in range(20):
        poll_resp = await client.get(location)
        assert poll_resp.status_code == 200
        poll_data = poll_resp.json()
        if poll_data["status"] == "completed":
            assert poll_data["access_token"] == "gho_secret_access_token"
            assert poll_data["token_type"] == "Bearer"
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("Async token request did not complete in time")


@pytest.mark.asyncio
async def test_get_nonexistent_request(client: AsyncClient):
    resp = await client.get("/requests/non-existent-uuid")
    assert resp.status_code == 404
