"""Node-number assignment triggered by a module's RQNN (Developer's Guide 6b §7.2)."""

import os
import time
import unittest
from unittest.mock import patch

from layout_fixture import sample_settings
from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_cbus_service import ConnectionStub

from workbench import node_number
from workbench.cbus_service import CbusService
from workbench.node_number import check_node_number, suggest_node_number
from workbench.node_number_dialog import NodeNumberDialog
from workbench.window import MainWindow

RQNP = b":SBFC0N10;"


def frame(can_id: int, payload: str) -> bytes:
    return f":S{(0x580 | can_id) << 5:04X}N{payload};".encode()


class NodeNumberRulesTests(unittest.TestCase):
    def test_reserved_numbers_are_refused(self):
        for number in (0, 100, 125, 126, 127, 65534, 65535):
            self.assertTrue(check_node_number(number, 0, {})[0], number)
        for number in (1, 99, 128, 256, 65533):
            self.assertEqual(check_node_number(number, 0, {}), ("", ""), number)

    def test_online_node_blocks_and_offline_node_warns(self):
        known = {300: True, 301: False}
        self.assertIn("online", check_node_number(300, 0, known)[0])
        reason, warning = check_node_number(301, 0, known)
        self.assertEqual(reason, "")
        self.assertIn("offline", warning)
        # A FLiM module may keep its own number.
        self.assertEqual(check_node_number(300, 300, known), ("", ""))

    def test_suggestion_starts_at_256_and_skips_known_numbers(self):
        self.assertEqual(suggest_node_number({}), 256)
        self.assertEqual(suggest_node_number({256: True, 257: False}), 258)


class NodeNumberAssignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connection = ConnectionStub("yard")
        self.connection.state = "Connected"
        self.service = CbusService(self.connection, 126)
        self.service.set_node_poll_seconds(0)
        self.assignment = self.service.node_number
        self.requests = []
        self.outcomes = []
        self.assignment.requested.connect(lambda: self.requests.append(True))
        self.assignment.finished.connect(
            lambda success, message: self.outcomes.append((success, message))
        )

    def tearDown(self):
        if not self.service._closed:
            self.service.close()

    def receive(self, can_id: int, payload: str) -> None:
        self.connection.frame_received.emit(frame(can_id, payload))

    def test_rqnn_assign_nnack_then_discovers_new_node(self):
        # A module without a node number may answer QNN with PNN for NN 0;
        # NN 0 belongs to commissioning, so it never becomes a node.
        discovered = []
        self.service.node_discovered.connect(discovered.append)
        sent = len(self.connection.sent)
        self.receive(5, "B60000A52007")
        self.assertNotIn(0, self.service.nodes)
        self.assertNotIn(0, self.service.node_states)
        self.assertNotIn(0, self.service.presence)
        self.assertEqual((discovered, len(self.connection.sent)), ([], sent))

        self.receive(5, "500000")
        self.assertEqual(self.requests, [True])
        self.assertEqual((self.assignment.current, self.assignment.can_id), (0, 5))

        self.assignment.request_parameters()
        self.receive(5, "EFA5612008100003")
        self.assertEqual(self.assignment.parameters[2], 0x20)

        self.assignment.assign(256, {})
        self.assertEqual(self.connection.sent[-1], b":SBFC0N420100;")
        self.assertEqual(self.outcomes, [])

        self.receive(5, "520100")
        self.assertEqual(self.outcomes, [(True, "Node number 256 assigned")])
        self.assertEqual(self.connection.sent[-1], b":SBFC0N0D;")  # QNN
        self.receive(5, "B60100A52007")
        self.assertIn(256, self.service.node_states)
        self.assertEqual([pnn.node_number for pnn in discovered], [256])
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73010000;")

    def test_existing_flim_node_renumbering_keeps_other_nodes(self):
        self.receive(7, "B60200A52007")  # Node 512 known before.
        self.receive(8, "B60300A52007")
        other = self.service.node_states[768]
        self.receive(7, "500200")
        self.assertEqual(self.assignment.current, 512)
        dialog = NodeNumberDialog("yard", self.assignment, lambda: {512: True})
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.number.value(), 512)  # Keeps its number by default.
        self.assertTrue(dialog.assign_button.isEnabled())
        self.assignment.assign(600, {512: True, 768: True})
        self.receive(7, "520258")
        self.assertTrue(self.outcomes[0][0])
        self.receive(8, "B60300A52007")  # Unchanged PNN after QNN.
        self.assertIs(self.service.node_states[768], other)

    def test_keeping_own_number_while_its_discovery_is_pending(self):
        self.receive(7, "B60200A52007")  # RQNPN(512, 0) now outstanding.
        self.receive(7, "500200")
        self.assignment.assign(512, {512: True})
        self.receive(7, "520200")
        self.assertTrue(self.outcomes[0][0])
        self.receive(7, "9B02000000")  # PARAN(0) reply to the rediscovery.
        self.assertEqual(self.service.node_states[512].parameters, {0: 0})

    def test_repeated_rqnn_is_one_request_and_competing_rqnn_blocks(self):
        self.receive(5, "500000")
        self.receive(5, "500000")
        self.assertEqual(self.requests, [True])
        self.assertEqual(self.assignment.unavailable_reason(256, {}), "")

        self.receive(6, "500000")
        self.assertEqual(self.requests, [True])
        self.assertIn("Another module", self.assignment.unavailable_reason(256, {}))
        with self.assertRaises(ValueError):
            self.assignment.assign(256, {})
        self.assertNotIn(b":SBFC0N420100;", self.connection.sent)

    def test_params_from_another_can_id_blocks(self):
        self.receive(5, "500000")
        self.receive(9, "EFA5612008100003")
        self.assertIn("CAN ID 9", self.assignment.unavailable_reason(256, {}))

    def test_timeout_and_cmderr_never_report_success(self):
        with patch.object(node_number.response_timeout, "RESPONSE_TIMEOUT_MS", 1):
            self.receive(5, "500000")
            self.assignment.assign(256, {})
            QTest.qWait(20)
        self.assertFalse(self.outcomes[0][0])
        self.assertIn("did not acknowledge", self.outcomes[0][1])

        self.receive(5, "500000")
        self.assignment.assign(257, {})
        self.receive(5, "6F000001")
        self.assertFalse(self.outcomes[1][0])
        self.assertIn("error 1", self.outcomes[1][1])
        self.receive(5, "520101")  # A late NNACK is not success.
        self.assertEqual(len(self.outcomes), 2)

        self.receive(5, "500000")
        self.assignment.assign(258, {})
        self.receive(9, "520102")  # Another module already using 258.
        self.assertFalse(self.outcomes[2][0])
        self.assertIn("CAN ID 9", self.outcomes[2][1])

    def test_disconnect_while_waiting_reports_uncertainty(self):
        self.receive(5, "500000")
        self.assignment.assign(256, {})
        self.service.close()
        self.assertFalse(self.outcomes[0][0])
        self.assertIn("Disconnected before", self.outcomes[0][1])

    def test_cancel_sends_nothing_and_next_rqnn_is_a_new_request(self):
        self.receive(5, "500000")
        sent = list(self.connection.sent)
        self.assignment.cancel()
        self.assertEqual(self.connection.sent, sent)
        self.receive(5, "500000")
        self.assertEqual(self.requests, [True, True])

    def test_dialog_proposes_number_and_explains_blocks(self):
        known = {256: True, 257: False}
        self.receive(5, "500000")
        dialog = NodeNumberDialog("yard", self.assignment, lambda: known)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.number.value(), 258)
        self.receive(5, "EFA5612008100003")
        self.assertIn("version 3a", dialog.module_label.text())

        dialog.number.setValue(256)
        self.assertFalse(dialog.assign_button.isEnabled())
        dialog.number.setValue(257)
        self.assertTrue(dialog.assign_button.isEnabled())
        self.assertIn("offline", dialog.reason.text())
        dialog.number.setValue(126)
        self.assertFalse(dialog.assign_button.isEnabled())

        dialog.number.setValue(258)
        dialog.assign_button.click()
        self.assertFalse(dialog.cancel_button.isEnabled())
        self.receive(5, "520102")
        self.assertEqual(dialog.finished_outcome, (True, "Node number 258 assigned"))


class NodeNumberWindowTests(unittest.TestCase):
    """RQNN alone opens one dialog per application, over the real TCP path."""

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
        self.window.connect_layout()
        self.wait_for(self.server.hasPendingConnections)
        self.peer = self.server.nextPendingConnection()
        self.wait_for(lambda: self.peer.bytesAvailable() >= len(b":SBFC0N0D;"))
        self.peer.readAll()

    def tearDown(self):
        # A failure report stays open; don't leave a modal widget for later tests.
        if self.window.node_number_dialog is not None:
            self.window.node_number_dialog.close()
        self.window.close()
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

    def test_rqnn_opens_one_dialog_and_disconnect_reports_it(self):
        self.peer.write(frame(5, "500000") + frame(5, "500000"))
        self.peer.flush()
        self.wait_for(lambda: self.window.node_number_dialog is not None)
        dialog = self.window.node_number_dialog
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.current_label.text(), "None (new module)")
        self.wait_for(lambda: self.peer.bytesAvailable() >= len(RQNP))
        self.assertEqual(bytes(self.peer.readAll()), RQNP)
        self.assertIs(self.window.node_number_dialog, dialog)

        self.window.disconnect_layout()
        self.assertFalse(dialog.finished_outcome[0])
        self.assertIn("Disconnected", dialog.status.text())

    def test_request_on_another_layout_is_refused_while_dialog_is_open(self):
        other_server = QTcpServer()
        self.assertTrue(other_server.listen(QHostAddress.SpecialAddress.LocalHost, 0))
        self.addCleanup(other_server.close)
        self.window.layout_settings["Test Layout"].update(
            host="127.0.0.1", port=other_server.serverPort(), can_id=100
        )
        other = next(
            a for a in self.window.layout_group.actions() if a.data() == "Test Layout"
        )
        other.setChecked(True)
        self.window.select_layout(other)
        self.window.connect_layout()
        self.wait_for(other_server.hasPendingConnections)
        other_peer = other_server.nextPendingConnection()
        self.addCleanup(other_peer.close)

        self.peer.write(frame(5, "500000"))
        self.peer.flush()
        self.wait_for(lambda: self.window.node_number_dialog is not None)
        dialog = self.window.node_number_dialog
        other_peer.write(frame(6, "500000"))
        other_peer.flush()
        self.wait_for(lambda: "ignored" in self.window.statusBar().currentMessage())
        self.assertIs(self.window.node_number_dialog, dialog)
        self.assertEqual(dialog.windowTitle(), "Assign Node Number — Home")
        self.window.disconnect_layout()
