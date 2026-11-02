"""Configure the application's persistent, plain-text log."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

TRACE = 5
logging.addLevelName(TRACE, "TRACE")

_log_path: Path | None = None


def trace(
    logger: logging.Logger, message: str, *args: object, **kwargs: object
) -> None:
    """Emit a TRACE record, e.g. ``trace(logger, "Opened %s", name)``."""
    logger.log(TRACE, message, *args, **kwargs)


def log_directory() -> Path:
    """Return the per-user log directory for the current operating system."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "CBUS Workbench" / "Logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "CBUS Workbench"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "cbus-workbench" / "logs"


class _PlainTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        fields = getattr(record, "fields", None)
        if fields:
            message += " " + " ".join(
                f"{key}={value!r}" for key, value in fields.items()
            )
        return message


def configure_logging(level: int | None = None) -> Path:
    """Set up logging once, defaulting to INFO in a packaged application.

    Supply structured fields with ``extra={"fields": {"layout_id": 12}}``.
    The first call determines the initial level and log destination for this process.
    """
    global _log_path
    if _log_path is not None:
        return _log_path

    directory = log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "cbus-workbench.log"

    handler = RotatingFileHandler(
        path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        _PlainTextFormatter(
            "%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    if level is None:
        level = logging.INFO if getattr(sys, "frozen", False) else TRACE
        # If the application is frozen (packaged), default to INFO level to avoid excessive logging.

    logger = logging.getLogger("workbench")
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    _log_path = path
    return path
