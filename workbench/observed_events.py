"""Passive event identities for one logical layout."""

import logging
import re
from dataclasses import dataclass

import yaml
from PySide6.QtCore import QObject, Signal

from .logging_config import trace
from .paths import application_directories

logger = logging.getLogger("workbench.events")


@dataclass(frozen=True, order=True)
class EventIdentity:
    node_number: int
    event_number: int

    def label(self) -> str:
        return f"{self.node_number}:{self.event_number}"


def decode_event(frame: bytes) -> EventIdentity | None:
    """Decode accessory ON/OFF, including responses and 1–3 data-byte variants.

    Short identities ignore the sender NN (CBUS Developer's Guide 6b, ASON).
    Request opcodes do not represent an observed ON/OFF event.
    """
    match = re.fullmatch(rb":S([0-9a-fA-F]{4})N([0-9a-fA-F]{10,16});", frame)
    if match is None or int(match[1], 16) & 0x1F or len(match[2]) % 2:
        return None
    payload = bytes.fromhex(match[2].decode("ascii"))
    opcode = payload[0]
    # Use explicit opcodes: ARON2/AROF2 are D4/D5, while D3 is EVANS.
    # Length bits cannot safely be masked to derive every event family.
    long_on = (0x90, 0xB0, 0xD0, 0xF0, 0x93, 0xB3, 0xD4, 0xF3)
    long_off = (0x91, 0xB1, 0xD1, 0xF1, 0x94, 0xB4, 0xD5, 0xF4)
    short_on = (0x98, 0xB8, 0xD8, 0xF8, 0x9D, 0xBD, 0xDD, 0xFD)
    short_off = (0x99, 0xB9, 0xD9, 0xF9, 0x9E, 0xBE, 0xDE, 0xFE)
    if opcode not in (*long_on, *long_off, *short_on, *short_off):
        return None
    if len(payload) != 1 + (opcode >> 5):
        return None
    short = opcode in (*short_on, *short_off)
    return EventIdentity(
        0 if short else int.from_bytes(payload[1:3], "big"),
        int.from_bytes(payload[3:5], "big"),
    )


class ObservedEvents(QObject):
    """Shared by views/connections using the same logical layout, never by nodes."""

    changed = Signal()

    def __init__(self, logical_layout: str):
        super().__init__()
        self.logical_layout = logical_layout
        self.path = (
            application_directories()["Data"]
            / "layouts"
            / logical_layout
            / "observed-events.yaml"
        )
        self.events: set[EventIdentity] = set()
        try:
            with self.path.open(encoding="utf-8") as stream:
                records = yaml.safe_load(stream) or []
            # Older records also contain type; NN/EN already hold their identity.
            for record in records:
                identity = EventIdentity(record["nodeNumber"], record["eventNumber"])
                if (
                    type(identity.node_number) is not int
                    or type(identity.event_number) is not int
                    or not 0 <= identity.node_number <= 65535
                    or not 0 <= identity.event_number <= 65535
                ):
                    raise ValueError(f"Invalid observed event identity in {self.path}")
                self.events.add(identity)
        except FileNotFoundError:
            pass
        trace(
            logger,
            "Observed identities loaded",
            extra={
                "fields": {
                    "layout": logical_layout,
                    "count": len(self.events),
                    "path": str(self.path),
                }
            },
        )

    def observe(self, identity: EventIdentity) -> None:
        """Persist a new identity before publishing it; ignore repeated sightings.

        Failed writes leave the identity new, so another reception can retry.
        The caller reports the failure through the existing UI error reporter.
        """
        if identity in self.events:
            trace(
                logger,
                "Observed identity already known",
                extra={
                    "fields": {"layout": self.logical_layout, "identity": str(identity)}
                },
            )
            return
        try:
            self._save({*self.events, identity})
        except OSError:
            logger.exception(
                "Could not persist observed event",
                extra={
                    "fields": {
                        "layout": self.logical_layout,
                        "identity": str(identity),
                    }
                },
            )
            raise
        self.events.add(identity)
        logger.info(
            "Observed identity saved",
            extra={
                "fields": {"layout": self.logical_layout, "identity": str(identity)}
            },
        )
        self.changed.emit()

    def forget(self, identities) -> None:
        """Remove identities from this layout's catalogue; annotations are untouched.

        The file is written before memory changes, so a failed save leaves both
        unchanged. A forgotten identity is rediscovered by the next observe().
        """
        forgotten = self.events & set(identities)
        if not forgotten:
            trace(
                logger,
                "No observed identities to forget",
                extra={"fields": {"layout": self.logical_layout}},
            )
            return
        labels = [item.label() for item in sorted(forgotten)]
        try:
            self._save(self.events - forgotten)
        except OSError:
            logger.exception(
                "Could not forget observed events",
                extra={"fields": {"layout": self.logical_layout, "events": labels}},
            )
            raise
        self.events -= forgotten
        # Forget All can be large: count at INFO, identities at TRACE.
        logger.info(
            "Observed identities forgotten",
            extra={
                "fields": {
                    "layout": self.logical_layout,
                    "count": len(forgotten),
                    "remaining": len(self.events),
                }
            },
        )
        trace(
            logger,
            "Forgotten identities",
            extra={"fields": {"layout": self.logical_layout, "events": labels}},
        )
        self.changed.emit()

    def _save(self, identities: set[EventIdentity]) -> None:
        """Replace the YAML file atomically so a failed write keeps the old one."""
        records = [
            {
                "nodeNumber": item.node_number,
                "eventNumber": item.event_number,
            }
            for item in sorted(identities)
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".yaml.tmp")
        temporary.write_text(yaml.safe_dump(records, sort_keys=False), encoding="utf-8")
        temporary.replace(self.path)
