"""Unit tests for OpenBao client."""

import httpx
import pytest
import respx
from app.openbao import OpenBaoClient, OpenBaoError, OpenBaoNotFoundError


@pytest.mark.asyncio
@respx.mock
async def test_configure_server():
    client = OpenBaoClient(base_url="http://mock-openbao:8200", token="test-root-token")
    mock_route = respx.post("http://mock-openbao:8200/v1/oauth2/servers/github").respond(status_code=204)

    await client.configure_server(
        name="github",
        provider="github",
        client_id="cid123",
        client_secret="csec123",
    )
    assert mock_route.called
    req = mock_route.calls.last.request
    assert req.headers["x-vault-token"] == "test-root-token"
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_auth_code_url():
    client = OpenBaoClient(base_url="http://mock-openbao:8200", token="test-root-token")
    respx.post("http://mock-openbao:8200/v1/oauth2/auth-code-url").respond(
        status_code=200,
        json={"data": {"url": "https://github.com/login/oauth/authorize?client_id=123"}},
    )

    url = await client.get_auth_code_url(server="github", state="state-abc")
    assert "https://github.com/login/oauth/authorize" in url
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code():
    client = OpenBaoClient(base_url="http://mock-openbao:8200", token="test-root-token")
    mock_route = respx.post("http://mock-openbao:8200/v1/oauth2/creds/github_alice").respond(status_code=204)

    await client.exchange_code(server="github", cred_name="github_alice", code="code-123")
    assert mock_route.called
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_credential_success():
    client = OpenBaoClient(base_url="http://mock-openbao:8200", token="test-root-token")
    respx.get("http://mock-openbao:8200/v1/oauth2/creds/github_alice").respond(
        status_code=200,
        json={
            "data": {
                "access_token": "gho_valid_token_xyz",
                "server": "github",
                "type": "Bearer",
                "expire_time": "2026-12-31T23:59:59Z",
            }
        },
    )

    creds = await client.get_credential("github_alice")
    assert creds["access_token"] == "gho_valid_token_xyz"
    assert creds["type"] == "Bearer"
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_credential_not_found():
    client = OpenBaoClient(base_url="http://mock-openbao:8200", token="test-root-token")
    respx.get("http://mock-openbao:8200/v1/oauth2/creds/github_unknown").respond(status_code=404)

    with pytest.raises(OpenBaoNotFoundError):
        await client.get_credential("github_unknown")
    await client.close()
