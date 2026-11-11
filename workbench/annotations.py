"""Local names and MDF overrides, independent of observations and hardware data."""

import logging
from pathlib import Path

import yaml
from PySide6.QtCore import QObject, Signal

from .logging_config import trace
from .mdf_tokens import normalise_overrides
from .paths import application_directories

logger = logging.getLogger("workbench.annotations")


def annotation_path(logical_layout: str, number: int | None = None) -> Path:
    path = application_directories()["Data"] / "layouts" / logical_layout
    if number is not None:
        path = path / "nodes" / str(number)
    return path / "annotations.yaml"


def validate_annotations(data: dict, *, node: bool) -> dict:
    """Validate names before saving or restoring, retaining only this contract."""
    if not isinstance(data, dict):
        raise TypeError("Expected an annotations mapping")
    result = {}
    if node:
        name = data.get("name", "")
        if not isinstance(name, str):
            raise TypeError("Expected a node name")
        if name.strip():
            result["name"] = name.strip()
        tokens = normalise_overrides(data.get("tokens", {}))
        if tokens:
            result["tokens"] = tokens
    events = data.get("consumedEvents" if node else "events", {})
    if not isinstance(events, dict):
        raise TypeError("Expected event identities mapped to names")
    names = {}
    for identity, name in events.items():
        parts = identity.split(":") if isinstance(identity, str) else []
        if (
            len(parts) != 2
            or not all(part.isdecimal() and 0 <= int(part) <= 65535 for part in parts)
            or not isinstance(name, str)
        ):
            raise ValueError(f"Invalid annotation event: {identity!r}")
        if name.strip():
            names[":".join(str(int(part)) for part in parts)] = name.strip()
    if names:
        result["consumedEvents" if node else "events"] = names
    return result


def load_annotations(logical_layout: str, number: int | None = None) -> dict:
    path = annotation_path(logical_layout, number)
    try:
        with path.open(encoding="utf-8") as stream:
            data = validate_annotations(
                yaml.safe_load(stream) or {}, node=number is not None
            )
    except FileNotFoundError:
        return {}
    except OSError, ValueError, TypeError, yaml.YAMLError:
        logger.exception("Cannot load annotations path=%s", path)
        raise
    trace(logger, "Loaded annotations path=%s", path)
    return data


def save_annotations(
    logical_layout: str, data: dict, number: int | None = None
) -> None:
    """Replace the file before publishing changes; a failed save preserves edits."""
    data = validate_annotations(data, node=number is not None)
    path = annotation_path(logical_layout, number)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".yaml.tmp")
        temporary.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        logger.exception("Cannot save annotations path=%s", path)
        raise
    logger.info(
        "Saved annotations layout=%s node=%s path=%s", logical_layout, number, path
    )


class Annotations(QObject):
    """Notify views sharing a logical layout after a successful local save."""

    changed = Signal(int)  # -1 denotes layout event names.

    def __init__(self, logical_layout: str):
        super().__init__()
        self.logical_layout = logical_layout

    def load(self, number: int | None = None) -> dict:
        return load_annotations(self.logical_layout, number)

    def save(self, data: dict, number: int | None = None) -> None:
        save_annotations(self.logical_layout, data, number)
        self.changed.emit(-1 if number is None else number)
