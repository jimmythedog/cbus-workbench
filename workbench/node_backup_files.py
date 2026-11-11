"""The issue #44 node configuration format and its timestamped files."""

import logging
from datetime import datetime
from pathlib import Path

import yaml

from .annotations import validate_annotations
from .cbus_service import DiscoveryProgress, NodeState
from .logging_config import trace
from .paths import application_directories

logger = logging.getLogger("workbench.backups")


def positional_values(
    values: dict[int, int | None], count: int | None
) -> list[int | None]:
    """Preserve known positions, including gaps when the total count is unknown."""
    last = max(values, default=0) if count is None else count
    return [values.get(index) for index in range(1, last + 1)]


def event_variables(
    values: dict[int, int | None], count: int | None
) -> list[int | None]:
    """Trim trailing confirmed absences, stopping at any unknown position."""
    result = positional_values(values, count)
    while result and len(result) in values and values[len(result)] is None:
        result.pop()
    return result


def node_backup(state: NodeState) -> dict:
    """Capture confirmed configuration without event-table indices or metadata."""
    done = DiscoveryProgress.COMPLETE
    skipped = DiscoveryProgress.SKIPPED
    events = [
        {
            "nodeNumber": identity[0],
            "eventNumber": identity[1],
            "eventVariables": event_variables(
                state.ev_values.get(index, {}), state.parameters.get(5)
            ),
        }
        for index, identity in state.event_identities.items()
    ]
    nvs = positional_values(state.nv_values, state.parameters.get(6))
    # Skipping event reads is valid only when PNN confirms no consumer support.
    events_complete = (
        not state.identity.is_consumer
        and state.event_progress == skipped
        and state.ev_progress == skipped
        and not events
    ) or (
        state.event_progress == done
        and state.stored_event_count is not None
        and len(events) == state.stored_event_count
        and state.ev_progress == done
        and (not events or state.parameters.get(5) is not None)
        # A present None is confirmed absent; a missing key is still unknown.
        and all(
            ev_index in state.ev_values.get(event_index, {})
            for event_index in state.event_identities
            for ev_index in range(1, state.parameters.get(5, 0) + 1)
        )
    )
    complete = (
        state.parameter_progress == done
        and state.nv_progress == done
        and state.parameters.get(6) is not None
        and events_complete
        and None not in nvs
    )
    backup = {
        "format_version": 1,
        "complete": complete,
        "partOfLayoutBackup": False,
        "node": state.identity.node_number,
        "nvs": nvs,
        "events": events,
    }
    trace(
        logger,
        "Node backup captured",
        extra={
            "fields": {
                "node_number": state.identity.node_number,
                "complete": complete,
                "event_count": len(events),
            }
        },
    )
    return backup


def backup_directory(logical_layout: str, node_number: int | None = None) -> Path:
    directory = application_directories()["Data"] / "layouts" / logical_layout
    if node_number is not None:
        directory = directory / "nodes" / str(node_number)
    return directory / "backups"


def save_backup(logical_layout: str, backup: dict, filename: str | None = None) -> Path:
    """Save a node record or manifest, optionally sharing a layout filename."""
    directory = backup_directory(logical_layout, backup.get("node"))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (filename or f"{datetime.now():%Y-%m-%d_%H-%M-%S-%f}.yaml")
    with path.open("x", encoding="utf-8") as stream:
        yaml.safe_dump(backup, stream, sort_keys=False)
    logger.info("Configuration backup saved", extra={"fields": {"path": str(path)}})
    return path


def list_backups(
    logical_layout: str, node_number: int | None = None
) -> list[tuple[Path, bool, str]]:
    directory = backup_directory(logical_layout, node_number)
    if not directory.exists():
        return []
    backups = []
    for path in sorted(directory.glob("*.yaml"), reverse=True):
        with path.open(encoding="utf-8") as stream:
            backup = yaml.safe_load(stream)
        description = backup.get("description", "")
        if node_number is not None and backup.get("partOfLayoutBackup") is True:
            # Layout members share their parent's filename, not its description.
            manifest_path = backup_directory(logical_layout) / path.name
            try:
                with manifest_path.open(encoding="utf-8") as stream:
                    manifest = yaml.safe_load(stream)
                description = manifest.get("description", "")
            except FileNotFoundError:
                description = ""
            trace(
                logger,
                "Layout member description resolved",
                extra={
                    "fields": {
                        "manifest": str(manifest_path),
                        "node_number": node_number,
                        "has_description": bool(description),
                    }
                },
            )
        backups.append((path, backup["complete"], description))
    trace(
        logger,
        "Configuration backups listed",
        extra={
            "fields": {
                "layout": logical_layout,
                "node_number": node_number,
                "count": len(backups),
            }
        },
    )
    return backups


def load_node_backup(path: Path) -> dict:
    """Load a node file for either the node UI or its owning layout manifest."""
    trace(logger, "Loading node backup", extra={"fields": {"path": str(path)}})
    with path.open(encoding="utf-8") as stream:
        backup = yaml.safe_load(stream)
    validate_backup(backup)
    return backup


def load_layout_node(manifest_path: Path, number: int) -> dict:
    """Resolve a manifest member by node number and the shared filename."""
    path = (
        manifest_path.parent.parent
        / "nodes"
        / str(number)
        / "backups"
        / manifest_path.name
    )
    node = load_node_backup(path)
    if node["node"] != number or not node["partOfLayoutBackup"]:
        raise ValueError(f"Node backup does not belong to manifest: {path}")
    return node


def validate_backup(backup: dict) -> None:
    """Reject malformed configuration before opening a saved YAML in the UI."""

    def integer(value):
        return type(value) is int

    def values(items):
        return isinstance(items, list) and all(
            value is None or integer(value) for value in items
        )

    if not (
        isinstance(backup, dict)
        and backup.get("format_version") == 1
        and type(backup.get("complete")) is bool
        and type(backup.get("partOfLayoutBackup")) is bool
        and integer(backup.get("node"))
        and values(backup.get("nvs"))
        and isinstance(backup.get("events"), list)
    ):
        raise ValueError("Invalid node YAML backup")
    if "annotations" in backup:
        validate_annotations(backup["annotations"], node=True)
    identities = set()
    for event in backup["events"]:
        if not (
            isinstance(event, dict)
            and integer(event.get("nodeNumber"))
            and integer(event.get("eventNumber"))
            and values(event.get("eventVariables"))
        ):
            raise ValueError("Invalid event in node YAML backup")
        identity = (event["nodeNumber"], event["eventNumber"])
        if identity in identities:
            raise ValueError("Duplicate event in node YAML backup")
        identities.add(identity)


def saved_node_numbers(logical_layout: str) -> list[int]:
    """Find saved nodes independently of live discovery."""
    directory = backup_directory(logical_layout).parent / "nodes"
    numbers = sorted(
        int(path.name)
        for path in directory.glob("*")
        if path.is_dir()
        and path.name.isdecimal()
        and (
            (path / "metadata.yaml").is_file()
            or (path / "annotations.yaml").is_file()
            or any((path / "backups").glob("*.yaml"))
        )
    )
    trace(
        logger,
        "Saved nodes listed",
        extra={
            "fields": {
                "layout": logical_layout,
                "node_numbers": numbers,
            }
        },
    )
    return numbers
