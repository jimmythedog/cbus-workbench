"""List serial ports and recognise a layout's previously confirmed USB adapter.

QSerialPortInfo reads operating-system device metadata without opening a port,
so listing ports never sends CBUS traffic or disturbs another device. USB
metadata identifies an adapter model (and a unit only when it has a serial
number); it does not prove that the device speaks CBUS. That is confirmed only
by a layout's normal discovery reaching Ready (see MainWindow).
"""

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtSerialPort import QSerialPortInfo
from PySide6.QtWidgets import QInputDialog, QMessageBox

from .logging_config import trace

logger = logging.getLogger("workbench.connection")

# udev's stable per-device names. The kernel's ttyACM/ttyUSB numbers depend on
# plug-in order; these names do not.
BY_ID_DIRECTORY = Path("/dev/serial/by-id")
CHOOSE_PROMPT = "Choose a serial device…"


@dataclass(frozen=True)
class SerialPort:
    path: str  # passed to QSerialPort: a stable Linux by-id path when available
    name: str  # the operating system's own name, e.g. /dev/ttyACM1 or COM3
    description: str
    manufacturer: str
    vendor_id: int | None
    product_id: int | None
    serial_number: str

    def label(self) -> str:
        """Describe the port using whatever metadata the platform provides."""
        text = self.description
        if self.manufacturer and not text.startswith(self.manufacturer):
            text = f"{self.manufacturer} {text}".strip()
        usb = ""
        if self.vendor_id is not None and self.product_id is not None:
            usb = f"{self.vendor_id:04X}:{self.product_id:04X}"
            if self.serial_number:
                usb += f" S/N {self.serial_number}"
        parts = [part for part in (text, f"[{usb}]" if usb else "") if part]
        return f"{' '.join(parts)} — {self.name}" if parts else self.name

    def identity(self) -> dict | None:
        """Return the USB identity to remember, or None without VID/PID."""
        if self.vendor_id is None or self.product_id is None:
            return None
        identity = {"vendor_id": self.vendor_id, "product_id": self.product_id}
        # Optional strings are kept for labels; an empty serial number means
        # the identity names an adapter model rather than one physical unit.
        for key in ("serial_number", "manufacturer", "description"):
            if getattr(self, key):
                identity[key] = getattr(self, key)
        return identity


def identity_label(identity: dict | None) -> str:
    if identity is None:
        return "None yet"
    text = " ".join(
        identity[key] for key in ("manufacturer", "description") if key in identity
    )
    usb = f"{identity['vendor_id']:04X}:{identity['product_id']:04X}"
    if "serial_number" in identity:
        usb += f" S/N {identity['serial_number']}"
    return f"{text} [{usb}]".strip()


def available_ports() -> list[SerialPort]:
    """List every serial port, USB adapters first; no port is opened."""
    links = _linux_stable_links() if sys.platform == "linux" else {}
    ports = []
    for info in QSerialPortInfo.availablePorts():
        location = info.systemLocation()
        if sys.platform == "darwin" and location.startswith("/dev/tty."):
            # macOS lists each device twice. The /dev/cu.* callout device is the
            # one for outgoing connections; tty.* waits for carrier detect.
            continue
        name = info.portName() if sys.platform == "win32" else location
        # Identical adapters without serial numbers share one by-id name, which
        # udev points at whichever was plugged in last. Only a serial number
        # makes that name stable for one physical adapter.
        path = links.get(location, name) if info.serialNumber() else name
        ports.append(
            SerialPort(
                path=path,
                name=name,
                description=info.description(),
                manufacturer=info.manufacturer(),
                vendor_id=(
                    info.vendorIdentifier() if info.hasVendorIdentifier() else None
                ),
                product_id=(
                    info.productIdentifier() if info.hasProductIdentifier() else None
                ),
                serial_number=info.serialNumber(),
            )
        )
    # Prioritise likely adapters without hiding anything; sorting is stable.
    ports.sort(key=lambda port: port.vendor_id is None)
    trace(
        logger,
        "Serial ports listed",
        extra={"fields": {"ports": [port.label() for port in ports]}},
    )
    return ports


def _linux_stable_links() -> dict[str, str]:
    """Map each device to its by-id symlink, e.g. /dev/ttyACM1 -> /dev/serial/by-id/…"""
    links = {}
    try:
        entries = sorted(BY_ID_DIRECTORY.iterdir())
    except OSError:
        return links  # No USB serial devices, or no udev.
    for link in entries:
        links.setdefault(os.path.realpath(link), str(link))
    return links


def matching_ports(identity: dict, ports: list[SerialPort]) -> list[SerialPort]:
    """Ports with the confirmed VID/PID and, if one was recorded, serial number.

    Manufacturer and description strings are not compared: they vary by
    platform (Windows reports a generic description) and are only labels.
    """
    return [
        port
        for port in ports
        if port.vendor_id == identity["vendor_id"]
        and port.product_id == identity["product_id"]
        and port.serial_number == identity.get("serial_number", port.serial_number)
    ]


def find_port(path: str, ports: list[SerialPort]) -> SerialPort | None:
    """Return the listed port a configured path opens, following symlinks."""
    names = {path}
    if path.startswith("/"):
        names.add(os.path.realpath(path))
    return next(
        (port for port in ports if names & {port.path, port.name}),
        None,
    )


def choose_serial_device(
    parent, layout: str, settings: dict
) -> tuple[str, dict | None] | None:
    """Return (path to open, USB identity) for a serial layout, or None if cancelled.

    Manual mode opens the configured path unchanged; the identity of the listed
    port it names is kept so discovery can confirm that adapter. Auto opens the
    confirmed adapter only if exactly one listed port matches; otherwise the
    user chooses.
    """
    ports = available_ports()
    fields = {"layout": layout, "ports": len(ports)}
    if not settings["auto_select"]:
        path = settings["serial_port"]
        port = find_port(path, ports)
        identity = port.identity() if port else None
        trace(
            logger,
            "Using configured serial device",
            extra={"fields": {**fields, "device": path, "identity": identity}},
        )
        return path, identity

    identity = settings["serial_identity"]
    matches = matching_ports(identity, ports) if identity else []
    if len(matches) == 1:
        logger.info(
            "Auto-selected confirmed serial adapter",
            extra={"fields": {**fields, "device": matches[0].path}},
        )
        return matches[0].path, matches[0].identity()
    if identity is None:
        reason = "No adapter has been confirmed by discovery for this layout yet."
    elif matches:
        reason = f"{len(matches)} connected adapters match {identity_label(identity)}."
    else:
        reason = f"The confirmed adapter {identity_label(identity)} was not found."
    logger.info(
        "Serial device needs an explicit choice: %s",
        reason,
        extra={"fields": {**fields, "matches": len(matches)}},
    )
    if not ports:
        QMessageBox.warning(
            parent,
            "No serial devices",
            f"{reason}\n\nNo serial ports were found. Connect the adapter and "
            "try again, or enter a device path in Layout → Edit.",
        )
        return None
    # Start on a placeholder so pressing Enter cannot open a port by default.
    labels = [CHOOSE_PROMPT, *(port.label() for port in ports)]
    label, accepted = QInputDialog.getItem(
        parent,
        "Select serial device",
        f"{reason}\n\nSelect the device for layout '{layout}':",
        labels,
        0,
        False,
    )
    if not accepted or label == CHOOSE_PROMPT:
        logger.info("Serial device choice cancelled", extra={"fields": fields})
        return None
    port = ports[labels.index(label) - 1]
    logger.info(
        "Serial device chosen", extra={"fields": {**fields, "device": port.path}}
    )
    return port.path, port.identity()
