"""Serial open/close behavior and the layout actions that own the port."""

from __future__ import annotations

import os
import unittest
from typing import ClassVar
from unittest.mock import patch

from layout_fixture import sample_settings
from PySide6.QtCore import QObject, Signal
from PySide6.QtSerialPort import QSerialPort
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from workbench.logging_config import TRACE
from workbench.pnn import Pnn
from workbench.send_frame_dialog import SendFrameDialog
from workbench.serial_connection import SerialConnection
from workbench.window import MainWindow


class FakeSerialPort(QObject):
    SerialPortError = QSerialPort.SerialPortError
    errorOccurred = Signal(QSerialPort.SerialPortError)
    readyRead = Signal()
    ports: ClassVar[list[FakeSerialPort]] = []
    open_succeeds = True

    def __init__(self, parent):
        super().__init__(parent)
        self.name = ""
        self.is_open = False
        self.close_count = 0
        self.incoming = bytearray()
        self.written = bytearray()
        self.write_result = None
        self.close_error = False
        self.ports.append(self)

    def setPortName(self, name):
        self.name = name

    def open(self, mode):
        if not self.open_succeeds:
            self.errorOccurred.emit(QSerialPort.SerialPortError.DeviceNotFoundError)
            return False
        self.is_open = True
        self.errorOccurred.emit(QSerialPort.SerialPortError.NoError)
        return True

    def close(self):
        was_open = self.is_open
        self.is_open = False
        self.close_count += 1
        if not was_open:
            self.errorOccurred.emit(QSerialPort.SerialPortError.NotOpenError)
        if self.close_error:
            self.close_error = False
            self.errorOccurred.emit(QSerialPort.SerialPortError.ResourceError)

    def isOpen(self):
        return self.is_open

    def write(self, data):
        if self.write_result is not None:
            return self.write_result
        self.written.extend(data)
        return len(data)

    def errorString(self):
        return "Device could not be opened"

    def error(self):
        return QSerialPort.SerialPortError.DeviceNotFoundError

    def readAll(self):
        data = bytes(self.incoming)
        self.incoming.clear()
        return data

    def feed(self, data):
        self.incoming.extend(data)
        self.readyRead.emit()


class SerialConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        FakeSerialPort.ports = []
        FakeSerialPort.open_succeeds = True
        self.port_patch = patch(
            "workbench.serial_connection.QSerialPort", FakeSerialPort
        )
        self.port_patch.start()
        self.addCleanup(self.port_patch.stop)

    def test_open_and_disconnect_report_state_and_close_port(self):
        connection = SerialConnection("Test Layout", self.app)
        states = []
        failures = []
        connection.state_changed.connect(states.append)
        connection.failed.connect(failures.append)

        connection.connect("/dev/serial/by-id/usb-SPROG_DCC_CAN_USB4-if00")
        port = FakeSerialPort.ports[-1]
        self.assertEqual(port.name, "/dev/serial/by-id/usb-SPROG_DCC_CAN_USB4-if00")
        self.assertTrue(port.is_open)
        self.assertEqual(connection.state, "Connected")

        connection.disconnect()
        self.assertFalse(port.is_open)
        self.assertEqual(states, ["Connected", "Disconnected"])
        self.assertEqual(port.close_count, 1)
        self.assertEqual(failures, [])

    def test_disconnect_already_closed_port_is_harmless(self):
        connection = SerialConnection("Test Layout", self.app)
        failures = []
        connection.failed.connect(failures.append)
        connection.connect("/dev/ttyACM1")
        port = FakeSerialPort.ports[-1]

        connection.disconnect()
        connection.disconnect()

        self.assertEqual(connection.state, "Disconnected")
        self.assertEqual(port.close_count, 1)
        self.assertEqual(failures, [])

    def test_open_failure_reports_error_and_allows_retry(self):
        FakeSerialPort.open_succeeds = False
        connection = SerialConnection("Test Layout", self.app)
        port = FakeSerialPort.ports[-1]
        port.close_error = True
        failures = []
        connection.failed.connect(failures.append)

        connection.connect("/dev/ttyACM1")
        self.assertEqual(connection.state, "Error")
        self.assertEqual(failures, ["Device could not be opened"])
        self.assertFalse(port.is_open)
        self.assertEqual(port.close_count, 1)

        FakeSerialPort.open_succeeds = True
        connection.connect("/dev/ttyACM1")
        self.assertEqual(connection.state, "Connected")

    def test_each_failed_open_reports_once_even_on_retry(self):
        FakeSerialPort.open_succeeds = False
        connection = SerialConnection("Test Layout", self.app)
        port = FakeSerialPort.ports[-1]
        failures = []
        connection.failed.connect(failures.append)

        port.close_error = True
        connection.connect("/dev/ttyACM1")
        self.assertEqual(failures, ["Device could not be opened"])
        self.assertEqual(port.close_count, 1)
        port.close_error = True
        connection.connect("/dev/ttyACM1")
        self.assertEqual(
            failures, ["Device could not be opened", "Device could not be opened"]
        )
        self.assertEqual(port.close_count, 2)
        self.assertEqual(connection.state, "Error")

    def test_error_emitted_during_close_does_not_reenter_handler(self):
        connection = SerialConnection("Test Layout", self.app)
        failures = []
        connection.failed.connect(failures.append)
        connection.connect("/dev/ttyACM1")
        port = FakeSerialPort.ports[-1]
        port.close_error = True

        port.errorOccurred.emit(QSerialPort.SerialPortError.ResourceError)

        self.assertEqual(connection.state, "Error")
        self.assertFalse(port.is_open)
        self.assertEqual(port.close_count, 1)
        self.assertEqual(failures, ["Device could not be opened"])

    def test_complete_frame_is_emitted_and_logged(self):
        connection = SerialConnection("Test Layout", self.app)
        frames = []
        connection.frame_received.connect(frames.append)
        connection.connect("/dev/ttyACM1")

        with self.assertLogs("workbench.connection", level=TRACE) as captured:
            FakeSerialPort.ports[-1].feed(b":S123N00;")

        self.assertEqual(frames, [b":S123N00;"])
        self.assertEqual(captured.records[0].fields["layout"], "Test Layout")
        self.assertEqual(captured.records[0].fields["frame"], ":S123N00;")

    def test_split_and_multiple_frames_across_reads(self):
        connection = SerialConnection("Test Layout", self.app)
        frames = []
        connection.frame_received.connect(frames.append)
        connection.connect("/dev/ttyACM1")
        port = FakeSerialPort.ports[-1]

        port.feed(b"noise:S123N")
        self.assertEqual(frames, [])
        port.feed(b"00;:S456N01;:S789N")
        self.assertEqual(frames, [b":S123N00;", b":S456N01;"])
        port.feed(b"02;")
        self.assertEqual(frames, [b":S123N00;", b":S456N01;", b":S789N02;"])

    def test_incomplete_frame_is_dropped_on_disconnect_and_failure(self):
        connection = SerialConnection("Test Layout", self.app)
        frames = []
        connection.frame_received.connect(frames.append)
        connection.connect("/dev/ttyACM1")
        port = FakeSerialPort.ports[-1]

        port.feed(b":S123N")
        connection.disconnect()
        connection.connect("/dev/ttyACM1")
        port.feed(b"00;:S456N01;")
        self.assertEqual(frames, [b":S456N01;"])

        port.feed(b":S789N")
        port.errorOccurred.emit(QSerialPort.SerialPortError.ResourceError)
        connection.connect("/dev/ttyACM1")
        port.feed(b"02;:S111N03;")
        self.assertEqual(frames, [b":S456N01;", b":S111N03;"])

    def test_send_queues_exact_frames_and_logs_each_one(self):
        connection = SerialConnection("Test Layout", self.app)
        sent = []
        connection.frame_sent.connect(sent.append)
        connection.connect("/dev/ttyACM1")
        port = FakeSerialPort.ports[-1]

        with self.assertLogs("workbench.connection", level=TRACE) as captured:
            connection.send(b":S123N00;")
            connection.send(b":S456N01;")

        self.assertEqual(port.written, b":S123N00;:S456N01;")
        self.assertEqual(sent, [b":S123N00;", b":S456N01;"])
        self.assertEqual(
            [record.fields["frame"] for record in captured.records],
            [":S123N00;", ":S456N01;"],
        )
        self.assertTrue(
            all(record.fields["layout"] == "Test Layout" for record in captured.records)
        )

    def test_send_rejects_invalid_frames_and_disconnected_port(self):
        connection = SerialConnection("Test Layout", self.app)
        connection.connect("/dev/ttyACM1")
        port = FakeSerialPort.ports[-1]

        for frame in (b"", b":;", b"S123N00;", b":S123N00", b":S1;:S2;", b":S\xff;"):
            with (
                self.subTest(frame=frame),
                self.assertRaisesRegex(ValueError, "one complete printable ASCII"),
            ):
                connection.send(frame)
        self.assertEqual(port.written, b"")

        connection.disconnect()
        with self.assertRaisesRegex(ConnectionError, "not connected"):
            connection.send(b":S123N00;")
        self.assertEqual(port.written, b"")

    def test_send_reports_immediate_write_failure(self):
        connection = SerialConnection("Test Layout", self.app)
        connection.connect("/dev/ttyACM1")
        port = FakeSerialPort.ports[-1]
        port.write_result = -1

        with self.assertRaisesRegex(OSError, "Could not queue GridConnect frame"):
            connection.send(b":S123N00;")
        self.assertEqual(port.written, b"")


class SerialLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        FakeSerialPort.ports = []
        FakeSerialPort.open_succeeds = True
        self.port_patch = patch(
            "workbench.serial_connection.QSerialPort", FakeSerialPort
        )
        self.port_patch.start()
        self.addCleanup(self.port_patch.stop)
        with patch("workbench.window.load_settings", return_value=sample_settings()):
            self.window = MainWindow()
        save_patch = patch("workbench.window.save_settings")
        save_patch.start()
        self.addCleanup(save_patch.stop)
        self.window.layout_settings["Home"].update(
            connection_type="Serial",
            serial_port="/dev/serial/by-id/usb-SPROG_DCC_CAN_USB4-if00",
        )
        self.window.update_connection_actions()
        self.addCleanup(self.window.close)

    def test_layout_actions_use_configured_device_and_disconnect(self):
        self.assertTrue(self.window.connect_action.isEnabled())
        self.window.connect_action.trigger()
        port = FakeSerialPort.ports[-1]

        self.assertEqual(port.name, self.window.layout_settings["Home"]["serial_port"])
        self.assertEqual(self.window.connection_status.text(), "Connected")
        self.assertTrue(self.window.disconnect_action.isEnabled())
        self.assertTrue(self.window.send_frame_action.isEnabled())

        self.window.disconnect_action.trigger()
        self.assertFalse(port.is_open)
        self.assertEqual(self.window.connection_status.text(), "Disconnected")
        self.assertFalse(self.window.send_frame_action.isEnabled())

    def test_manual_connection_discovers_nodes_and_reconnect_starts_fresh(self):
        self.window.layout_settings["Home"]["can_id"] = 127
        self.window.connect_layout()
        port = FakeSerialPort.ports[-1]
        first_service = self.window.cbus_services["Home"]
        self.assertEqual(port.written, b":SBFE0N0D;")

        port.feed(b":SB040NB601020D2203;")
        self.assertEqual(first_service.nodes, {258: Pnn(258, 13, 34, 3)})
        table = self.window.diagnostics_dock.widget().table
        self.assertEqual(table.rowCount(), 3)
        self.assertIn("Home: node 258 (manufacturer 13", table.item(1, 3).text())
        self.assertEqual(table.item(2, 2).text(), "RQNPN")

        self.window.disconnect_layout()
        self.assertEqual(self.window.cbus_services, {})
        self.window.connect_layout()
        self.assertIsNot(self.window.cbus_services["Home"], first_service)
        self.assertEqual(self.window.cbus_services["Home"].nodes, {})
        self.assertEqual(port.written, b":SBFE0N0D;:SBFE0N73010200;:SBFE0N0D;")

        with patch.object(QMessageBox, "warning"):
            port.errorOccurred.emit(QSerialPort.SerialPortError.ResourceError)
        self.assertEqual(self.window.connection_states["Home"], "Error")
        self.assertEqual(self.window.cbus_services, {})

    def test_existing_dialog_sends_serial_frames_and_keeps_status(self):
        self.window.connect_layout()
        port = FakeSerialPort.ports[-1]
        connection = self.window.connections["Home"]
        dialog = SendFrameDialog("Home", connection, self.window)
        dialog.show()

        dialog.frame_edit.setText("S123N00")
        dialog.send_button.click()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.status_label.text(), "Frame sent (1)")
        self.assertEqual(port.written, b":SBFC0N0D;:S123N00;")

        dialog.frame_edit.setText(":S456N01;")
        self.assertEqual(dialog.status_label.text(), "")
        dialog.send_button.click()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.status_label.text(), "Frame sent (2)")
        self.assertEqual(port.written, b":SBFC0N0D;:S123N00;:S456N01;")

        dialog.frame_edit.setText(":S1;:S2;")
        messages = []
        with (
            patch.object(
                QMessageBox, "warning", side_effect=lambda _p, _t, m: messages.append(m)
            ),
            self.assertNoLogs("workbench.connection", level="ERROR"),
        ):
            dialog.send_button.click()
        self.assertTrue(dialog.isVisible())
        self.assertIn("complete printable ASCII", messages[0])
        self.assertEqual(dialog.status_label.text(), "")
        self.assertEqual(port.written, b":SBFC0N0D;:S123N00;:S456N01;")

        buttons = dialog.findChild(QDialogButtonBox)
        buttons.button(QDialogButtonBox.StandardButton.Close).click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_serial_send_menu_opens_existing_dialog(self):
        self.window.connect_layout()
        with patch("workbench.window.SendFrameDialog") as dialog_type:
            self.window.send_frame_action.trigger()
        dialog_type.assert_called_once_with(
            "Home", self.window.connections["Home"], self.window
        )

    def test_serial_dialog_write_error_is_logged_and_keeps_it_open(self):
        self.window.connect_layout()
        port = FakeSerialPort.ports[-1]
        port.write_result = -1
        dialog = SendFrameDialog("Home", self.window.connections["Home"], self.window)
        dialog.show()
        dialog.frame_edit.setText(":S123N00;")
        messages = []

        with (
            patch.object(
                QMessageBox, "warning", side_effect=lambda _p, _t, m: messages.append(m)
            ),
            self.assertLogs("workbench.connection", level="ERROR") as captured,
        ):
            dialog.send_button.click()

        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].fields["layout"], "Home")
        self.assertEqual(captured.records[0].fields["operation"], "send_frame")
        self.assertIsNone(captured.records[0].exc_info)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.status_label.text(), "")
        self.assertEqual(dialog.send_count, 0)
        self.assertIn("Could not queue GridConnect frame", messages[0])
        dialog.close()

    def test_open_failure_is_logged_and_shown_in_existing_dialog(self):
        FakeSerialPort.open_succeeds = False
        messages = []
        with (
            patch.object(
                QMessageBox, "warning", side_effect=lambda _p, _t, m: messages.append(m)
            ),
            self.assertLogs("workbench.connection", level="ERROR") as captured,
        ):
            self.window.connect_layout()

        self.assertEqual(self.window.connection_status.text(), "Error")
        self.assertIn("Device could not be opened", messages[0])
        self.assertIn("Serial connection failed", captured.output[0])

    def test_disconnect_then_delete_and_window_close_release_ports(self):
        self.window.connect_layout()
        first_port = FakeSerialPort.ports[-1]
        self.assertFalse(self.window.delete_action.isEnabled())
        self.window.disconnect_layout()
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            self.window.delete_layout()
        self.assertFalse(first_port.is_open)
        self.assertNotIn("Home", self.window.connections)

        other = self.window.layout_group.checkedAction()
        self.window.layout_settings[other.data()].update(
            connection_type="Serial", serial_port="/dev/ttyACM1"
        )
        self.window.connect_layout()
        second_port = FakeSerialPort.ports[-1]
        self.window.close()
        self.assertFalse(second_port.is_open)
        self.assertEqual(self.window.cbus_services, {})

    def test_window_close_after_disconnect_does_not_report_failure(self):
        self.window.connect_layout()
        port = FakeSerialPort.ports[-1]
        self.window.disconnect_layout()
        self.assertEqual(self.window.connection_status.text(), "Disconnected")

        with patch.object(QMessageBox, "warning") as warning:
            self.window.close()

        self.assertEqual(port.close_count, 1)
        self.assertEqual(self.window.connection_states["Home"], "Disconnected")
        warning.assert_not_called()

    def test_changing_serial_device_path_after_disconnect_replaces_connection(self):
        self.window.connect_layout()
        port = FakeSerialPort.ports[-1]
        self.assertFalse(self.window.edit_action.isEnabled())
        self.window.disconnect_layout()
        updated = self.window.layout_settings["Home"].copy()
        updated["serial_port"] = "/dev/ttyACM1"
        with patch("workbench.window.LayoutSettingsDialog") as dialog_type:
            dialog = dialog_type.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.settings.return_value = updated
            self.window.edit_layout()

        self.assertFalse(port.is_open)
        self.assertNotIn("Home", self.window.connections)
        self.assertEqual(self.window.connection_status.text(), "Disconnected")
        self.window.connect_layout()
        self.assertEqual(FakeSerialPort.ports[-1].name, "/dev/ttyACM1")


if __name__ == "__main__":
    unittest.main()
