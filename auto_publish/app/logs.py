"""Structured JSON-lines operational log (complements the hash-chained audit_log)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .clock import Clock, iso_utc

LOGGER_NAME = "auto_publish"


class JsonLinesHandler(logging.Handler):
    def __init__(self, path: Path, clock: Clock):
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.clock = clock

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts_utc": iso_utc(self.clock.now()),
                "level": record.levelname,
                "event": record.getMessage(),
            }
            fields = getattr(record, "fields", None)
            if fields:
                entry.update(fields)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        except Exception:  # logging must never crash the pipeline
            self.handleError(record)


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def configure(log_dir: Path, clock: Clock) -> logging.Logger:
    logger = get_logger()
    logger.setLevel(logging.INFO)
    target = log_dir / "auto_publish.jsonl"
    for h in list(logger.handlers):
        if isinstance(h, JsonLinesHandler):
            logger.removeHandler(h)
    logger.addHandler(JsonLinesHandler(target, clock))
    logger.propagate = False
    return logger


def log(event: str, level: int = logging.INFO, **fields) -> None:
    get_logger().log(level, event, extra={"fields": fields})
