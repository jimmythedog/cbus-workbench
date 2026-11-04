"""Interpret standard CBUS parameters shown in Node Details.

Codes come from MERG cbusdefs.csv: CbusParams, CbusBusTypes,
CbusProcessorManufacturers, CbusMicrochipProcessors, and CbusArmProcessors.
https://github.com/MERG-DEV/cbusdefs/blob/master/cbusdefs.csv
"""

_TRANSPORT_NAMES = {1: "CAN", 2: "Ethernet", 3: "MiWi", 4: "USB"}

_MICROCHIP_PROCESSORS = {
    1: "P18F2480",
    2: "P18F4480",
    3: "P18F2580",
    4: "P18F4580",
    5: "P18F2585",
    6: "P18F4585",
    7: "P18F2680",
    8: "P18F4680",
    9: "P18F2682",
    10: "P18F4682",
    11: "P18F2685",
    12: "P18F4685",
    13: "P18F25K80",
    14: "P18F45K80",
    15: "P18F26K80",
    16: "P18F46K80",
    17: "P18F65K80",
    18: "P18F66K80",
    19: "P18F25K83",
    20: "P18F26K83",
    21: "P18F27Q84",
    22: "P18F47Q84",
    23: "P18F27Q83",
    25: "P18F14K22",
    30: "P32MX534F064",
    31: "P32MX564F064",
    32: "P32MX564F128",
    33: "P32MX575F256",
    34: "P32MX575F512",
    35: "P32MX764F128",
    36: "P32MX775F256",
    37: "P32MX775F512",
    38: "P32MX795F512",
}

_ARM_PROCESSORS = {
    1: "ARM1176JZF_S",
    2: "ARMCortex_A7",
    3: "ARMCortex_A53",
}


def transport_name(code: int | None) -> str | None:
    """Return a defined CBUS bus name, or None for an absent/unknown code."""
    return _TRANSPORT_NAMES.get(code)


def cpu_name(manufacturer: int | None, processor: int | None) -> str | None:
    """Interpret a processor code only within its confirmed manufacturer table."""
    if manufacturer == 1:
        return _MICROCHIP_PROCESSORS.get(processor)
    if manufacturer == 3:
        return _ARM_PROCESSORS.get(processor)
    return None


def firmware_version(parameters: dict[int, int]) -> str | None:
    """Format confirmed version parts; an absent major version is unknown."""
    if 7 not in parameters:
        return None

    version = str(parameters[7])
    minor = parameters.get(2)
    if minor is not None and 32 < minor <= 126:
        version += chr(minor)
    beta = parameters.get(20)
    if beta is not None and beta != 0:
        version += f" Beta {beta}"
    return version


def vlcb_compatible(flags: int | None) -> bool | None:
    """Decode parameter 8 bit 6; unavailable flags must remain unknown."""
    return None if flags is None else bool(flags & 0x40)
