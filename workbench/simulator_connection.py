"""An in-process connection to simulated CBUS nodes (issue #90).

It offers the same signals and send() contract as the TCP and serial
connections, so the CBUS service and every workflow above it are unchanged.
The simulator has no settings: the layout's logical layout identifies its nodes.
State exists only between connect() and disconnect().
"""

import logging
from collections import deque

import yaml
from PySide6.QtCore import QObject, QTimer, Signal

from .cbus_simulator import CbusSimulator, load_simulated_nodes
from .gridconnect import validate_frame
from .logging_config import trace

logger = logging.getLogger("workbench.connection")


class SimulatorConnection(QObject):
    state_changed = Signal(str)
    failed = Signal(str)
    frame_received = Signal(bytes)
    frame_sent = Signal(bytes)

    def __init__(self, layout_name: str, parent: QObject):
        super().__init__(parent)
        self.layout_name = layout_name
        self.state = "Disconnected"
        self.logical_layout = ""
        # {node number: reason} for saved nodes the metadata cannot identify.
        self.skipped_nodes: dict[int, str] = {}
        self._simulator: CbusSimulator | None = None
        self._replies: deque[bytes] = deque()
        # Callers record an outstanding request only after send() returns, as
        # with a real transport, so replies arrive on a later event-loop turn.
        self._delivery = QTimer(self)
        self._delivery.setSingleShot(True)
        self._delivery.setInterval(0)
        self._delivery.timeout.connect(self._deliver_replies)

    def connect(self, logical_layout: str) -> None:
        self.logical_layout = logical_layout
        trace(
            logger,
            "Starting CBUS simulator",
            extra={
                "fields": {"layout": self.layout_name, "logical_layout": logical_layout}
            },
        )
        try:
            nodes, self.skipped_nodes = load_simulated_nodes(logical_layout)
        # ValueError includes UnicodeDecodeError from a file that is not UTF-8.
        except (OSError, ValueError, yaml.YAMLError) as error:
            logger.exception(
                "Could not load simulated nodes",
                extra={"fields": {"layout": self.layout_name}},
            )
            self._set_state("Error")
            self.failed.emit(f"Could not load saved node metadata: {error}")
            return
        self._simulator = CbusSimulator(nodes)
        logger.info(
            "CBUS simulator started",
            extra={
                "fields": {
                    "layout": self.layout_name,
                    "nodes": sorted(self._simulator.nodes),
                    "skipped": self.skipped_nodes,
                }
            },
        )
        self._set_state("Connected")

    def disconnect(self) -> None:
        trace(
            logger,
            "Stopping CBUS simulator",
            extra={"fields": {"layout": self.layout_name}},
        )
        # All simulated state, including undelivered replies, is discarded.
        self._simulator = None
        self._replies.clear()
        self._delivery.stop()
        self._set_state("Disconnected")

    def send(self, frame: bytes) -> None:
        """Accept one complete, printable ASCII GridConnect frame."""
        validate_frame(frame)
        if self.state != "Connected" or self._simulator is None:
            raise ConnectionError(
                "Cannot send GridConnect frame: simulator is not connected"
            )
        trace(
            logger,
            "GridConnect frame sent to simulator",
            extra={
                "fields": {
                    "layout": self.layout_name,
                    "frame": frame.decode("ascii", errors="replace"),
                }
            },
        )
        self.frame_sent.emit(frame)
        replies = self._simulator.handle(frame)
        if replies:
            self._replies.extend(replies)
            self._delivery.start()

    def _deliver_replies(self) -> None:
        # Deliver only replies already queued; frames sent while handling them
        # get their own later turn, as on a real transport.
        simulator = self._simulator
        for _ in range(len(self._replies)):
            if self._simulator is not simulator or not self._replies:
                return  # A receiver disconnected (and perhaps reconnected).
            frame = self._replies.popleft()
            trace(
                logger,
                "GridConnect frame received from simulator",
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
