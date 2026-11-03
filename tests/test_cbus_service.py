"""CBUS node state and QNN command over the existing connection contract."""

import unittest

from PySide6.QtCore import QObject, Signal

from workbench.cbus_service import CbusService
from workbench.pnn import Pnn


class ConnectionStub(QObject):
    frame_received = Signal(bytes)

    def __init__(self, layout_name: str):
        super().__init__()
        self.layout_name = layout_name
        self.sent: list[bytes] = []
        self.send_error: Exception | None = None

    def send(self, frame: bytes) -> None:
        if self.send_error:
            raise self.send_error
        self.sent.append(frame)


class CbusServiceTests(unittest.TestCase):
    def setUp(self):
        self.connection = ConnectionStub("Test Layout")
        self.service = CbusService(self.connection, can_id=126)
        self.discovered = []
        self.updated = []
        self.service.node_discovered.connect(self.discovered.append)
        self.service.node_updated.connect(self.updated.append)

    def test_discovers_node_without_a_prior_query(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")

        node = Pnn(258, 13, 34, 3)
        self.assertEqual(self.service.nodes, {258: node})
        self.assertEqual(self.discovered, [node])
        self.assertEqual(self.updated, [])

    def test_repeated_pnn_is_silent_and_changed_identity_emits_update(self):
        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.connection.frame_received.emit(b":SB060NB601020D2203;")
        self.connection.frame_received.emit(b":SB040NB601020D2303;")

        self.assertEqual(self.discovered, [Pnn(258, 13, 34, 3)])
        self.assertEqual(self.updated, [Pnn(258, 13, 35, 3)])
        self.assertEqual(self.service.nodes[258], Pnn(258, 13, 35, 3))

    def test_malformed_frames_do_not_block_later_pnn(self):
        self.connection.frame_received.emit(b":SB040NB60102;")
        self.connection.frame_received.emit(b":SB040NB601020D22G3;")
        self.connection.frame_received.emit(b":SB040N0D;")
        self.connection.frame_received.emit(b":SB040NB601020D2203;")

        self.assertEqual(self.discovered, [Pnn(258, 13, 34, 3)])
        self.assertEqual(self.updated, [])

    def test_qnn_uses_assigned_can_id_and_transport_send(self):
        self.service.discover_nodes()

        self.assertEqual(self.connection.sent, [b":SBFC0N0D;"])
        self.assertEqual(self.service.nodes, {})

    def test_qnn_send_failure_is_reported(self):
        self.connection.send_error = ConnectionError("not connected")

        with (
            self.assertLogs("workbench.cbus", level="ERROR") as captured,
            self.assertRaisesRegex(ConnectionError, "not connected"),
        ):
            self.service.discover_nodes()
        self.assertEqual(self.connection.sent, [])
        self.assertEqual(len(captured.records), 1)
        self.assertIsNotNone(captured.records[0].exc_info)

    def test_services_keep_layout_state_separate(self):
        other_connection = ConnectionStub("Other Layout")
        other_service = CbusService(other_connection, can_id=127)

        self.connection.frame_received.emit(b":SB040NB601020D2203;")
        self.assertEqual(other_service.nodes, {})
        other_connection.frame_received.emit(b":SB040NB601030D2203;")
        self.assertEqual(self.service.nodes, {258: Pnn(258, 13, 34, 3)})
        self.assertEqual(other_service.nodes, {259: Pnn(259, 13, 34, 3)})

    def test_rejects_can_ids_outside_pc_range(self):
        for can_id in (0, 99, 128):
            with self.subTest(can_id=can_id), self.assertRaises(ValueError):
                CbusService(ConnectionStub("Test Layout"), can_id)


if __name__ == "__main__":
    unittest.main()
