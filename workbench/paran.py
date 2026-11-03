"""Decode a CBUS PARAN response from a received GridConnect frame."""

import logging
import re
from dataclasses import dataclass

from .logging_config import trace

logger = logging.getLogger("workbench.cbus")


@dataclass(frozen=True)
class Paran:
    node_number: int
    parameter_index: int
    parameter_value: int


def decode_paran(frame: bytes) -> Paran | None:
    """Return PARAN data, or None for another opcode in a valid standard data frame.

    CBUS PARAN is 9B, NN high, NN low, parameter index, parameter value
    (Developer's Guide 6b). Reject malformed frames and PARANs of other lengths.
    """
    match = re.fullmatch(rb":S([0-9A-Fa-f]{4})N([0-9A-Fa-f]{0,16});", frame)
    # GridConnect carries left-justified SIDH/SIDL bytes. The five unused
    # low bits of SIDL must be zero.
    if match is None or int(match.group(1), 16) & 0x1F:
        raise ValueError("Expected one standard GridConnect data frame")

    payload_hex = match.group(2)
    if len(payload_hex) % 2:
        raise ValueError("GridConnect payload must contain whole bytes")
    payload = bytes.fromhex(payload_hex.decode("ascii"))
    if not payload or payload[0] != 0x9B:
        return None
    if len(payload) != 5:
        raise ValueError("PARAN payload must contain exactly five bytes")

    paran = Paran(
        node_number=(payload[1] << 8) | payload[2],
        parameter_index=payload[3],
        parameter_value=payload[4],
    )
    trace(
        logger,
        "PARAN decoded",
        extra={
            "fields": {
                "node_number": paran.node_number,
                "parameter_index": paran.parameter_index,
                "parameter_value": paran.parameter_value,
            }
        },
    )
    return paran
