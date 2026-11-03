"""Main window initialization from the persisted layout configuration."""

import os
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QMessageBox

from workbench.app_settings import load_settings, save_settings
from workbench.pnn import Pnn
from workbench.window import MainWindow


class RecordingSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self, value):
        for callback in self.callbacks:
            callback(value)


class RecordingConnection(QObject):
    attempts: ClassVar[list] = []
    failing_layout = None

    def __init__(self, layout_name, parent):
        super().__init__(parent)
        self.layout_name = layout_name
        self.window = parent
        self.state_changed = RecordingSignal()
        self.failed = RecordingSignal()
        self.frame_received = RecordingSignal()
        self.sent = []

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

    def send(self, frame):
        self.sent.append(frame)

    def deleteLater(self):
        pass


class RecordingTcpConnection(RecordingConnection):
    # PySide exposes QObject.connect/disconnect on subclasses unless overridden here.
    connect = RecordingConnection.connect
    disconnect = RecordingConnection.disconnect


class RecordingSerialConnection(RecordingConnection):
    connect = RecordingConnection.connect
    disconnect = RecordingConnection.disconnect


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
                "can_id": 126,
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

    def test_auto_connected_services_use_layout_ids_and_keep_nodes_separate(self):
        self.save_startup_layouts(
            [("First", "TCP/IP", True), ("Default", "Serial", True)]
        )
        settings = load_settings(self.path)
        settings["layouts"]["First"]["connection"]["can_id"] = 127
        save_settings(settings, self.path)

        window = self.start_with_recording_connections()
        first = window.connections["First"]
        second = window.connections["Default"]
        self.assertEqual(first.sent, [b":SBFE0N0D;"])
        self.assertEqual(second.sent, [b":SBFC0N0D;"])
        self.assertEqual(set(window.cbus_services), {"First", "Default"})

        with self.assertLogs("workbench.cbus", level="INFO") as captured:
            first.frame_received.emit(b":SB040NB601020D2203;")
            first.frame_received.emit(b":SB040NB601020D2303;")
            second.frame_received.emit(b":SB040NB601030D2203;")

        self.assertEqual(
            window.cbus_services["First"].nodes, {258: Pnn(258, 13, 35, 3)}
        )
        self.assertEqual(
            window.cbus_services["Default"].nodes, {259: Pnn(259, 13, 34, 3)}
        )
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Node discovered", "Node identity updated", "Node discovered"],
        )
        self.assertEqual(captured.records[0].fields["layout"], "First")
        table = window.diagnostics_dock.widget().table
        self.assertEqual(table.rowCount(), 5)
        self.assertIn("First: node 258 updated", table.item(3, 3).text())

    def test_navigator_tracks_each_layout_and_refreshes_selected_identity(self):
        self.save_startup_layouts(
            [("First", "TCP/IP", True), ("Default", "Serial", True)]
        )
        window = self.start_with_recording_connections()
        first_view = window.layouts["First"].node_view
        default_view = window.layouts["Default"].node_view
        self.assertEqual(first_view.node_list.count(), 0)
        self.assertEqual(default_view.node_list.count(), 0)

        # PNNs arrive for the hidden layout too, without a new query on selection.
        window.connections["First"].frame_received.emit(b":SB040NB601020D2203;")
        self.assertEqual(first_view.node_list.count(), 1)
        self.assertEqual(default_view.node_list.count(), 0)
        first_action = next(
            action
            for action in window.layout_group.actions()
            if action.data() == "First"
        )
        first_action.setChecked(True)
        window.select_layout(first_action)
        item = first_view.node_list.item(0)
        first_view.node_list.setCurrentItem(item)
        details = first_view.details
        self.assertEqual(item.text(), "258 - 34")
        self.assertEqual(details.node_number.text(), "258")
        self.assertEqual(details.manufacturer.text(), "13")
        self.assertEqual(details.module_type.text(), "34")
        self.assertEqual(details.flags.text(), "0x03")
        self.assertEqual(details.firmware.text(), "-")
        self.assertFalse(details.edit_button.isEnabled())

        window.connections["First"].frame_received.emit(b":SB040NB601020D2307;")
        self.assertIs(first_view.node_list.currentItem(), item)
        self.assertEqual(first_view.node_list.count(), 1)
        self.assertEqual(item.text(), "258 - 35")
        self.assertEqual(details.module_type.text(), "35")
        self.assertEqual(details.flags.text(), "0x07")

        window.connections["Default"].frame_received.emit(b":SB040NB601030D2203;")
        default_action = next(
            action
            for action in window.layout_group.actions()
            if action.data() == "Default"
        )
        default_action.setChecked(True)
        window.select_layout(default_action)
        self.assertIs(window.layout_stack.currentWidget(), window.layouts["Default"])
        self.assertEqual(default_view.node_list.item(0).text(), "259 - 34")
        self.assertEqual(first_view.node_list.item(0).text(), "258 - 35")

        window.connections["First"].disconnect()
        self.assertEqual(first_view.node_list.count(), 0)
        self.assertIsNone(first_view.details.node)
        self.assertEqual(first_view.details.node_number.text(), "-")
        self.assertEqual(default_view.node_list.count(), 1)

    def test_reconnect_clears_discovery_and_sends_one_new_query(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        first_service = window.cbus_services["Default"]
        connection.frame_received.emit(b":SB040NB601020D2203;")
        self.assertEqual(first_service.nodes, {258: Pnn(258, 13, 34, 3)})
        navigator = window.layouts["Default"].node_view.node_list
        self.assertEqual(navigator.count(), 1)

        window.disconnect_layout()
        self.assertEqual(window.cbus_services, {})
        self.assertEqual(navigator.count(), 0)
        connection.frame_received.emit(b":SB040NB601030D2203;")
        self.assertEqual(first_service.nodes, {258: Pnn(258, 13, 34, 3)})
        self.assertEqual(navigator.count(), 0)

        window.connect_layout()
        self.assertEqual(connection.sent, [b":SBFC0N0D;", b":SBFC0N0D;"])
        self.assertIsNot(window.cbus_services["Default"], first_service)
        self.assertEqual(window.cbus_services["Default"].nodes, {})
        self.assertEqual(navigator.count(), 0)

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
        self.assertNotIn("First", window.cbus_services)
        self.assertIn("Default", window.cbus_services)
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
