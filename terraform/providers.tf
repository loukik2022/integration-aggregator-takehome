terraform {
  required_version = ">= 1.5.0"
  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 4.2.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30.0"
    }
  }
}

provider "vault" {
  address = var.openbao_address
  token   = var.openbao_token
}

provider "kubernetes" {
  config_path = var.create_kubernetes_secret ? var.kubeconfig_path : null
}
