"""Decode WRACK replies from nodes (MERG CBUS Developer's Guide 6b)."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Wrack:
    node_number: int


def decode_wrack(frame: bytes) -> Wrack | None:
    """Return a write acknowledgement, ignore other opcodes, or reject a bad frame."""
    match = re.fullmatch(rb":S([0-9A-Fa-f]{4})N([0-9A-Fa-f]{0,16});", frame)
    if match is None or int(match.group(1), 16) & 0x1F:
        raise ValueError("Expected one standard GridConnect data frame")
    payload_hex = match.group(2)
    if len(payload_hex) % 2:
        raise ValueError("GridConnect payload must contain whole bytes")
    payload = bytes.fromhex(payload_hex.decode("ascii"))
    if not payload or payload[0] != 0x59:
        return None
    if len(payload) != 3:
        raise ValueError("WRACK payload must contain exactly three bytes")
    return Wrack((payload[1] << 8) | payload[2])
