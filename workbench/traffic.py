"""Small CBUS frame summary for the Diagnostics pane."""

import re

from .pnn import decode_pnn

# Opcodes displayed by Diagnostics. Keep the names here so its detailed and
# generic frame summaries use the same CBUS mnemonic.
OPCODE_NAMES = {
    0x0D: "QNN",
    0x57: "NERD",
    0x58: "RQEVN",
    0x59: "WRACK",
    0x6F: "CMDERR",
    0x71: "NVRD",
    0x73: "RQNPN",
    0x74: "NUMEV",
    0x90: "ACON",
    0x91: "ACOF",
    0x96: "NVSET",
    0x97: "NVANS",
    0x98: "ASON",
    0x99: "ASOF",
    0x9B: "PARAN",
    0x9C: "REVAL",
    0xB5: "NEVAL",
    0xB6: "PNN",
    0xF2: "ENRSP",
}


def describe_frame(frame: bytes, layout: str) -> tuple[str, str]:
    """Return an opcode label and details without changing live node state."""
    raw = frame.decode("ascii", errors="replace")
    match = re.fullmatch(rb":S([0-9A-Fa-f]{4})N([0-9A-Fa-f]{0,16});", frame)
    if match is None:
        return "GridConnect", f"{layout}: {raw}"

    header = int(match.group(1), 16)
    payload_hex = match.group(2)
    if header & 0x1F or len(payload_hex) % 2:
        return "GridConnect", f"{layout}: {raw}"
    payload = bytes.fromhex(payload_hex.decode("ascii"))
    if not payload:
        return "GridConnect", f"{layout}: {raw}"

    opcode = payload[0]
    label = OPCODE_NAMES.get(opcode, f"0x{opcode:02X}")
    if opcode == 0x0D and len(payload) == 1:
        return label, f"{layout}: CAN ID {(header >> 5) & 0x7F}"
    if opcode == 0xB6 and len(payload) == 6:
        pnn = decode_pnn(frame)
        if pnn is not None:
            return (
                label,
                (
                    f"{layout}: node {pnn.node_number} "
                    f"(manufacturer {pnn.manufacturer}, type {pnn.module_type}, flags {pnn.flags})"
                ),
            )
    if opcode == 0x73 and len(payload) == 4:
        node = (payload[1] << 8) | payload[2]
        return label, f"{layout}: node {node}, parameter {payload[3]}"
    if opcode == 0x9B and len(payload) == 5:
        node = (payload[1] << 8) | payload[2]
        return (
            label,
            f"{layout}: node {node}, parameter {payload[3]} = {payload[4]}",
        )
    return label, f"{layout}: {raw}"
