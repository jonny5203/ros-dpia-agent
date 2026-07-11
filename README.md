# Kommune DPIA & ROS Copilot

A local-first, document-driven RAG copilot for **Sandefjord Kommune** that helps
privacy officers, project managers and IT-security staff draft **DPIA**
(Datatilsynet) and **ROS** (NSM) documentation from uploaded project files —
extracting a structured profile, finding gaps, drafting cited reports, and
**never making a legal/compliance decision.**

> ⚠️ Portfolio/demo project. Uses **synthetic** Norwegian sample documents only.
> See [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md) for the full design.

---

## Status — Phase 0 (repo skeleton, infra, CI)

`make k8s-up` brings every backing service up healthy in a local Kubernetes
(kind) cluster; the app boots and answers `/api/health`. No business logic yet —
that arrives in Phases 1–7.

---

## 🔐 Never commit secrets

Three layers protect API keys (OpenRouter, etc.) from reaching GitHub:

1. **`.gitignore`** — `.env` and key material are untracked by default.
2. **Pre-commit hook** (`.githooks/pre-commit`) — blocks real `.env` files and
   scans staged additions for key patterns. Active once you run `make git-init`
   (already set if you bootstrapped via the steps below).
3. **CI gitleaks** (`.github/workflows/ci.yml`) — scans every push/PR.

**Rules:**
- Copy `.env.example` → `.env` and put real values **only** in `.env`.
- Never paste a key into any other file. If the hook fires, it's doing its job.
- Bypass only with `git commit --no-verify` and only for a known false positive.

---

## Prerequisites

- **Docker ≥ 24** — builds the backend/frontend images and runs the kind node
- **kind** → https://kind.sigs.k8s.io/docs/user/quick-start (Kubernetes-in-Docker)
- **kubectl** → https://kubernetes.io/docs/tasks/tools/
- An **OpenRouter API key** → https://openrouter.ai/keys (the MVP's chat + embeddings provider)
- GNU Make (optional — every command is a thin wrapper around `kind`/`kubectl`)

No GPU, no local Python/Node required — everything runs in containers inside the
kind cluster. Each service runs in its own pod network namespace, so the local
host-port collisions that affect bare docker-compose (e.g. a stray `uvicorn` on
8000) cannot recur — only host port `8081` is touched.

---

## First run

> Run every `make …` command from the **repo root** — the Makefile paths and the
> `.env` load are anchored there.

```bash
git clone <this-repo> && cd ROSAndDPIARAGAgent
cp .env.example .env          # then edit .env and set OPENROUTER_API_KEY=sk-or-...
make git-init                 # activate the pre-commit secret guard
make k8s-up                   # create the kind cluster, build+load images, apply manifests, wait for health
make k8s-ps                   # wait until every pod shows "Running" (1/1)
```

`make k8s-up` does, in order: create the `dpia-ros` kind cluster (idempotent) →
build `dpia-ros-backend:dev` and `dpia-ros-web:dev` on the host → load them into
the kind node → create the `dpia-secrets` Secret + init ConfigMaps from `.env`
and `infra/` → `kubectl apply -k infra/k8s` → wait on each rollout.

Then:

```bash
curl -s http://localhost:8081/api/health | jq .   # API health (incl. OpenRouter reachability)
open http://localhost:8081                          # SPA shell loads
```

The Keycloak admin console is reachable by port-forwarding (it isn't exposed on
a host port, by design): `kubectl -n dpia-ros port-forward svc/keycloak 8080:8080`
then open http://localhost:8080 (admin / admin).

Default seeded Keycloak realm is `sandefjord` (Phase 1 wires login; for now it
just needs to import cleanly).

---

## Common commands

```bash
make k8s-up          # start the whole stack (create cluster + build + apply + wait)
make k8s-down        # scale every Deployment to 0 (stops pods, keeps cluster + data)
make k8s-ps          # pod status
make k8s-logs s=api  # tail one service (api|worker|web|postgres|qdrant|...)
make k8s-api-sh      # shell into the api pod
make backend-lint    # ruff + mypy (inside the running api pod)
make backend-test    # pytest
make frontend-build  # production SPA build
make check-secrets   # gitleaks scan of the worktree
make k8s-clean       # ⚠ delete namespace + PVCs (data loss)
make k8s-nuke        # ⚠ delete the kind cluster entirely
```

---

## Project layout

```
backend/    FastAPI (Python 3.12) — app/{core,api,ai,domain,...}, alembic, tests
frontend/   Vite + React 19 + TypeScript (Tailwind + shadcn/ui, React Router 7)
infra/k8s/  kind cluster config + Kubernetes manifests (kustomize) for the whole stack
infra/      initdb/, keycloak/realm-sandefjord.json, minio/init.sh, nginx/ (sourced into ConfigMaps)
knowledge-base/   Bundled, versioned regulatory KB (GDPR, Datatilsynet, NSM, Digdir, ...)
sample-data/      Synthetic Norwegian sample documents (HSO scenario)
eval/       RAG evaluation harness (Ragas + custom citation/extraction gates)
docs/       Architecture diagram, demo script, interview talking points
```

---

## Services (MVP stack)

All services run in the `dpia-ros` namespace of the local kind cluster. Only the
`web` NodePort reaches the host (via kind's `8081 → 30080` port mapping); the
backing services are ClusterIP-internal and reached by the app over in-cluster DNS.

| Service    | Image                       | Exposure            |
|------------|-----------------------------|---------------------|
| web        | nginx (serves SPA + proxy)  | http://localhost:8081 |
| api        | python:3.12-slim (FastAPI)  | internal (proxied by web) |
| worker     | same image (arq)            | —                   |
| postgres   | postgres:16-alpine          | internal            |
| qdrant     | qdrant/qdrant:v1.18.0       | internal            |
| redis      | redis:7-alpine              | internal            |
| minio      | minio/minio                 | internal            |
| keycloak   | quay.io/keycloak:26.6       | internal (port-forward to access) |

See [`infra/k8s/README.md`](./infra/k8s/README.md) for the manifest layout and
how each old docker-compose service maps to its Kubernetes equivalent.

> **Note on OpenRouter:** the MVP sends chat completions **and embeddings**
> (`text-embedding-3-large`) to OpenRouter, so document text leaves the box
> during ingestion. A **pre-embedding PII gate** (Phase 3) blocks unacknowledged
> special-category text from being embedded. A fully-local Ollama mode is a
> post-MVP roadmap item. See `IMPLEMENTATION_PLAN.md` §11 and §16 R7.
