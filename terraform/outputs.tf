output "oauth_mount_path" {
  description = "The mount path of the OAuthapp secrets engine"
  value       = vault_mount.oauthapp.path
}

output "policy_name" {
  description = "The name of the applied OpenBao policy"
  value       = vault_policy.integration_aggregator.name
}

output "kubernetes_secret_name" {
  description = "The Kubernetes secret created for the aggregator service"
  value       = var.create_kubernetes_secret && length(kubernetes_secret.openbao_token) > 0 ? kubernetes_secret.openbao_token[0].metadata[0].name : null
}

output "registered_providers" {
  description = "List of declaratively configured OAuth provider servers"
  value       = keys(var.oauth_providers)
}
