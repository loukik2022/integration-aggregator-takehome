"""Async OpenBao client interfacing with the openbao-plugin-secrets-oauthapp plugin."""

import logging
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("integration_aggregator.openbao")


class OpenBaoError(Exception):
    """Base exception for OpenBao API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class OpenBaoNotFoundError(OpenBaoError):
    """Raised when a secret or credential is not found in OpenBao."""


class OpenBaoClient:
    """Async HTTP client for OpenBao oauthapp plugin operations."""

    def __init__(
        self,
        base_url: str,
        token: str,
        mount_path: str = "oauth2",
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.mount_path = mount_path.strip("/")
        self.headers = {
            "X-Vault-Token": token,
            "X-Bao-Token": token,
            "Content-Type": "application/json",
        }
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        """Lazily initialize and return shared AsyncClient."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _endpoint(self, path: str) -> str:
        """Construct full API path under mount."""
        return f"/v1/{self.mount_path}/{path.lstrip('/')}"

    async def configure_server(
        self,
        name: str,
        provider: str,
        client_id: str,
        client_secret: str,
        provider_options: Optional[Dict[str, str]] = None,
    ) -> None:
        """Register or update an OAuth provider server in the plugin catalog."""
        client = await self.get_client()
        payload: Dict[str, Any] = {
            "provider": provider,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if provider_options:
            # Pass provider_options map (e.g. issuer_url)
            payload["provider_options"] = provider_options

        endpoint = self._endpoint(f"servers/{name}")
        resp = await client.post(endpoint, json=payload)
        if resp.status_code not in (200, 204):
            logger.error("Failed to configure server %s: status %d", name, resp.status_code)
            raise OpenBaoError(
                f"Failed to configure provider server: {resp.text}",
                status_code=resp.status_code,
            )

    async def get_auth_code_url(
        self,
        server: str,
        state: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        redirect_url: Optional[str] = None,
    ) -> str:
        """Request authorization code URL from OpenBao plugin."""
        client = await self.get_client()
        payload: Dict[str, Any] = {"server": server}
        if state:
            payload["state"] = state
        if scopes:
            payload["scopes"] = ",".join(scopes)
        if redirect_url:
            payload["redirect_url"] = redirect_url

        endpoint = self._endpoint("auth-code-url")
        resp = await client.post(endpoint, json=payload)
        if resp.status_code != 200:
            logger.error("Failed to generate auth-code-url for server %s: %d", server, resp.status_code)
            raise OpenBaoError(
                f"Failed to get authorization URL: {resp.text}",
                status_code=resp.status_code,
            )

        data = resp.json().get("data", {})
        url = data.get("url")
        if not url:
            raise OpenBaoError("OpenBao returned no URL in auth-code-url response")
        return url

    async def exchange_code(
        self,
        server: str,
        cred_name: str,
        code: str,
    ) -> None:
        """Exchange temporary auth code for tokens and store in OpenBao."""
        client = await self.get_client()
        payload = {"server": server, "code": code}
        endpoint = self._endpoint(f"creds/{cred_name}")
        resp = await client.post(endpoint, json=payload)
        if resp.status_code not in (200, 204):
            logger.error("Failed to exchange code for credential %s: %d", cred_name, resp.status_code)
            raise OpenBaoError(
                f"Failed to exchange authorization code: {resp.text}",
                status_code=resp.status_code,
            )

    async def get_credential(self, cred_name: str) -> Dict[str, Any]:
        """Retrieve token from OpenBao. The plugin transparently refreshes expired tokens."""
        client = await self.get_client()
        endpoint = self._endpoint(f"creds/{cred_name}")
        resp = await client.get(endpoint)
        if resp.status_code == 404:
            raise OpenBaoNotFoundError(f"Credential {cred_name} not found")
        if resp.status_code != 200:
            logger.error("Error reading credential %s: status %d", cred_name, resp.status_code)
            raise OpenBaoError(
                f"Error retrieving credential: {resp.text}",
                status_code=resp.status_code,
            )

        data = resp.json().get("data", {})
        access_token = data.get("access_token")
        if not access_token:
            raise OpenBaoError("No access token present in OpenBao response")
        return data
