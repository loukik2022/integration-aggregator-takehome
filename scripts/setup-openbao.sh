#!/usr/bin/env bash
# scripts/setup-openbao.sh
# Idempotently registers the oauthapp plugin, enables the secrets engine,
# writes the least-privilege policy, and provisions the service token into a K8s secret.

set -euo pipefail

OPENBAO_POD="${OPENBAO_POD:-openbao-0}"
ROOT_TOKEN="${ROOT_TOKEN:-root}"
SECRET_NAME="${SECRET_NAME:-integration-aggregator-openbao-token}"

echo "==> Waiting for OpenBao pod '${OPENBAO_POD}' to be Ready..."
kubectl wait --for=condition=ready pod/"${OPENBAO_POD}" --timeout=180s

echo "==> Verifying OpenBao status..."
kubectl exec "${OPENBAO_POD}" -- env BAO_TOKEN="${ROOT_TOKEN}" bao status || true

echo "==> Inspecting oauthapp plugin binary in pod..."
PLUGIN_PATH="/bao/plugins/openbao-plugin-secrets-oauthapp"
if ! kubectl exec "${OPENBAO_POD}" -- test -f "${PLUGIN_PATH}"; then
    POD_ARCH=$(kubectl exec "${OPENBAO_POD}" -- uname -m | tr -d '\r\n')
    case "${POD_ARCH}" in
        x86_64|amd64)
            ARCH_SUFFIX="linux-amd64"
            ;;
        aarch64|arm64)
            ARCH_SUFFIX="linux-arm64"
            ;;
        *)
            echo "Warning: Unrecognized pod architecture '${POD_ARCH}', defaulting to linux-amd64"
            ARCH_SUFFIX="linux-amd64"
            ;;
    esac
    echo "Detected pod architecture: ${POD_ARCH} -> downloading ${ARCH_SUFFIX} binary..."
    curl -fsSL "https://github.com/openbao/openbao-plugin-secrets-oauthapp/releases/download/v3.4.0/openbao-plugin-secrets-oauthapp-v3.4.0-${ARCH_SUFFIX}.tar.xz" | tar -xJ -C "${TMP_DIR}"
    PLUGIN_BIN=$(find "${TMP_DIR}" -type f -perm -111 -o -type f | head -n1)
    kubectl cp "${PLUGIN_BIN}" "${OPENBAO_POD}:${PLUGIN_PATH}" 2>/dev/null || \
        kubectl exec -i "${OPENBAO_POD}" -- sh -c "cat > ${PLUGIN_PATH}" < "${PLUGIN_BIN}"
    kubectl exec "${OPENBAO_POD}" -- chmod +x "${PLUGIN_PATH}"
    kubectl exec "${OPENBAO_POD}" -- ln -sf "${PLUGIN_PATH}" /bao/plugins/oauthapp
    rm -rf "${TMP_DIR}"
    echo "Plugin installed successfully into pod."
fi

SHA256=$(kubectl exec "${OPENBAO_POD}" -- sha256sum "${PLUGIN_PATH}" | awk '{print $1}')
echo "Plugin SHA256: ${SHA256}"

echo "==> Registering plugin in catalog (idempotent)..."
kubectl exec "${OPENBAO_POD}" -- env BAO_TOKEN="${ROOT_TOKEN}" \
    bao plugin register -sha256="${SHA256}" -command=openbao-plugin-secrets-oauthapp secret oauthapp || true

echo "==> Checking if oauth2 secrets engine is enabled..."
ENABLED_SECRETS=$(kubectl exec "${OPENBAO_POD}" -- env BAO_TOKEN="${ROOT_TOKEN}" bao secrets list -format=json)
if echo "${ENABLED_SECRETS}" | grep -q '"oauth2/"'; then
    echo "Secrets engine 'oauth2/' is already enabled."
else
    echo "Enabling 'oauthapp' secrets engine at 'oauth2/'..."
    kubectl exec "${OPENBAO_POD}" -- env BAO_TOKEN="${ROOT_TOKEN}" \
        bao secrets enable -path=oauth2 oauthapp
    echo "Secrets engine 'oauth2/' enabled successfully."
fi

echo "==> Applying least-privilege policy 'integration-aggregator'..."
kubectl exec -i "${OPENBAO_POD}" -- env BAO_TOKEN="${ROOT_TOKEN}" \
    bao policy write integration-aggregator - < deploy/openbao-policy.hcl

echo "==> Generating service token with policy 'integration-aggregator'..."
TOKEN_JSON=$(kubectl exec "${OPENBAO_POD}" -- env BAO_TOKEN="${ROOT_TOKEN}" \
    bao token create -policy=integration-aggregator -period=720h -format=json)
SERVICE_TOKEN=$(echo "${TOKEN_JSON}" | grep -o '"client_token": "[^"]*' | cut -d'"' -f4)

if [ -z "${SERVICE_TOKEN}" ]; then
    echo "Failed to extract client token, falling back to root token."
    SERVICE_TOKEN="${ROOT_TOKEN}"
fi

echo "==> Storing token in Kubernetes Secret '${SECRET_NAME}' (idempotent)..."
kubectl create secret generic "${SECRET_NAME}" \
    --from-literal=token="${SERVICE_TOKEN}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "==> OpenBao setup completed successfully!"
