"""Read MMC layout annotations without loading backups or touching MMC files."""

import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .annotations import validate_annotations
from .logging_config import trace
from .mdf_tokens import normalise_overrides

logger = logging.getLogger("workbench.mmc_import")


def mmc_layouts_directory() -> Path:
    """Locate MMC's effective layouts directory; detection never creates files."""
    home = Path.home()
    base = (
        Path("C:/ProgramData/MMC-SERVER")
        if sys.platform == "win32"
        else home / "MMC-SERVER"
    )
    effective = base
    try:
        settings = json.loads((base / "appSettings.json").read_text(encoding="utf-8"))
        custom = settings.get("customUserDirectory")
        if (
            settings.get("userDataMode") == "CUSTOM"
            and isinstance(custom, str)
            and custom.strip()
        ):
            candidate = Path(custom)
            if candidate.is_absolute() and candidate.is_dir():
                effective = candidate
    except FileNotFoundError:
        trace(logger, "MMC settings absent base=%s", base)
    except OSError, ValueError, AttributeError:
        logger.exception("Cannot read MMC settings base=%s; using OS default", base)
    layouts = effective / "layouts"
    try:
        # Actually enumerate: is_dir alone does not establish readability.
        list(layouts.iterdir())
    except OSError:
        trace(logger, "MMC layouts unavailable path=%s; using home", layouts)
        return home
    trace(logger, "MMC chooser directory=%s", layouts)
    return layouts


@dataclass
class MmcLayout:
    path: Path
    title: str
    connection: dict
    annotations: dict
    nodes: dict[int, dict]
    skipped: tuple[str, ...]
    connection_note: str


def mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def connection_settings(value: object) -> tuple[dict, str]:
    """CW needs complete settings even when MMC has no translatable endpoint."""
    result = {
        "type": "TCP/IP",
        "host": "",
        "port": 5550,
        "serial_port": "",
        "can_id": 126,
    }
    if isinstance(value, dict):
        if (
            value.get("mode") == "SerialPort"
            and isinstance(value.get("serialPort"), str)
            and value["serialPort"].strip()
        ):
            result.update(type="Serial", serial_port=value["serialPort"])
            return (
                result,
                "Serial settings imported; check the device before connecting.",
            )
        if (
            value.get("mode") == "Network"
            and isinstance(value.get("host"), str)
            and value["host"].strip()
        ):
            port = value.get("hostPort")
            if isinstance(port, str) and port.isdecimal():
                port = int(port)
            if type(port) is int and 1 <= port <= 65535:
                result.update(host=value["host"], port=port)
                return result, "TCP/IP settings imported; auto-connect disabled."
    return (
        result,
        "No supported MMC connection; configure it in Layouts → Edit… before connecting.",
    )


def read_mmc_layout(path: Path) -> MmcLayout:
    """Translate only supported annotations and validate them before any writes."""
    trace(logger, "Reading MMC layout path=%s", path)
    try:
        data = mapping(json.loads(path.read_text(encoding="utf-8")), "Layout")
        details = mapping(data.get("layoutDetails", {}), "layoutDetails")
        title = details.get("title", path.parent.name)
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Layout title must be non-empty text")
        skipped = set()
        skipped.update(f"layoutDetails.{key}" for key in details.keys() - {"title"})
        skipped.update(
            data.keys()
            - {"layoutDetails", "connectionDetails", "nodeDetails", "eventDetails"}
        )
        connection, note = connection_settings(data.get("connectionDetails"))
        if isinstance(data.get("connectionDetails"), dict):
            skipped.update(
                f"connectionDetails.{key}"
                for key in data["connectionDetails"].keys()
                - {"mode", "serialPort", "host", "hostPort"}
            )
        nodes = {}
        for number, record in mapping(
            data.get("nodeDetails", {}), "nodeDetails"
        ).items():
            # MMC persists a mixed object, not a node-only map. Its server
            # writes it unchanged; nonnumeric keys can even hold node-shaped
            # objects (e.g. updateTimestamp). Select identities before records.
            try:
                node_number = int(number)
            except ValueError:
                trace(logger, "Ignoring non-node MMC entry key=%s", number)
                continue
            if node_number == 0:
                continue
            if not number.isdecimal() or not 1 <= node_number <= 65535:
                raise ValueError(f"Invalid node number: {number!r}")
            if node_number in nodes:
                raise ValueError(f"Duplicate node number: {number}")
            record = mapping(record, f"Node {number}")
            tokens = {}
            for token, definition in mapping(
                record.get("tokens", {}), "tokens"
            ).items():
                definition = mapping(definition, f"Token {token}")
                tokens[token] = dict(
                    mapping(definition.get("userNames", {}), "userNames")
                )
                skipped.update(
                    f"tokens.{key}" for key in definition.keys() - {"userNames"}
                )
            tokens = normalise_overrides(tokens)
            # Normalise before combining modern and legacy channel spellings.
            for channel, definition in mapping(
                record.get("channels", {}), "channels"
            ).items():
                definition = mapping(definition, f"Channel {channel}")
                if "channelName" in definition:
                    legacy = normalise_overrides(
                        {"channel": {channel: definition["channelName"]}}
                    )
                    for key, value in legacy.get("channel", {}).items():
                        tokens.setdefault("channel", {}).setdefault(key, value)
                skipped.update(
                    f"channels.{key}" for key in definition.keys() - {"channelName"}
                )
            nodes[node_number] = validate_annotations(
                {"name": record.get("name", ""), "tokens": tokens}, node=True
            )
            skipped.update(
                f"nodeDetails.{key}"
                for key in record.keys() - {"name", "tokens", "channels"}
            )
        events = {}
        for identity, record in mapping(
            data.get("eventDetails", {}), "eventDetails"
        ).items():
            # As with nodes, select real identities before inspecting values.
            # Real MMC files also retain entries like undefined and 0NAN0NAN.
            if not re.fullmatch(r"[0-9a-fA-F]{8}", identity):
                trace(logger, "Ignoring non-event MMC entry key=%s", identity)
                continue
            record = mapping(record, f"Event {identity}")
            key = f"{int(identity[:4], 16)}:{int(identity[4:], 16)}"
            if key in events:
                raise ValueError(f"Duplicate event identity: {identity}")
            # MMC also persists null for an unnamed event; it supplies no edit.
            events[key] = "" if record.get("name") is None else record["name"]
            skipped.update(
                f"eventDetails.{field}" for field in record.keys() - {"name"}
            )
        annotations = validate_annotations({"events": events}, node=False)
    except OSError, UnicodeError, ValueError, TypeError:
        logger.exception("Invalid MMC layout path=%s", path)
        raise
    logger.info(
        "Read MMC layout path=%s nodes=%s event_names=%s skipped=%s",
        path,
        len(nodes),
        len(annotations.get("events", {})),
        sorted(skipped),
    )
    return MmcLayout(
        path,
        title.strip(),
        connection,
        annotations,
        nodes,
        tuple(sorted(skipped)),
        note,
    )


def find_mmc_layouts(source: Path) -> list[MmcLayout]:
    """Accept one file, one layout directory, or the parent layouts directory."""
    if source.is_file():
        paths = [source]
    elif (source / "layoutData.json").is_file():
        paths = [source / "layoutData.json"]
    else:
        paths = sorted(source.glob("*/layoutData.json"))
    if not paths:
        raise ValueError(f"No layoutData.json files found in {source}")
    return [read_mmc_layout(path) for path in paths]
