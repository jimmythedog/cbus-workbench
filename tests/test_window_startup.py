"""Main window initialization from the persisted layout configuration."""

import os
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from layout_fixture import sample_settings
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from workbench.app_settings import load_settings, save_settings
from workbench.layout_settings import LayoutSettingsDialog
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
        self.frame_sent = RecordingSignal()
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
        self.frame_sent.emit(frame)

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

    def test_discovery_status_tracks_selected_connection_and_reconnect(self):
        settings = sample_settings()
        # Two connections can refer to the same logical layout.
        settings["layouts"]["Test Layout"]["logical_layout"] = "home"
        for layout in settings["layouts"].values():
            layout["connection"]["host"] = "localhost"
        save_settings(settings, self.path)
        with (
            patch("workbench.window.TcpConnection", RecordingTcpConnection),
            patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 30),
        ):
            window = self.open_window()
            window.connect_layout()
            self.assertEqual(window.discovery_status.text(), "Discovering…")
            QTest.qWait(60)
            self.assertEqual(window.discovery_status.text(), "Incomplete")
            actions = window.layout_group.actions()
            actions[1].trigger()
            self.assertTrue(window.discovery_status.isHidden())
            self.assertTrue(window.discovery_separator.isHidden())
            window.connect_layout()
            self.assertEqual(window.discovery_status.text(), "Discovering…")
            actions[0].trigger()
            self.assertEqual(window.discovery_status.text(), "Incomplete")
            self.assertEqual(window.connection_status.text(), "Connected")
            QTest.mouseDClick(window.connection_status, Qt.MouseButton.LeftButton)
            self.assertEqual(window.connection_status.text(), "Disconnected")
            self.assertTrue(window.discovery_status.isHidden())
            self.assertTrue(window.discovery_separator.isHidden())
            QTest.mouseDClick(window.connection_status, Qt.MouseButton.LeftButton)
            self.assertFalse(window.discovery_status.isHidden())
            self.assertFalse(window.discovery_separator.isHidden())
            self.assertEqual(window.discovery_status.text(), "Discovering…")
            QTest.qWait(60)
            self.assertEqual(window.discovery_status.text(), "Incomplete")

    def test_status_bar_orders_separate_fields_and_shows_ready(self):
        settings = sample_settings()
        settings["layouts"]["Home"]["connection"]["host"] = "localhost"
        save_settings(settings, self.path)
        with (
            patch("workbench.window.TcpConnection", RecordingTcpConnection),
            patch("workbench.response_timeout.RESPONSE_TIMEOUT_MS", 30),
        ):
            window = self.open_window()
            window.show()
            window.connect_layout()
            self.app.processEvents()
            self.assertEqual(window.layout_status.text(), "Home")
            self.assertEqual(window.discovery_status.text(), "Discovering…")
            self.assertTrue(window.discovery_status.isVisible())
            self.assertTrue(window.discovery_separator.isVisible())
            self.assertEqual(window.connection_status.text(), "Connected")
            self.assertLess(window.layout_status.x(), window.discovery_separator.x())
            self.assertLess(window.discovery_separator.x(), window.discovery_status.x())
            self.assertLess(window.discovery_status.x(), window.connection_status.x())
            connection = window.connections["Home"]
            connection.frame_received.emit(b":SB040NB601020D2203;")
            connection.frame_received.emit(b":SB040N9B01020006;")
            for index in (2, 4, 5, 6):
                connection.frame_received.emit(f":SB040N9B0102{index:02X}00;".encode())
            connection.frame_received.emit(b":SB040N74010200;")
            QTest.qWait(60)
            self.assertEqual(window.discovery_status.text(), "Ready")
            self.assertTrue(window.discovery_status.isVisible())
            self.assertEqual(window.connection_status.text(), "Connected")

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
        self.assertEqual(table.rowCount(), 7)
        self.assertTrue(
            any(
                "First: node 258 (manufacturer 13, type 35, flags 3)"
                == table.item(row, 3).text()
                for row in range(table.rowCount())
            )
        )

    def test_identical_pnn_frames_are_both_shown_but_discovered_once(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        service = window.cbus_services["Default"]
        discoveries = []
        service.node_discovered.connect(discoveries.append)
        table = window.diagnostics_dock.widget().table

        frame = b":SB040NB601020D2203;"
        connection.frame_received.emit(frame)
        connection.frame_received.emit(frame)

        pnn_rows = [
            (table.item(row, 1).text(), table.item(row, 3).text())
            for row in range(table.rowCount())
            if table.item(row, 2).text() == "PNN"
        ]
        expected = (
            "RX",
            "Default: node 258 (manufacturer 13, type 34, flags 3)",
        )
        self.assertEqual(pnn_rows, [expected, expected])
        self.assertEqual(discoveries, [Pnn(258, 13, 34, 3)])
        self.assertEqual(window.layouts["Default"].node_view.node_list.count(), 1)

    def test_diagnostics_shows_sent_and_network_frames_once(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        table = window.diagnostics_dock.widget().table

        connection.frame_received.emit(b":SB040NB601020D2203;")
        connection.frame_received.emit(b":SB040N9B01020002;")
        connection.frame_received.emit(b":SB060N73010304;")  # Another application.
        connection.frame_received.emit(b":SB060N9B01030405;")
        connection.frame_received.emit(b":SB060N00;")

        records = [
            tuple(table.item(row, column).text() for column in (1, 2, 3))
            for row in range(table.rowCount())
        ]
        self.assertEqual(records[0], ("TX", "QNN", "Default: CAN ID 126"))
        self.assertEqual(
            [record for record in records if record[1] == "PNN"],
            [
                (
                    "RX",
                    "PNN",
                    "Default: node 258 (manufacturer 13, type 34, flags 3)",
                )
            ],
        )
        self.assertIn(("TX", "RQNPN", "Default: node 258, parameter 0"), records)
        self.assertIn(("RX", "PARAN", "Default: node 258, parameter 0 = 2"), records)
        self.assertIn(("RX", "RQNPN", "Default: node 259, parameter 4"), records)
        self.assertIn(("RX", "PARAN", "Default: node 259, parameter 4 = 5"), records)
        self.assertIn(("RX", "0x00", "Default: :SB060N00;"), records)

    def test_frame_diagnostics_use_renamed_layout_on_reused_connection(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        table = window.diagnostics_dock.widget().table
        frame = b":SB060N00;"

        connection.send(frame)
        connection.frame_received.emit(frame)
        connection.disconnect()

        def rename(dialog):
            dialog.name_edit.setText("Renamed")
            return QDialog.DialogCode.Accepted

        with (
            patch("workbench.app_settings.settings_path", return_value=self.path),
            patch.object(LayoutSettingsDialog, "exec", rename),
        ):
            window.edit_layout()

        self.assertIs(window.connections["Renamed"], connection)
        self.assertEqual(connection.layout_name, "Renamed")
        window.connect_layout()
        self.assertIs(window.connections["Renamed"], connection)
        connection.send(frame)
        connection.frame_received.emit(frame)

        records = [
            (table.item(row, 1).text(), table.item(row, 3).text())
            for row in range(table.rowCount())
            if table.item(row, 2).text() == "0x00"
        ]
        self.assertEqual(
            records,
            [
                ("TX", "Default: :SB060N00;"),
                ("RX", "Default: :SB060N00;"),
                ("TX", "Renamed: :SB060N00;"),
                ("RX", "Renamed: :SB060N00;"),
            ],
        )

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
        item = first_view.node_list.item(0)
        self.assertIs(first_view.node_list.currentItem(), item)
        self.assertEqual(first_view.details.node_number.text(), "258")
        first_action = next(
            action
            for action in window.layout_group.actions()
            if action.data() == "First"
        )
        first_action.setChecked(True)
        window.select_layout(first_action)
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
        self.assertIs(
            default_view.node_list.currentItem(), default_view.node_list.item(0)
        )
        self.assertEqual(default_view.details.node_number.text(), "259")
        self.assertEqual(first_view.node_list.item(0).text(), "258 - 35")

        window.connections["First"].disconnect()
        self.assertEqual(first_view.node_list.count(), 0)
        self.assertIsNone(first_view.node_list.currentItem())
        self.assertIsNone(first_view.details.node)
        self.assertEqual(first_view.details.node_number.text(), "-")
        self.assertEqual(default_view.node_list.count(), 1)

    def test_navigator_keeps_selection_on_later_discoveries(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        view = window.layouts["Default"].node_view
        navigator = view.node_list

        connection.frame_received.emit(b":SB040NB601020D2203;")
        first_item = navigator.item(0)
        connection.frame_received.emit(b":SB040NB601030D2303;")
        self.assertIs(navigator.currentItem(), first_item)
        self.assertEqual(view.details.node_number.text(), "258")

        navigator.clearSelection()
        self.assertEqual(navigator.selectedItems(), [])
        navigator.setCurrentItem(None)
        self.assertIsNone(navigator.currentItem())
        connection.frame_received.emit(b":SB040NB601040D2403;")
        self.assertEqual(navigator.selectedItems(), [])
        self.assertIsNone(navigator.currentItem())
        self.assertIsNone(view.details.node)

    def test_pnn_flags_update_selected_capabilities_and_clear_on_disconnect(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        view = window.layouts["Default"].node_view
        details = view.details

        for flags, expected in (
            (0x00, ("SLiM", "No", "No", "No", "No")),
            (0x01, ("SLiM", "No", "Yes", "No", "No")),
            (0x02, ("SLiM", "Yes", "No", "No", "No")),
            (0x04, ("FLiM", "No", "No", "No", "No")),
            (0x08, ("SLiM", "No", "No", "No", "Yes")),
            (0x10, ("SLiM", "No", "No", "Yes", "No")),
            (0x1F, ("FLiM", "Yes", "Yes", "Yes", "Yes")),
            (0x20, ("SLiM", "No", "No", "No", "No")),
            (0xC0, ("SLiM", "No", "No", "No", "No")),
        ):
            with self.subTest(flags=flags):
                connection.frame_received.emit(
                    f":SB040NB601020D22{flags:02X};".encode()
                )
                self.assertEqual(view.node_list.count(), 1)
                self.assertIs(view.node_list.currentItem(), view.node_list.item(0))
                self.assertEqual(details.flags.text(), f"0x{flags:02X}")
                self.assertEqual(
                    (
                        details.node_mode.text(),
                        details.producer.text(),
                        details.consumer.text(),
                        details.consumes_own_events.text(),
                        details.supports_bootloading.text(),
                    ),
                    expected,
                )
                self.assertEqual(details.summary_mode.text(), f"Mode: {expected[0]}")
                self.assertEqual(details.can_id.text(), "2")
                self.assertEqual(details.status.text(), "Online")

        connection.disconnect()
        self.assertEqual(details.flags.text(), "-")
        self.assertEqual(details.node_mode.text(), "-")
        self.assertEqual(details.producer.text(), "-")
        self.assertEqual(details.consumer.text(), "-")
        self.assertEqual(details.consumes_own_events.text(), "-")
        self.assertEqual(details.supports_bootloading.text(), "-")
        self.assertEqual(details.summary_mode.text(), "Mode: -")

    def test_selected_node_details_refresh_from_confirmed_parameters(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        view = window.layouts["Default"].node_view
        connection.frame_received.emit(b":SB040NB601020D2203;")
        selected = view.node_list.currentItem()
        details = view.details

        connection.frame_received.emit(b":SB040N9B01020703;")
        self.assertIs(view.node_list.currentItem(), selected)
        self.assertEqual(details.firmware.text(), "3")
        connection.frame_received.emit(b":SB040N9B01020264;")
        self.assertEqual(details.firmware.text(), "3d")
        self.assertEqual(details.summary_firmware.text(), "Firmware: 3d")
        connection.frame_received.emit(b":SB040N9B01020400;")
        connection.frame_received.emit(b":SB040N9B01020514;")
        connection.frame_received.emit(b":SB040N9B01020600;")
        self.assertEqual(details.event_count.text(), "0")
        self.assertEqual(details.ev_count.text(), "20")
        self.assertEqual(details.nv_count.text(), "0")
        self.assertEqual(details.manufacturer.text(), "13")
        self.assertEqual(details.module_type.text(), "34")
        self.assertEqual(details.flags.text(), "0x03")
        self.assertEqual(details.node_name.text(), "-")
        self.assertEqual(details.cpu_name.text(), "-")
        connection.frame_received.emit(b":SB040N9B01021301;")
        self.assertEqual(details.cpu_name.text(), "-")
        connection.frame_received.emit(b":SB040N9B0102090D;")
        self.assertEqual(details.cpu_name.text(), "P18F25K80")
        connection.frame_received.emit(b":SB040N9B01020A01;")
        self.assertEqual(details.interface.text(), "CAN")
        connection.frame_received.emit(b":SB040N9B01020900;")
        connection.frame_received.emit(b":SB040N9B01020A00;")
        self.assertEqual(details.cpu_name.text(), "-")
        self.assertEqual(details.interface.text(), "-")
        self.assertEqual(details.event_count.text(), "0")
        self.assertEqual(details.nv_count.text(), "0")
        connection.frame_received.emit(b":SB040NB601020D2307;")
        self.assertEqual(details.module_type.text(), "35")
        self.assertEqual(details.flags.text(), "0x07")
        self.assertEqual(details.firmware.text(), "3d")
        self.assertEqual(details.event_count.text(), "0")

    def test_live_nv_count_and_progressive_values_keep_selection_and_rows(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        view = window.layouts["Default"].node_view
        connection.frame_received.emit(b":SB040NB601020D2203;")
        selected = view.node_list.currentItem()
        details = view.details
        table = details.raw_values
        # Finish parameter discovery so these NVANS answer actual queued reads.
        connection.frame_received.emit(b":SB040N9B01020006;")
        for index in (2, 4, 5):
            connection.frame_received.emit(f":SB040N9B0102{index:02X}00;".encode())
        connection.frame_received.emit(b":SB040N9B01020603;")

        self.assertTrue(
            details.tabs.isTabEnabled(details.tabs.indexOf(details.variables_page))
        )
        self.assertIs(details.variables.currentWidget(), table)
        self.assertEqual(table.editTriggers(), table.EditTrigger.NoEditTriggers)
        self.assertEqual(
            [
                (table.item(row, 0).text(), table.item(row, 1).text())
                for row in range(3)
            ],
            [("1", "-"), ("2", "-"), ("3", "-")],
        )
        first_row = table.item(0, 0)
        connection.frame_received.emit(b":SB040N970102012A;")
        connection.frame_received.emit(b":SB040N9701020200;")
        self.assertIs(view.node_list.currentItem(), selected)
        self.assertIs(table.item(0, 0), first_row)
        self.assertEqual(
            [table.item(row, 1).text() for row in range(3)],
            ["42", "0", "-"],
        )

    def test_live_nv_values_follow_selection_and_unknown_count(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        view = window.layouts["Default"].node_view
        connection.frame_received.emit(b":SB040NB601020D2203;")
        connection.frame_received.emit(b":SB040NB601030D2303;")
        service = window.cbus_services["Default"]
        service.record_nv(258, 1, 7)
        service.record_nv(259, 3, 0)
        table = view.details.raw_values
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual((table.item(0, 0).text(), table.item(0, 1).text()), ("1", "7"))

        view.node_list.setCurrentItem(view.node_list.item(1))
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual((table.item(0, 0).text(), table.item(0, 1).text()), ("3", "0"))
        connection.frame_received.emit(b":SB040N9B01030603;")
        self.assertEqual(
            [table.item(row, 1).text() for row in range(3)],
            ["-", "-", "0"],
        )
        view.node_list.setCurrentItem(view.node_list.item(0))
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 1).text(), "7")

    def test_live_nv_display_clears_on_disconnect_and_reconnect(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        view = window.layouts["Default"].node_view
        connection.frame_received.emit(b":SB040NB601020D2203;")
        service = window.cbus_services["Default"]
        service.record_nv(258, 1, 42)
        self.assertEqual(view.details.raw_values.item(0, 1).text(), "42")

        connection.disconnect()
        self.assertEqual(view.details.raw_values.rowCount(), 0)
        connection.connect()
        connection.frame_received.emit(b":SB040NB601020D2203;")
        connection.frame_received.emit(b":SB040N9B01020601;")
        self.assertEqual(view.details.raw_values.item(0, 1).text(), "-")
        window.cbus_services["Default"].record_nv(258, 1, 0)
        self.assertEqual(view.details.raw_values.item(0, 1).text(), "0")

    def test_switching_nodes_shows_each_nodes_confirmed_parameters(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        view = window.layouts["Default"].node_view
        connection.frame_received.emit(b":SB040NB601020D2203;")
        connection.frame_received.emit(b":SB040NB601030D2303;")
        connection.frame_received.emit(b":SB040N9B01030409;")
        connection.frame_received.emit(b":SB040N9B01030700;")
        connection.frame_received.emit(b":SB040N9B01030261;")
        connection.frame_received.emit(b":SB040N9B01030901;")
        connection.frame_received.emit(b":SB040N9B01030A02;")
        connection.frame_received.emit(b":SB040N9B01031301;")

        self.assertEqual(view.details.event_count.text(), "-")
        self.assertEqual(view.details.firmware.text(), "-")
        self.assertEqual(view.details.cpu_name.text(), "-")
        self.assertEqual(view.details.interface.text(), "-")
        view.node_list.setCurrentItem(view.node_list.item(1))
        self.assertEqual(view.details.node_number.text(), "259")
        self.assertEqual(view.details.event_count.text(), "9")
        self.assertEqual(view.details.firmware.text(), "0a")
        self.assertEqual(view.details.ev_count.text(), "-")
        self.assertEqual(view.details.cpu_name.text(), "P18F2480")
        self.assertEqual(view.details.interface.text(), "Ethernet")
        view.node_list.setCurrentItem(view.node_list.item(0))
        self.assertEqual(view.details.event_count.text(), "-")
        self.assertEqual(view.details.firmware.text(), "-")
        self.assertEqual(view.details.cpu_name.text(), "-")
        self.assertEqual(view.details.interface.text(), "-")

    def test_beta_build_updates_firmware_and_summary(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        details = window.layouts["Default"].node_view.details
        connection.frame_received.emit(b":SB040NB601020D2203;")

        connection.frame_received.emit(b":SB040N9B01021401;")
        connection.frame_received.emit(b":SB040N9B01020264;")
        self.assertEqual(details.firmware.text(), "-")
        self.assertEqual(details.summary_firmware.text(), "Firmware: -")
        connection.frame_received.emit(b":SB040N9B01020703;")
        self.assertEqual(details.firmware.text(), "3d Beta 1")
        self.assertEqual(details.summary_firmware.text(), "Firmware: 3d Beta 1")
        connection.frame_received.emit(b":SB040N9B01021400;")
        self.assertEqual(details.firmware.text(), "3d")
        self.assertEqual(details.summary_firmware.text(), "Firmware: 3d")

    def test_parameter_presentation_is_isolated_and_cleared_on_disconnect(self):
        self.save_startup_layouts(
            [("First", "TCP/IP", True), ("Default", "Serial", True)]
        )
        window = self.start_with_recording_connections()
        first = window.connections["First"]
        second = window.connections["Default"]
        first_view = window.layouts["First"].node_view
        second_view = window.layouts["Default"].node_view
        pnn = b":SB040NB601020D2203;"
        first.frame_received.emit(pnn)
        second.frame_received.emit(pnn)
        first.frame_received.emit(b":SB040N9B01020405;")
        first.frame_received.emit(b":SB040N9B0102090D;")
        first.frame_received.emit(b":SB040N9B01021301;")
        first.frame_received.emit(b":SB040N9B01020A01;")
        first.frame_received.emit(b":SB040N9B01020703;")
        first.frame_received.emit(b":SB040N9B01021401;")
        self.assertEqual(first_view.details.event_count.text(), "5")
        self.assertEqual(first_view.details.cpu_name.text(), "P18F25K80")
        self.assertEqual(first_view.details.interface.text(), "CAN")
        self.assertEqual(first_view.details.firmware.text(), "3 Beta 1")
        self.assertEqual(second_view.details.event_count.text(), "-")
        second.frame_received.emit(b":SB040N9B01020400;")
        self.assertEqual(second_view.details.event_count.text(), "0")

        first.disconnect()
        self.assertEqual(first_view.node_list.count(), 0)
        self.assertEqual(first_view.details.event_count.text(), "-")
        self.assertEqual(first_view.details.firmware.text(), "-")
        self.assertEqual(first_view.details.summary_firmware.text(), "Firmware: -")
        self.assertEqual(first_view.details.cpu_name.text(), "-")
        self.assertEqual(first_view.details.interface.text(), "-")
        self.assertEqual(second_view.details.event_count.text(), "0")

        first.connect()
        first.frame_received.emit(pnn)
        self.assertEqual(first_view.details.event_count.text(), "-")
        self.assertEqual(first_view.details.cpu_name.text(), "-")
        self.assertEqual(first_view.details.interface.text(), "-")

    def test_reconnect_clears_discovery_and_sends_one_new_query(self):
        self.save_startup_layouts([("Default", "TCP/IP", True)])
        window = self.start_with_recording_connections()
        connection = window.connections["Default"]
        first_service = window.cbus_services["Default"]
        connection.frame_received.emit(b":SB040NB601020D2203;")
        self.assertEqual(first_service.nodes, {258: Pnn(258, 13, 34, 3)})
        navigator = window.layouts["Default"].node_view.node_list
        self.assertEqual(navigator.count(), 1)
        first_service.record_nv(258, 1, 42)
        self.assertEqual(first_service.node_states[258].nv_values, {1: 42})

        window.disconnect_layout()
        self.assertEqual(window.cbus_services, {})
        self.assertEqual(navigator.count(), 0)
        self.assertIsNone(window.layouts["Default"].node_view.state_lookup)
        connection.frame_received.emit(b":SB040NB601030D2203;")
        self.assertEqual(first_service.nodes, {258: Pnn(258, 13, 34, 3)})
        self.assertEqual(navigator.count(), 0)

        window.connect_layout()
        self.assertEqual(
            connection.sent,
            [b":SBFC0N0D;", b":SBFC0N73010200;", b":SBFC0N0D;"],
        )
        self.assertIsNot(window.cbus_services["Default"], first_service)
        self.assertEqual(window.cbus_services["Default"].nodes, {})
        self.assertEqual(window.cbus_services["Default"].node_states, {})
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
