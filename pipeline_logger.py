#!/usr/bin/env python3
"""
pipeline_logger — unified structured logging for the IBKR pipeline
====================================================================
Every module calls ``get_logger(__name__)`` to get a configured
``logging.Logger`` with both console (stdout) and rotating-file
outputs.  Call once from the entry point to activate.
"""

import logging
import logging.handlers
import sys
from pathlib import Path

# Singleton flag
_logging_configured = False

LOGS_DIR = Path(__file__).resolve().parent / "logs"


def configure_pipeline_logging(
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> logging.Logger:
    """Configure logging for the whole pipeline (idempotent).

    Args:
        console_level: Minimum level for stdout messages.
        file_level: Minimum level for the rotating log file.

    Returns:
        The root logger so the caller can emit an initial banner line.
    """
    global _logging_configured
    if _logging_configured:
        return logging.getLogger()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s] %(name)-20s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(fmt)
    root.addHandler(console)

    # Rotating file handler (10 MB x 3 backups)
    log_path = LOGS_DIR / "pipeline.log"
    file_handler = logging.handlers.RotatingFileHandler(
        str(log_path), maxBytes=10 * 1024 * 1024, backupCount=3,
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    _logging_configured = True
    root.info("Pipeline logging initialised — file: %s, console level: %s",
              log_path, logging.getLevelName(console_level))
    return root


def get_logger(name: str) -> logging.Logger:
    """Return (and auto-configure if needed) a per-module logger.

    Args:
        name: Usually ``__name__`` from the calling module.

    Returns:
        A :class:`logging.Logger`.
    """
    if not _logging_configured:
        configure_pipeline_logging()
    return logging.getLogger(name)
