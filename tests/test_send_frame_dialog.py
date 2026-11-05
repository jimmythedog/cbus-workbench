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
            details = view.details
            details.tabs.setCurrentWidget(details.events_page)
            details.events_edit_button.click()
            details.raw_values.item(0, 1).setText("9")
            results = []
            service.restore.finished.connect(lambda *args: results.append(args))
            details.events_save_button.click()
            self.wait_for(lambda: self.peer.bytesAvailable() > 0)
            self.assertIn(b"N9601020109", bytes(self.peer.readAll()))
            self.peer.close()  # Full window/service/selection teardown.
            self.wait_for(lambda: "Home" not in self.window.cbus_services)
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0][1])
            expected = f"Node 258: {results[0][2]}"
            self.assertIn("Connection ended", expected)
            self.assertEqual(details.nv_result.text(), expected)
            self.assertEqual(details.events_result.text(), expected)
            self.assertEqual(view.node_list.currentItem().text(), "258 (offline)")
            self.assertIsNone(details.desired_configuration)
            self.assertFalse(details.saving_configuration)
            view.node_list.setCurrentRow(1)
            self.assertEqual(view.node_list.currentItem().text(), "259 (offline)")
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
