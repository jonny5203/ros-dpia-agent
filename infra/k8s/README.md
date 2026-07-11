# Kubernetes local dev stack (kind)

This replaces the previous `docker-compose.yml`. The same 9 services run as
Deployments/Jobs in a dedicated **kind** cluster (`dpia-ros`), exposed on a
single host port (`http://localhost:8081`). Each pod has its own network
namespace, so the host-port collisions that hit docker-compose (e.g. a local
uvicorn on 8000) can't recur — only port 8081 ever touches the host.

## Layout

| File | What |
|---|---|
| `kind.yaml` | kind cluster config: `name: dpia-ros`, host `8081` → node `30080` |
| `kustomization.yaml` | Resource order + generates ConfigMaps from `infra/{minio,keycloak,initdb}/` |
| `namespace.yaml` | `Namespace: dpia-ros` |
| `postgres.yaml` / `qdrant.yaml` / `redis.yaml` / `minio.yaml` / `keycloak.yaml` | Stateful services (each: Deployment + Service + PVC) |
| `api.yaml` / `worker.yaml` | App tiers (FastAPI + arq), image `dpia-ros-backend:dev` |
| `web.yaml` | nginx SPA + reverse proxy, `type: NodePort` (30080) |
| `minio-init-job.yaml` | One-shot bucket seeder (mirrors the old `minio-init` sidecar) |

## How the docker-compose mapping holds

- **Service DNS**: a Service named `postgres` is reachable in-namespace as
  `postgres`, so `.env` connection strings (`http://qdrant:6333`,
  `redis://redis:6379/0`, `http://minio:9000`, `http://keycloak:8080`,
  `…@postgres:5432`) work unchanged.
- **`frontend/nginx.conf`** proxies to `http://api:8000` and `http://keycloak:8080`
  — same bare names, same resolution. No nginx change needed.
- **`depends_on: service_healthy`** → readiness probes. Pods that need a
  dependency restart-loop until it's ready (k8s `restartPolicy: Always`).
- **Named volumes** → one PVC per stateful service.
- **Init scripts** (`infra/initdb/01_pgcrypto.sql`, `infra/minio/init.sh`,
  `infra/keycloak/realm-sandefjord.json`) are inlined into ConfigMaps by
  kustomize — they remain the single source of truth.

## Secrets

Sensitive values live in `.env` (gitignored). `make k8s-up` regenerates the
`dpia-secrets` Kubernetes Secret from `.env` on every run, so editing `.env`
then re-running `make k8s-up` picks up the change (same workflow as the old
compose flow). api/worker load it via `envFrom`; api additionally overrides the
browser-facing `KEYCLOAK_PUBLIC_URL`/`CORS_ORIGINS` to `http://localhost:8081`.

## Day-to-day

```bash
make k8s-up          # create cluster + build/load images + apply + wait healthy
make k8s-ps          # pod status
make k8s-logs s=api  # tail one service
make k8s-api-sh      # shell into the api pod
make k8s-down        # delete namespace (keeps cluster + PVCs)
make k8s-clean       # delete namespace + PVCs (data loss)
make k8s-nuke        # delete the kind cluster entirely
```

## Known gaps

- **Alembic migrations are not auto-run.** This matches the previous docker
  setup (compose didn't run them either). When Phase 1 DB code lands, add a
  pre-api `initContainer`/`Job` running `alembic upgrade head`.
- **No Ingress controller.** A single NodePort is the simplest local exposure.
  For TLS or multiple public hostnames, add an Ingress + kind's
  [ingress guide](https://kind.sigs.k8s.io/docs/user/ingress/).
- **Keycloak runs in `start-dev` mode** (no TLS, H2 file store on the PVC) —
  fine for local dev; production hardening is post-MVP (plan §16 R5).
