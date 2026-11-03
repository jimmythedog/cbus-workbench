"""Observable TCP connection and GridConnect frame behaviour."""

import time
import unittest

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer

from workbench.logging_config import TRACE
from workbench.tcp_connection import TcpConnection


class TcpConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.server = QTcpServer()
        self.assertTrue(self.server.listen(QHostAddress.SpecialAddress.LocalHost, 0))
        self.connection = TcpConnection("Test Layout", self.app)
        self.frames = []
        self.connection.frame_received.connect(self.frames.append)
        self.connection.connect("127.0.0.1", self.server.serverPort())
        self.wait_for(lambda: self.connection.state == "Connected")
        self.wait_for(self.server.hasPendingConnections)
        self.peer = self.server.nextPendingConnection()

    def tearDown(self):
        self.connection.disconnect()
        self.peer.close()
        self.server.close()
        self.connection.deleteLater()
        self.app.processEvents()

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.005)
        self.fail("Timed out waiting for a Qt socket event")

    def pump_events(self):
        deadline = time.monotonic() + 0.05
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)

    def send_to_connection(self, data):
        self.peer.write(data)
        self.peer.flush()

    def test_complete_frame_is_emitted_and_logged(self):
        frame = b":S123N00;"
        with self.assertLogs("workbench.connection", level=TRACE) as captured:
            self.send_to_connection(frame)
            self.wait_for(lambda: len(self.frames) == 1)

        self.assertEqual(self.frames, [frame])
        self.assertEqual(captured.records[0].fields["layout"], "Test Layout")
        self.assertEqual(captured.records[0].fields["frame"], frame.decode("ascii"))

    def test_split_frame_waits_for_terminator(self):
        self.send_to_connection(b":S123N")
        self.pump_events()
        self.assertEqual(self.frames, [])

        self.send_to_connection(b"00;")
        self.wait_for(lambda: len(self.frames) == 1)
        self.assertEqual(self.frames, [b":S123N00;"])

    def test_multiple_frames_in_one_write(self):
        self.send_to_connection(b":S123N00;:S456N01;")
        self.wait_for(lambda: len(self.frames) == 2)
        self.assertEqual(self.frames, [b":S123N00;", b":S456N01;"])

    def test_partial_frame_is_discarded_after_peer_disconnect(self):
        self.send_to_connection(b":S123N")
        self.pump_events()
        self.peer.close()
        self.wait_for(lambda: self.connection.state == "Disconnected")

        self.connection.connect("127.0.0.1", self.server.serverPort())
        self.wait_for(lambda: self.connection.state == "Connected")
        self.wait_for(self.server.hasPendingConnections)
        self.peer = self.server.nextPendingConnection()
        self.send_to_connection(b"00;:S456N01;")
        self.wait_for(lambda: len(self.frames) == 1)
        self.assertEqual(self.frames, [b":S456N01;"])

    def test_disconnect_still_closes_socket(self):
        self.connection.disconnect()
        self.assertEqual(self.connection.state, "Disconnected")
        self.assertEqual(
            self.connection.socket.state(),
            QAbstractSocket.SocketState.UnconnectedState,
        )

    def test_send_delivers_exact_frame_and_logs_it(self):
        frame = b":S123N00;"
        sent = []
        self.connection.frame_sent.connect(sent.append)
        with self.assertLogs("workbench.connection", level=TRACE) as captured:
            self.connection.send(frame)
            self.wait_for(lambda: self.peer.bytesAvailable() == len(frame))

        self.assertEqual(bytes(self.peer.readAll()), frame)
        self.assertEqual(sent, [frame])
        self.assertEqual(captured.records[0].fields["layout"], "Test Layout")
        self.assertEqual(captured.records[0].fields["frame"], frame.decode("ascii"))

    def test_multiple_sends_preserve_order(self):
        frames = [b":S123N00;", b":S456N01;"]
        for frame in frames:
            self.connection.send(frame)

        self.wait_for(lambda: self.peer.bytesAvailable() == sum(map(len, frames)))
        self.assertEqual(bytes(self.peer.readAll()), b"".join(frames))

    def test_send_rejects_invalid_or_incomplete_frames(self):
        for frame in (b"", b":;", b"S123N00;", b":S123N00", b":S1;:S2;", b":S\xff;"):
            with (
                self.subTest(frame=frame),
                self.assertRaisesRegex(ValueError, "one complete printable ASCII"),
            ):
                self.connection.send(frame)
        self.assertEqual(self.peer.bytesAvailable(), 0)

    def test_send_rejects_disconnected_socket(self):
        sent = []
        self.connection.frame_sent.connect(sent.append)
        self.connection.disconnect()
        with self.assertRaisesRegex(ConnectionError, "not connected"):
            self.connection.send(b":S123N00;")
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
