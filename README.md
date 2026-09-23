# Integration Aggregator


An internal microservice that centralizes OAuth 2.0 and OIDC integrations for public and internal providers (GitHub, Google, Dex, Mock OIDC). Other internal services simply request a user's access token, eliminating redundant OAuth implementations across product teams.

---

## Table of Contents

- [Architecture & Sequence Flows](#architecture--sequence-flows)
- [Prerequisites & Setup on macOS (MacBook)](#prerequisites--setup-on-macos-macbook)
- [Idempotent Lifecycle Commands](#idempotent-lifecycle-commands)
- [Running Tests](#running-tests)
- [Onboarding Guide: Google & GitHub](#onboarding-guide-google--github)
- [Terraform & OpenBao Provider Integration](#terraform--openbao-provider-integration)
- [Repository Index](#repository-index)

---

## Architecture & Sequence Flows

### Division of Labor
- **[OpenBao](https://openbao.org)** (`openbao-plugin-secrets-oauthapp`): Stores all sensitive credentials (client secrets, refresh tokens, access tokens). It performs the authorization code exchange and handles transparent token refresh before expiration.
- **Integration Aggregator Service** (FastAPI): Manages provider registration, generates cryptographic anti-CSRF state tokens, drives the consent callback, and serves tokens via a non-blocking asynchronous 202 flow.
- **Service Memory**: Transient connection states and async polling requests. **No secrets or tokens are ever written to disk or logged.**

### Core Flows & Sequence Diagrams

#### 1. Register a Provider
An operator or automated pipeline registers an OAuth provider with client credentials. Client secrets are stored encrypted inside OpenBao only and are never returned in responses or logs.

```text
Caller                    Aggregator API                    OpenBao
  │                             │                              │
  ├── 1. POST /providers ───────>│                              │
  │   (name, id, client_secret) │── 2. POST servers/{name} ────>│
  │                             │      (write client secret)   │── Stores secret
  │                             │                              │   encrypted at rest
  │                             │<────────── 3. 200 OK ────────┤
  │<────── 4. 201 Created ───────│                              │
  │   (name, "registered")      │                              │
```

#### 2. Connect a User & Complete Consent
The caller requests an authorization URL for a `(provider, user)` pair. The service generates a one-time anti-CSRF `state` token, requests the provider's OAuth authorization URL from OpenBao, and directs the user to consent. Upon redirect, `/callback` exchanges the code via OpenBao and persists the tokens.

```text
User Browser          Caller           Aggregator API            OpenBao           OAuth Provider
     │                  │                     │                     │                    │
     │                  ├── 1. POST /connect ─>│                     │                    │
     │                  │   (provider, user)  │── 2. Generate State │                    │
     │                  │                     │── 3. Get Auth URL ─>│                    │
     │                  │                     │<── 4. auth_url ─────┤                    │
     │                  │<── 5. 200 auth_url ─┤                     │                    │
     │<── 6. Redirect ──┤                     │                     │                    │
     │── 7. Authenticate & Grant Consent ───────────────────────────────────────────────>│
     │<── 8. 302 Redirect to /callback?code=...&state=... ───────────────────────────────┤
     │── 9. GET /callback?code=...&state=... ─>│                     │                    │
     │                                        │── 10. Validate State│                    │
     │                                        │── 11. Write Code ──>│                    │
     │                                        │                     │── 12. Exchange ───>│
     │                                        │                     │<── 13. Tokens ─────┤
     │                                        │<── 14. 200 Stored ──┤                    │
     │<── 15. 200 OK ("connected") ───────────┤                     │                    │
```

#### 3. Asynchronous Non-Blocking Token Retrieval (202 Flow)
To avoid blocking HTTP worker threads on downstream OAuth refresh latency, `GET /{p}/{u}` returns `202 Accepted` immediately with a `Location: /requests/{id}` header. An internal background worker fulfills the request asynchronously against OpenBao, and the caller polls for completion.

```text
Caller                     Aggregator API            Background Worker            OpenBao
  │                              │                           │                       │
  ├── 1. GET /{provider}/{user} ─>│                           │                       │
  │                              │── 2. Enqueue Job ────────>│                       │
  │<── 3. 202 Accepted ──────────┤   (request_id)            │                       │
  │    Location: /requests/{id}  │                           │                       │
  │                              │                           ├── 4. Read Token ─────>│
  │                              │                           │      creds/{p}_{u}    │── Transparent
  │                              │                           │<── 5. 200 Token ──────┤   token refresh
  │                              │<── 6. Store Result ───────┤                       │
  │                              │    (status: completed)    │                       │
  │                              │                           │                       │
  ├── 7. GET /requests/{id} ─────>│                           │                       │
  │      (Poll request status)   │                           │                       │
  │<── 8. 200 OK (access_token) ─┤                           │                       │
```



---

## Prerequisites & Setup on macOS (MacBook)

### 1. Install Tooling via Homebrew
Open Terminal on your MacBook and run:

```bash
# 1. Install Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Install required CLI tools
brew install minikube kubectl helm k6 python@3.12
```

### 2. Container Runtime
Ensure you have a container runtime active:
- **Docker Desktop**: [Download and start Docker Desktop](https://www.docker.com/products/docker-desktop/)

---

## Idempotent Lifecycle Commands

All orchestration is automated via `make`. The targets are completely **idempotent**: running them multiple times in succession will safely verify the desired state without breaking existing resources or producing duplicates.

> **Where to Run**:
> - **Working Directory**: Run these commands from the **root directory of the repository** (where the `Makefile` is located).
> - **Terminal Shell**:
>   - **macOS / Linux**: Open **Terminal** or iTerm2. Ensure Docker Desktop (or Colima) is started.
>   - **Windows**: Use **Git Bash** or **WSL2** (since the targets invoke bash automation scripts).

### Start the Service (`make up`)
```bash
# Run from repository root
make up
```

#### What `make up` does automatically:
1. **Cluster Initialization**: Checks if minikube is running; starts it if not.
2. **Container Image Build**: Builds `integration-aggregator:latest` from the local `Dockerfile` and loads it directly into minikube.
3. **OpenBao Deployment**: Adds the OpenBao Helm repository and deploys OpenBao in dev-mode via Helm with the custom plugin volume attached.
4. **Plugin & Security Setup** (`scripts/setup-openbao.sh`):
   - Dynamically inspects the pod architecture (`arm64` on Apple Silicon or `amd64` on Intel/CI) and downloads the matching `openbao-plugin-secrets-oauthapp` binary.
   - Calculates the SHA-256 checksum and registers the plugin in OpenBao's catalog.
   - Enables the `oauthapp` secrets engine at path `oauth2/`.
   - Writes the least-privilege policy (`deploy/openbao-policy.hcl`).
   - Generates an isolated periodic service token and mounts it into Kubernetes Secret `integration-aggregator-openbao-token`.
5. **Mock OIDC Provider**: Deploys `mock-oauth2-server` for instant local testing and CI verification without requiring internet access.
6. **Aggregator Deployment**: Installs the production Helm chart from `./chart/integration-aggregator`.

Verify running pods:
```bash
kubectl get pods
```
Output:
```
NAME                                      READY   STATUS    RESTARTS   AGE
integration-aggregator-7d498679f5-h6d2g   1/1     Running   0          45s
mock-oauth2-server-5f7bb484d4-j9s2p       1/1     Running   0          55s
openbao-0                                 1/1     Running   0          75s
```

### Stop & Remove the Service (`make down`)
Tears down the Helm releases, deletes secrets, mock server, and stops the minikube cluster:
```bash
make down
```

---

## Running Tests

### 1. Python Unit Tests (`make test`)
Executes the comprehensive pytest suite with 100% pass rate:
```bash
# Using local virtualenv / python 3.12
make test
```
*Covers API routing, anti-CSRF state token store TTL eviction, asynchronous worker queue dispatch, OpenBao HTTP client interactions, and secret-masking log filters.*

### 2. End-to-End Automated Smoke Test (`make smoke-test`)
Tests the complete end-to-end user journey against the running cluster:
```bash
make smoke-test
```
*Flow executed:*
1. Health check `/healthz`.
2. Registers the `mock-oidc` provider (`POST /providers`).
3. Verifies that the client secret is **never** leaked in the response or logs.
4. Initiates connection for user `alice` (`POST /providers/mock-oidc/users/alice/connect`).
5. Simulates automated browser consent via `mock-oauth2-server` redirected to `/callback`.
6. Requests token asynchronously (`GET /mock-oidc/alice`), validating `202 Accepted` and `Location: /requests/{id}`.
7. Polls `/requests/{id}` until status becomes `completed` and verifies receipt of a valid Bearer token.

### 3. Performance & Load Benchmark (`make perf`)
Runs the k6 load test against the asynchronous token path:
```bash
make perf
```
See [`PERF.md`](PERF.md) for full benchmark results (sub-50ms p50 latency across 10, 50, and 100 virtual users).

---

## Onboarding Guide: Google & GitHub

Follow these steps to connect real public providers to the running aggregator service.

### Port Forwarding
If not running inside the Kubernetes pod network, forward port 8080:
```bash
kubectl port-forward svc/integration-aggregator 8080:8080
```

---

### A. GitHub Onboarding

#### Step 1: Create GitHub OAuth Application
1. Go to **GitHub Settings** -> **Developer Settings** -> **OAuth Apps** -> **[New OAuth App](https://github.com/settings/applications/new)**.
2. Fill in:
   - **Application name**: `Integration Aggregator Local`
   - **Homepage URL**: `http://localhost:8080`
   - **Authorization callback URL**: `http://localhost:8080/callback`
3. Click **Register application**.
4. Generate a new **Client secret**. Copy your **Client ID** and **Client Secret**.

#### Step 2: Register GitHub with Integration Aggregator
```bash
curl -X POST http://localhost:8080/providers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "github",
    "provider": "github",
    "client_id": "<YOUR_GITHUB_CLIENT_ID>",
    "client_secret": "<YOUR_GITHUB_CLIENT_SECRET>",
    "scopes": ["read:user", "user:email"]
  }'
```
Response (`201 Created`):
```json
{"name":"github","status":"registered"}
```

#### Step 3: Initiate User Connection
```bash
curl -X POST http://localhost:8080/providers/github/users/octocat/connect
```
Response (`200 OK`):
```json
{
  "auth_url": "https://github.com/login/oauth/authorize?client_id=...&redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fcallback&response_type=code&scope=read%3Auser+user%3Aemail&state=X6g7Y9...",
  "state": "X6g7Y9..."
}
```

#### Step 4: Complete User Consent
Open the returned `auth_url` in your browser. Log in to GitHub and click **Authorize**.
GitHub redirects to:
```
http://localhost:8080/callback?code=abc123xyz&state=X6g7Y9...
```
You will see:
```json
{"status":"connected","provider":"github","user":"octocat"}
```

#### Step 5: Retrieve Access Token (Async 202 Flow)
Request the token:
```bash
curl -i http://localhost:8080/github/octocat
```
Response:
```http
HTTP/1.1 202 Accepted
Location: /requests/e404b3a1-7fb8-410a-b328-97c02bcf1b70
Content-Type: application/json

{"request_id":"e404b3a1-7fb8-410a-b328-97c02bcf1b70","status":"pending","location":"/requests/e404b3a1-7fb8-410a-b328-97c02bcf1b70"}
```

Poll the location:
```bash
curl http://localhost:8080/requests/e404b3a1-7fb8-410a-b328-97c02bcf1b70
```
Response (`200 OK`):
```json
{
  "request_id": "e404b3a1-7fb8-410a-b328-97c02bcf1b70",
  "status": "completed",
  "access_token": "ghu_16C7e42F292c6912E7710c838347Ae178B4a",
  "token_type": "Bearer",
  "expires_at": null,
  "error": null
}
```

---

### B. Google Onboarding

#### Step 1: Create Google OAuth 2.0 Credentials
1. Open the **[Google Cloud Console Credentials Page](https://console.cloud.google.com/apis/credentials)**.
2. Click **Create Credentials** -> **OAuth client ID**.
3. Choose **Application type**: `Web application`.
4. Add **Authorized redirect URIs**:
   - `http://localhost:8080/callback`
5. Click **Create** and copy the **Client ID** and **Client Secret**.

#### Step 2: Register Google with Integration Aggregator
```bash
curl -X POST http://localhost:8080/providers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "google",
    "provider": "google",
    "client_id": "<YOUR_GOOGLE_CLIENT_ID>.apps.googleusercontent.com",
    "client_secret": "<YOUR_GOOGLE_CLIENT_SECRET>",
    "scopes": ["openid", "email", "profile"]
  }'
```

#### Step 3: Connect User & Consent
```bash
curl -X POST http://localhost:8080/providers/google/users/john.doe/connect
```
Open the generated `auth_url` in your browser, select your Google account, and grant consent.

#### Step 4: Retrieve Token
```bash
curl -i http://localhost:8080/google/john.doe
# Poll the returned Location header
curl http://localhost:8080/requests/<request_id>
```

---

## Terraform & OpenBao Provider Integration

### Working Terraform Module in this Repository
We have included a complete, working Terraform module in [`terraform/`](terraform/):
- **`terraform/providers.tf`**: Configures the `vault` (OpenBao-compatible) and `kubernetes` providers.
- **`terraform/main.tf`**:
  - Mounts the `oauthapp` secrets engine at `oauth2/`.
  - Applies [`deploy/openbao-policy.hcl`](deploy/openbao-policy.hcl).
  - Issues a scoped periodic token.
  - Generates the `integration-aggregator-openbao-token` Kubernetes Secret.
  - Declaratively registers OAuth providers (`for_each = var.oauth_providers`).
- **`terraform/variables.tf` & `terraform.tfvars.example`**: Clean variable schemas for enterprise deployment.

#### Running the Terraform Module:
```bash
# 1. Forward OpenBao port
kubectl port-forward svc/openbao 8200:8200 &

# 2. Initialize and Apply
cd terraform
terraform init
terraform plan
terraform apply -auto-approve
```

---

## Repository Index

- [`DESIGN.md`](DESIGN.md): Detailed architectural design, concurrency model, multi-replica scaling limitations, and production hardening recommendations.
- [`PERF.md`](PERF.md): Performance benchmarks, p50/p95/p99 latency tables, and concurrency scaling analysis.
- [`terraform/`](terraform/): Declarative Terraform configuration and OpenBao provider resources.
- [`deploy/`](deploy/): OpenBao Helm values, HCL policies, and mock OAuth2 server manifests.
- [`chart/`](chart/): Production-grade Helm chart for the Integration Aggregator service.
- [`scripts/`](scripts/): Idempotent automation scripts (`setup-openbao.sh`, `smoke-test.sh`, `perf-test.sh`).
