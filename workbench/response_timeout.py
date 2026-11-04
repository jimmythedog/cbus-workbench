"""Temporary shared response timeout for hardware testing."""

import os


def read_response_timeout_ms() -> int:
    """Read a positive millisecond duration that fits Qt's signed int timer API."""
    name = "CBUS_WORKBENCH_RESPONSE_TIMEOUT_MS"
    raw = os.environ.get(name, "2000")
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a positive integer in milliseconds") from None
    if not 1 <= value <= 2_147_483_647:
        raise ValueError(
            f"{name} must be a positive integer in milliseconds (1–2147483647)"
        )
    return value


RESPONSE_TIMEOUT_MS = read_response_timeout_ms()
