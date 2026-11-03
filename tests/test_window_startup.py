"""Main window initialization from the persisted layout configuration."""

import os
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

from workbench.app_settings import save_settings
from workbench.window import MainWindow


class RecordingSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, value):
        for callback in self.callbacks:
            callback(value)


class RecordingConnection:
    attempts: ClassVar[list] = []
    failing_layout = None

    def __init__(self, layout_name, parent):
        self.layout_name = layout_name
        self.window = parent
        self.state_changed = RecordingSignal()
        self.failed = RecordingSignal()

    def connect(self, *endpoint):
        selected = self.window.layout_group.checkedAction().data()
        self.attempts.append(
            (self.layout_name, type(self).__name__, endpoint, selected)
        )
        if self.layout_name == self.failing_layout:
            self.state_changed.emit("Error")
            self.failed.emit("Connection refused")
        else:
            self.state_changed.emit("Connected")

    def disconnect(self):
        self.state_changed.emit("Disconnected")

    def deleteLater(self):
        pass


class RecordingTcpConnection(RecordingConnection):
    pass


class RecordingSerialConnection(RecordingConnection):
    pass


class WindowStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        RecordingConnection.attempts = []
        RecordingConnection.failing_layout = None
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "settings.yaml"

    def open_window(self):
        with patch("workbench.app_settings.settings_path", return_value=self.path):
            window = MainWindow()
        self.addCleanup(window.close)
        return window

    def test_loads_multiple_layouts_and_selects_configured_default(self):
        save_settings(
            {
                "default_layout": "Workshop",
                "layouts": {
                    "Home": {
                        "logical_layout": "home",
                        "auto_connect": False,
                        "connection": {
                            "type": "TCP/IP",
                            "host": "localhost",
                            "port": 5551,
                            "serial_port": "/dev/ttyACM0",
                        },
                    },
                    "Workshop": {
                        "logical_layout": "workshop",
                        "auto_connect": False,
                        "connection": {
                            "type": "Serial",
                            "host": "other-host",
                            "port": 5552,
                            "serial_port": "/dev/ttyACM1",
                        },
                    },
                },
            },
            self.path,
        )

        window = self.open_window()

        self.assertEqual(list(window.layouts), ["Home", "Workshop"])
        self.assertEqual(
            [action.text() for action in window.layout_group.actions()],
            ["Home", "Workshop ★"],
        )
        self.assertEqual(window.layout_group.checkedAction().data(), "Workshop")
        self.assertEqual(window.layout_status.text(), "Workshop")
        self.assertIs(window.layout_stack.currentWidget(), window.layouts["Workshop"])
        self.assertEqual(
            window.layout_settings["Home"],
            {
                "name": "Home",
                "logical_layout": "home",
                "auto_connect": False,
                "connection_type": "TCP/IP",
                "host": "localhost",
                "port": 5551,
                "serial_port": "/dev/ttyACM0",
            },
        )
        self.assertEqual(
            window.layout_settings["Workshop"]["logical_layout"], "workshop"
        )
        self.assertEqual(
            window.layout_settings["Workshop"]["connection_type"], "Serial"
        )
        self.assertEqual(window.layout_settings["Workshop"]["host"], "other-host")
        self.assertEqual(window.layout_settings["Workshop"]["port"], 5552)
        self.assertEqual(
            window.layout_settings["Workshop"]["serial_port"], "/dev/ttyACM1"
        )
        self.assertFalse(window.layout_settings["Workshop"]["auto_connect"])
        self.assertEqual(window.connections, {})
        self.assertEqual(
            window.connection_states,
            {"Home": "Disconnected", "Workshop": "Disconnected"},
        )

    def test_missing_settings_file_starts_without_layouts(self):
        window = self.open_window()
        self.assert_empty(window)
        self.assertFalse(self.path.exists())

    def test_explicitly_empty_layout_collection_starts_without_layouts(self):
        save_settings({"default_layout": None, "layouts": {}}, self.path)
        original = self.path.read_bytes()

        window = self.open_window()

        self.assert_empty(window)
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_settings_are_reported_without_overwriting_file(self):
        original = b"default_layout: Home\nlayouts:\n  Home: broken\n"
        self.path.write_bytes(original)

        with patch.object(QMessageBox, "critical") as critical:
            window = self.open_window()

        self.assert_empty(window)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(critical.call_count, 1)
        self.assertIn("Could not load settings", critical.call_args.args[2])
        self.assertIn("SettingsError", critical.call_args.args[2])

    def save_startup_layouts(self, auto_connect):
        layouts = {}
        for name, connection_type, enabled in auto_connect:
            layouts[name] = {
                "logical_layout": name.lower(),
                "auto_connect": enabled,
                "connection": {
                    "type": connection_type,
                    "host": f"{name.lower()}.example",
                    "port": 5550 + len(layouts),
                    "serial_port": f"/dev/{name.lower()}",
                },
            }
        save_settings({"default_layout": "Default", "layouts": layouts}, self.path)

    def start_with_recording_connections(self):
        with (
            patch("workbench.window.TcpConnection", RecordingTcpConnection),
            patch("workbench.window.SerialConnection", RecordingSerialConnection),
        ):
            window = self.open_window()
            self.assertEqual(RecordingConnection.attempts, [])
            self.app.processEvents()
        return window

    def test_no_auto_connect_layouts_remain_disconnected(self):
        self.save_startup_layouts(
            [("Default", "TCP/IP", False), ("Other", "Serial", False)]
        )

        window = self.start_with_recording_connections()

        self.assertEqual(RecordingConnection.attempts, [])
        self.assertEqual(window.connections, {})
        self.assertEqual(set(window.connection_states.values()), {"Disconnected"})

    def test_one_tcp_or_serial_layout_auto_connects(self):
        for connection_type, expected_type, endpoint in (
            ("TCP/IP", "RecordingTcpConnection", ("other.example", 5551)),
            ("Serial", "RecordingSerialConnection", ("/dev/other",)),
        ):
            with self.subTest(connection_type=connection_type):
                RecordingConnection.attempts = []
                self.save_startup_layouts(
                    [("Default", "TCP/IP", False), ("Other", connection_type, True)]
                )

                window = self.start_with_recording_connections()

                self.assertEqual(
                    RecordingConnection.attempts,
                    [("Other", expected_type, endpoint, "Default")],
                )
                self.assertEqual(window.connection_states["Other"], "Connected")
                self.assertEqual(window.connection_states["Default"], "Disconnected")
                self.assertEqual(window.layout_group.checkedAction().data(), "Default")
                self.assertIs(
                    window.layout_stack.currentWidget(), window.layouts["Default"]
                )

    def test_multiple_layouts_connect_without_changing_default_selection(self):
        self.save_startup_layouts(
            [
                ("First", "TCP/IP", True),
                ("Default", "Serial", True),
                ("Last", "TCP/IP", False),
            ]
        )

        window = self.start_with_recording_connections()

        self.assertEqual(
            [(name, selected) for name, _, _, selected in RecordingConnection.attempts],
            [("First", "Default"), ("Default", "Default")],
        )
        self.assertEqual(window.connection_states["Last"], "Disconnected")
        self.assertEqual(window.layout_group.checkedAction().data(), "Default")
        self.assertEqual(window.layout_status.text(), "Default")

    def test_failed_connection_does_not_prevent_other_startup_attempts(self):
        self.save_startup_layouts(
            [("First", "Serial", True), ("Default", "TCP/IP", True)]
        )
        RecordingConnection.failing_layout = "First"

        with patch.object(QMessageBox, "warning") as warning:
            window = self.start_with_recording_connections()

        self.assertEqual(
            [name for name, _, _, _ in RecordingConnection.attempts],
            ["First", "Default"],
        )
        self.assertEqual(window.connection_states["First"], "Error")
        self.assertEqual(window.connection_states["Default"], "Connected")
        self.assertEqual(window.layout_group.checkedAction().data(), "Default")
        warning.assert_called_once()

    def assert_empty(self, window):
        self.assertEqual(window.layouts, {})
        self.assertEqual(window.layout_settings, {})
        self.assertEqual(window.layout_group.actions(), [])
        self.assertIsNone(window.layout_group.checkedAction())
        self.assertEqual(window.layout_status.text(), "No layout")
        self.assertFalse(window.edit_action.isEnabled())
        self.assertFalse(window.set_default_action.isEnabled())
        self.assertFalse(window.connect_action.isEnabled())


if __name__ == "__main__":
    unittest.main()
