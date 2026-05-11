"""Logging configuration for the customization system.

Two sinks:
  - stderr at INFO+, human-readable.
  - logs/runs/<ISO-timestamp>.jsonl at DEBUG+, structured (one JSON object
    per line) for forensic inspection. The path is returned so the CLI can
    print it on startup.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from loguru import logger


def setup_logging(log_root: Path) -> Path:
    log_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = log_root / f"{ts}.jsonl"

    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss.SSS}</green> <level>{level:<7}</level> "
        "<cyan>{name}</cyan> {message} <dim>{extra}</dim>",
        backtrace=False,
        diagnose=False,
    )
    logger.add(
        path,
        level="DEBUG",
        serialize=True,
        backtrace=True,
        diagnose=False,
        enqueue=False,
    )
    logger.info("logging initialised", jsonl=str(path))
    return path
