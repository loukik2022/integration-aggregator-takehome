variable "openbao_address" {
  type        = string
  description = "Address of the OpenBao server"
  default     = "http://localhost:8200"
}

variable "openbao_token" {
  type        = string
  description = "Administrative / Root token for configuring OpenBao"
  default     = "root"
  sensitive   = true
}

variable "kubeconfig_path" {
  type        = string
  description = "Path to the kubeconfig file"
  default     = "~/.kube/config"
}

variable "kubernetes_namespace" {
  type        = string
  description = "Kubernetes namespace where integration-aggregator is deployed"
  default     = "default"
}

variable "create_kubernetes_secret" {
  type        = bool
  description = "Whether to create a Kubernetes secret for the token (requires active cluster)"
  default     = false
}

variable "oauth_mount_path" {
  type        = string
  description = "Mount path for the openbao-plugin-secrets-oauthapp secrets engine"
  default     = "oauth2"
}

variable "oauth_providers" {
  type = map(object({
    provider         = string # e.g. "github", "google", "oidc"
    client_id        = string
    client_secret    = string
    provider_options = optional(map(string), {})
    scopes           = optional(list(string), [])
  }))
  description = "OAuth / OIDC providers to register idempotently during provisioning"
  default     = {}
}
