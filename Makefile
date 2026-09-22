.PHONY: all up down test smoke-test perf lint chart-package clean help

SHELL := /bin/bash
IMAGE_NAME := integration-aggregator
IMAGE_TAG := latest
HELM_RELEASE := integration-aggregator
OPENBAO_RELEASE := openbao
NAMESPACE := default

help: ## Show this help message
	@echo "Integration Aggregator - Management Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up: ## Start minikube, OpenBao with oauthapp plugin, mock OIDC, and deploy service via Helm (idempotent)
	@echo "==> [1/6] Ensuring minikube cluster is running..."
	@if command -v minikube >/dev/null 2>&1; then \
		minikube status >/dev/null 2>&1 || minikube start; \
	else \
		echo "Warning: minikube not found on PATH, assuming current kubectl context is active."; \
	fi

	@echo "==> [2/6] Building container image..."
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

	@if command -v minikube >/dev/null 2>&1; then \
		echo "==> Loading image into minikube..."; \
		minikube image load $(IMAGE_NAME):$(IMAGE_TAG); \
	fi

	@echo "==> [3/6] Deploying OpenBao via Helm..."
	@if command -v helm >/dev/null 2>&1; then \
		helm repo add openbao https://openbao.github.io/openbao-helm 2>/dev/null || true; \
		helm repo update openbao; \
		helm upgrade --install $(OPENBAO_RELEASE) openbao/openbao \
			-f deploy/openbao-values.yaml \
			--namespace $(NAMESPACE) \
			--wait --timeout 5m; \
	else \
		echo "ERROR: helm is required for deployment."; exit 1; \
	fi

	@echo "==> [4/6] Configuring OpenBao plugin, secrets engine, and policy..."
	bash scripts/setup-openbao.sh

	@echo "==> [5/6] Deploying mock-oauth2-server for CI/local testing..."
	kubectl apply -f deploy/mock-oauth2-server.yaml
	kubectl wait --for=condition=ready pod -l app=mock-oauth2-server --timeout=120s

	@echo "==> [6/6] Deploying Integration Aggregator from local Helm chart..."
	helm upgrade --install $(HELM_RELEASE) ./chart/integration-aggregator \
		--namespace $(NAMESPACE) \
		--set image.repository=$(IMAGE_NAME) \
		--set image.tag=$(IMAGE_TAG) \
		--set image.pullPolicy=Never \
		--wait --timeout 3m

	@echo ""
	@echo "==> Deployment complete! Pod status:"
	kubectl get pods -n $(NAMESPACE)

down: ## Teardown service, OpenBao, mock OIDC, and stop minikube
	@echo "==> Tearing down deployment..."
	-helm uninstall $(HELM_RELEASE) -n $(NAMESPACE) 2>/dev/null || true
	-helm uninstall $(OPENBAO_RELEASE) -n $(NAMESPACE) 2>/dev/null || true
	-kubectl delete -f deploy/mock-oauth2-server.yaml -n $(NAMESPACE) 2>/dev/null || true
	-kubectl delete secret integration-aggregator-openbao-token -n $(NAMESPACE) 2>/dev/null || true
	@if command -v minikube >/dev/null 2>&1; then \
		echo "Stopping minikube..."; \
		minikube stop 2>/dev/null || true; \
	fi
	@echo "==> Teardown complete."

test: ## Run unit tests with pytest
	@echo "==> Running Python unit tests..."
	python -m pytest -v tests/

smoke-test: ## Run full end-to-end automated smoke test
	@echo "==> Executing smoke test..."
	bash scripts/smoke-test.sh

perf: ## Run performance benchmark against token endpoint
	@echo "==> Executing performance benchmark..."
	bash scripts/perf-test.sh

chart-package: ## Package Helm chart
	@mkdir -p dist
	helm package ./chart/integration-aggregator -d dist/

clean: ## Clean build and test caches
	rm -rf .pytest_cache dist/ build/ *.egg-info .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
