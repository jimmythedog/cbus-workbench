"""Qt's per-user application directories."""

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths

APP_NAME = "cbus-workbench"
DISPLAY_NAME = "CBUS Workbench"


def resource_directory() -> Path:
    """Resolve read-only resources relative to source or PyInstaller's bundle root."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "resources"


def system_mdf_directory() -> Path:
    return resource_directory() / "mdfs"


def user_guide_path() -> Path:
    """Resolve the HTML guide built by scripts/build_user_guide.py."""
    return resource_directory() / "user-guide" / "user-guide.html"


def user_mdf_directory() -> Path:
    """Resolve persistent user descriptors without creating the directory."""
    return application_directories()["Data"] / "mdfs"


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
