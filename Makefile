# `.RECIPEPREFIX` lets us use `>` instead of hard tabs.
.RECIPEPREFIX := >
SHELL := /usr/bin/env bash

CLUSTER      := dpia-ros
NAMESPACE    := dpia-ros
KIND_CONFIG  := infra/k8s/kind.yaml
K8S_DIR      := infra/k8s
IMG_BACKEND  := dpia-ros-backend:dev
IMG_WEB      := dpia-ros-web:dev
# Host port the web NodePort (30080) is forwarded to by kind.
WEB_PORT     := 8081

# Services whose rollout we wait on in k8s-up (in dependency order).
ROLLOUT_TARGETS := postgres qdrant redis minio keycloak api worker web

.PHONY: help require-env k8s-cluster k8s-namespace k8s-build k8s-load k8s-secret k8s-configmaps \
        k8s-apply k8s-up k8s-redeploy k8s-down k8s-ps k8s-logs \
        k8s-api-sh k8s-worker-sh k8s-web-sh \
        backend-lint backend-test \
        frontend-install frontend-lint frontend-build \
        check-secrets k8s-clean k8s-minio-init k8s-nuke git-init \
        db-migrate db-current db-shell db-forward db-revision

help: ## Show this help
> @grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) \
>   | sed 's/:\(.*\)*## /:## /' \
>   | awk 'BEGIN {FS = ":## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' || true

require-env: ## (internal) fail fast if .env is missing
> @test -f .env || { \
>   echo "[make] .env not found. Run:"; \
>   echo "    cp .env.example .env   # then set OPENROUTER_API_KEY"; \
>   exit 1; }

# ── Cluster lifecycle ───────────────────────────────────────────────────────

k8s-cluster: ## Create the kind cluster (idempotent)
> @command -v kind >/dev/null 2>&1 || { echo "[make] kind not installed; see https://kind.sigs.k8s.io/"; exit 1; }
> @kind get clusters | grep -qx "$(CLUSTER)" && echo "[make] kind cluster '$(CLUSTER)' exists" || \
>   kind create cluster --config $(KIND_CONFIG)
> @kubectl config use-context kind-$(CLUSTER)

k8s-namespace: k8s-cluster ## Ensure the namespace exists (idempotent)
> kubectl apply --dry-run=client -o yaml -f $(K8S_DIR)/namespace.yaml | kubectl apply -f -

k8s-build: ## Build the backend + web images on the host
> @command -v docker >/dev/null 2>&1 || { echo "[make] docker required"; exit 1; }
> docker build -t $(IMG_BACKEND) ./backend
> docker build -t $(IMG_WEB)     ./frontend

k8s-load: k8s-build ## Load the built images into the kind node
> kind load docker-image $(IMG_BACKEND) --name $(CLUSTER)
> kind load docker-image $(IMG_WEB)     --name $(CLUSTER)

k8s-secret: require-env k8s-namespace ## (Re)apply the dpia-secrets Secret from .env
> kubectl -n $(NAMESPACE) create secret generic dpia-secrets \
>   --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -

k8s-configmaps: k8s-namespace ## (Re)apply init-script ConfigMaps from infra/ source files
> kubectl -n $(NAMESPACE) create configmap minio-init-sh \
>   --from-file=init.sh=infra/minio/init.sh --dry-run=client -o yaml | kubectl apply -f -
> kubectl -n $(NAMESPACE) create configmap keycloak-realm \
>   --from-file=realm-sandefjord.json=infra/keycloak/realm-sandefjord.json --dry-run=client -o yaml | kubectl apply -f -
> kubectl -n $(NAMESPACE) create configmap pgcrypto-sql \
>   --from-file=01_pgcrypto.sql=infra/initdb/01_pgcrypto.sql --dry-run=client -o yaml | kubectl apply -f -

k8s-apply: ## Apply the kustomized manifests
> kubectl apply -k $(K8S_DIR)

k8s-up: require-env k8s-namespace k8s-load k8s-configmaps k8s-secret k8s-apply ## Bring up the full stack and wait for health
> @echo "[make] waiting for rollouts (this can take ~3 min on first run)..."
> @for svc in $(ROLLOUT_TARGETS); do \
>   echo "  → $$svc"; \
>   kubectl -n $(NAMESPACE) rollout status deployment/$$svc --timeout=300s || exit 1; \
> done
> @echo "[make] ✅ stack is up — web at http://localhost:$(WEB_PORT)"
> @echo "       health: curl -s http://localhost:$(WEB_PORT)/api/health | jq ."

k8s-redeploy: k8s-load ## Rebuild + reload image, then restart api + worker pods to pick it up
> @echo "[make] restarting api + worker to pick up the new image..."
> @kubectl -n $(NAMESPACE) rollout restart deployment/api deployment/worker
> @kubectl -n $(NAMESPACE) rollout status deployment/api --timeout=180s
> @kubectl -n $(NAMESPACE) rollout status deployment/worker --timeout=180s
> @echo "[make] ✅ redeployed — new image is live"

# ── Day-to-day ops ──────────────────────────────────────────────────────────

k8s-down: ## Scale every Deployment to 0 (stops pods, keeps cluster + PVCs + data)
> @for svc in $(ROLLOUT_TARGETS); do \
>   kubectl -n $(NAMESPACE) scale deployment/$$svc --replicas=0; \
> done
> @echo "[make] all deployments scaled to 0 — data preserved. Bring back with: make k8s-up"

k8s-ps: ## Pod status
> kubectl -n $(NAMESPACE) get pods -o wide

k8s-logs: ## Tail logs. Usage: make k8s-logs s=api
> kubectl -n $(NAMESPACE) logs -f deployment/$(if $(s),$(s),api)

k8s-api-sh: ## Shell into the api pod
> kubectl -n $(NAMESPACE) exec -it deployment/api -- bash

k8s-worker-sh: ## Shell into the worker pod
> kubectl -n $(NAMESPACE) exec -it deployment/worker -- bash

k8s-web-sh: ## Shell into the web pod
> kubectl -n $(NAMESPACE) exec -it deployment/web -- sh

k8s-minio-init: ## Re-run the MinIO bucket seeder Job (after editing init.sh)
> kubectl -n $(NAMESPACE) delete job minio-init --ignore-not-found
> kubectl -n $(NAMESPACE) apply -f $(K8S_DIR)/minio-init-job.yaml

# ── Backend lint/test (in-cluster) ──────────────────────────────────────────

backend-lint: ## Ruff + mypy inside the running api pod
> @kubectl -n $(NAMESPACE) exec deployment/api -- sh -c 'ruff check . && mypy app' \
>   || echo "[make] api pod not ready — run 'make k8s-up' first"

backend-test: ## pytest inside the running api pod
> @kubectl -n $(NAMESPACE) exec deployment/api -- pytest -q \
>   || echo "[make] api pod not ready — run 'make k8s-up' first"

# ── Frontend (local dev) ────────────────────────────────────────────────────

frontend-install: ## npm install (local dev)
> cd frontend && npm install

frontend-lint: ## TypeScript + ESLint
> cd frontend && npx tsc --noEmit && npx eslint src --max-warnings=0

frontend-build: ## Production build of the SPA
> cd frontend && npm run build

# ── Teardown / secrets ─────────────────────────────────────────────────────

check-secrets: ## Scan the worktree for leaked secrets (gitleaks, via docker)
> @command -v docker >/dev/null 2>&1 || { echo "[make] docker required"; exit 1; }
> docker run --rm -v "$(PWD):/repo" zricethezav/gitleaks:latest detect --source=/repo --no-banner --redact

git-init: ## (Re)apply git hooks path (idempotent)
> git config core.hooksPath .githooks
> @echo "[make] hooks path -> .githooks (pre-commit secret guard active)"

k8s-clean: ## Delete namespace + PVCs (data loss!) — keeps the cluster
> @read -r -p "This deletes ALL data (PVCs). Continue? [y/N] " ans; \
> [ "$$ans" = "y" ] || { echo "aborted"; exit 1; }
> kubectl delete namespace $(NAMESPACE) --wait

k8s-nuke: ## Delete the kind cluster entirely (cluster + everything in it)
> @read -r -p "Delete the kind cluster '$(CLUSTER)' entirely? [y/N] " ans; \
> [ "$$ans" = "y" ] || { echo "aborted"; exit 1; }
> kind delete cluster --name $(CLUSTER)

# ── Database / migrations ────────────────────────────────────────────────────
# Revisions are authored locally (repo is source of truth) and applied inside
# the api pod at deploy time (initContainer runs `alembic upgrade head`).
# Generating a revision requires `make db-forward` running in another shell.

db-migrate: ## Apply pending migrations (alembic upgrade head) inside the api pod
> @kubectl -n $(NAMESPACE) exec deployment/api -- alembic upgrade head

db-revision: require-env ## Create a new migration locally. Run `make db-forward` first. Usage: make db-revision m="add_users_table"
> @test -n "$(m)" || { echo 'Usage: make db-revision m="<message>"'; exit 1; }
> @cd backend && DATABASE_URL=$$(grep -E '^DATABASE_URL=' ../.env | sed 's/@postgres:/@localhost:/') .venv/bin/alembic revision -m "$(m)"
> @echo "[make] revision written to backend/alembic/versions/ — build & redeploy to apply"

db-current: ## Show current alembic version + pending migrations
> @kubectl -n $(NAMESPACE) exec deployment/api -- sh -c 'echo "== current ==" && alembic current && echo "== heads ==" && alembic heads'

db-shell: ## psql inside the postgres pod
> @kubectl -n $(NAMESPACE) exec -it deployment/postgres -- psql -U dpia -d dpia

db-forward: ## Port-forward Postgres to localhost:5432 (run psql locally)
> @echo "[make] forwarding postgres:5432 -> localhost:5432 (Ctrl+C to stop)"
> @kubectl -n $(NAMESPACE) port-forward svc/postgres 5432:5432
