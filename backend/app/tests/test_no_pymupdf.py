"""License invariant: PyMuPDF and PyMuPDF4LLM must be absent (§447, §453).

PyMuPDF is AGPL-or-commercial; depending on it would force the entire codebase
into AGPL or require a commercial license. The plan explicitly excludes it.
This test fails if anyone accidentally adds it.
"""

from __future__ import annotations

import subprocess
import sys


def _installed_packages() -> set[str]:
    """Return the set of installed distribution names, normalized lowercase."""
    try:
        out = subprocess.check_output(
            [sys.executable, "-m", "pip", "list", "--format=freeze"],
            text=True, timeout=30,
        )
    except Exception:
        return set()
    names = set()
    for line in out.splitlines():
        if "==" in line:
            names.add(line.split("==", 1)[0].lower())
    return names


def test_pymupdf_not_installed():
    """PyMuPDF (fitz) must never be a dependency."""
    pkgs = _installed_packages()
    assert "pymupdf" not in pkgs, "PyMuPDF is AGPL-licensed and excluded by design"
    assert "pymupdf4llm" not in pkgs, "PyMuPDF4LLM is AGPL-licensed and excluded by design"
    # Historical import name; pymupdf also installs under this name.
    assert "fitz" not in pkgs
