"""Structured (key=value) logging helper."""

from __future__ import annotations

import logging


class _KVFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record)} {record.levelname} {record.name} {record.getMessage()}"
        extra = getattr(record, "kv", None)
        if extra:
            base += " " + " ".join(f"{k}={v}" for k, v in extra.items())
        return base


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger("tfalgo")
    if root.handlers:
        return
    h = logging.StreamHandler()
    h.setFormatter(_KVFormatter())
    root.addHandler(h)
    root.setLevel(level)


def log_kv(logger: logging.Logger, level: int, msg: str, **kv: object) -> None:
    logger.log(level, msg, extra={"kv": kv})
