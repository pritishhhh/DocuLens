"""Structured stdout logs work on local and read-only serverless filesystems."""
import json
import logging
import time
from contextlib import contextmanager

logger = logging.getLogger("doculens")


@contextmanager
def trace_step(name: str, metadata: dict | None = None):
    start = time.monotonic()
    error = None
    try:
        yield
    except Exception as exc:
        error = type(exc).__name__
        raise
    finally:
        logger.info(json.dumps({"step": name, "duration_ms": round((time.monotonic() - start) * 1000, 2),
                                "metadata": metadata or {}, "error": error}))
