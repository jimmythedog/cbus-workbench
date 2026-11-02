"""The raw frame dialog and its availability in the Layout menu."""

import os
import time
import unittest
from unittest.mock import patch

from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
)

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

    def test_menu_action_requires_connected_tcp_layout(self):
        self.assertFalse(self.window.send_frame_action.isEnabled())
        self.connect_home()
        self.assertTrue(self.window.send_frame_action.isEnabled())

        other = next(
            action
            for action in self.window.layout_group.actions()
            if action.text() == "Test Layout"
        )
        self.window.layout_settings["Test Layout"]["connection_type"] = "Serial"
        other.setChecked(True)
        self.window.select_layout(other)
        self.assertFalse(self.window.send_frame_action.isEnabled())

        home = next(
            action
            for action in self.window.layout_group.actions()
            if action.text() == "Home"
        )
        home.setChecked(True)
        self.window.select_layout(home)
        self.assertTrue(self.window.send_frame_action.isEnabled())
        self.window.disconnect_layout()
        self.assertFalse(self.window.send_frame_action.isEnabled())

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
