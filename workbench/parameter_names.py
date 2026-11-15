"""Interpret standard CBUS parameters shown in Node Details.

Codes come from MERG cbusdefs.csv: CbusParams, CbusBusTypes,
CbusProcessorManufacturers, CbusMicrochipProcessors, and CbusArmProcessors.
https://github.com/MERG-DEV/cbusdefs/blob/master/cbusdefs.csv
"""

# Manufacturer names from CW-OLD's src/cbus-node-metadata.js.
_MANUFACTURER_NAMES = {
    13: "DEVELOPMENT",
    42: "SHAG",
    70: "ROCRAIL",
    80: "SPECTRUM",
    165: "MERG",
    250: "VLCB",
    255: "unknown",
}

# Explicit MERG identities from MMC-SERVER VLCB-server/config/mergConfig.json
# (jimmythedog/MMC-SERVER, commit f4242d92). Module IDs are manufacturer-specific.
# Type 8 was CANACC4_2, subsequently renamed CANSOL (developer-confirmed).
# The CANSOL descriptor also exists at resources/mdfs/CANSOL-A522-1B.json;
# type 34 retains its separate CANSOL identity. Do not infer IDs from filenames.
_MODULE_NAMES = {
    (165, 1): "CANACC4",
    (165, 2): "CANACC5",
    (165, 3): "CANACC8",
    (165, 4): "CANACE3",
    (165, 5): "CANACE8C",
    (165, 6): "CANLED",
    (165, 7): "CANLED64",
    (165, 8): "CANSOL",
    (165, 9): "CANCAB",
    (165, 10): "CANCMD",
    (165, 11): "CANSERVO",
    (165, 12): "CANBC",
    (165, 13): "CANRPI",
    (165, 14): "CANTTCA",
    (165, 15): "CANTTCB",
    (165, 16): "CANHS",
    (165, 17): "CANTOTI",
    (165, 18): "CAN8I8O",
    (165, 19): "CANSERVO8C",
    (165, 20): "CANRFID",
    (165, 21): "CANTC4",
    (165, 22): "CANACE16C",
    (165, 23): "CANIO8",
    (165, 24): "CANSNDX",
    (165, 25): "CANETHER",
    (165, 26): "CANSIG64",
    (165, 27): "CANSIG8",
    (165, 28): "CANCOND8C",
    (165, 29): "CANPAN",
    (165, 30): "CANACE3C",
    (165, 31): "CANPanel",
    (165, 32): "CANMIO",
    (165, 33): "CANACE8MIO",
    (165, 34): "CANSOL",
    (165, 35): "CANBIP",
    (165, 36): "CANCDU",
    (165, 37): "CANACC4CDU",
    (165, 38): "CANWiBase",
    (165, 39): "WiCAB",
    (165, 40): "CANWiFi",
    (165, 41): "CANFTT",
    (165, 42): "CANHNDST",
    (165, 43): "CANTCHNDST",
    (165, 44): "CANRFID8",
    (165, 45): "CANmchRFID",
    (165, 46): "CANPiWi",
    (165, 47): "CAN4DC",
    (165, 48): "CANELEV",
    (165, 49): "CANSCAN",
    (165, 50): "CANMIO-SVO",
    (165, 51): "CANMIO-INP",
    (165, 52): "CANMIO-OUT",
    (165, 53): "CANBIP-OUT",
    (165, 54): "CANASTOP",
    (165, 55): "CANCSB",
    (165, 56): "CANMAG",
    (165, 57): "CANACE16CMIO",
    (165, 58): "CANPiNODE",
    (165, 59): "CANDISP",
    (165, 60): "CANCOMPUTE",
    (165, 61): "CANRC522",
    (165, 62): "CANINP",
    (165, 63): "CANOUT",
    (165, 64): "CANXIO",
    (165, 65): "CANCABDC",
    (165, 66): "CANRCOM",
    (165, 67): "CANMP3",
    (165, 68): "XMAS",
    (165, 69): "CANSVOSET",
    (165, 70): "CANCMDDC",
    (165, 71): "CANTEXT",
    (165, 72): "CANASIGNAL",
    (165, 73): "CANSLIDER",
    (165, 74): "CANDCATC",
    (165, 75): "CANGATE",
    (165, 76): "CANSINP",
    (165, 77): "CANSOUT",
    (165, 78): "CANSBIP",
    (165, 79): "CANBUFFER",
    (165, 80): "CANLEVER",
    (165, 81): "CANSHIELD",
    (165, 82): "CAN4IN4OUT",
    (165, 83): "CANCMDB",
    (165, 84): "CANPIXEL",
    (165, 85): "CANCABPE",
    (165, 86): "CANSMARTTD",
    (165, 87): "CANARGB",
    (165, 88): "CANCDU_U",
    (165, 89): "CANGATEX",
    (165, 90): "CANGATEXL",
    (165, 252): "CANDEV",
    (165, 253): "CANUSB",
    (165, 254): "EMPTY",
    (165, 255): "CAN_SW",
}


def manufacturer_name(manufacturer: int) -> str:
    """Display a known manufacturer name, retaining unknown numeric IDs."""
    return _MANUFACTURER_NAMES.get(manufacturer, str(manufacturer))


def module_name(
    manufacturer: int | None, module_type: int | None, mdf_name: str | None = None
) -> str:
    """Prefer the static identity name, then a compatible MDF name, then the type."""
    if module_type is None:
        return "-"
    name = _MODULE_NAMES.get((manufacturer, module_type))
    if name is not None:
        return name
    if isinstance(mdf_name, str) and mdf_name.strip():
        return mdf_name
    return str(module_type)


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


# Parameter indices from cbusdefs.csv (CbusParams). Index 0 is the parameter
# count (Developer's Guide 6b, RQNPN). Multi-byte values are named by first index.
PARAMETER_NAMES = {
    0: "Number of parameters",
    1: "Manufacturer",
    2: "Minor version",
    3: "Module type",
    4: "Number of events",
    5: "Event variables per event",
    6: "Number of node variables",
    7: "Major version",
    8: "Flags",
    9: "Processor type",
    10: "Bus type",
    11: "Load address",
    15: "CPU manufacturer ID",
    19: "CPU manufacturer",
    20: "Beta revision",
}

# Node flag bits from cbusdefs.csv (CbusParamFlags); PNN uses the same bits.
_FLAG_NAMES = (
    (0x01, "Consumer"),
    (0x02, "Producer"),
    (0x04, "FLiM"),
    (0x08, "Bootloader"),
    (0x10, "Consumes own events"),
    (0x20, "Learn mode"),
    (0x40, "VLCB"),
)


def flag_names(flags: int) -> list[str]:
    """Name the set node flag bits; unnamed bits are not reported."""
    return [name for bit, name in _FLAG_NAMES if flags & bit]


def vlcb_compatible(flags: int | None) -> bool | None:
    """Decode parameter 8 bit 6; unavailable flags must remain unknown."""
    return None if flags is None else bool(flags & 0x40)
