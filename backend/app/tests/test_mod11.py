"""Mod-11 fødselsnummer validation tests (acceptance §447).

The numbers below are NOT real people's IDs. The fødselsnummer is a publicly-
known teaching example; the D-nummer and H-nummer were brute-force discovered
to pass the mod11 algorithm. None correspond to actual individuals.
"""

from __future__ import annotations

from app.ingestion.pii import _mod11_digits

# Valid fødselsnummer (control digits pass mod11). Publicly-known teaching number.
VALID_FNR = "15076500565"

# Valid D-nummer (first digit in 4-5 range; same mod11 algorithm).
# Brute-force discovered to pass the checksum; not a real person's ID.
VALID_D_NUMMER = "44210249947"

# Valid H-nummer (third digit in 4-5 range; same mod11 algorithm).
VALID_H_NUMMER = "47434936183"

# Random 11-digit run that fails mod11 — looks like an ID but isn't.
INVALID_11 = "11111111111"

# Another invalid 11-digit run (random invoice-number-shaped).
INVALID_11_B = "52601815908"


def test_valid_fodselsnummer_passes_mod11():
    result = _mod11_digits(f"kontakt: {VALID_FNR}")
    assert len(result) == 1
    assert result[0][0] == VALID_FNR
    assert result[0][3] is True


def test_valid_d_nummer_passes_mod11():
    """D-nummer shares the mod11 algorithm — one function covers both."""
    result = _mod11_digits(f"d-nummer: {VALID_D_NUMMER}")
    assert len(result) == 1
    assert result[0][3] is True


def test_valid_h_nummer_passes_mod11():
    """H-nummer (3rd digit +40) also shares the mod11 algorithm."""
    result = _mod11_digits(f"h-nummer: {VALID_H_NUMMER}")
    assert len(result) == 1
    assert result[0][3] is True


def test_invalid_11_digit_run_fails_mod11():
    """A number that looks like an ID but fails the checksum."""
    result = _mod11_digits(f"ref: {INVALID_11}")
    assert len(result) == 1
    assert result[0][3] is False


def test_second_invalid_11_digit_run_fails_mod11():
    """Another invalid run — guard against false positives on random digits."""
    result = _mod11_digits(f"fakturanr: {INVALID_11_B}")
    assert len(result) == 1
    assert result[0][3] is False


def test_offsets_record_position_in_text():
    """Sample offsets must point at the actual location of the match."""
    text = f"foo {VALID_FNR} bar"
    result = _mod11_digits(text)
    match, start, end, _ = result[0]
    assert text[start:end] == match == VALID_FNR


def test_no_11_digit_run_returns_empty():
    assert _mod11_digits("no numbers here") == []


def test_multiple_matches_all_returned():
    text = f"{VALID_FNR} og {VALID_FNR}"
    result = _mod11_digits(text)
    assert len(result) == 2
    assert all(r[3] for r in result)


def test_word_boundary_prevents_12_digit_match():
    """12-digit runs must NOT be flagged (fødselsnummer is exactly 11 digits)."""
    result = _mod11_digits("123456789012")
    assert result == []
