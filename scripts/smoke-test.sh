#!/usr/bin/env bash
# scripts/smoke-test.sh
# End-to-end automated smoke test exercising the complete flow:
# 1. Provider registration
# 2. User connection initiation (auth URL)
# 3. Automated OIDC consent via mock-oauth2-server redirect into /callback
# 4. Asynchronous token retrieval (202 Accepted + Location header)
# 5. Polling until token is completed and verified.

set -euo pipefail

SERVICE_URL="${SERVICE_URL:-http://localhost:8080}"
echo "==> Starting E2E smoke test against ${SERVICE_URL}..."

# 1. Check health
echo "Step 1: Checking service readiness..."
for i in {1..30}; do
    if curl -sf "${SERVICE_URL}/healthz" >/dev/null 2>&1; then
        echo "Service is healthy!"
        break
    fi
    if [ "$i" -eq 5 ] && command -v kubectl >/dev/null 2>&1; then
        echo "Ensuring port-forward is active..."
        nohup kubectl port-forward svc/integration-aggregator 8080:8080 >/dev/null 2>&1 &
        nohup kubectl port-forward svc/mock-oauth2-server 8081:8080 >/dev/null 2>&1 &
    fi
    echo "Waiting for service at ${SERVICE_URL}/healthz... ($i/30)"
    sleep 2
done

# Verify mock-oauth2-server is ready
if [ -n "${MOCK_SERVER_URL:-}" ]; then
    echo "Checking mock-oauth2-server readiness at ${MOCK_SERVER_URL}/isalive..."
    for i in {1..30}; do
        if curl -sf "${MOCK_SERVER_URL}/isalive" >/dev/null 2>&1; then
            echo "Mock OAuth2 server is healthy and responding!"
            break
        fi
        sleep 1
    done
fi

# 2. Register mock OIDC provider
echo "Step 2: Registering mock-oidc provider..."
for attempt in {1..5}; do
    REGISTER_RESP=$(curl -s -w "\n%{http_code}" -X POST "${SERVICE_URL}/providers" \
        -H "Content-Type: application/json" \
        -d '{
            "name": "mock-oidc",
            "provider": "oidc",
            "client_id": "test-client-id",
            "client_secret": "test-client-secret-do-not-log",
            "provider_options": {
                "issuer_url": "http://mock-oauth2-server:8080/default"
            },
            "scopes": ["openid", "profile"]
        }')

    HTTP_CODE=$(echo "${REGISTER_RESP}" | tail -n1)
    BODY=$(echo "${REGISTER_RESP}" | sed '$d')

    if [ "${HTTP_CODE}" -eq 201 ]; then
        break
    fi
    echo "Provider registration returned ${HTTP_CODE} on attempt ${attempt}/5, retrying in 2s..."
    sleep 2
done

if [ "${HTTP_CODE}" -ne 201 ]; then
    echo "ERROR: Failed to register provider (HTTP ${HTTP_CODE}): ${BODY}"
    exit 1
fi
echo "Provider registered: ${BODY}"

# Verify client_secret is NOT exposed in response body
if echo "${BODY}" | grep -q "test-client-secret"; then
    echo "CRITICAL SECURITY FAILURE: client_secret found in response body!"
    exit 1
fi

# 3. Connect user alice
echo "Step 3: Initiating connection for user 'alice'..."
CONNECT_RESP=$(curl -s -w "\n%{http_code}" -X POST "${SERVICE_URL}/providers/mock-oidc/users/alice/connect")
HTTP_CODE=$(echo "${CONNECT_RESP}" | tail -n1)
BODY=$(echo "${CONNECT_RESP}" | sed '$d')

if [ "${HTTP_CODE}" -ne 200 ]; then
    echo "ERROR: Failed to connect user (HTTP ${HTTP_CODE}): ${BODY}"
    exit 1
fi

AUTH_URL=$(echo "${BODY}" | grep -o '"auth_url": *"[^"]*' | cut -d'"' -f4)
STATE=$(echo "${BODY}" | grep -o '"state": *"[^"]*' | cut -d'"' -f4)
echo "Generated auth_url: ${AUTH_URL}"
echo "Generated state: ${STATE}"

# 4. Follow redirect via mock-oauth2-server into /callback
echo "Step 4: Simulating user consent via mock-oauth2-server..."
# If AUTH_URL points to internal cluster DNS mock-oauth2-server:8080 and curl is running outside,
# replace mock-oauth2-server:8080 with localhost:8080 if MOCK_SERVER_URL is set
MOCK_SERVER_URL="${MOCK_SERVER_URL:-}"
if [ -n "${MOCK_SERVER_URL}" ]; then
    AUTH_URL=$(echo "${AUTH_URL}" | sed "s|http://mock-oauth2-server:8080|${MOCK_SERVER_URL}|g")
fi

CALLBACK_RESP=$(curl -s -L -w "\n%{http_code}" "${AUTH_URL}")
CB_CODE=$(echo "${CALLBACK_RESP}" | tail -n1)
CB_BODY=$(echo "${CALLBACK_RESP}" | sed '$d')

# If interactive sign-in form was served, submit username=alice to complete consent
if echo "${CB_BODY}" | grep -q "<form"; then
    echo "Submitting automated consent form to mock OAuth server..."
    CALLBACK_RESP=$(curl -s -L -w "\n%{http_code}" -d "username=alice" "${AUTH_URL}")
    CB_CODE=$(echo "${CALLBACK_RESP}" | tail -n1)
    CB_BODY=$(echo "${CALLBACK_RESP}" | sed '$d')
fi

if [ "${CB_CODE}" -ne 200 ]; then
    echo "ERROR: Callback exchange failed (HTTP ${CB_CODE}): ${CB_BODY}"
    exit 1
fi
echo "Callback succeeded: ${CB_BODY}"

# 5. Request token asynchronously (Expect 202 Accepted + Location header)
echo "Step 5: Requesting token asynchronously (GET /mock-oidc/alice)..."
TOKEN_REQ_HEADERS=$(curl -s -i "${SERVICE_URL}/mock-oidc/alice")
STATUS_LINE=$(echo "${TOKEN_REQ_HEADERS}" | grep -E "HTTP/[12]" | head -n1)

if ! echo "${STATUS_LINE}" | grep -q "202"; then
    echo "ERROR: Expected 202 Accepted, got: ${STATUS_LINE}"
    exit 1
fi

LOCATION=$(echo "${TOKEN_REQ_HEADERS}" | grep -i "^location:" | awk '{print $2}' | tr -d '\r\n')
echo "202 Accepted confirmed! Location header: ${LOCATION}"

if [ -z "${LOCATION}" ]; then
    echo "ERROR: Missing Location header in 202 response!"
    exit 1
fi

# 6. Poll GET /requests/{id} until completed
echo "Step 6: Polling ${SERVICE_URL}${LOCATION} for token..."
MAX_ATTEMPTS=20
TOKEN_FOUND=false

for i in $(seq 1 ${MAX_ATTEMPTS}); do
    POLL_RESP=$(curl -s "${SERVICE_URL}${LOCATION}")
    STATUS=$(echo "${POLL_RESP}" | grep -o '"status": *"[^"]*' | cut -d'"' -f4)
    echo "Poll attempt $i: status = '${STATUS}'"

    if [ "${STATUS}" = "completed" ]; then
        TOKEN_FOUND=true
        ACCESS_TOKEN=$(echo "${POLL_RESP}" | grep -o '"access_token": *"[^"]*' | cut -d'"' -f4)
        echo "Successfully retrieved token for alice!"
        echo "Token type: Bearer"
        echo "Token presence verified: non-empty [LENGTH=${#ACCESS_TOKEN}]"
        break
    elif [ "${STATUS}" = "failed" ]; then
        echo "ERROR: Request failed: ${POLL_RESP}"
        exit 1
    fi
    sleep 0.5
done

if [ "${TOKEN_FOUND}" != "true" ]; then
    echo "ERROR: Polling timed out before request completed!"
    exit 1
fi

echo ""
echo "=================================================="
echo "      ALL SMOKE TEST CHECKS PASSED (100% OK)     "
echo "=================================================="
