"""A serial port connection for GridConnect frames."""

import logging

from PySide6.QtCore import QIODeviceBase, QObject, Signal
from PySide6.QtSerialPort import QSerialPort

from .gridconnect import extract_frames, validate_frame
from .logging_config import trace

logger = logging.getLogger("workbench.connection")


class SerialConnection(QObject):
    state_changed = Signal(str)
    failed = Signal(str)
    frame_received = Signal(bytes)

    def __init__(self, layout_name: str, parent: QObject):
        super().__init__(parent)
        self.layout_name = layout_name
        self.state = "Disconnected"
        self._receive_buffer = bytearray()
        self.port = QSerialPort(self)
        self.port.errorOccurred.connect(self._error)
        self.port.readyRead.connect(self._receive_data)

    def connect(self, device_path: str) -> None:
        if self.state == "Error":
            self._set_state("Disconnected")
        trace(
            logger,
            "Opening serial port",
            extra={"fields": {"layout": self.layout_name, "device": device_path}},
        )
        self.port.setPortName(device_path)
        # Use Qt's default 9600, 8 data bits, no parity, one stop bit and no flow
        # control. These are port defaults only; no CBUS framing is assumed here.
        if self.port.open(QIODeviceBase.OpenModeFlag.ReadWrite):
            self._set_state("Connected")
            trace(
                logger,
                "Serial port opened",
                extra={"fields": {"layout": self.layout_name}},
            )

    def disconnect(self) -> None:
        trace(
            logger,
            "Closing serial port",
            extra={"fields": {"layout": self.layout_name}},
        )
        if self.port.isOpen():
            self.port.close()
        self._receive_buffer.clear()
        self._set_state("Disconnected")

    def send(self, frame: bytes) -> None:
        """Queue one complete, printable ASCII GridConnect frame for sending."""
        validate_frame(frame)
        if not self.port.isOpen():
            raise ConnectionError(
                "Cannot send GridConnect frame: serial port is not connected"
            )

        written = self.port.write(frame)
        if written != len(frame):
            raise OSError(
                f"Could not queue GridConnect frame: {self.port.errorString()}"
            )
        trace(
            logger,
            "GridConnect frame queued for sending",
            extra={
                "fields": {"layout": self.layout_name, "frame": frame.decode("ascii")}
            },
        )

    def _receive_data(self) -> None:
        # Serial reads may split a frame or contain several frames at once.
        self._receive_buffer.extend(bytes(self.port.readAll()))
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

    def _error(self, error: QSerialPort.SerialPortError) -> None:
        if error == QSerialPort.SerialPortError.NoError or self.state == "Error":
            return
        message = self.port.errorString()
        # close() can emit another errorOccurred signal, so mark this failure first.
        self._set_state("Error")
        self.port.close()
        self._receive_buffer.clear()
        self.failed.emit(message)
