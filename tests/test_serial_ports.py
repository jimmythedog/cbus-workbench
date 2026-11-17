"""Serial port listing and the device chosen for manual and Auto layouts."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from workbench import serial_ports
from workbench.serial_ports import SerialPort, available_ports, choose_serial_device

CANUSB4 = {
    "vendor_id": 0x04D8,
    "product_id": 0xF80C,
    "manufacturer": "SPROG DCC",
    "description": "CAN USB4",
}


class FakePortInfo:
    """The QSerialPortInfo metadata an operating system may or may not supply."""

    def __init__(
        self, location, description="", manufacturer="", vid=None, pid=None, serial=""
    ):
        self.location = location
        self.metadata = (description, manufacturer, vid, pid)
        self.serial = serial

    def systemLocation(self):
        return self.location

    def portName(self):
        return self.location.rsplit("/", 1)[-1]

    def description(self):
        return self.metadata[0]

    def manufacturer(self):
        return self.metadata[1]

    def hasVendorIdentifier(self):
        return self.metadata[2] is not None

    def vendorIdentifier(self):
        return self.metadata[2] or 0

    def hasProductIdentifier(self):
        return self.metadata[3] is not None

    def productIdentifier(self):
        return self.metadata[3] or 0

    def serialNumber(self):
        return self.serial


def port(path, vid=None, pid=None, serial_number="", description=""):
    return SerialPort(path, path, description, "", vid, pid, serial_number)


def serial_settings(auto_select, identity=None, path=""):
    return {
        "auto_select": auto_select,
        "serial_identity": identity,
        "serial_port": path,
    }


class AvailablePortTests(unittest.TestCase):
    def list_ports(self, infos, by_id=None):
        with (
            patch.object(
                serial_ports.QSerialPortInfo, "availablePorts", return_value=infos
            ),
            patch.object(serial_ports, "BY_ID_DIRECTORY", by_id or Path("/missing")),
        ):
            return available_ports()

    def test_lists_every_port_with_available_metadata_and_usb_first(self):
        ports = self.list_ports(
            [
                FakePortInfo("/dev/ttyS0"),
                FakePortInfo("/dev/ttyACM1", "CAN USB4", "SPROG DCC", 0x04D8, 0xF80C),
                FakePortInfo("/dev/ttyUSB0", vid=0x1234, pid=0xABCD),
            ]
        )

        self.assertEqual(
            [port.label() for port in ports],
            [
                "SPROG DCC CAN USB4 [04D8:F80C] — /dev/ttyACM1",
                "[1234:ABCD] — /dev/ttyUSB0",
                "/dev/ttyS0",
            ],
        )
        self.assertEqual(ports[0].identity(), CANUSB4)
        # A port without USB metadata stays selectable but cannot be learned.
        self.assertIsNone(ports[2].identity())
        self.assertEqual(self.list_ports([]), [])

    @unittest.skipUnless(sys.platform == "linux", "udev by-id paths are Linux only")
    def test_linux_uses_by_id_path_only_for_adapters_with_serial_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            unique = Path(directory) / "usb-FTDI_FT232R_A1B2-if00"
            unique.symlink_to("/dev/ttyUSB0")
            # Shared by identical adapters, so it may name either of them.
            (Path(directory) / "usb-SPROG_DCC_CAN_USB4-if00").symlink_to("/dev/ttyACM7")
            ports = self.list_ports(
                [
                    FakePortInfo("/dev/ttyUSB0", vid=0x0403, pid=0x6001, serial="A1B2"),
                    FakePortInfo("/dev/ttyACM7", vid=0x04D8, pid=0xF80C),
                ],
                Path(directory),
            )

        self.assertEqual(ports[0].path, str(unique))
        self.assertEqual(ports[0].name, "/dev/ttyUSB0")
        self.assertEqual(ports[1].path, "/dev/ttyACM7")


class ChooseSerialDeviceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def choose(self, settings, ports, choice=None):
        """Return the result and the ports offered.

        choice is a port index, "default" accepts the initial item, None cancels.
        """
        offered = []

        def get_item(_parent, _title, _text, labels, current, _editable):
            offered.extend(labels[1:])
            if choice is None:
                return "", False
            return labels[current if choice == "default" else choice + 1], True

        with (
            patch.object(serial_ports, "available_ports", return_value=ports),
            patch.object(serial_ports.QInputDialog, "getItem", get_item),
            patch.object(serial_ports.QMessageBox, "warning") as warning,
        ):
            result = choose_serial_device(None, "Home", settings)
        return result, offered, warning.called

    def test_auto_reconnects_confirmed_adapter_after_device_name_changes(self):
        ports = [
            port("/dev/ttyACM0", 0x2C99, 0x0002),
            port("/dev/ttyACM3", 0x04D8, 0xF80C),
        ]

        result, offered, _warned = self.choose(serial_settings(True, CANUSB4), ports)

        self.assertEqual(result[0], "/dev/ttyACM3")
        self.assertEqual(offered, [])

    def test_auto_asks_when_adapter_is_unconfirmed_missing_or_ambiguous(self):
        unknown = port("/dev/ttyUSB0", 0x1234, 0xABCD)
        no_metadata = port("/dev/ttyS0")
        cases = {
            "unconfirmed": (None, [unknown, no_metadata]),
            "missing": (CANUSB4, [unknown, no_metadata]),
            "ambiguous": (
                CANUSB4,
                [
                    port("/dev/ttyACM1", 0x04D8, 0xF80C),
                    port("/dev/ttyACM2", 0x04D8, 0xF80C),
                ],
            ),
        }
        for case, (identity, ports) in cases.items():
            with self.subTest(case):
                result, offered, _warned = self.choose(
                    serial_settings(True, identity), ports, choice=1
                )
                # Every port is offered, including unknown and metadata-free ones.
                self.assertEqual(offered, [p.label() for p in ports])
                self.assertEqual(result, (ports[1].path, ports[1].identity()))

                cancelled, _offered, _warned = self.choose(
                    serial_settings(True, identity), ports
                )
                self.assertIsNone(cancelled)

                # The initial item is a prompt, so Enter cannot pick a port.
                default, _offered, _warned = self.choose(
                    serial_settings(True, identity), ports, choice="default"
                )
                self.assertIsNone(default)

    def test_auto_without_ports_warns_instead_of_guessing(self):
        result, offered, warned = self.choose(serial_settings(True, CANUSB4), [])

        self.assertIsNone(result)
        self.assertEqual(offered, [])
        self.assertTrue(warned)

    def test_serial_number_distinguishes_identical_adapters(self):
        identity = {"vendor_id": 0x0403, "product_id": 0x6001, "serial_number": "B"}
        ports = [
            port("/dev/ttyUSB0", 0x0403, 0x6001, "A"),
            port("/dev/ttyUSB1", 0x0403, 0x6001, "B"),
        ]

        result, offered, _warned = self.choose(serial_settings(True, identity), ports)

        self.assertEqual(result[0], "/dev/ttyUSB1")
        self.assertEqual(offered, [])

    def test_manual_path_is_used_unchanged_even_when_auto_would_match(self):
        ports = [port("/dev/ttyACM1", 0x04D8, 0xF80C, description="CAN USB4")]

        listed = self.choose(serial_settings(False, None, "/dev/ttyACM1"), ports)
        unlisted = self.choose(serial_settings(False, CANUSB4, "/dev/ttyAMA0"), ports)

        self.assertEqual(
            listed[0],
            (
                "/dev/ttyACM1",
                {"vendor_id": 0x04D8, "product_id": 0xF80C, "description": "CAN USB4"},
            ),
        )
        # An unusual device that is not listed remains usable, with no identity.
        self.assertEqual(unlisted[0], ("/dev/ttyAMA0", None))
        self.assertEqual(listed[1] + unlisted[1], [])


if __name__ == "__main__":
    unittest.main()
