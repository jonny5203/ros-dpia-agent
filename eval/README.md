# eval

RAG evaluation harness (post-MVP, roadmap R1 — see `IMPLEMENTATION_PLAN.md` §14).

Two layers:

1. **Ragas 0.2** — directional metrics (faithfulness, answer relevancy, context
   precision). The judge is a strong cloud model on OpenRouter, never the model
   under test.
2. **Custom deterministic harness** (the hard gates) — citation-existence rate,
   NLI entailment pass-rate, claim-coverage, retrieval recall@5/@10, extraction
   field accuracy, gap-detection recall.

The bilingual golden set (~40 items, EN + Norwegian Bokmål) lives in `golden/`
and is version-locked to the chunker config.

Planned files: `run_ragas.py`, `test_citations.py`, `test_extraction.py`,
`test_retrieval.py`. Empty for Phase 0.
