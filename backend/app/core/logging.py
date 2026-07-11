"""Logging setup. stdlib-only for Phase 0; structured (structlog) + traces land
in roadmap item R5 (production observability).
"""

from __future__ import annotations

import logging
import sys

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_LOG_DATEFMT = "%Y-%m-%dT%H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # Quiet chatty HTTP libs so health-check polls don't spam.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
