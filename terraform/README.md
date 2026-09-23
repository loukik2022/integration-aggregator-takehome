# Terraform & OpenBao Provider Integration

This directory demonstrates how to manage the **OpenBao** secrets engine, least-privilege policies, service authentication tokens, and OAuth provider registrations declaratively using Terraform and the OpenBao / Vault Provider (`hashicorp/vault` or `openbao/openbao`).

---

## 1. Why Use Terraform Instead of Imperative Shell Scripts?

While `scripts/setup-openbao.sh` uses `kubectl exec` and `bao` CLI commands for local development:

| Capability | Shell Script (`scripts/setup-openbao.sh`) | Terraform (`hashicorp/vault` / `openbao`) |
|---|---|---|
| **Paradigm** | Imperative (step-by-step commands) | Declarative (desired-state configuration) |
| **State Tracking** | None (checks status via regex / exit codes) | Managed `terraform.tfstate` |
| **Drift Detection** | None (cannot detect if someone deleted a policy or altered an engine) | `terraform plan` detects and corrects out-of-band drifts |
| **Execution Context** | Requires `kubectl exec` into pod (blocked in locked-down production clusters) | Communicates securely over HTTPS/gRPC directly with OpenBao API |
| **Multi-Environment Promotion** | Requires brittle environment variable stitching | Clean separation via workspaces or `.tfvars` (`dev.tfvars`, `prod.tfvars`) |
| **Secret Ingestion** | Environment variables or local `.env` files | Native integration with HashiCorp Vault, AWS Secrets Manager, or CI/CD secrets |

---

## 2. Resources Managed

- **`vault_mount.oauthapp`**: Mounts the `openbao-plugin-secrets-oauthapp` engine at path `oauth2/`.
- **`vault_policy.integration_aggregator`**: Enforces the least-privilege HCL policy defined in [`deploy/openbao-policy.hcl`](../deploy/openbao-policy.hcl).
- **`vault_token.service_token`**: Generates a long-lived periodic client token strictly scoped to the `integration-aggregator` policy.
- **`kubernetes_secret.openbao_token`**: Synchronizes the generated token into Kubernetes as Secret `integration-aggregator-openbao-token`.
- **`vault_generic_endpoint.oauth_servers`**: Declaratively registers OAuth providers (GitHub, Google, mock OIDC) at `${mount_path}/servers/${provider}`.

---

## 3. Usage

### Prerequisites
1. OpenBao running (e.g. via `minikube` + Helm or standalone server).
2. OpenBao port-forward active:
   ```bash
   kubectl port-forward svc/openbao 8200:8200
   ```
3. Terraform CLI installed (`brew install terraform` or `brew install opentofu`).

### Deployment Steps
```bash
# 1. Initialize Terraform
cd terraform
terraform init

# 2. Review Execution Plan
terraform plan -var="openbao_address=http://localhost:8200" -var="openbao_token=root"

# 3. Apply Configuration
terraform apply -var="openbao_address=http://localhost:8200" -var="openbao_token=root" -auto-approve
```

To register providers declaratively via Terraform, copy `terraform.tfvars.example` to `terraform.tfvars`, fill in your OAuth client credentials, and run `terraform apply`.
