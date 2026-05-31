from __future__ import annotations

import logging
from pathlib import Path
from .models import ensure_dir


def configure_loggers(output_dir: str | Path) -> dict[str, logging.Logger]:
    base = ensure_dir(output_dir)
    names = {
        "execution": "execution.log",
        "assertions": "assertions.log",
        "cleanup": "cleanup.log",
        "errors": "errors.log",
    }
    loggers: dict[str, logging.Logger] = {}
    for name, filename in names.items():
        logger = logging.getLogger(f"docker_lab_validator.{name}")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        handler = logging.FileHandler(base / filename, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
        loggers[name] = logger
    return loggers
