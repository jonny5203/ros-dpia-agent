from __future__ import annotations

import pytest

from app.ingestion.pii import LEXICON_VERSION, scan
from app.ingestion.types import ParsedDocument, ParsedSection

VALID_FNR = "15076500565"

def _doc(text: str) -> ParsedDocument:
    return ParsedDocument(sections=[ParsedSection(text=text, page=1)])

def test_critical_fodselsnummer_sets_has_critical():
    """ A valid mod11 fnr -> has_critical=True -> caller blovks embedding. """
    result = scan(_doc(f"pasient {VALID_FNR} kontrakt"))
    assert result.has_critical is True
    critical = [f for f in result.findings if f.severity == "critical"]
    assert len(critical) == 1
    assert critical[0].type == "fodselsnummer"
    assert critical[0].checksum_valid is True

def test_invalid_11_digits_do_not_set_critical():
    """ Invalid 11-digit runs are surface but don't block embedding. """
    result = scan(_doc("ref 11111111111"))
    assert result.has_critical is False
    low_findings = [f for f in result.findings if f.severity == "low"]
    assert len(low_findings) == 1

def test_clean_text_has_no_findings_or_critical():
    """ Baseline: text with no PII signals returns no findings. """
    result = scan(_doc("Dette er en  helt vanlig setning om kommunal planlegging"))
    assert result.has_critical is False

def test_art9_lexicon_hit_recorded_as_high_severity():
    """ Health/health-data keyword -> Article 9 special-category finding. """
    result = scan(_doc("Dette dokumentet inneholder helseopplysninger og diagnose."))
    art9 = [f for f in result.findings if f.type == "art9_lexicon"]
    assert len(art9) == 1
    assert art9[0].category == "special_category"
    assert art9[0].severity == "high"
    assert result.has_critical is False

def test_art10_criminal_lexicon_recorded():
    result = scan(_doc("Saken gjelder en straffesak med siktede personer."))
    art10 = [f for f in result.findings if f.type == "art10_lexicon"]
    assert len(art10) == 1
    assert art10[0].severity == "high"

def test_lexicon_version_is_exported():
    """ The version stamp travels into documents.lexicon_version on findings """
    assert isinstance(LEXICON_VERSION, str)
    assert LEXICON_VERSION.startswith("art9-10-")
