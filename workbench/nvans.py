"""Decode a CBUS NVANS response from a received GridConnect frame.

NVRD/NVANS formats: MERG Developer's Guide 6b, sections 7.2.6 and 12.1.
https://www.merg.org.uk/merg_wiki/lib/exe/fetch.php?media=public%3Acbuspublic%3Adeveloper_6b.pdf
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Nvans:
    node_number: int
    nv_index: int
    nv_value: int


def decode_nvans(frame: bytes) -> Nvans | None:
    """Return NVANS data, None for another opcode, or reject a malformed frame."""
    match = re.fullmatch(rb":S([0-9A-Fa-f]{4})N([0-9A-Fa-f]{0,16});", frame)
    if match is None or int(match.group(1), 16) & 0x1F:
        raise ValueError("Expected one standard GridConnect data frame")
    payload_hex = match.group(2)
    if len(payload_hex) % 2:
        raise ValueError("GridConnect payload must contain whole bytes")
    payload = bytes.fromhex(payload_hex.decode("ascii"))
    if not payload or payload[0] != 0x97:
        return None
    if len(payload) != 5 or payload[3] == 0:
        raise ValueError("NVANS must contain a node, nonzero NV index and value")
    return Nvans((payload[1] << 8) | payload[2], payload[3], payload[4])
