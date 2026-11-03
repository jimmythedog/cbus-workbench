"""Read and atomically replace the application's YAML settings file."""

import logging
from pathlib import Path

import yaml
from PySide6.QtCore import QIODeviceBase, QSaveFile, QStandardPaths

from .logging_config import trace

logger = logging.getLogger("workbench.settings")
APP_NAME = "CBUS Workbench"


class SettingsError(ValueError):
    """The settings file could not be read, validated or saved."""


def settings_path() -> Path:
    """Use Qt's per-user application data location on each platform."""
    directory = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(directory) / "settings.yaml"


def _validate_layout(name: object, value: object) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise SettingsError("Layout names must be non-empty strings")
    if not isinstance(value, dict):
        raise SettingsError(f"Layout '{name}' must be a mapping")
    if set(value) - {"logical_layout", "auto_connect", "connection"}:
        raise SettingsError(f"Layout '{name}' has unsupported fields")
    logical_layout = value.get("logical_layout")
    if (
        not isinstance(logical_layout, str)
        or not logical_layout.strip()
        or logical_layout in (".", "..")
        or "/" in logical_layout
        or "\\" in logical_layout
    ):
        raise SettingsError(
            f"Layout '{name}' needs a valid logical_layout directory name"
        )
    auto_connect = value.get("auto_connect", False)
    if not isinstance(auto_connect, bool):
        raise SettingsError(f"Layout '{name}' needs a Boolean auto_connect")

    connection = value.get("connection")
    if not isinstance(connection, dict):
        raise SettingsError(f"Layout '{name}' needs a connection mapping")
    if set(connection) - {"type", "host", "port", "serial_port", "can_id"} or not {
        "type",
        "host",
        "port",
        "serial_port",
    } <= set(connection):
        raise SettingsError(
            f"Layout '{name}' connection needs type, host, port and serial_port"
        )
    if connection["type"] not in ("TCP/IP", "Serial"):
        raise SettingsError(f"Layout '{name}' has an unsupported connection type")
    if not isinstance(connection["host"], str) or not isinstance(
        connection["serial_port"], str
    ):
        raise SettingsError(f"Layout '{name}' connection paths must be strings")
    port = connection["port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise SettingsError(f"Layout '{name}' TCP port must be from 1 to 65535")
    can_id = connection.get("can_id", 126)
    if type(can_id) is not int or not 100 <= can_id <= 127:
        raise SettingsError(f"Layout '{name}' CAN ID must be from 100 to 127")

    return {
        "logical_layout": logical_layout,
        "auto_connect": auto_connect,
        "connection": {**connection, "can_id": can_id},
    }


def validate_settings(value: object, *, recover_default: bool = False) -> dict:
    """Validate settings; loading may recover an absent or stale default."""
    if not isinstance(value, dict) or set(value) - {"default_layout", "layouts"}:
        raise SettingsError("Settings must contain only default_layout and layouts")
    layouts = value.get("layouts")
    if not isinstance(layouts, dict):
        raise SettingsError("Settings needs a layouts mapping")
    default_layout = value.get("default_layout")
    if default_layout is not None and (
        not isinstance(default_layout, str) or not default_layout.strip()
    ):
        raise SettingsError("default_layout must be a layout name or null")
    names = set()
    validated = {}
    for name, layout in layouts.items():
        checked = _validate_layout(name, layout)
        folded = name.casefold()
        if folded in names:
            raise SettingsError(f"Duplicate layout name: {name}")
        names.add(folded)
        validated[name] = checked
    if default_layout not in validated and (default_layout is not None or validated):
        if not recover_default:
            raise SettingsError(
                "default_layout must name an existing layout, or be null when layouts is empty"
            )
        if default_layout is not None:
            logger.warning(
                "Default layout '%s' is missing; selecting another layout",
                default_layout,
                extra={"fields": {"missing_layout": default_layout}},
            )
        default_layout = next(iter(validated), None)
    return {"default_layout": default_layout, "layouts": validated}


def layout_settings_for_ui(stored_layouts: dict[str, dict]) -> dict[str, dict]:
    """Flatten layouts returned by load_settings for the window and its dialog."""
    return {
        name: {
            "name": name,
            "logical_layout": saved["logical_layout"],
            "connection_type": saved["connection"]["type"],
            "host": saved["connection"]["host"],
            "port": saved["connection"]["port"],
            "serial_port": saved["connection"]["serial_port"],
            "can_id": saved["connection"]["can_id"],
            "auto_connect": saved["auto_connect"],
        }
        for name, saved in stored_layouts.items()
    }


def layout_settings_for_storage(layouts: dict[str, dict]) -> dict[str, dict]:
    """Nest the window's layout settings for save_settings validation and storage."""
    return {
        name: {
            "logical_layout": settings["logical_layout"],
            "auto_connect": settings["auto_connect"],
            "connection": {
                "type": settings["connection_type"],
                "host": settings["host"],
                "port": settings["port"],
                "serial_port": settings["serial_port"],
                "can_id": settings["can_id"],
            },
        }
        for name, settings in layouts.items()
    }


def load_settings(path: Path | None = None) -> dict:
    """Load settings; a missing file represents a new, empty configuration."""
    path = settings_path() if path is None else Path(path)
    trace(logger, "Loading application settings", extra={"fields": {"path": str(path)}})
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.info("Settings file not found; starting empty")
        return {"default_layout": None, "layouts": {}}
    except (OSError, UnicodeError) as error:
        logger.exception("Could not read settings file")
        raise SettingsError(f"Could not read {path}: {error}") from error

    try:
        settings = validate_settings(yaml.safe_load(content), recover_default=True)
    except (yaml.YAMLError, SettingsError) as error:
        logger.exception("Invalid settings file")
        raise SettingsError(f"Invalid settings in {path}: {error}") from error
    logger.info(
        "Application settings loaded",
        extra={"fields": {"layouts": len(settings["layouts"])}},
    )
    return settings


def save_settings(settings: dict, path: Path | None = None) -> None:
    """Validate before saving, and never replace a file that cannot be loaded."""
    path = settings_path() if path is None else Path(path)
    try:
        validated = validate_settings(settings)
    except SettingsError:
        logger.exception("Invalid settings cannot be saved")
        raise
    if path.exists():
        load_settings(path)
    trace(logger, "Saving application settings", extra={"fields": {"path": str(path)}})

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        output = yaml.safe_dump(validated, sort_keys=False, allow_unicode=True).encode(
            "utf-8"
        )
        file = QSaveFile(str(path))
        if not file.open(QIODeviceBase.OpenModeFlag.WriteOnly):
            raise OSError(file.errorString())
        if file.write(output) != len(output):
            file.cancelWriting()
            raise OSError(file.errorString())
        if not file.commit():
            raise OSError(file.errorString())
    except OSError as error:
        logger.exception("Could not save settings file")
        raise SettingsError(f"Could not save {path}: {error}") from error
    logger.info(
        "Application settings saved",
        extra={"fields": {"layouts": len(validated["layouts"])}},
    )
