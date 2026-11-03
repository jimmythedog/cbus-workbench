"""Decode a CBUS PNN response from a received GridConnect frame."""

import logging
import re
from dataclasses import dataclass

from .logging_config import trace

logger = logging.getLogger("workbench.cbus")


@dataclass(frozen=True)
class Pnn:
    node_number: int
    manufacturer: int
    module_type: int
    flags: int


def decode_pnn(frame: bytes) -> Pnn | None:
    """Return PNN data, or None for another opcode in a valid standard data frame.

    Reject malformed frames and PNNs with the wrong payload length. CBUS PNN is
    B6, NN high, NN low, manufacturer, module type, flags (Developer's Guide 6b).
    """
    match = re.fullmatch(rb":S([0-9A-Fa-f]{4})N([0-9A-Fa-f]{0,16});", frame)
    # CBUS GridConnect carries left-justified SIDH/SIDL bytes, not an 11-bit
    # integer. The five unused low bits of SIDL must be zero.
    if match is None or int(match.group(1), 16) & 0x1F:
        raise ValueError("Expected one standard GridConnect data frame")

    payload_hex = match.group(2)
    if len(payload_hex) % 2:
        raise ValueError("GridConnect payload must contain whole bytes")
    payload = bytes.fromhex(payload_hex.decode("ascii"))
    if not payload or payload[0] != 0xB6:
        return None
    if len(payload) != 6:
        raise ValueError("PNN payload must contain exactly six bytes")

    pnn = Pnn(
        node_number=(payload[1] << 8) | payload[2],
        manufacturer=payload[3],
        module_type=payload[4],
        flags=payload[5],
    )
    trace(
        logger,
        "PNN decoded",
        extra={
            "fields": {
                "node_number": pnn.node_number,
                "manufacturer": pnn.manufacturer,
                "module_type": pnn.module_type,
                "flags": pnn.flags,
            }
        },
    )
    return pnn
