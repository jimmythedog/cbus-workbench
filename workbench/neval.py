"""Decode NEVAL replies to REVAL (MERG CBUS Developer's Guide 6b)."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Neval:
    node_number: int
    event_index: int
    ev_index: int
    value: int


def decode_neval(frame: bytes) -> Neval | None:
    """Return a confirmed EV value, ignore other opcodes, or reject a bad frame."""
    match = re.fullmatch(rb":S([0-9A-Fa-f]{4})N([0-9A-Fa-f]{0,16});", frame)
    if match is None or int(match.group(1), 16) & 0x1F:
        raise ValueError("Expected one standard GridConnect data frame")
    payload_hex = match.group(2)
    if len(payload_hex) % 2:
        raise ValueError("GridConnect payload must contain whole bytes")
    payload = bytes.fromhex(payload_hex.decode("ascii"))
    if not payload or payload[0] != 0xB5:
        return None
    if len(payload) != 6 or payload[4] == 0:
        raise ValueError(
            "NEVAL must contain a node, event index, nonzero EV index and value"
        )
    return Neval((payload[1] << 8) | payload[2], payload[3], payload[4], payload[5])
