"""Configure the application's persistent, plain-text log."""

import faulthandler
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from .paths import application_directories

TRACE = 5
logging.addLevelName(TRACE, "TRACE")

# The levels offered in View → Logging Level and accepted as settings.yaml log_level.
LOG_LEVELS = {
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "TRACE": TRACE,
}

_log_path: Path | None = None
# Kept open for the whole process: faulthandler writes to its descriptor at crash time.
_crash_file: TextIO | None = None


def trace(
    logger: logging.Logger, message: str, *args: object, **kwargs: object
) -> None:
    """Emit a TRACE record, e.g. ``trace(logger, "Opened %s", name)``."""
    logger.log(TRACE, message, *args, **kwargs)


def log_directory() -> Path:
    """Return the log directory within Qt's per-user state location."""
    return application_directories()["State"] / "logs"


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
    global _log_path, _crash_file
    if _log_path is not None:
        return _log_path

    directory = log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "cbus-workbench.log"

    handler = RotatingFileHandler(
        # Nine backups: each run rolls over at startup, so this keeps the last several
        # runs (the failing one may be a few restarts back). Worst case is 50 MiB.
        path,
        maxBytes=5 * 1024 * 1024,
        backupCount=9,
        encoding="utf-8",
    )
    handler.setFormatter(
        _PlainTextFormatter(
            "%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    # Start each run in a fresh file so it is easy to find; the previous run, often
    # the one that failed, moves to .1 rather than being deleted. If renaming fails
    # (e.g. another instance has the file open on Windows), keep appending.
    rollover_error = None
    if path.stat().st_size > 0:
        try:
            handler.doRollover()
        except OSError as error:
            rollover_error = error

    if level is None:
        level = logging.INFO if getattr(sys, "frozen", False) else TRACE
        # If the application is frozen (packaged), default to INFO level to avoid excessive logging.

    logger = logging.getLogger("workbench")
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    _log_path = path
    if rollover_error is not None:
        logger.warning(
            "Could not start a new log file; appending to the existing one",
            extra={"fields": {"error": str(rollover_error)}},
        )

    # A native crash (e.g. a segfault in Qt or the serial driver) bypasses Python
    # exception handling, so faulthandler dumps every thread's stack instead. It
    # writes straight to the file descriptor, so it gets its own file: sharing the
    # rotating log would interleave output, and after rotation a descriptor opened
    # at startup would point at the renamed backup. stderr is not used because
    # windowed packaged builds may have none.
    crash_path = directory / "crash.log"
    # Not a context manager: the file must stay open until the process exits.
    _crash_file = open(crash_path, "a", encoding="utf-8")  # noqa: SIM115
    faulthandler.enable(_crash_file, all_threads=True)
    logger.info(
        "Crash diagnostics enabled", extra={"fields": {"crash_file": str(crash_path)}}
    )
    return path
