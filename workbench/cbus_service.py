"""Live CBUS node identities for one GridConnect connection."""

import logging

from PySide6.QtCore import QObject, Signal

from .logging_config import trace
from .pnn import Pnn, decode_pnn
from .serial_connection import SerialConnection
from .tcp_connection import TcpConnection

logger = logging.getLogger("workbench.cbus")


class CbusService(QObject):
    node_discovered = Signal(Pnn)
    node_updated = Signal(Pnn)

    def __init__(self, connection: TcpConnection | SerialConnection, can_id: int):
        """Use a unique PC CAN ID (100–127) assigned for this network."""
        if not 100 <= can_id <= 127:
            raise ValueError("PC CAN ID must be between 100 and 127")
        super().__init__(connection)
        self.connection = connection
        self.can_id = can_id
        self.nodes: dict[int, Pnn] = {}
        connection.frame_received.connect(self._receive_frame)

    def close(self) -> None:
        """Stop observing frames when this connection's live state ends."""
        self.connection.frame_received.disconnect(self._receive_frame)

    def discover_nodes(self) -> None:
        """Queue one QNN request; PNN responses arrive independently by signal."""
        # The guide specifies major priority bits 0b10 and minor priority
        # bits 0b11 for a starting query. GridConnect left-justifies CAN bits.
        header = (0x580 | self.can_id) << 5
        frame = f":S{header:04X}N0D;".encode("ascii")
        fields = {"layout": self.connection.layout_name, "can_id": self.can_id}
        trace(logger, "Sending QNN", extra={"fields": fields})
        try:
            self.connection.send(frame)
        except OSError:
            logger.exception("Could not send QNN", extra={"fields": fields})
            raise
        trace(logger, "QNN queued", extra={"fields": fields})

    def _receive_frame(self, frame: bytes) -> None:
        try:
            pnn = decode_pnn(frame)
        except ValueError as error:
            trace(
                logger,
                "Ignoring malformed CBUS frame: %s",
                error,
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                        "frame": frame.decode("ascii", errors="replace"),
                    }
                },
            )
            return
        if pnn is None:
            return

        previous = self.nodes.get(pnn.node_number)
        if previous == pnn:
            return
        is_new = previous is None
        self.nodes[pnn.node_number] = pnn
        logger.info(
            "Node discovered" if is_new else "Node identity updated",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "node_number": pnn.node_number,
                    "manufacturer": pnn.manufacturer,
                    "module_type": pnn.module_type,
                    "flags": pnn.flags,
                    "previous": previous,
                }
            },
        )
        if is_new:
            self.node_discovered.emit(pnn)
        else:
            self.node_updated.emit(pnn)
