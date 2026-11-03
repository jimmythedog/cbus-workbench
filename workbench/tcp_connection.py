"""An asynchronous TCP connection to a configured CBUS hub."""

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket

from .gridconnect import extract_frames, validate_frame
from .logging_config import trace

logger = logging.getLogger("workbench.connection")


class TcpConnection(QObject):
    state_changed = Signal(str)
    failed = Signal(str)
    frame_received = Signal(bytes)
    frame_sent = Signal(bytes)

    def __init__(self, layout_name: str, parent: QObject):
        super().__init__(parent)
        self.layout_name = layout_name
        self.state = "Disconnected"
        self._receive_buffer = bytearray()
        self.socket = QTcpSocket(self)
        self.socket.connected.connect(self._connected)
        self.socket.disconnected.connect(self._disconnected)
        self.socket.errorOccurred.connect(self._error)
        self.socket.readyRead.connect(self._receive_data)

    def connect(self, host: str, port: int) -> None:
        self._set_state("Connecting")
        self.socket.connectToHost(host, port)

    def disconnect(self) -> None:
        # abort() also cancels an in-progress connection without waiting for a timeout.
        self.socket.abort()
        self._receive_buffer.clear()
        self._set_state("Disconnected")

    def send(self, frame: bytes) -> None:
        """Queue one complete, printable ASCII GridConnect frame for sending."""
        validate_frame(frame)
        if self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
            raise ConnectionError(
                "Cannot send GridConnect frame: TCP socket is not connected"
            )

        written = self.socket.write(frame)
        if written != len(frame):
            raise OSError(
                f"Could not queue GridConnect frame: {self.socket.errorString()}"
            )
        trace(
            logger,
            "GridConnect frame queued for sending",
            extra={
                "fields": {
                    "layout": self.layout_name,
                    "frame": frame.decode("ascii", errors="replace"),
                }
            },
        )
        self.frame_sent.emit(frame)

    def _receive_data(self) -> None:
        # TCP read boundaries do not match GridConnect frame boundaries.
        self._receive_buffer.extend(bytes(self.socket.readAll()))
        for frame in extract_frames(self._receive_buffer):
            trace(
                logger,
                "GridConnect frame received",
                extra={
                    "fields": {
                        "layout": self.layout_name,
                        "frame": frame.decode("ascii", errors="replace"),
                    }
                },
            )
            self.frame_received.emit(frame)

    def _set_state(self, state: str) -> None:
        if self.state != state:
            self.state = state
            self.state_changed.emit(state)

    def _connected(self) -> None:
        self._set_state("Connected")

    def _disconnected(self) -> None:
        self._receive_buffer.clear()
        if self.state != "Error":
            self._set_state("Disconnected")

    def _error(self, error: QAbstractSocket.SocketError) -> None:
        # Qt reports an orderly peer close as an error before emitting disconnected.
        if error == QAbstractSocket.SocketError.RemoteHostClosedError:
            return
        self._receive_buffer.clear()
        self._set_state("Error")
        self.failed.emit(self.socket.errorString())
