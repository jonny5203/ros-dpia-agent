from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.ingestion.types import Finding, ParsedDocument

logger = logging.getLogger(__name__)

LEXICON_VERSION = "art9-10-v1"

_ART9_HINTS = {
    "helseopplysning", "pasient", "diagnose", "psykiatr", "generisk",
    "biometrisk", "etnisk", "religion", "seksuell", "politisk",
}
_ART10_HINTS = {
    "straffesak", "domfelt", "siktet", "kriminell",
}

def _mod11_digits(text: str) -> list[tuple[str, int, int, bool]]:
    """
        Find and validate Norwegian fødselsnummer/D-nummer via mod11.
        Returns (match, start, end, checksum_valid). Covers D-nummer /first digit +40)
        and H-nummer (3rd digit +40) which share the mod11 algorithm.
    """
    out: list[tuple[str, int, int, bool]] = []
    weights1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
    weights2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    for m in re.finditer(r"\b\d{11}\b", text):
        digits = [int(c) for c in m.group(0)]
        c1 = sum(w * d for w, d in zip(weights1, digits[:9], strict=True)) % 11
        ctrl1 = 0 if c1 == 0 else 11 - c1
        ok1 = ctrl1 == digits[9]
        c2 = sum(w * d for w, d in zip(weights2, digits[:10], strict=True)) % 11
        ctrl2 = 0 if c2 == 0 else 11 - c2
        ok2 = ctrl2 == digits[10]
        valid = ok1 and ok2 and c1 != 1 and c2 != 1
        out.append((m.group(0), m.start(), m.end(), valid))
    return out

@dataclass
class ScanResult:
    findings: list[Finding]
    has_critical: bool

def scan(parsed: ParsedDocument) -> ScanResult:
    """
        Run the pre-embedding PII over a parsed document.

        Critical = a *valid-mod11* fødselsnummber/D-nummer. Invalid 11-digit runs
        are logged low/medium (probably nor reald IDs) but still surfaced so an
        officer can decide. This ordering means NO text leaves for Openrouter
        until the caller has checked has_critical.
    """
    findings: list[Finding] = []
    full = "\n".join(s.text for s in parsed.sections)

    fnr = _mod11_digits(full)
    valid = [(s, e) for _, s, e, v in fnr if v]
    invalid = [(s, e) for _, s, e, v in fnr if not v]

    if valid:
        findings.append(Finding(
            type="fodselsnummer",
            category="personal",
            severity="critical",
            count=len(valid),
            sample_offsets=valid[:5],
            checksum_valid=True,
        ))

    if invalid:
        findings.append(Finding(
            type="fodeselsnummer_invalid",
            category="personal",
            severity="low",
            count=len(invalid),
            sample_offsets=invalid[:5],
            checksum_valid=False,
        ))

    try:
        from presidio_analyzer import AnalyzerEngine

        # AnalyzerEngine() triggers spaCy auto-download of en_core_web_lg when
        # the model isn't installed. spaCy's downloader calls sys.exit(1) on
        # failure (e.g. no pip in the venv), which raises SystemExit — a
        # BaseException that `except Exception` won't catch. So we catch
        # BaseException here, log, and skip NER. In production, install the
        # model in the image so this path isn't hit.
        analyzer = AnalyzerEngine()

        results = analyzer.analyze(
            text=full,
            language="en",
            entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION"],
            return_decision_process=False,
        )

        if results:
            findings.append(Finding(
                type="presidio_ner",
                category="personal",
                severity="medium",
                count=len(results),
                sample_offsets=[(r.start, r.end) for r in results[:5]],
            ))
    except BaseException as exc:
        # BaseException (not Exception) because spaCy's downloader raises
        # SystemExit on failure, which we must not let propagate.
        logger.warning("Presidio unavailable, skipping NER: %s", exc)

    low = full.lower()
    art9_hits = [w for w in _ART9_HINTS if w in low]
    if art9_hits:
        findings.append(Finding(
            type="art9_lexicon",
            category="special_category",
            severity="high",
            count=len(art9_hits),
            sample_offsets=[],
        ))
    art10_hits = [w for w in _ART10_HINTS if w in low]
    if art10_hits:
        findings.append(Finding(
            type="art10_lexicon",
            category="special_category",
            severity="high",
            count=len(art10_hits),
            sample_offsets=[],
        ))
    has_critical = any(
        f.severity == "critical" for f in findings
    )

    return ScanResult(findings=findings, has_critical=has_critical)
