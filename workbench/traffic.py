"""Small CBUS frame summary for the Diagnostics pane."""

import re

from .cmderr import CMDERR_NAMES
from .parameter_names import (
    PARAMETER_NAMES,
    flag_names,
    manufacturer_name,
    module_name,
    transport_name,
)
from .pnn import decode_pnn

# Opcodes displayed by Diagnostics. Keep the names here so its detailed and
# generic frame summaries use the same CBUS mnemonic.
OPCODE_NAMES = {
    0x0D: "QNN",
    0x10: "RQNP",
    0x42: "SNN",
    0x50: "RQNN",
    0x51: "NNREL",
    0x52: "NNACK",
    0x53: "NNLRN",
    0x54: "NNULN",
    0x57: "NERD",
    0x58: "RQEVN",
    0x59: "WRACK",
    0x6F: "CMDERR",
    0x71: "NVRD",
    0x73: "RQNPN",
    0x74: "NUMEV",
    0x90: "ACON",
    0x91: "ACOF",
    0x95: "EVULN",
    0x96: "NVSET",
    0x97: "NVANS",
    0x98: "ASON",
    0x99: "ASOF",
    0x9B: "PARAN",
    0x9C: "REVAL",
    0xB2: "REQEV",
    0xB5: "NEVAL",
    0xB6: "PNN",
    0xD2: "EVLRN",
    0xD3: "EVANS",
    0xEF: "PARAMS",
    0xF2: "ENRSP",
}

# Data fields after the opcode for each opcode in OPCODE_NAMES, as (name, bytes),
# from the MERG CBUS Developer's Guide 6b. Long events carry the event's node
# number; a short event's NN is the sending node, not part of the event. Frames
# whose length differs from the layout are not broken down.
_NN = ("Node number", 2)
_EVENT = (("Event node number", 2), ("Event number", 2))
_OPCODE_FIELDS = {
    0x0D: (),
    0x10: (),
    0x42: (_NN,),
    0x50: (_NN,),
    0x51: (_NN,),
    0x52: (_NN,),
    0x53: (_NN,),
    0x54: (_NN,),
    0x57: (_NN,),
    0x58: (_NN,),
    0x59: (_NN,),
    0x6F: (_NN, ("Error", 1)),
    0x71: (_NN, ("NV index", 1)),
    0x73: (_NN, ("Parameter index", 1)),
    0x74: (_NN, ("Stored events", 1)),
    0x90: _EVENT,
    0x91: _EVENT,
    0x95: _EVENT,
    0x96: (_NN, ("NV index", 1), ("NV value", 1)),
    0x97: (_NN, ("NV index", 1), ("NV value", 1)),
    0x98: (_NN, ("Device number", 2)),
    0x99: (_NN, ("Device number", 2)),
    0x9B: (_NN, ("Parameter index", 1), ("Parameter value", 1)),
    0x9C: (_NN, ("Event index", 1), ("EV index", 1)),
    0xB2: (*_EVENT, ("EV index", 1)),
    0xB5: (_NN, ("Event index", 1), ("EV index", 1), ("EV value", 1)),
    0xB6: (_NN, ("Manufacturer", 1), ("Module type", 1), ("Flags", 1)),
    0xD2: (*_EVENT, ("EV index", 1), ("EV value", 1)),
    0xD3: (*_EVENT, ("EV index", 1), ("EV value", 1)),
    0xEF: (
        ("Manufacturer", 1),
        ("Minor version", 1),
        ("Module type", 1),
        ("Supported events", 1),
        ("EVs per event", 1),
        ("Supported NVs", 1),
        ("Major version", 1),
    ),
    0xF2: (_NN, *_EVENT, ("Event index", 1)),
}


def _named(value: int, name: str | None) -> str:
    """Show a decimal value with its name when one is known."""
    return f"{value} ({name})" if name and name != str(value) else str(value)


def _field_text(name: str, value: int, fields: dict[str, int]) -> str:
    """Translate codes into spec names; other fields are plain quantities."""
    if name == "Manufacturer":
        return _named(value, manufacturer_name(value))
    if name == "Module type":
        return _named(value, module_name(fields["Manufacturer"], value))
    if name == "Flags":
        return _named(value, ", ".join(flag_names(value)))
    if name == "Error":
        return _named(value, CMDERR_NAMES.get(value))
    if name == "Parameter index":
        return _named(value, PARAMETER_NAMES.get(value))
    if name == "Parameter value":
        # Only parameters whose meaning is fixed by the spec. Module type (3)
        # depends on the manufacturer, which is not in this frame.
        index = fields["Parameter index"]
        if index == 1:
            return _named(value, manufacturer_name(value))
        if index == 8:
            return _named(value, ", ".join(flag_names(value)))
        if index == 10:
            return _named(value, transport_name(value))
    return str(value)


def _standard_frame(frame: bytes) -> tuple[int, bytes] | None:
    """Return the header and payload of a standard GridConnect data frame."""
    match = re.fullmatch(rb":S([0-9A-Fa-f]{4})N([0-9A-Fa-f]{0,16});", frame)
    if match is None:
        return None
    header = int(match.group(1), 16)
    payload_hex = match.group(2)
    if header & 0x1F or len(payload_hex) % 2:
        return None
    payload = bytes.fromhex(payload_hex.decode("ascii"))
    if not payload:
        return None
    return header, payload


def decode_can_frame(frame: bytes) -> list[tuple[str, str]]:
    """Return decimal label/value rows for a standard CBUS frame, or []."""
    parsed = _standard_frame(frame)
    if parsed is None:
        return []
    header, payload = parsed
    # GridConnect carries the 11-bit CAN identifier left-shifted by 5. CBUS
    # splits it into major priority (2 bits), minor priority (2) and CAN ID (7).
    identifier = header >> 5
    opcode = payload[0]
    name = OPCODE_NAMES.get(opcode)
    rows = [
        ("Major priority", str((identifier >> 9) & 0x3)),
        ("Minor priority", str((identifier >> 7) & 0x3)),
        ("CAN ID", str(identifier & 0x7F)),
        ("Opcode", f"{opcode} ({name})" if name else str(opcode)),
    ]
    layout = _OPCODE_FIELDS.get(opcode)
    if layout is not None and len(payload) == 1 + sum(size for _, size in layout):
        fields = {}
        position = 1
        for name, size in layout:
            fields[name] = int.from_bytes(payload[position : position + size])
            position += size
        rows += [
            (name, _field_text(name, value, fields)) for name, value in fields.items()
        ]
    rows.append(("Data bytes", ", ".join(str(byte) for byte in payload)))
    rows.append(("Data length", str(len(payload))))
    return rows


def describe_frame(frame: bytes, layout: str) -> tuple[str, str]:
    """Return an opcode label and details without changing live node state."""
    raw = frame.decode("ascii", errors="replace")
    parsed = _standard_frame(frame)
    if parsed is None:
        return "GridConnect", f"{layout}: {raw}"
    header, payload = parsed

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
