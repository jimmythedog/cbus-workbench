"""Decode ENRSP replies to NERD (MERG CBUS Developer's Guide 6b)."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Enrsp:
    node_number: int
    event_node_number: int
    event_number: int
    event_index: int


def decode_enrsp(frame: bytes) -> Enrsp | None:
    """Return one stored event, ignore other opcodes, or reject a bad frame."""
    match = re.fullmatch(rb":S([0-9A-Fa-f]{4})N([0-9A-Fa-f]{0,16});", frame)
    if match is None or int(match.group(1), 16) & 0x1F:
        raise ValueError("Expected one standard GridConnect data frame")
    payload_hex = match.group(2)
    if len(payload_hex) % 2:
        raise ValueError("GridConnect payload must contain whole bytes")
    payload = bytes.fromhex(payload_hex.decode("ascii"))
    if not payload or payload[0] != 0xF2:
        return None
    if len(payload) != 8:
        raise ValueError("ENRSP payload must contain exactly eight bytes")
    return Enrsp(
        (payload[1] << 8) | payload[2],
        (payload[3] << 8) | payload[4],
        (payload[5] << 8) | payload[6],
        payload[7],
    )
