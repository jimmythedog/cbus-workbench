"""Last confirmed node identification values, separate from live discovery."""

import logging

import yaml

from .cbus_service import NodeState
from .logging_config import trace
from .node_backup_files import backup_directory

logger = logging.getLogger("workbench.metadata")


def load_metadata(logical_layout: str, number: int) -> dict:
    """Load CW-OLD positional parameters (including parameter zero) and CAN ID."""
    path = backup_directory(logical_layout, number).parent / "metadata.yaml"
    try:
        with path.open(encoding="utf-8") as stream:
            metadata = yaml.safe_load(stream) or {}
    except FileNotFoundError:
        return {}
    trace(logger, "Node metadata loaded", extra={"fields": {"path": str(path)}})
    return metadata


def save_metadata(logical_layout: str, state: NodeState) -> None:
    """Merge only confirmed fields; missing replies never erase earlier values."""
    number = state.identity.node_number
    path = backup_directory(logical_layout, number).parent / "metadata.yaml"
    previous = load_metadata(logical_layout, number)
    metadata = dict(previous)
    parameters = list(previous.get("parameters", []))
    for index, value in state.parameters.items():
        if index >= len(parameters):
            parameters.extend([None] * (index + 1 - len(parameters)))
        parameters[index] = value
    if parameters:
        metadata["parameters"] = parameters
    if state.can_id is not None:
        metadata["canId"] = state.can_id
    if metadata == previous and path.exists():
        trace(logger, "Node metadata unchanged", extra={"fields": {"path": str(path)}})
        return
    # Even an empty record remembers a discovered node without assuming CAN.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(metadata, stream, sort_keys=False)
    logger.info("Node metadata saved", extra={"fields": {"path": str(path)}})
