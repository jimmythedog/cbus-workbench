"""Qt's per-user application directories."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths

APP_NAME = "cbus-workbench"
DISPLAY_NAME = "CBUS Workbench"


def application_directories() -> dict[str, Path]:
    """Resolve directories without creating them."""
    locations = QStandardPaths.StandardLocation
    return {
        name: Path(QStandardPaths.writableLocation(location))
        for name, location in (
            ("Configuration", locations.AppConfigLocation),
            ("Data", locations.AppDataLocation),
            ("State", locations.StateLocation),
            ("Cache", locations.CacheLocation),
        )
    }
