"""EVIDENCE block renderer (plan §9, §10.2).

Turns retrieved chunks into the opaque `[Cn] (documentName, p.X): "…"` block the
LLM sees, plus the `Cn -> EvidenceEntry` token map the gate resolves against.

Per §9 the model sees `[C1]`, never the raw UUID — opaque tokens reduce conflation
with English-looking UUID strings and make prompt-injection "cite chunk <uuid>"
harder.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


def _tok(n: int) -> str:
    return f"C{n + 1}"


@dataclass(frozen=True)
class EvidenceEntry:
    token: str
    chunk_id: UUID
    document_id: UUID | None
    document_name: str | None
    page: int | None
    section_title: str | None
    text: str


@dataclass(frozen=True)
class EvidenceBlock:
    """Rendered EVIDENCE block text + the token->entry map the gate resolves."""

    text: str
    token_map: dict[str, EvidenceEntry]


def render_evidence(chunks: list[dict]) -> EvidenceBlock:
    """Render retrieved chunks as the opaque EVIDENCE block.

    `chunks` is the shape returned by `ai.store.qdrant.hybrid_query`:
        [{chunk_id, document_id, page, section_title, text, score}, ...]
    Order is preserved — the model is told to cite tokens in the order given.
    """
    lines: list[str] = []
    token_map: dict[str, EvidenceEntry] = {}
    for i, c in enumerate(chunks):
        cid = c.get("chunk_id")
        if cid is None:
            continue
        tok = _tok(i)
        document_id = _to_uuid(c.get("document_id"))
        token_map[tok] = EvidenceEntry(
            token=tok,
            chunk_id=UUID(str(cid)),
            document_id=document_id,
            document_name=c.get("document_name"),
            page=c.get("page"),
            section_title=c.get("section_title"),
            text=(c.get("text") or "").strip(),
        )
        page = c.get("page")
        doc = c.get("document_name") or c.get("section_title") or "document"
        loc = f"p.{page}" if page is not None else "p.?"
        text = (c.get("text") or "").strip()
        lines.append(f'[{tok}] ({doc}, {loc}): "{text}"')
    return EvidenceBlock(text="\n".join(lines), token_map=token_map)


def _to_uuid(v) -> UUID | None:
    if v is None:
        return None
    return UUID(str(v))
