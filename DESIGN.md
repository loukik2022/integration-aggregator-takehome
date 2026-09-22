# Integration Aggregator: System Design

This document details the architecture, data boundaries, concurrency model, and production considerations for the Integration Aggregator service.

---

## Architecture & Responsibilities

The service acts as an internal gateway for microservices needing OAuth access tokens for third-party providers (such as GitHub, Google, or internal OIDC). Instead of each client application managing client secrets, OAuth redirect flows, and refresh token loops, the integration aggregator provides a single interface.

### Division of Labor
- **OpenBao (`secrets-oauthapp` plugin)**: The source of truth for all sensitive material. It stores OAuth client secrets, refresh tokens, and access tokens. It transparently handles token expiry checks and refresh token exchanges when reading credentials.
- **Aggregator Service**: A lightweight FastAPI application orchestrating provider registration, generating anti-CSRF state tokens for consent redirects, completing code exchanges, and exposing a non-blocking token retrieval API.
- **Service Memory**: Transient connection states, the in-memory background worker queue, and async request status records. **The service persists nothing to disk and implements no OAuth crypto or refresh logic directly.**

---

## Data Placement & Security

| Data Item | Location | Rationale |
|---|---|---|
| Client Secrets | OpenBao (`oauth2/servers/{name}`) | Never written to disk or logged. OpenBao encrypts them at rest. |
| Access & Refresh Tokens | OpenBao (`oauth2/creds/{p}_{u}`) | OpenBao owns token lifecycle and refresh cycles. |
| OAuth State (`state`) | Service Memory (`StateStore`) | Ephemeral single-use tokens with a 10-minute TTL. Evicted immediately upon redemption to prevent replay attacks. |
| Async Request Status | Service Memory (`RequestStore`) | Ephemeral polling records (`pending`, `completed`, `failed`) and retrieved token cache. Cleaned up after 10 minutes. |

### Security Measures
- **Log Masking**: A custom logging filter (`SecretMaskingFilter`) strips client secrets, authorization codes, and access/refresh tokens from all stdout logs.
- **Clean Endpoints**: `POST /providers` and `GET /callback` never return secrets or codes in their response payloads.
- **Least-Privilege Policy**: Rather than relying on OpenBao's root token, the service uses an isolated token bound to an explicit policy (`integration-aggregator`) restricted solely to `oauth2/*` endpoints.

---

## Asynchronous 202 Retrieval Pattern

Calling OpenBao to retrieve a token can involve downstream network I/O if the plugin needs to refresh an expired token against GitHub or an OIDC provider. To avoid blocking HTTP worker threads on downstream latency:

1. `GET /{provider}/{user}` immediately generates a request ID, writes a `pending` record to memory, enqueues the job to an internal `asyncio.Queue`, and returns `202 Accepted` with a `Location: /requests/{id}` header.
2. Background worker tasks consume the queue concurrently, fetch the fresh token from OpenBao (`GET /v1/oauth2/creds/{provider}_{user}`), and mark the record `completed`.
3. The client polls `GET /requests/{id}`. Once ready, it receives `200 OK` with the token.

---

## Multi-Replica Scaling & Failure Modes

The service currently runs as a single replica with state held in memory.

### What breaks with more than one replica?
1. **OAuth Callback Rejection**: If `POST /connect` lands on Replica A, the generated `state` is stored in Replica A's memory. When the user completes consent and the provider redirects to `/callback`, the request may hit Replica B. Replica B has no record of the state and returns `400 Bad Request`.
2. **Lost Async Requests**: If `GET /{provider}/{user}` is handled by Replica A, the polling request `GET /requests/{id}` may hit Replica B, returning `404 Not Found`.

### How to fix it in production:
- **Shared State Store**: Replace the in-memory `StateStore` and `RequestStore` with a distributed cache like **Redis** or **Valkey** with native key TTLs (`SETEX state:{id} 600 {data}`).
- **Distributed Task Queue**: Replace `asyncio.Queue` with **Redis Streams**, **RabbitMQ**, or **NATS** so background workers across any replica can consume jobs and write results to the shared cache.

---

## OpenBao Dev Mode vs. Production

In development and CI, OpenBao runs in `-dev` mode for zero-overhead startup.

### Dev Mode Limitations:
- **In-Memory Storage**: OpenBao storage runs in RAM. Pod restarts wipe all registered providers and user credentials.
- **Auto-Unsealed with Insecure Root Token**: Dev mode auto-unseals and outputs a well-known root token (`root`), bypassing Shamir key shares or KMS unseal workflows.
- **Plain HTTP**: Dev mode runs without TLS/mTLS encryption.

### Production Recommendations:
1. **Storage**: Deploy OpenBao in High Availability (HA) mode with integrated Raft consensus storage across 3 or 5 nodes with persistent volume claims (PVCs).
2. **Auto-Unseal**: Use cloud KMS (AWS KMS, GCP Cloud KMS, or Azure Key Vault) for automated unsealing on boot.
3. **mTLS**: Terminate TLS at the OpenBao listener using certificates provisioned via `cert-manager`.
4. **Kubernetes Auth**: Replace static tokens with OpenBao's Kubernetes Authentication method (`auth/kubernetes`), allowing pods to exchange their projected ServiceAccount tokens for short-lived, auto-rotating Vault tokens.
