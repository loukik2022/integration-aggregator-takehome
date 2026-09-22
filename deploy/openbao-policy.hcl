# Policy for the integration aggregator service
path "oauth2/servers/*" {
  capabilities = ["create", "update", "read", "list"]
}

path "oauth2/auth-code-url" {
  capabilities = ["create", "update"]
}

path "oauth2/creds/*" {
  capabilities = ["create", "update", "read", "list"]
}
