"""Present persisted backup filenames as local, locale-formatted date/time."""

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QDateTime, QLocale, QTime, QTimeZone

logger = logging.getLogger("workbench.backups")


def backup_date_time(path: Path) -> str:
    # Both writers use naive datetime.now(): these are local wall times, not UTC.
    # No offset is stored, so the repeated hour at DST's end is ambiguous.
    try:
        saved = datetime.strptime(path.stem, "%Y-%m-%d_%H-%M-%S-%f")
    except ValueError:
        logger.warning("Backup filename has no recognised timestamp path=%s", path)
        return path.name
    local = QDateTime(
        QDate(saved.year, saved.month, saved.day),
        QTime(saved.hour, saved.minute, saved.second),
        QTimeZone.systemTimeZone(),
    )
    locale = QLocale()
    pattern = (
        locale.dateFormat(QLocale.FormatType.ShortFormat)
        + " "
        + locale.timeFormat(QLocale.FormatType.ShortFormat)
    )
    return locale.toString(local, pattern)
