# 1. Mount the oauthapp secrets engine
resource "vault_mount" "oauthapp" {
  path        = var.oauth_mount_path
  type        = "oauthapp"
  description = "OAuth 2.0 application secrets engine (openbao-plugin-secrets-oauthapp)"

  options = {
    # Custom plugin options if required
  }
}

# 2. Define least-privilege policy for the Integration Aggregator service
resource "vault_policy" "integration_aggregator" {
  name   = "integration-aggregator"
  policy = file("${path.module}/../deploy/openbao-policy.hcl")
}

# 3. Create scoped periodic service token for the aggregator service
resource "vault_token" "service_token" {
  policies = [vault_policy.integration_aggregator.name]
  period   = "720h"
  no_parent = true
  renewable = true

  metadata = {
    "service" = "integration-aggregator"
    "managed" = "terraform"
  }

  depends_on = [vault_policy.integration_aggregator]
}

# 4. Synchronize token to Kubernetes Secret for the service Pod to consume
resource "kubernetes_secret" "openbao_token" {
  count = var.create_kubernetes_secret ? 1 : 0

  metadata {
    name      = "integration-aggregator-openbao-token"
    namespace = var.kubernetes_namespace
  }

  data = {
    token = vault_token.service_token.client_token
  }

  type = "Opaque"
}

# 5. Declarative Provider Registration (GitHub, Google, Mock OIDC)
resource "vault_generic_endpoint" "oauth_servers" {
  for_each = var.oauth_providers

  path                 = "${vault_mount.oauthapp.path}/servers/${each.key}"
  ignore_absent_fields = true

  data_json = jsonencode({
    provider         = each.value.provider
    client_id        = each.value.client_id
    client_secret    = each.value.client_secret
    provider_options = length(each.value.provider_options) > 0 ? each.value.provider_options : null
  })

  depends_on = [vault_mount.oauthapp]
}
