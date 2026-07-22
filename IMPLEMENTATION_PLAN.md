# Kommune DPIA & ROS Copilot — Implementation Plan

> **Municipal Privacy Risk Assistant** — a local-first, document-driven RAG copilot that helps Sandefjord Kommune privacy officers, project managers and IT-security staff prepare **DPIA** (Datatilsynet) and **ROS** (NSM) documentation faster. It uploads project documents, indexes them with citations, extracts a structured project profile, finds missing information, drafts DPIA screenings and ROS risk registers, and exports human-reviewable reports — **without ever making a legal/compliance decision.**

Status: **DRAFT v2 — ready for review.**
Owner: _you._
Last updated: 2026-07-04.

---

## 0. How to read this plan

- **Status legend for tasks:** `- [ ]` not started · `- [~]` in progress · `- [x]` done.
- **Every phase** (sections 15–16) has the same shape: **Goal → Scope → Tasks (checkboxes) → Deliverables → Acceptance criteria → Risks.**
- Acceptance criteria are written as _observable, testable_ conditions — if you can't demo it, the phase isn't done.
- Section 13 (frontend), 12 (infra), 10 (citations) and 9 (prompts) are the cross-cutting specs the phases build against.
- **This document is the plan only. No code is written in this pass** — review, then we scaffold (see §17 open questions first).

---

## 1. Executive summary

The product is a **RAG + structured-workflow** assistant, deliberately _not_ a chatbot and _not_ an autonomous agent swarm. The core insight from `Project.txt`: for ROS/DPIA work, **evidence is the product.** A generic AI answer is useless to a privacy officer; a citation-backed extraction with an explicit "here is what the uploaded files do **not** tell us" gap list is valuable.

The MVP delivers one end-to-end vertical slice — create project → upload Norwegian synthetic docs → index → extract profile → DPIA screening → ROS register → Markdown export — that is demo-ready for the **"AI assistant for HSO routines"** scenario. The roadmap then hardens it (eval harness, DOCX/PDF export, ID-porten federation, deployment).

**Non-goals (explicit):** no fine-tuning, no autonomous decisions, no legal-conclusion engine, no real personal/health data in the demo, no multi-agent framework in v1.

---

## 2. Vision & guardrails (what it does / does NOT do)

| The assistant **MAY** | The assistant **MUST NOT** |
|---|---|
| Summarize uploaded documents | Approve or reject a DPIA |
| Identify missing information (gap-finding) | Declare a project compliant / non-compliant |
| Draft DPIA / ROS text **for human review** | Make decisions about citizens |
| Suggest follow-up questions for the supplier | Process real health data in the demo |
| Suggest risk-reducing measures | Send documents externally without explicit approval |
| Cite source chunks for every claim | Modify official records automatically |
| Flag sensitive data on upload | Invent citations or infer facts not in the evidence |

These guardrails are enforced _structurally_ (Pydantic schemas without a "compliant" enum, a deterministic citation-verification gate, a system prompt with hard negatives), not just stylistically. See §9 and §10.

---

## 3. Confirmed decisions & final stack

Locked via two rounds of requirements gathering + a July-2026 best-practices research pass.

| Dimension | Decision | Notes |
|---|---|---|
| **Deployment** | **Local-first via Kubernetes (kind)** — manifests in `infra/k8s/`, applied with `make k8s-up` | Azure stays a _documented production target_, not a hard dependency. All services run as pods in a local kind cluster (`dpia-ros`), exposed on a single host port (`http://localhost:8081`); each pod's own network namespace eliminates the host-port collisions that affect bare docker-compose. The MVP's LLM + embeddings call OpenRouter (internet required) — a fully-offline Ollama mode is post-MVP (§16 R7). |
| **Backend** | **Python 3.12 + FastAPI** | Layered: routers → services → repositories → domain. |
| **Frontend** | **React 19 + TypeScript, Vite 6** | React Router 7 (data mode), TanStack Query v5, shadcn/ui + Tailwind. |
| **Relational DB** | **PostgreSQL 16** (asyncpg + SQLAlchemy 2.x async + Alembic) | Metadata, RBAC, analyses, risks, audit. |
| **Vector store** | **Qdrant ≥1.16** (hybrid dense + BM25 sparse) | **Per-project collection** (`chunks_{projectId}`) for hard isolation + clean deletion + per-project lexical stats. |
| **Embeddings** | **`openai/text-embedding-3-large` (3072-dim) via OpenRouter `/v1/embeddings`** | Cloud embedding model (MVP default); multilingual incl. Norwegian; per-project `embed_model`/`embed_dim` tracked in `index_manifest` so a future local-model switch is detected and re-indexed. A **pre-embedding PII gate** sends only PII-cleared text to the cloud (§11). Local `bge-m3`/Ollama embeddings are a post-MVP roadmap mode (different dim ⇒ re-index on switch). `dimensions=1024` truncation is available if storage ever matters. |
| **LLM (chat)** | **OpenRouter (user-selectable model)** behind one provider abstraction | The model is **user-selectable** at runtime from OpenRouter's structured-output-capable catalog (default `anthropic/claude-sonnet-4.5`), chosen per project; a vision-capable model captions diagrams. OpenRouter is the **sole MVP path** for chat; local Ollama (`qwen2.5`/`qwen3`) chat + embeddings is a **post-MVP roadmap** mode (offline / privacy-hardened, §16 R7). |
| **Structured output** | **`instructor` + Pydantic v2** | `response_model=` on every extraction call. |
| **Object storage** | **MinIO (S3-compatible)** | Original uploaded files; `aioboto3` async client. |
| **Auth** | **Lightweight real OIDC/JWT — BFF pattern + Keycloak 26** | FastAPI runs Authorization-Code + PKCE, stores tokens in a signed `httpOnly` `SameSite=Lax` cookie, re-validates JWT against JWKS per request with server-side refresh. The SPA does credentialed `fetch` only — it never holds tokens. |
| **RBAC** | IdP group → global app role **+** app-owned `project_members` table for per-project membership | Roles: Viewer, Project Manager, Privacy Officer, IT-Security, Admin. |
| **Background jobs** | **`arq` + Redis** (async-native) | Document ingestion + the 5-step AI pipeline. Job status mirrored to Postgres. |
| **UI language** | **English UI + Norwegian (Bokmål) synthetic sample documents** | Authentic data where it matters; broadly readable demo. |
| **PDF parsing** | **Docling via modular `docling-slim` (MIT)** primary; `pypdf` (BSD-3-Clause) text-only fallback | Install only Docling's PDF, local-model, and RapidOCR/ONNX extras, with CPU-only PyTorch wheels for the Linux backend. This provides local layout, reading-order, table, and OCR-aware extraction without introducing PyMuPDF/PyMuPDF4LLM's AGPL-or-commercial-license choice. The fallback is an explicit degraded mode for born-digital PDFs, never a silent quality downgrade. Pin and review Docling model artifacts separately from the MIT-licensed code. |
| **Errors** | **RFC 9457 `application/problem+json`** | Stable error `type` URNs the frontend can branch on. |
| **Plan scope** | **Full phased vision** (detailed MVP + post-MVP roadmap) | §15–§16. |

---

## 4. System architecture

```
                         ┌──────────────────────────────────────────────┐
                         │                   Browser (React SPA)         │
                         │  Dashboard · Upload · Analysis+Chat · ROS ·   │
                         │  Export   (TanStack Query, credentialed fetch)│
                         └───────────────┬──────────────────────────────┘
                                         │  https://app.local  (single origin)
                          ┌──────────────▼──────────────┐
                          │           nginx              │  SPA static + reverse proxy
                          │  /api → api:8000  /oidc → kc │  (/api, /oidc same-origin ⇒ no CORS)
                          └──────┬───────────────┬───────┘
                  /oidc (PKCE)   │               │  /api (cookie auth)
                    ┌────────────▼──┐       ┌─────▼───────────────────────────┐
                    │  Keycloak 26  │       │          FastAPI (api)           │
                    │  realm import │◄──────┤  routers→services→repos→domain   │
                    │  JWKS / OAuth │  JWKS │  app/ai/{providers,retrieval,    │
                    └───────────────┘  val. │   agents,orchestrator}           │
                                            └─┬──────┬──────┬──────────┬───────┘
                    ┌────────────┐  ┌────────┘      │      │          │
            Redis ──│  arq worker│  │   Postgres 16 │      │          │ MinIO (S3)
            (queue) │ ingestion +│  │ (metadata,    │      │          │ original files
                    │  AI pipeline│  │  RBAC, audit, │      │          └──────────┘
                    └─────┬──────┘  │  analyses)    │      │
                          │         └───────────────┘      │
       ┌────────────────────────┬──────────────────┐
       ▼                        ▼                  ▼
  ┌────────────┐         ┌──────────────┐   ┌──────────┐
  │  Qdrant    │         │  OpenRouter  │   │ (MinIO)  │
  │ chunks_{p} │         │ chat LLM +   │   │ already  │
  │ dense+BM25 │         │ embeddings   │   │  above   │
  │ (per proj) │         │(text-emb-3-lg│   └──────────┘
  └────────────┘         └──────────────┘
```

**Data flow for one document (the ingestion pipeline, run by the `arq` worker):**

```
upload → store bytes in MinIO → documents row (status=parsing) →
route by type (pdf/docx/xlsx/md/png) → extract text (page/section-aware) →
detect PII / special-category data (CRITICAL **blocks cloud embedding + indexing** until acknowledged) →
chunk (800 tok / 150 overlap, structural + recursive) →
embed dense (text-embedding-3-large via OpenRouter; text already PII-cleared) + store text for BM25 → upsert to chunks_{projectId} →
status=ready → (on demand) AI pipeline: extract → screen → ros → checklist → draft
```

Every AI step retrieves scoped chunks, builds an `EVIDENCE` block, calls the LLM with a Pydantic `response_model`, then runs the **citation-verification gate** before persisting. See §10.

---

## 5. Domain grounding (the permanent knowledge base — source area A)

This is what makes the tools credible rather than hand-wavy. The knowledge base is **bundled, versioned, offline-capable** (local-first means no runtime fetches).

### 5.1 Legal / guidance
- **GDPR** Articles 5 (principles), 6 (lawful basis), 9 (special categories), 12–22 (rights), 30 (records of processing / *behandlingskatalog*), 32 (security), **35 (DPIA — incl. 35(3) mandatory list)**, **36 (prior consultation)**. Source: `gdpr-info.eu`.
- **Datatilsynet** DPIA guidance — the **9 WP29/EDPB screening criteria** (WP248 rev.01, rendered in Norwegian on `datatilsynet.no`): evaluation/scoring; automated decisions with legal/similar effect; systematic monitoring; special categories / highly personal data; large-scale processing; matching/combining datasets; vulnerable data subjects; innovative use / new technology; prevents a service/contract. **Threshold heuristic: ≥2 criteria → DPIA required; 1 → likely; 0 → not indicated** (a single strong criterion can still require one).

### 5.2 Security / governance
- **NSM Grunnprinsipper for IKT-sikkerhet v2.1** — **21 principles / 118 measures** across four categories: **IDENTIFY · PROTECT & MAINTAIN · DETECT · RESPOND & RECOVER**, with an official ISO/IEC 27002:2022 crosswalk. Bundled as a versioned **YAML** (`knowledge-base/nsm/grunnprinsipper.yaml`). The ROS generator emits risks _per principle_, never ad hoc.
- **Digdir** *Internkontroll i praksis – Informasjonssikkerhet* (governance overlay: leadership responsibility, annual risk-review, Art 30 processing register, privacy officer involvement, deviation handling, improvement measures).
- **Helsedirektoratet** *Normen* risikostyring — applied **only** when health/omsorg data is detected (EPJ, pasient, helseopplysning).

### 5.3 Templates & routines (municipal)
ROS template, DPIA template, data-processing-agreement checklist, supplier security questionnaire, cloud-assessment checklist, AI-usage / prompt-logging / human-review policies, "how we assess new systems," data classification routine. These are the seed content for `CompareAgainstChecklist`.

`★ Insight ─────────────────────────────────────`
The DPIA tool is deliberately a **deterministic rules engine over a verbatim regulatory checklist**, not an LLM "opinion." The LLM's job is to populate the _profile fields_ that feed the rules; the rules engine then fires the criteria with citations. This split is what lets you say in an interview: "the screening conclusion is reproducible and auditable — the model never decides whether a DPIA is needed, the Datatilsynet criteria do."
`─────────────────────────────────────────────────`

---

## 6. Data model

### 6.1 PostgreSQL (refined from `Project.txt`, async-ready)

```text
users           (id, oidc_sub UNIQUE, email, display_name, app_role, is_admin, created_at)
projects        (id, name, description, owner_id→users, status, classification, embed_model, embed_dim, created_at, created_by)
project_members (project_id→projects, user_id→users, role, created_at)   -- composite PK; per-project RBAC
documents       (id, project_id, filename, mime, ext, s3_key, sha256, classification,
                 processing_status, max_severity, acked_by, acked_at, lexicon_version, uploaded_by, uploaded_at)
document_findings (id, document_id, type, category, severity, count, sample_offsets JSONB, checksum_valid)
chunks          (id UUID PK, project_id, document_id, chunk_index, page, section_title, section_path,
                 char_start, char_end, sha8, qdrant_point_id)            -- single source of truth for the citation gate
project_profiles (id, project_id, profile JSONB, overall_confidence, model, prompt_version, created_at)
screenings      (id, project_id, result JSONB, conclusion, criteria_count, art35_3, art36_flag, created_at)
risks           (id, project_id, principle_id, title, cause, consequence, likelihood, impact, score,
                 treatment, residual_severity, owner, status, source_references JSONB, created_at)
checklist_items (id, project_id, category, principle_id, question, status, evidence, source_references JSONB)
reports         (id, project_id, kind, body_md, model, prompt_version, created_at)
jobs            (id, project_id, kind, status, progress_pct, error, arq_job_id, created_at, updated_at)
audit_logs      (id, project_id, user_id, action, target_type, target_id, metadata JSONB, ts)
prompt_versions (id, name, version, template, created_at)                -- every generation records its version
index_manifest  (project_id, embed_model, embed_dim, chunk_count, indexed_at)   -- detects embedding-model drift
```

- PKs are `UUID` (`gen_random_uuid()` via `pgcrypto`).
- `risk.score = likelihood × impact` is computed **server-side**, never by the model.
- `source_references` everywhere is `list[ChunkRef]` (see §10) — grounding is a schema-level obligation.

### 6.2 Qdrant — one collection per project: `chunks_{projectId}`

```text
vectors_config:        { "dense": { size: 3072, distance: Cosine } }   # text-embedding-3-large (native dim)
sparse_vectors_config: { "bm25":  { modifier: IDF } }                  # server-side BM25 over payload.text
payload:               { text, documentId, documentName, documentType, page,
                          sectionTitle, sectionPath, classification, chunkIndex, sha8, lang }
payload indexes:       documentId (keyword), documentType (keyword),
                       classification (keyword), page (integer)
```

Created on project creation; **dropped on project deletion** (atomic, certain cleanup of derived vectors). Queried only via the Universal Query API (`query_points`) with a mandatory `projectId`-equivalent filter (collection name itself enforces isolation).

### 6.3 Object storage (MinIO)
Bucket `kommune-docs`, key `projects/{projectId}/{documentId}{ext}`. Raw bytes encrypted at rest; never the embedding/vector store. `s3_key` persisted on the `documents` row.

---

## 7. API surface (FastAPI, `/api/v1`)

Refined from `Project.txt`; all errors are RFC 9457 `problem+json`.

```http
# Auth (BFF)
GET  /auth/login                    → 302 to Keycloak (PKCE)
GET  /auth/callback                 → code exchange, set session cookie, 302 /
POST /auth/logout
GET  /auth/me                       → current user + global role

# Projects + membership
POST /api/v1/projects
GET  /api/v1/projects
GET  /api/v1/projects/{id}
PATCH /api/v1/projects/{id}
POST /api/v1/projects/{id}/members          # invite / set role (Privacy Officer/Admin)
DELETE /api/v1/projects/{id}                # cascades: MinIO prefix, chunks rows, DROP Qdrant collection

# Documents + ingestion
POST /api/v1/projects/{id}/documents        # multipart upload → 201 + findings + job_id
GET  /api/v1/projects/{id}/documents
GET  /api/v1/projects/{id}/documents/{docId}          # incl. findings/classification
DELETE /api/v1/projects/{id}/documents/{docId}        # deletes original + chunks + vectors + derived analyses
POST /api/v1/projects/{id}/documents/{docId}/acknowledge   # approve indexing of special-category data (audited)
GET  /api/v1/projects/{id}/documents/{docId}/chunks/{chunkId}   # citation drill-down (text + page + section)

# AI pipeline (the 5 tools) — each enqueues an arq job, returns job_id
POST /api/v1/projects/{id}/analyze          # extract project profile
POST /api/v1/projects/{id}/dpia-screening
POST /api/v1/projects/{id}/ros              # generate risk register
POST /api/v1/projects/{id}/checklist        # compare against DPIA/ROS/supplier checklist
POST /api/v1/projects/{id}/report           # draft report (Markdown)
POST /api/v1/projects/{id}/chat             # SSE streaming, scoped RAG, citations

# Results (read) + edits
GET  /api/v1/projects/{id}/profile
GET  /api/v1/projects/{id}/screening
GET  /api/v1/projects/{id}/risks
PATCH /api/v1/projects/{id}/risks/{riskId}  # officer edits (likelihood/impact/treatment/owner/status)

# Jobs + audit + export
GET  /api/v1/jobs/{jobId}                   # status / progress (polled by the SPA)
GET  /api/v1/projects/{id}/audit-log
GET  /api/v1/projects/{id}/export/markdown  # bundle (screening + ros + checklist + summary)
```

Auth dependencies: `get_session`, `get_current_user` (JWT via JWKS), `get_project_context` (resolves `project_id` → verifies membership/role, **404 not 403** on non-membership to avoid enumeration). Mutations gated by `ctx.require(role)`.

---

## 8. The five agent tools + orchestrator

All five live in `backend/app/ai/agents/` and follow the **same shape**: `retrieve scoped chunks → render EVIDENCE → LLM call with Pydantic response_model → citation-verification gate → persist with citations`. They are _tools_, not autonomous agents — invoked by deterministic buttons, orchestrated in order.

**Provider & model selection.** The `ai/providers/` abstraction exposes one `LLMClient` over OpenRouter (an OpenAI-compatible gateway) for the MVP. **OpenRouter is the sole path** for the high-stakes stages (extract / screen / ros / report / chat): the **model is user-selectable** — fetched live from OpenRouter's catalog (`GET /api/v1/models`, filtered to models that support structured output) and persisted per-project (`projects.preferred_model`, default `anthropic/claude-sonnet-4.5`). **Embeddings also go through OpenRouter** — `openai/text-embedding-3-large` (3072-dim) via the `/v1/embeddings` endpoint, pinned per-project (`projects.embed_model`/`embed_dim`). A local Ollama backend (`qwen2.5`/`qwen3` chat + `bge-m3` embeddings) is reserved for a **post-MVP roadmap** offline/privacy-hardened mode (§16 R7); because `bge-m3` is 1024-dim, switching a project to local embeddings is a re-index event detected via `index_manifest`. Every generation logs `provider`, `model`, `prompt_version`, tokens, and the per-call cost (from OpenRouter usage) for audit; a per-project token/latency budget guards against a stuck cloud call hanging the `arq` job.

### 8.1 `extract_profile` (AnalyzeUploadedDocuments)
- **Input:** all indexed chunks for the project (representative sample + targeted retrieval).
- **Output:** `ProjectProfile` — `purpose`, `dataSubjects[]`, `personalDataCategories[]`, `specialCategories[]`, `systems[]`, `processors[]`, `retention`, `accessControl`, `internationalTransfer`, `missingInfo[]`, `openQuestions[]`, `overallConfidence`. Every leaf field carries `sourceReferences: list[ChunkRef]`.
- **Two-pass:** Pass A extracts the profile; **Pass B is a "red-team gap finder"** that receives Pass A's output + EVIDENCE and returns **only** `list[Gap]` + open questions.

### 8.2 `screen_dpia` (RunDpiaScreening)
- **Input:** extracted `ProjectProfile` + document findings (Art 9/10 flags).
- **Output:** the 9 Datatilsynet criteria (each: id, Norwegian label, triggered?, profile evidence, citation), `criteria_count`, `art35_3_triggered`, **`conclusion`** (`DPIA_REQUIRED` | `DPIA_LIKELY` | `DPIA_NOT_INDICATED`), cautious rationale in Norwegian, source citations. **Art 36** prior-consultation flag added after the ROS when residual risk is HIGH.
- **Tone (hard-coded into output, not the model's whim):** *"Based on the uploaded information, this project has indicators that normally require DPIA review… A privacy officer should confirm."* — never *"DPIA is legally required"* and never *"compliant / non-compliant."*

### 8.3 `generate_ros` (GenerateRosRegister)
- **Input:** profile + NSM Grunnprinsipper YAML + retrieved controls evidence.
- **Output:** risk rows `{principle_id, principle_label_nb, threat, cause, consequence, likelihood, impact, score(server-computed), treatment, residual_risk, owner, sourceReferences}` — **one row per applicable NSM principle** + Digdir internkontroll overlay (+ Normen rows only if health data detected).
- **Rule:** the LLM _proposes_; `score = likelihood × impact`; `status='draft'` until the officer confirms. Never auto-assert a control is satisfied.

### 8.4 `compare_checklists` (CompareAgainstChecklist)
- **Input:** profile + extracted controls vs. DPIA/ROS/supplier-checklist knowledge base.
- **Output:** `Complete[]` / `Missing[]` (retention, data location, access-control model, logging policy, sub-processor list, deletion process, legal basis, …) each with evidence or a `Gap`, plus suggested supplier follow-up questions.

### 8.5 `draft_report` (DraftReport)
- **Input:** profile + screening + risks + checklist.
- **Output:** a Markdown draft (DPIA screening section, ROS table, supplier questions, summary) with inline citations. **Markdown first** (MVP); DOCX/PDF are roadmap (server-side `python-docx` / WeasyPrint — the backend owns citation footnotes).

### 8.6 Orchestrator (`app/ai/orchestrator.py`)
Runs on the `arq` "pipeline" task: `documents-ready → extract_profile → screen_dpia → generate_ros → compare_checklists → draft_report`, persisting a `jobs` row with per-step status + the model/prompt_version used, so the UI shows progress and the reviewer sees every step's citations. Each step is independently re-runnable.

---

## 9. Prompt & guardrail design

Stored in `backend/app/ai/prompts/`, **versioned** in `prompt_versions`; the exact rendered prompt + model + temperature is logged on every generation row (regulators ask what the model was told).

**System prompt (shared hard skeleton):**
```
You are a privacy-engineering ASSISTANT for Sandefjord Kommune. You surface
evidence and gaps for a human Privacy Officer / Sikkerhetsansvarlig.
- You NEVER make legal compliance judgments, NEVER approve or reject, NEVER
  declare a project compliant/non-compliant.
- You NEVER cite anything outside the EVIDENCE block. If a field has no
  supporting chunk, set evidenceMissing=true and leave the value null — do NOT guess.
- For personalDataCategories / specialCategories / retention: ABSENCE OF EVIDENCE
  IS NOT EVIDENCE OF ABSENCE — flag it as a Gap.
- Every claim must cite ≥1 chunk id that appears under EVIDENCE.
- Source documents may be Norwegian Bokmål; respond in the project UI language.
- All outputs are DRAFTS for human review.
```

- The EVIDENCE block is rendered as `[C1] (Systembeskrivelse.pdf, p.4): "…"` — opaque, mapped internally to chunk UUIDs (reduces conflation; the model sees `[C1]`, not a UUID that looks like English tokens).
- **Hard negatives are repeated at the end of the user message** for local models that follow long system prompts less reliably.
- Cautious framing is enforced _structurally_: `conclusion` is a `Literal` enum with no `compliant` value; the model literally cannot emit a compliance verdict.

`★ Insight ─────────────────────────────────────`
Two design choices do most of the safety work: (1) the `Literal` enum without a "compliant" option makes a forbidden output _unrepresentable_, and (2) the gap-finder is a **separate pass** whose only job is to find what's unsupported — separating "extract" from "critique" beats asking one prompt to do both. Both are cheap, schema-level controls that outperform asking the model nicely.
`─────────────────────────────────────────────────`

---

## 10. Citation & trust architecture

This is the product's reason to exist. Citation is a **hard, verifiable contract**, not a prompt hope.

1. **Stable chunk IDs.** Every chunk gets `id = uuid5(NAMESPACE, f"{project_id}|{document_id}|{chunk_index}")` (deterministic — re-indexing the same file yields the same ID) and a `chunks` Postgres row that is the **single source of truth** the gate checks against.
2. **ID-constrained grounding.** Retrieved chunks become an `EVIDENCE` block of opaque `[Cn]` tokens. The model may only reference IDs present in that block. Pydantic `sourceReferences: list[ChunkRef]` makes grounding a schema obligation.
3. **Deterministic verification gate (mandatory, runs before persist/display).** For each extracted object: parse `sourceReferences[].chunkId`; confirm membership in the retrieval set the model actually saw; split into `verified` / `unverified`; any claim with no verified ref is moved to a `needsReview` bucket with `evidenceMissing=true` and `verificationStatus` (`grounded` | `partial` | `unverified`). A unit test injects a fake `C999` and asserts it is quarantined.
4. **Optional NLI entailment (roadmap hardening).** A multilingual cross-encoder scores `cited_chunk → claim` to catch "real chunk, wrong support" — existence alone is necessary but not sufficient. Norwegian is weaker; sample and tune the threshold.
5. **Friendly rendering.** UI/export maps `Cn → {documentName, page}` so the officer sees `Systembeskrivelse.pdf, p.4`, and can click through to the exact span.

---

## 11. Security, privacy & data hygiene

- **Per-project isolation** at three layers: Postgres (`ProjectScopedRepository` — `project_id` is a non-default ctor arg so a forgotten scope is a `TypeError`, not a leak), Qdrant (dedicated collection per project), MinIO (key prefix).
- **Sensitive-data detection on upload** (the heart of safe handling):
  - **Fødselsnummer / D-nummer** via the exact **Modulo-11** checksum (weights `3,7,6,1,8,9,4,5,2` for _both_ control digits; reject remainder 10; D-nummer = first digit +4; H-nummer and FH-nummer flagged separately). Near-zero false positives vs. a naive 11-digit regex.
  - **Presidio** with a Norwegian-capable NER backend (`NbAiLab/nb-bert-base` or `ltg/norbert3-base`) + hand-written recognizers (Norwegian phone, postnummer, kontonummer, email).
  - **GDPR Art 9 / Art 10** Norwegian keyword lexicon (versioned YAML) with a context anchor (a PERSON or fødselsnummer within ±N tokens) to suppress false positives.
  - Findings persisted to `document_findings`; **CRITICAL findings block cloud embedding + indexing** until a Privacy Officer acknowledges (audited) — so unacknowledged special-category text is never sent to OpenRouter. Display shows masked values only (last 4 + derived year-of-birth) — never the full ID, even to admins.
- **Derived-data deletion.** Deleting a document removes: MinIO original → extracted text → `chunks` rows → Qdrant points → derived analyses/reports (unless archived). Deleting a project additionally **drops the Qdrant collection** (atomic). This demonstrates RAG creates derived data and you control it.
- **Cloud embeddings (MVP default) + pre-embedding PII gate.** Embeddings run on OpenRouter (`text-embedding-3-large`), so chunk text is sent off-box during ingestion. To keep the safe-handling story credible, a **pre-embedding PII gate** runs fødselsnummer / Art-9 / Art-10 detection _before_ any text is sent for embedding, and CRITICAL findings **block cloud embedding + indexing** until a Privacy Officer acknowledges (audited) — unacknowledged special-category text never reaches the cloud. The chat LLM path additionally sends only already-extracted/quoted text the user accepted (gated in config). A local-embedding mode (Ollama `bge-m3`, raw text never leaves the box) is a post-MVP roadmap item (§16 R7).
- **Audit log** of every analysis/acknowledge/edit/export action (`audit_logs`).
- **Retention policy** controls when files, text, vectors and drafts are deleted (roadmap: per-project TTL + manual purge).
- **Human approval** required before export.

---

## 12. Local development environment

Kubernetes manifests in `infra/k8s/` (applied with kustomize via `make k8s-up`), running in a local **kind** cluster (`dpia-ros`). Everything is same-origin behind the `web` nginx (zero CORS). Each service runs in its own pod network namespace, so only host port `8081` is touched (the `web` NodePort 30080, forwarded by kind) — backing services are ClusterIP-internal and resolve over in-cluster DNS using the same bare names (`postgres`, `qdrant`, `redis`, `minio`, `keycloak`, `api`) as the old compose service names, so the `.env` connection strings work unchanged. See `infra/k8s/README.md` for the manifest layout and the compose→k8s mapping.

| Service | Image | Exposure | Notes |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | internal | readiness `pg_isready`; init SQL mounted into `/docker-entrypoint-initdb.d` (runs on fresh PVC) via ConfigMap |
| `qdrant` | `qdrant/qdrant:v1.18.0` | internal | REST + gRPC; TCP readiness probe on 6333 |
| `keycloak` | `quay.io/keycloak/keycloak:26.6` | internal (mgmt 9000) | `start-dev --import-realm`; realm JSON mounted via ConfigMap (realm + public PKCE client + 4 groups + 4 seeded users + `groups` & `aud` protocol mappers); `KC_HEALTH_ENABLED=true` → `/health/ready` probe |
| `redis` | `redis:7-alpine` | internal | arq queue; readiness `redis-cli ping` |
| `minio` + `minio-init` Job | `minio/minio` + `minio/mc` | internal | one-shot Job mounts `infra/minio/init.sh` via ConfigMap, creates the `kommune-docs` bucket idempotently |
| `api` | `python:3.12-slim` build (`dpia-ros-backend:dev`) | internal (proxied by web) | `uvicorn app.main:app`; readiness `/api/health` |
| `worker` | same image | — | `arq app.workers.arq_app.WorkerSettings` |
| `web` | `nginx` build (`dpia-ros-web:dev`) | **http://localhost:8081** (NodePort 30080) | serves built SPA + proxies `/api`, `/oidc` |

**`.env`** (gitignored; ship `.env.example`): `DATABASE_URL=postgresql+asyncpg://…`, `QDRANT_URL`, `REDIS_URL`, `MINIO_*`, `KEYCLOAK_*`, `OPENROUTER_API_KEY`, `LLM_MODEL` (default `anthropic/claude-sonnet-4.5`), `EMBED_MODEL` (default `openai/text-embedding-3-large`), `EMBED_DIM` (3072), `APP_SECRET_KEY`, `CORS_ORIGINS`. `.env` is loaded into the `dpia-secrets` Secret by `make k8s-up` (regenerated each run), and the api additionally overrides `KEYCLOAK_PUBLIC_URL`/`CORS_ORIGINS` to `http://localhost:8081`. (No `OLLAMA_*` vars in the MVP — added by the post-MVP local mode.)

**First run:** `cp .env.example .env` (set `OPENROUTER_API_KEY`) `&& make k8s-up` → Keycloak imports realm, MinIO Job creates bucket, Postgres runs init SQL → log in as a seeded user → the "HSO AI Assistant" project with Norwegian sample docs is ready. (No model-pull/GPU step — chat + embeddings are served by OpenRouter.)

---

## 13. Frontend architecture

- **Toolchain:** Vite 6 + React 19 + TS (strict); React Router 7 (data mode) for routes/loaders; TanStack Query v5 for all server state (reads via `useQuery`, mutations + `onSuccess` invalidation, job-status polling via `refetchInterval`); **auth = credentialed `fetch`** (BFF cookie — no client-side tokens, no `oidc-client-ts`).
- **UI:** shadcn/ui + Tailwind; TanStack Table v8 for the editable ROS register; `react-hook-form` + `zod` for the profile form; Sonner toasts.
- **Routes (the 5 pages):** `/` Dashboard · `/projects/:id/documents` Upload · `/projects/:id/analysis` AI Analysis (+chat drawer) · `/projects/:id/ros` ROS Register · `/projects/:id/export` Export — plus `/login`, `/callback`.
- **Citation-aware rendering:** `react-markdown` + `remark-gfm` + `rehype-sanitize` (non-negotiable — untrusted LLM output) + a custom `remarkCitations` plugin turning `[Cn]` tokens into clickable superscript badges that open a Sheet showing the chunk text + page. (rehype-sanitize schema extended to allow the citation `<a>` data-attrs.)
- **Upload UX:** `react-dropzone` + `axios` (`onUploadProgress` — `fetch` can't report upload progress), per-file progress + retry, then poll the ingestion job; accept `.pdf,.docx,.xlsx,.md,.png`; show extraction/index/PII-detection as separate stages.
- **Chat:** SSE streaming from FastAPI (`StreamingResponse`); accumulate tokens, render live with markdown+citations; "context documents" chips per turn; stop-generation button. (nginx: `proxy_buffering off;` + `X-Accel-Buffering: no`.)
- **ROS table:** debounced (600 ms) auto-save via `useMutation`, optimistic update + rollback, derived `score = likelihood × impact` shown live.
- **Typed client:** FastAPI exports `openapi.json` → `openapi-typescript` → typed fetch + `zod` schemas (keeps wire format and Pydantic models from drifting).
- **Model picker:** project settings expose an OpenRouter model selector populated from the live catalog (filtered to structured-output-capable models, with cost/context hints); the choice drives all AI stages and is shown in the Analysis header.

---

## 14. Testing & evaluation strategy

- **Unit tests:** parsers (PDF/DOCX/XLSX/MD) · PII detectors (fødselsnummer mod11 incl. D/H-nummer, Art 9 lexicon) · DPIA rules engine (criteria → conclusion) · chunking · citation gate (fake `C999` quarantined) · risk-score math.
- **Integration tests:** upload → ingest → query → extract → screen, against the real compose stack (testcontainers or a `make test-e2e` profile). RBAC tests (404 on non-membership, 403 on wrong role).
- **RAG eval harness (post-MVP, the credibility layer):**
  - **Ragas 0.2** for directional metrics (faithfulness, answer relevancy, context precision) — judge via a **strong cloud model on OpenRouter**, never the same local model under test (avoids self-preference bias). Trend-only signal.
  - **Custom deterministic harness** (the hard gates): **citation-existence rate** (every cited ID ∈ retrieval set), **NLI entailment pass-rate** (cited chunk entails claim), **claim-coverage**, **retrieval recall@5/@10** vs. gold chunk IDs, **extraction field accuracy** (scalar exact-match + list-F1) and **gap-detection recall** vs. a gold profile.
  - **Golden set:** ~40 items, half English / half Norwegian Bokmål, spanning factoid / gap-detection / comparison / multi-hop, version-locked to the chunker config.

---

## 15. MVP delivery — phased

> The MVP is one demoable vertical slice for the **HSO AI Assistant** scenario (§16). Phases are ordered by dependency; later phases assume earlier acceptance criteria hold.

### Phase 0 — Repo skeleton, infra, and CI

**Goal:** `make k8s-up` brings up every backing service healthy in a local kind cluster; app boots and answers `/api/health`.

- [x] Monorepo layout (Appendix A): `backend/`, `frontend/`, `infra/`, `knowledge-base/`, `sample-data/`, `eval/`, `docs/`.
- [x] `knowledge-base/` scaffold (per-area dirs + `README.md` noting source + licence + last-curated date) — content curated in later phases (NSM in Phase 6, templates/routines thereafter).
- [x] `infra/k8s/` manifests (kind cluster config + kustomize) with postgres, qdrant, redis, minio (+init Job), keycloak (+realm import ConfigMap), api, worker, web (nginx) — Deployments + Services + PVCs + readiness/liveness probes. **No Ollama/GPU in the MVP stack**; OpenRouter serves chat + embeddings (Ollama returns in §16 R7).
- [x] `.env.example` + gitignored `.env`; `Makefile`/`justfile` for common commands.
- [x] Backend: FastAPI `create_app()` factory, `pyproject.toml`, `app/core/{config,logging,exceptions}`, `/api/health`; OpenRouter client wired (chat + `/v1/embeddings`) and confirmed reachable on boot.
- [x] Frontend: Vite + React 19 + TS scaffold, Tailwind + shadcn init, React Router 7 shell, nginx dev/proxy.
- [x] CI: lint (ruff/mypy, eslint/tsc), `pytest`, build images.
- [x] `README.md` quickstart.

**Deliverables:** running stack; healthy services; empty-but-booting app.
**Status (2026-07-07):** scaffold complete. Verified offline → ruff/mypy/pytest green, `tsc`/`eslint`/`vite build` green, `kubectl kustomize infra/k8s` renders valid manifests, all JSON/YAML valid, gitleaks clean. Runtime moved from docker-compose to kind (local Kubernetes) — `make k8s-up` is the single bring-up command. **Remaining:** the live `make k8s-up` smoke test (needs the user's `OPENROUTER_API_KEY` and a first image build).
**Acceptance criteria:**
- `make k8s-up` reaches all pods `Running`/ready within ~3 min on a fresh clone (no GPU / multi-GB model-pull step).
- `curl http://localhost:8081/api/health` → 200 (incl. an OpenRouter reachability sub-check); the SPA loads at `http://localhost:8081`.
- MinIO bucket `kommune-docs` exists; Keycloak realm `sandefjord` imported; `OPENROUTER_API_KEY` is set and the `/v1/chat/completions` + `/v1/embeddings` endpoints respond.
**Risks:** Keycloak realm-import-only-on-first-start (document the PVC-wipe re-seed step — `make k8s-clean`); OpenRouter API-key / rate-limit / outage (local Ollama mode is the post-MVP fallback, §16 R7).

### Phase 1 — Auth & RBAC (BFF + Keycloak)

**Goal:** a real user logs in via Keycloak and is authorized per-project; SPA never holds tokens.

- [x] FastAPI: Starlette `SessionMiddleware` (signed httpOnly `SameSite=Lax` cookie), `/auth/{login,callback,logout,me}`, PyJWT `PyJWKClient` JWKS validation, server-side refresh.
- [x] Keycloak realm JSON: realm `sandefjord`, public PKCE client `dpia-bff`, 4 groups, 4 users, `groups` + `aud` (`dpia-api`) protocol mappers.
- [x] Domain: `users`, `projects`, `project_members`; `get_current_user`, `get_project_context`; group→role mapping; **404-not-403** on non-membership.
- [x] SPA: redirect-to-login on 401, credentialed fetch wrapper, `/login` + `/callback`.
- [x] Tests: login flow; RBAC allow/deny; non-member → 404.

**Acceptance criteria:**
- Log in as each seeded user; `/auth/me` returns correct global role.
- A user not on a project gets 404 (not 403) for that project's endpoints; a member with the wrong role gets 403 on mutations.
- No token appears in browser `localStorage`/JS (BFF confirmed).
**Risks:** `groups`/`aud` mappers missing ⇒ silent RBAC/JWT break (test explicitly); `localhost` vs `127.0.0.1` in Keycloak redirect URIs.

### Phase 2 — Projects, upload & object storage

**Goal:** create a project, upload Norwegian sample docs to MinIO, list/delete them.

- [ ] `POST/GET/PATCH/DELETE /projects`; `POST/GET/DELETE /projects/{id}/documents` (multipart); membership seeding (owner auto-added).
- [ ] MinIO client (`aioboto3`); store under `projects/{projectId}/{documentId}{ext}`; persist `documents` row + `sha256`.
- [ ] Frontend: Dashboard (create project), Upload center (dropzone + progress + retry), document list with delete.
- [ ] Project-create also creates the Qdrant collection `chunks_{projectId}`; project-delete cascades MinIO prefix + rows + `DROP` collection.

**Acceptance criteria:**
- Create the "HSO AI Assistant" project; upload all 7 sample docs; they appear with size/sha.
- Deleting a document removes the MinIO object and the `documents` row; deleting a project removes everything and drops the Qdrant collection.
- Upload progress is shown per file; RBAC enforced on every endpoint.
**Risks:** large-file multipart; MinIO bucket re-create idempotency.

### Phase 3 — Ingestion pipeline + hybrid RAG + PII detection

**Goal:** an uploaded doc is parsed, chunked, embedded, PII-scanned, and searchable with citations; CRITICAL findings block indexing until acknowledged.

- [ ] `arq` worker: `ingest_document` job (parse → detect → chunk → embed → upsert → status=ready); `jobs` table + `/jobs/{id}` polling.
- [ ] Parsers: PDF (**Docling through `docling-slim[format-pdf,models-local,feat-ocr-rapidocr-onnx]`** — local page/layout/reading-order/table extraction + OCR; export page-aware structured content for chunking), with `pypdf` only as a clearly labelled text-only degraded fallback for born-digital PDFs. Resolve PyTorch from its CPU-only package index for the Linux backend. Preserve `{parser, parserVersion, extractionQuality}` in document metadata and never fall back silently. DOCX (`python-docx`, body-order, headings), XLSX (`openpyxl` read-only/data-only), MD (frontmatter + `MarkdownHeaderTextSplitter`), images (Tesseract `nor+eng` + vision caption). Do not install or invoke PyMuPDF/PyMuPDF4LLM. Pin Docling code and model-artifact versions and retain their license notices.
- [ ] Chunking: structural split + `RecursiveCharacterTextSplitter` (800 tok / 150 overlap, `tiktoken`); metadata `{documentId, page, sectionTitle, sectionPath, classification, chunkIndex}`; deterministic `uuid5` IDs.
- [ ] Embeddings: `openai/text-embedding-3-large` (3072) via OpenRouter `/v1/embeddings` (assert dims); `index_manifest` row. _Local `bge-m3`/Ollama embeddings are a post-MVP roadmap mode (§16 R7) — different dim ⇒ re-index on switch._
- [ ] Qdrant: dense (text-embedding-3-large) + server-side BM25 (`modifier=IDF`, text in payload); `query_points` hybrid (RRF), payload-filtered to the project collection.
- [ ] **PII detection (pre-embedding gate):** fødselsnummer/D-nummer mod11, Presidio (nb NER) + custom recognizers, Art 9/10 lexicon → `document_findings`; runs **before** any text is sent to OpenRouter for embedding; classification banner; **CRITICAL blocks cloud embedding + indexing** until acknowledged; `/acknowledge` (audited).
- [ ] `GET /documents/{docId}/chunks/{chunkId}` drill-down.
- [ ] Tests: Docling parser fixtures for a born-digital PDF with a table and a scanned Norwegian PDF requiring OCR; assert page-aware citations and extraction metadata; assert the dependency lock contains no PyMuPDF/PyMuPDF4LLM package. Cover the explicitly degraded `pypdf` fallback; parser unit tests for Norwegian DOCX headings; mod11 incl. D/H-nummer; hybrid retrieval recall smoke test.

**Acceptance criteria:**
- Upload a doc with a planted fødselsnummer → flagged CRITICAL → **not sent to OpenRouter for embedding** and not indexed until acknowledged; after ack, embedded + indexed.
- A natural-language query returns ranked chunks with `[doc, page]` citations, scoped strictly to that project.
- Re-uploading the same file overwrites (deterministic IDs), not duplicates.
- PyMuPDF and PyMuPDF4LLM are absent from the direct and transitive dependency lock; a `pypdf` fallback result is visibly marked as degraded.
**Risks:** Docling model-artifact size, license drift, first-run downloads, and ML dependency weight (mitigation: use modular extras + CPU-only wheels, approve/pin/scan artifacts, and pre-bundle them); OCR confidence on scanned pages; embedding-dim drift (assert + manifest).

### Phase 4 — Profile extraction (the first "wow")

**Goal:** one "Analyze" button produces the structured `ProjectProfile` with citations + a gap list.

- [ ] `extract_profile` agent: retrieve representative chunks, render EVIDENCE (`[Cn]`), LLM with `response_model=ProjectProfile` (cloud default), citation gate, persist `project_profiles`.
- [ ] Two-pass: Pass A extract + Pass B red-team gap-finder (`list[Gap]` + open questions).
- [ ] `POST /projects/{id}/analyze` → job; `GET /projects/{id}/profile`.
- [ ] Frontend: Analysis page renders profile with clickable citations + a "Missing information" panel + "Open questions".
- [ ] Tests: citation gate quarantines `C999`; gap-finder surfaces planted missing fields.

**Acceptance criteria:**
- On the HSO project, "Analyze" returns systems (Azure OpenAI, Blob, AI Search, Entra ID), processors (Microsoft), personal-data categories, special-category flags, and a non-empty `missingInfo` (retention, data location, sub-processors, logging…), each grounded in cited chunks.
- Every displayed claim has a clickable citation; unverifiable claims are visibly flagged, not presented as fact.
**Risks:** model emits plausible-but-wrong citations ⇒ gate + visible flag mitigate; OpenRouter structured-output reliability ⇒ Response Healing + instructor retries.

### Phase 5 — DPIA screening

**Goal:** a reproducible, cited DPIA screening with a cautious conclusion.

- [ ] Deterministic rules engine over the 9 Datatilsynet criteria + Art 35(3) hard triggers, fed by the profile + findings; criteria inspectable & overridable (override logged).
- [ ] `screen_dpia` agent wraps evidence lookup per criterion; `POST /projects/{id}/dpia-screening`; `GET .../screening`.
- [ ] Cautious framing (Literal `conclusion` enum, no "compliant"); Norwegian rationale text.
- [ ] Frontend: Screening page — triggered criteria with evidence chips, conclusion badge, "needs review" framing.
- [ ] Tests: criteria→conclusion truth table (≥2 → REQUIRED; Art 35(3) → REQUIRED; 1 → LIKELY; 0 → NOT_INDICATED).

**Acceptance criteria:**
- The HSO project screens to a "likely/required" conclusion citing health-data + new-tech + systematic-logging indicators, with cautious wording and no compliance verdict.
- Flipping a criterion re-scores live; the override is in the audit log.
**Risks:** "large scale" has no fixed number ⇒ expose the threshold as a heuristic with a UI note.

### Phase 6 — ROS risk register generator

**Goal:** an editable ROS table generated per NSM principle.

- [ ] **Source & transcribe NSM Grunnprinsipper v2.1** from the official `nsm.no/gp-ikt` source (PDF/XLSX) into `knowledge-base/nsm/grunnprinsipper.yaml` — all **21 principles / 118 measures** across IDENTIFY · PROTECT & MAINTAIN · DETECT · RESPOND & RECOVER, plus the official ISO/IEC 27002:2022 crosswalk. Version + date-stamp the file; record the source URL. _(Planned manual-curation task — offline/local-first ⇒ no runtime fetch.)_
- [ ] Digdir *internkontroll* overlay + (conditional) Helsedirektoratet *Normen* rows, emitted only when health/omsorg data is detected.
- [ ] `generate_ros` agent: one risk row per applicable principle, `score` computed server-side, `status='draft'`; `POST /projects/{id}/ros`; `GET/PATCH .../risks/{riskId}`.
- [ ] Frontend: TanStack Table ROS register — editable likelihood/impact/treatment/owner/status, live score, debounced auto-save, citation badges.
- [ ] Tests: never auto-satisfies a control; score math; principle coverage.

**Acceptance criteria:**
- ROS generation produces rows referencing NSM principle IDs (e.g. access control, logging, supplier-chain) each with a citation; the officer can edit any cell and the score updates and persists.
- No risk row is auto-marked "resolved".
**Risks:** NSM YAML curation effort (manual transcription from the official source); Norwegian compound tokenization in BM25.

### Phase 7 — Checklist comparison, Markdown export & demo polish

**Goal:** gap report vs. checklist + one-click Markdown export; demo-ready.

- [ ] `compare_checklists` agent: Complete/Missing vs. DPIA/ROS/supplier checklist + supplier follow-up questions; `POST /projects/{id}/checklist`.
- [ ] `draft_report` agent: Markdown bundle (screening + ROS + checklist + summary), inline citations; `POST /projects/{id}/report`, `GET .../export/markdown`.
- [ ] Frontend: Export page (one click per artifact), Markdown preview with citations; SOPHISTICATED `rehype-sanitize`.
- [ ] Audit-log page; role labels; risk/severity badges; "not legal advice" disclaimer footer.
- [ ] Seed: the 7 synthetic Norwegian docs in `sample-data/`; demo script (§16); architecture diagram; `README` + interview talking points.

**Acceptance criteria:**
- "Export" downloads a coherent Markdown report where every claim cites a source and the "missing information" section is populated.
- The full demo (§16) runs end-to-end against the seeded HSO project without errors.
**Risks:** export citation footnote format; sanitization vs. citation data-attrs.

---

## 16. Post-MVP roadmap (phased vision)

- [ ] **R1 — RAG evaluation harness.** Ragas 0.2 + custom deterministic citation/extraction/recall harness + ~40-item bilingual golden set; gate prompt/model changes on regression thresholds (§14).
- [ ] **R2 — DOCX & PDF export.** Server-side `python-docx` + WeasyPrint; backend owns citation footnotes.
- [ ] **R3 — Citation NLI hardening.** Multilingual cross-encoder entailment gate for "real chunk, wrong support"; sample/tune threshold on Bokmål.
- [ ] **R4 — Advanced ingestion.** Robust Excel (merged cells, multi-sheet profiles), scanned-PDF OCR pipeline, diagram vision-captioning quality, de-compounding for Norwegian BM25.
- [ ] **R5 — Deployment & production readiness.** The local runtime has migrated from docker-compose to Kubernetes (kind cluster `dpia-ros`, manifests in `infra/k8s/`). Remaining production hardening: Keycloak `start` prod mode, TLS via an Ingress controller (Caddy/Traefik), backup/restore of the 5 PVCs, secrets via a real secret store (not the dev `dpia-secrets` from `.env`), nginx prod config, `openapi.json` codegen in CI, retention/TTL purge job, observability (structlog + traces).
- [ ] **R6 — i18n + ID-porten federation prep.** NO/EN UI toggle (i18n); Keycloak OpenID Federation 1.0 toward a future ID-porten integration (the documented path from the municipality's real SSO).
- [ ] **R7 — Local/offline & privacy-hardened mode (Ollama).** Wire the Ollama backend into the provider abstraction for both chat (`qwen2.5`/`qwen3`) and embeddings (`bge-m3`, 1024-dim) so the tool runs fully air-gapped with raw text never leaving the box (restores the original §11 "local-only" posture). Because `bge-m3` differs in dimension from the cloud `text-embedding-3-large`, switching a project to local embeddings is a **re-index event** (detected via `index_manifest`, surfaced in the UI). Adds the `ollama` + `ollama-init` compose services back (GPU via `nvidia-container-toolkit`, CPU override documented).

---

## 17. Risks, assumptions & open questions

**Assumptions**
- An **OpenRouter API key is available** — required for both chat and embeddings in the MVP (a fully-local Ollama mode is the post-MVP fallback, §16 R7). No GPU is needed for the MVP.
- The NSM Grunnprinsipper v2.1 measures are transcribed into YAML by hand from the official source (offline/local-first ⇒ no runtime fetch).

**Top risks**
- **Citation fabrication** by weaker/local models → mitigated by the deterministic gate + cloud default for high-stakes stages + visible `unverified` flags.
- **Embedding-model drift** (dim mismatch silently corrupts recall) → asserted dims + `index_manifest` + re-index detection.
- **Keycloak realm re-seed** only on first start → documented volume-wipe step.
- **Parser licensing** → PyMuPDF/PyMuPDF4LLM are excluded; pin and scan Docling, its model artifacts, and the BSD-licensed `pypdf` fallback, and retain required third-party notices.
- **Norwegian NER / BM25 / embedding quality** → `text-embedding-3-large` (multilingual) + server-side BM25 + eval set to measure.

**Decisions resolved (2026-07-03, updated 2026-07-13)**
1. **Chat model** — **user-selectable** at runtime from OpenRouter's structured-output-capable catalog (default `anthropic/claude-sonnet-4.5`), chosen per project. OpenRouter is the **sole MVP path**; local Ollama chat is deferred to the post-MVP roadmap (§16 R7). (See §3, §8.)
2. **PDF parser** — **Docling via modular `docling-slim` (MIT)** is primary for local layout-, table-, and OCR-aware extraction. Install only its PDF, local-model, and RapidOCR/ONNX extras and use CPU-only PyTorch wheels in the Linux backend. `pypdf` (BSD-3-Clause) is retained only as an explicit text-only degraded fallback for born-digital PDFs. PyMuPDF/PyMuPDF4LLM are excluded so the product does not depend on their AGPL-or-commercial licensing path. Docling model artifacts are pinned and reviewed separately because their licenses are not implied by the code license. (See §3, Phase 3.)
3. **NSM YAML** — **explicit planned task** in Phase 6: source + transcribe v2.1 from `nsm.no/gp-ikt`.
4. **Fødselsnummer masking** — **last-4 + derived year-of-birth** (default).
5. **Normen (health) rows** — **conditional on health-data detection** (default).
6. **Embeddings + provider scope (2026-07-04)** — **OpenRouter for both chat _and_ embeddings**, replacing the earlier "local `bge-m3`/Ollama" design. Embeddings: `openai/text-embedding-3-large` (3072-dim) via OpenRouter `/v1/embeddings`. A **pre-embedding PII gate** sends only PII-cleared text to the cloud; CRITICAL findings block embedding until acknowledged. **Ollama is removed from the entire MVP** (Phases 0–7) and re-introduced as a post-MVP local/offline mode (§16 R7); because the local embedding model (`bge-m3`, 1024-dim) differs from the cloud one, switching a project to local is a re-index event. This _supersedes_ the prior "embeddings always local `bge-m3`" stance and the Phase 0 GPU assumption. (See §3, §4, §8, §11, §12, Phase 0, Phase 3.)

---

## Appendix A — Repository layout

```
ROSAndDPIARAGAgent/
  Project.txt
  IMPLEMENTATION_PLAN.md          ← this file
  README.md
  Makefile
  backend/
    pyproject.toml  alembic.ini  alembic/
    app/
      main.py  core/  db/  domain/  schemas/  repositories/  services/
      ai/{providers,embeddings,retrieval,prompts,agents,orchestrator.py}
      api/{deps.py, v1/}  workers/  tests/
  frontend/
    package.json  vite.config.ts  src/{api, routes, components, features, lib}
  infra/
    k8s/  nginx/  keycloak/realm-sandefjord.json  initdb/*.sql  minio/init.sh
  knowledge-base/
    gdpr/  datatilsynet/  nsm/grunnprinsipper.yaml  digdir/  templates/  routines/
  sample-data/        ← 7 synthetic Norwegian docs for the HSO scenario
  eval/{golden/, run_ragas.py, test_citations.py, test_extraction.py, test_retrieval.py}
  docs/               ← architecture diagram, demo script, interview talking points
```

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| **DPIA** | Data Protection Impact Assessment (GDPR Art 35); *vurdering av personvernkonsekvenser* |
| **ROS** | Risk- og sårbarhetsanalyse (risk & vulnerability assessment) |
| **Datatilsynet** | Norwegian Data Protection Authority |
| **NSM Grunnprinsipper** | NSM basic principles for ICT security (v2.1: 21 principles / 118 measures) |
| **Digdir** | Norwegian Digitalisation Agency (internkontroll / governance) |
| **Normen** | Helsedirektoratet's norm for information-security risk management (health/omsorg) |
| **Behandlingskatalog** | Record of processing activities (GDPR Art 30) |
| **Fødselsnummer / D-nummer** | Norwegian national ID numbers (11-digit, Mod-11 checksum) |
| **BFF** | Backend-for-frontend (server holds tokens; SPA uses a cookie) |
| **RRF** | Reciprocal Rank Fusion (fuses dense + BM25 result lists) |

## Appendix C — Key references

Datatilsynet DPIA guidance · WP248 rev.01 (9 criteria) · GDPR Art 5/6/9/30/32/35/36 (`gdpr-info.eu`) · NSM Grunnprinsipper for IKT-sikkerhet v2.1 (`nsm.no/gp-ikt`) · Digdir internkontroll · Helsedirektoratet Normen · Qdrant hybrid queries (Universal Query API, RRF) · Ollama (`/api/embed`, `/api/chat`, structured outputs) · OpenRouter (model catalog, structured outputs, Response Healing) · `instructor` + Pydantic v2 · Keycloak 26 (realm import, federation) · PyJWT `PyJWKClient` · arq (Redis) · Docling (MIT) / pypdf (BSD-3-Clause) / python-docx / openpyxl · Presidio + `NbAiLab/nb-bert-base` · Ragas 0.2. _(Full URL list in the research digest.)_
