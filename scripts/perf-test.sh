#!/usr/bin/env bash
# scripts/perf-test.sh
# Runs performance test using k6 against the token retrieval endpoint.

set -euo pipefail

TARGET_URL="${TARGET_URL:-http://localhost:8080}"
PROVIDER="${PROVIDER:-mock-oidc}"
USER="${USER:-alice}"

echo "==> Running load test against ${TARGET_URL}..."

if ! curl -sf "${TARGET_URL}/healthz" >/dev/null 2>&1; then
    if command -v kubectl >/dev/null 2>&1; then
        echo "Reconnecting port-forward for integration-aggregator (8080)..."
        nohup kubectl port-forward svc/integration-aggregator 8080:8080 >/dev/null 2>&1 &
        sleep 3
    fi
fi

if ! command -v k6 &> /dev/null; then
    echo "ERROR: k6 is not installed. Please install k6 (https://grafana.com/docs/k6/latest/set-up/install-k6/)."
    exit 1
fi

TARGET_URL="${TARGET_URL}" PROVIDER="${PROVIDER}" USER="${USER}" \
    k6 run test/k6-load-test.js
