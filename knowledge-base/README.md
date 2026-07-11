# Knowledge Base (source area A)

The permanent, **bundled, versioned, offline-capable** regulatory knowledge base
that makes the tool credible rather than hand-wavy. Local-first ⇒ **no runtime
fetches** — everything here is committed to the repo.

Each subdirectory has its own `README.md` noting: **source URL · licence ·
version · last-curated date**. Content is curated incrementally, per
`IMPLEMENTATION_PLAN.md` §5:

| Area             | Curated in phase | Status     |
|------------------|------------------|------------|
| `gdpr/`          | reference        | pending    |
| `datatilsynet/`  | Phase 5 (DPIA)   | pending    |
| `nsm/`           | Phase 6 (ROS)    | placeholder (`grunnprinsipper.yaml`) |
| `digdir/`        | Phase 6 (ROS)    | pending    |
| `templates/`     | Phase 7          | pending    |
| `routines/`      | Phase 7          | pending    |

> The 9 Datatilsynet DPIA screening criteria and the 21 NSM Grunnprinsipper /
> 118 measures are transcribed **by hand** from official sources and date-
> stamped. Never auto-fetched at runtime.
