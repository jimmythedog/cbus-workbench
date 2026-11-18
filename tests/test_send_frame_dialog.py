"""The raw frame dialog and its availability in the Layout menu."""

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layout_fixture import sample_settings
from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
)

from workbench.cbus_service import DiscoveryProgress, NodeState
from workbench.node_backup_files import node_backup, save_backup
from workbench.pnn import Pnn
from workbench.send_event_dialog import SendEventDialog, send_existing
from workbench.send_frame_dialog import SendFrameDialog
from workbench.window import MainWindow


class SendFrameDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.server = QTcpServer()
        self.assertTrue(self.server.listen(QHostAddress.SpecialAddress.LocalHost, 0))
        with patch("workbench.window.load_settings", return_value=sample_settings()):
            self.window = MainWindow()
        self.window.layout_settings["Home"].update(
            host="127.0.0.1", port=self.server.serverPort()
        )
        self.peer = None

    def tearDown(self):
        self.window.close()
        if self.peer is not None:
            self.peer.close()
        self.server.close()
        self.app.processEvents()

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.005)
        self.fail("Timed out waiting for a Qt socket event")

    def connect_home(self):
        self.window.connect_layout()
        self.wait_for(lambda: self.window.connection_status.text() == "Connected")
        self.wait_for(self.server.hasPendingConnections)
        self.peer = self.server.nextPendingConnection()
        self.wait_for(lambda: self.peer.bytesAvailable() >= len(b":SBFC0N0D;"))
        self.assertEqual(bytes(self.peer.readAll()), b":SBFC0N0D;")

    def test_event_dialog_sends_exact_long_short_frames_and_stays_open(self):
        self.connect_home()
        service = self.window.cbus_services["Home"]
        dialog = SendEventDialog(service, self.window)
        dialog.show()
        self.app.processEvents()
        self.assertGreaterEqual(dialog.width(), 450)
        initial = dialog.size()
        growth = dialog.fontMetrics().height()
        dialog.resize(initial.width() + growth, initial.height() + growth)
        self.app.processEvents()
        self.assertGreater(dialog.width(), initial.width())
        self.assertGreater(dialog.height(), initial.height())
        self.assertFalse(dialog.on_button.isEnabled())
        service.nodes[513] = Pnn(513, 13, 34, 0)
        service.nodes[258] = Pnn(258, 13, 34, 0)
        dialog.short_radio.click()
        self.assertEqual(dialog.node_number.value(), 0)
        self.assertEqual(dialog.node_number.text(), "0")
        self.assertFalse(dialog.node_number.isEnabled())
        dialog.long_radio.click()
        self.assertTrue(dialog.node_number.isEnabled())
        self.assertEqual(dialog.node_number.value(), 513)
        dialog.node_number.setValue(258)
        dialog.event_number.setValue(65535)
        for event_type, on_frame, off_frame in (
            ("Long", b":SBFC0N900102FFFF;", b":SBFC0N910102FFFF;"),
            ("Short", b":SBFC0N980000FFFF;", b":SBFC0N990000FFFF;"),
        ):
            radio = dialog.long_radio if event_type == "Long" else dialog.short_radio
            radio.click()
            for button, expected in (
                (dialog.on_button, on_frame),
                (dialog.off_button, off_frame),
            ):
                button.click()
                self.wait_for(
                    lambda expected=expected: (
                        self.peer.bytesAvailable() >= len(expected)
                    )
                )
                self.assertEqual(bytes(self.peer.readAll()), expected)
                self.assertTrue(dialog.isVisible())
                self.assertEqual(
                    dialog.status.text(),
                    "ON frame sent" if button is dialog.on_button else "OFF frame sent",
                )
                diagnostics = self.window.diagnostics_dock.widget().table
                row = diagnostics.rowCount() - 1
                self.assertEqual(diagnostics.item(row, 1).text(), "TX")
                self.assertIn(expected.decode("ascii"), diagnostics.item(row, 3).text())
        self.window.disconnect_layout()
        self.assertFalse(dialog.on_button.isEnabled())
        self.assertFalse(dialog.off_button.isEnabled())
        for event_type, nn in (("Long", 258), ("Short", 0)):
            with (
                self.subTest(event_type=event_type),
                self.assertRaises(ConnectionError),
            ):
                service.send_event(event_type, nn, 1, True)
        dialog.close()

    def test_sent_events_appear_without_echo_and_received_echo_deduplicates(self):
        self.connect_home()
        view = self.window.layouts["Home"]
        observations = view.observed_events
        # Use an isolated collection so existing user data cannot satisfy the test.
        with TemporaryDirectory() as directory:
            observations.events.clear()
            observations.path = Path(directory) / "observed-events.yaml"
            view.refresh_observed_events()
            configured = {nn: dict(events) for nn, events in view.events.items()}
            dialog = SendEventDialog(self.window.cbus_services["Home"], self.window)
            self.addCleanup(dialog.close)
            dialog.short_radio.click()
            dialog.event_number.setValue(30001)
            dialog.on_button.click()
            table = view.layout_events.table
            self.assertEqual(table.topLevelItemCount(), 1)
            self.assertEqual(table.topLevelItem(0).text(0), "0:30001")
            self.wait_for(lambda: self.peer.bytesAvailable() > 0)
            self.assertEqual(bytes(self.peer.readAll()), b":SBFC0N9800007531;")
            dialog.long_radio.click()
            dialog.node_number.setValue(258)
            dialog.on_button.click()
            self.assertEqual(table.topLevelItemCount(), 2)
            self.assertEqual(table.topLevelItem(1).text(0), "258:30001")
            self.peer.write(b":SB040N9901037531;:SB040N9101027531;")
            self.peer.flush()
            self.wait_for(
                lambda: (
                    self.window.diagnostics_dock.widget()
                    .table.item(
                        self.window.diagnostics_dock.widget().table.rowCount() - 1, 1
                    )
                    .text()
                    == "RX"
                )
            )
            self.assertEqual(table.topLevelItemCount(), 2)
            self.assertEqual(view.events, configured)
            produced = view.node_view.details.node_events
            produced.show_produced_events(258)
            self.assertEqual(produced.produced_table.topLevelItemCount(), 1)

    def test_event_actions_use_selected_layout_without_fallback(self):
        self.assertFalse(self.window.send_event_action.isEnabled())
        self.connect_home()
        self.assertTrue(self.window.send_event_action.isEnabled())
        opened = []
        with patch.object(
            SendEventDialog, "exec", lambda dialog: opened.append(dialog.service)
        ):
            self.window.show_send_event_dialog()
            other = next(
                a
                for a in self.window.layout_group.actions()
                if a.data() == "Test Layout"
            )
            other.setChecked(True)
            self.window.select_layout(other)
            self.assertFalse(self.window.send_event_action.isEnabled())
            self.window.show_send_event_dialog()
        self.assertEqual(opened, [self.window.cbus_services["Home"]])
        self.assertEqual(self.peer.bytesAvailable(), 0)

    def test_event_uses_selected_connection_when_two_layouts_are_connected(self):
        self.connect_home()
        other_server = QTcpServer()
        self.assertTrue(other_server.listen(QHostAddress.SpecialAddress.LocalHost, 0))
        other_peer = None
        try:
            self.window.layout_settings["Test Layout"].update(
                host="127.0.0.1",
                port=other_server.serverPort(),
                can_id=100,
            )
            other = next(
                a
                for a in self.window.layout_group.actions()
                if a.data() == "Test Layout"
            )
            other.setChecked(True)
            self.window.select_layout(other)
            self.window.connect_layout()
            self.wait_for(lambda: self.window.connection_status.text() == "Connected")
            self.wait_for(other_server.hasPendingConnections)
            other_peer = other_server.nextPendingConnection()
            self.wait_for(lambda: other_peer.bytesAvailable() > 0)
            self.assertEqual(bytes(other_peer.readAll()), b":SBC80N0D;")

            def send_from_dialog(dialog):
                dialog.node_number.setValue(65535)
                dialog.event_number.setValue(0)
                dialog.on_button.click()
                dialog.short_radio.click()
                dialog.event_number.setValue(30001)
                dialog.off_button.click()

            with patch.object(SendEventDialog, "exec", send_from_dialog):
                self.window.show_send_event_dialog()
            expected = b":SBC80N90FFFF0000;:SBC80N9900007531;"
            self.wait_for(lambda: other_peer.bytesAvailable() >= len(expected))
            self.assertEqual(bytes(other_peer.readAll()), expected)
            self.assertEqual(self.peer.bytesAvailable(), 0)
        finally:
            self.window.disconnect_layout()
            if other_peer is not None:
                other_peer.close()
            other_server.close()

    def test_existing_events_send_on_off_immediately_without_opening_dialog(self):
        self.connect_home()
        service = self.window.cbus_services["Home"]
        with patch.object(
            SendEventDialog,
            "exec",
            side_effect=AssertionError("Event context actions must not open a dialog"),
        ):
            for identity, on, expected in (
                ((258, 0), True, b":SBFC0N9001020000;"),
                ((258, 0), False, b":SBFC0N9101020000;"),
                ((0, 30001), True, b":SBFC0N9800007531;"),
                ((0, 30001), False, b":SBFC0N9900007531;"),
            ):
                with self.subTest(identity=identity, on=on):
                    send_existing(self.window, service, identity, on)
                    self.wait_for(
                        lambda expected=expected: (
                            self.peer.bytesAvailable() >= len(expected)
                        )
                    )
                    self.assertEqual(bytes(self.peer.readAll()), expected)

    def test_event_validation_rejects_invalid_type_or_numbers(self):
        self.connect_home()
        service = self.window.cbus_services["Home"]
        for args in (
            ("Other", 1, 1, True),
            ("Long", 0, 1, True),
            ("Short", 1, 1, True),
            ("Short", 0, -1, True),
            ("Short", 0, 65536, False),
            ("Long", 65536, 1, True),
            ("Long", 1, -1, True),
            ("Short", 1, 65536, False),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                service.send_event(*args)
        self.assertEqual(self.peer.bytesAvailable(), 0)

    def test_event_transmission_error_is_reported_without_closing(self):
        self.connect_home()
        dialog = SendEventDialog(
            self.window.cbus_services["Home"], self.window, (258, 1)
        )
        dialog.show()
        with (
            patch.object(
                self.window.connections["Home"],
                "send",
                side_effect=OSError("Write failed"),
            ),
            patch.object(QMessageBox, "warning") as warning,
        ):
            dialog.on_button.click()
        self.assertEqual(warning.call_args.args[2], "Write failed")
        self.assertEqual(dialog.status.text(), "")
        self.assertTrue(dialog.isVisible())
        dialog.close()

    def test_requested_disconnect_waits_for_ev_learn_exit(self):
        self.connect_home()
        service = self.window.cbus_services["Home"]
        service.node_states[258] = NodeState(
            Pnn(258, 13, 34, 5),
            parameters={5: 2, 8: 5},
            event_identities={4: (0, 1000)},
            ev_values={4: {2: 12}},
            event_progress=DiscoveryProgress.COMPLETE,
            can_id=2,
        )
        service.ev_write.begin(258, {(0, 1000, 2): 13})
        expected = b":SBFC0N530102;:SBFC0N73010208;"
        self.wait_for(lambda: self.peer.bytesAvailable() >= len(expected))
        self.assertEqual(bytes(self.peer.readAll()), expected)
        self.peer.write(b":SB040N9B01020825;")
        expected = b":SBFC0ND2000003E8020D;"
        self.wait_for(lambda: self.peer.bytesAvailable() >= len(expected))
        self.assertEqual(bytes(self.peer.readAll()), expected)
        self.window.disconnect_layout()
        expected = b":SBFC0N540102;:SBFC0N73010208;"
        self.wait_for(lambda: self.peer.bytesAvailable() >= len(expected))
        self.assertEqual(bytes(self.peer.readAll()), expected)
        self.assertEqual(self.window.connection_status.text(), "Connected")
        self.peer.write(b":SB040N9B01020805;")
        self.wait_for(lambda: self.window.connection_status.text() == "Disconnected")

    def test_save_disconnect_preserves_result_through_offline_selection_rebuild(self):
        with (
            TemporaryDirectory() as directory,
            patch(
                "workbench.node_backup_files.application_directories",
                return_value={"Data": Path(directory)},
            ),
        ):
            self.connect_home()
            service = self.window.cbus_services["Home"]
            done = DiscoveryProgress.COMPLETE
            state = NodeState(
                Pnn(258, 13, 34, 4),
                parameters={5: 0, 6: 1},
                nv_values={1: 7},
                parameter_progress=done,
                nv_progress=done,
                event_progress=DiscoveryProgress.SKIPPED,
                ev_progress=DiscoveryProgress.SKIPPED,
                can_id=2,
            )
            service.node_states[258] = state
            service.nodes[258] = state.identity
            backup = node_backup(state)
            save_backup("home", backup)
            save_backup("home", {**backup, "node": 259})
            view = self.window.layouts["Home"].node_view
            view.show_identity(state.identity)
            service.discovery_status_changed.emit("Configuration ready")
            details = view.details
            details.tabs.setCurrentWidget(details.variables_page)
            details.edit_button.click()
            details.raw_values.item(0, 1).setText("9")
            results = []
            service.nv_save.finished.connect(lambda *args: results.append(args))
            details.save_button.click()
            self.wait_for(lambda: self.peer.bytesAvailable() > 0)
            self.assertIn(b"N9601020109", bytes(self.peer.readAll()))
            self.peer.close()  # Full window/service/selection teardown.
            self.wait_for(lambda: "Home" not in self.window.cbus_services)
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0][1])
            expected = details.nv_result.text()
            self.assertTrue(expected.startswith("Node 258: Partial Save:"))
            self.assertIn("Connection ended", expected)
            self.assertEqual(details.events_result.text(), "")
            self.assertEqual(view.node_list.currentItem().text(), "258 (Offline)")
            self.assertIsNone(details.desired_configuration)
            self.assertFalse(details.saving_configuration)
            view.node_list.setCurrentRow(1)
            self.assertEqual(view.node_list.currentItem().text(), "259 (Offline)")
            self.assertEqual(details.nv_result.text(), "")
            self.assertEqual(details.events_result.text(), "")

    def test_menu_action_requires_connected_tcp_layout(self):
        self.assertFalse(self.window.send_frame_action.isEnabled())
        self.connect_home()
        self.assertTrue(self.window.send_frame_action.isEnabled())

        other = next(
            action
            for action in self.window.layout_group.actions()
            if action.data() == "Test Layout"
        )
        self.window.layout_settings["Test Layout"]["connection_type"] = "Serial"
        other.setChecked(True)
        self.window.select_layout(other)
        self.assertFalse(self.window.send_frame_action.isEnabled())

        home = next(
            action
            for action in self.window.layout_group.actions()
            if action.data() == "Home"
        )
        home.setChecked(True)
        self.window.select_layout(home)
        self.assertTrue(self.window.send_frame_action.isEnabled())
        self.window.disconnect_layout()
        self.assertFalse(self.window.send_frame_action.isEnabled())

    def test_tcp_pnn_discovery_ends_when_peer_disconnects(self):
        self.connect_home()
        self.peer.write(b":SB040NB601020D2203;")
        self.peer.flush()
        self.wait_for(lambda: 258 in self.window.cbus_services["Home"].nodes)
        self.assertEqual(
            self.window.cbus_services["Home"].nodes,
            {258: Pnn(258, 13, 34, 3)},
        )

        self.peer.close()
        self.wait_for(lambda: self.window.connection_states["Home"] == "Disconnected")
        self.assertEqual(self.window.cbus_services, {})

    def test_successive_sends_deliver_frames_and_increment_status(self):
        self.connect_home()
        dialog = SendFrameDialog("Home", self.window.connections["Home"], self.window)
        dialog.show()
        self.assertIn("Home", [label.text() for label in dialog.findChildren(QLabel)])
        dialog.frame_edit.setText(":S123N00;")
        dialog.send_button.click()

        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.status_label.text(), "Frame sent (1)")
        self.wait_for(lambda: self.peer.bytesAvailable() == len(b":S123N00;"))
        self.assertEqual(bytes(self.peer.readAll()), b":S123N00;")

        dialog.frame_edit.setText(":S456N01;")
        self.assertEqual(dialog.status_label.text(), "")
        dialog.send_button.click()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.status_label.text(), "Frame sent (2)")
        self.wait_for(lambda: self.peer.bytesAvailable() == len(b":S456N01;"))
        self.assertEqual(bytes(self.peer.readAll()), b":S456N01;")
        dialog.close()

    def test_input_without_delimiters_is_sent_with_them(self):
        self.connect_home()
        dialog = SendFrameDialog("Home", self.window.connections["Home"], self.window)
        dialog.show()
        dialog.frame_edit.setText("S123N00")
        dialog.send_button.click()

        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.status_label.text(), "Frame sent (1)")
        self.wait_for(lambda: self.peer.bytesAvailable() == len(b":S123N00;"))
        self.assertEqual(bytes(self.peer.readAll()), b":S123N00;")
        dialog.close()

    def test_invalid_frame_shows_error_without_incrementing_status(self):
        self.connect_home()
        dialog = SendFrameDialog("Home", self.window.connections["Home"], self.window)
        dialog.show()
        dialog.frame_edit.setText(":S123N00;")
        dialog.send_button.click()
        self.wait_for(lambda: self.peer.bytesAvailable() == len(b":S123N00;"))
        self.assertEqual(bytes(self.peer.readAll()), b":S123N00;")
        self.assertEqual(dialog.status_label.text(), "Frame sent (1)")

        dialog.frame_edit.setText(":S123N00;:S456N01;")
        self.assertEqual(dialog.status_label.text(), "")
        messages = []
        with patch.object(
            QMessageBox, "warning", side_effect=lambda _p, _t, m: messages.append(m)
        ):
            dialog.send_button.click()

        self.assertTrue(dialog.isVisible())
        self.assertIn("complete printable ASCII", messages[0])
        self.assertEqual(dialog.status_label.text(), "")
        self.assertEqual(self.peer.bytesAvailable(), 0)

        dialog.frame_edit.setText(":S456N01;")
        dialog.send_button.click()
        self.assertEqual(dialog.status_label.text(), "Frame sent (2)")
        self.wait_for(lambda: self.peer.bytesAvailable() == len(b":S456N01;"))
        self.assertEqual(bytes(self.peer.readAll()), b":S456N01;")
        dialog.close()

    def test_connection_error_keeps_dialog_open(self):
        self.connect_home()
        dialog = SendFrameDialog("Home", self.window.connections["Home"], self.window)
        dialog.show()
        self.window.disconnect_layout()
        dialog.frame_edit.setText(":S123N00;")
        messages = []
        with patch.object(
            QMessageBox, "warning", side_effect=lambda _p, _t, m: messages.append(m)
        ):
            dialog.send_button.click()

        self.assertTrue(dialog.isVisible())
        self.assertIn("not connected", messages[0])
        dialog.close()

    def test_close_sends_nothing(self):
        self.connect_home()
        dialog = SendFrameDialog("Home", self.window.connections["Home"], self.window)
        dialog.show()
        dialog.frame_edit.setText(":S123N00;")
        buttons = dialog.findChild(QDialogButtonBox)
        buttons.button(QDialogButtonBox.StandardButton.Close).click()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.app.processEvents()
        self.assertEqual(self.peer.bytesAvailable(), 0)


if __name__ == "__main__":
    unittest.main()
