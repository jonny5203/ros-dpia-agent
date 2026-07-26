from __future__ import annotations
from app.ingestion.parser.base import Parser
from app.ingestion.types import ParsedDocument, ParsedSection


class MarkdownParser(Parser):
    name = "langchain-md"
    version = "langchain-text-splitters>=0.3"

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        from langchain_text_splitters import MarkdownHeaderTextSplitter
        text = data.decode("utf-8", errors="replace")
        # Strip YAML frontmatter first if present
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                text = text[end + 4 :]
        splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
        )
        docs = splitter.split_text(text)
        sections = [
            ParsedSection(
                text=d.page_content,
                section_title=d.metadata.get("h3") or d.metadata.get("h2") or d.metadata.get("h1"),
                section_path=" > ".join(
                    v for v in (d.metadata.get("h1"), d.metadata.get("h2"), d.metadata.get("h3")) if v
                ) or None,
            )
            for d in docs
        ]
        return ParsedDocument(sections=sections, parser=self.name,
                              parser_version=self.version)
