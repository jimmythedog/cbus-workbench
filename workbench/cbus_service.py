"""Live CBUS node identities and configuration for one GridConnect connection."""

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal

from . import response_timeout
from .cmderr import decode_cmderr
from .enrsp import decode_enrsp
from .ev_write import EvWrite
from .logging_config import trace
from .neval import decode_neval
from .numev import decode_numev
from .nv_write import NvWrite
from .nvans import decode_nvans
from .observed_events import decode_event
from .parameter_names import vlcb_compatible
from .paran import decode_paran
from .pnn import Pnn, decode_pnn
from .serial_connection import SerialConnection
from .tcp_connection import TcpConnection
from .wrack import decode_wrack

logger = logging.getLogger("workbench.cbus")
PARAMETER_READ_ORDER = (2, 4, 5, 6, 7, 8, 10, 20, 19, 9, 1, 3)
RequestIndex = int | tuple[int, int]


class DiscoveryProgress(Enum):
    NOT_STARTED = "not started"
    IN_PROGRESS = "in progress"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    SKIPPED = "skipped"


@dataclass
class NodeState:
    """Live discovery values and independent progress for one node."""

    identity: Pnn
    parameters: dict[int, int] = field(default_factory=dict)
    nv_values: dict[int, int] = field(default_factory=dict)
    stored_event_count: int | None = None
    # The index identifies a slot in this node's event table, not the event number.
    event_identities: dict[int, tuple[int, int]] = field(default_factory=dict)
    # Integer: confirmed value; None: confirmed absent; missing key: unknown.
    ev_values: dict[int, dict[int, int | None]] = field(default_factory=dict)
    parameter_progress: DiscoveryProgress = DiscoveryProgress.NOT_STARTED
    nv_progress: DiscoveryProgress = DiscoveryProgress.NOT_STARTED
    event_progress: DiscoveryProgress = DiscoveryProgress.NOT_STARTED
    ev_progress: DiscoveryProgress = DiscoveryProgress.NOT_STARTED
    can_id: int | None = None


class CbusService(QObject):
    presence_checked = Signal(int, bool, int)  # Node, responded, module type.
    node_refresh_finished = Signal(int)
    discovery_status_changed = Signal(str)
    node_discovered = Signal(Pnn)
    node_updated = Signal(Pnn)
    parameter_updated = Signal(int, int, int)  # Node number, index, value.
    # Observers read the current state by node number, including progress changes.
    node_state_updated = Signal(int)
    event_received = Signal(object)

    def __init__(self, connection: TcpConnection | SerialConnection, can_id: int):
        """Use a unique PC CAN ID (100–127) assigned for this network."""
        if not 100 <= can_id <= 127:
            raise ValueError("PC CAN ID must be between 100 and 127")
        super().__init__(connection)
        self.connection = connection
        self.can_id = can_id
        self.nodes: dict[int, Pnn] = {}
        self.node_states: dict[int, NodeState] = {}
        self._request_queue: deque[tuple[str, int, RequestIndex]] = deque()
        self._outstanding_request: tuple[str, int, RequestIndex] | None = None
        self._nv_read_recovery = False
        self._nv_started: dict[int, int] = {}
        self._ev_started: set[int] = set()
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.timeout.connect(self._request_timed_out)
        self.discovery_status = "Disconnected"
        self._closed = False
        self._qnn_failed = False
        # QNN has no final acknowledgement. Wait for a quiet response window,
        # then judge only the work initiated for nodes actually observed.
        self._discovery_window = QTimer(self)
        self._discovery_window.setSingleShot(True)
        self._discovery_window.timeout.connect(self._update_discovery_status)
        # Defer aggregation until the current reply has queued all follow-on work.
        self._status_update = QTimer(self)
        self._status_update.setSingleShot(True)
        self._status_update.timeout.connect(self._update_discovery_status)
        self.node_state_updated.connect(lambda _node: self._status_update.start(0))
        self.nv_write = NvWrite(self)
        self.ev_write = EvWrite(self)
        self.refreshing_node = None
        # Import after the service types are defined; serializers also use them.
        from .node_restore import NodeRestore

        self.restore = NodeRestore(self)
        connection.frame_received.connect(self._receive_frame)

    def close(self) -> None:
        """Stop observing frames when this connection's live state ends."""
        self._closed = True
        self._discovery_window.stop()
        self._status_update.stop()
        self._set_discovery_status("Disconnected")
        self.connection.frame_received.disconnect(self._receive_frame)
        self.restore.disconnect()
        self.nv_write.disconnect()
        self.ev_write.disconnect()
        self._request_timer.stop()
        self._request_queue.clear()
        self._outstanding_request = None
        self._nv_read_recovery = False
        self._nv_started.clear()
        self._ev_started.clear()
        trace(
            logger,
            "Automatic discovery work cleared",
            extra={"fields": {"layout": self.connection.layout_name}},
        )

    def _set_discovery_status(self, status: str) -> None:
        if self.discovery_status != status:
            trace(
                logger,
                "Connection discovery status changed",
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                        "previous": self.discovery_status,
                        "status": status,
                    }
                },
            )
            self.discovery_status = status
            self.discovery_status_changed.emit(status)

    def _update_discovery_status(self) -> None:
        """Aggregate confirmed progress after reply-triggered phases are queued."""
        if self._closed:
            return
        if (
            self._discovery_window.isActive()
            or self._outstanding_request is not None
            or self._request_queue
            or self.restore.active
            or self.nv_write.active
            or self.nv_write.refreshing
            or self.ev_write.active
            or self.ev_write.refreshing
        ):
            status = "Discovering configuration…"
        else:
            complete = (DiscoveryProgress.COMPLETE, DiscoveryProgress.SKIPPED)
            ready = (
                bool(self.node_states)
                and not self._qnn_failed
                and all(
                    progress in complete
                    for state in self.node_states.values()
                    for progress in (
                        state.parameter_progress,
                        state.nv_progress,
                        state.event_progress,
                        state.ev_progress,
                    )
                )
            )
            status = "Configuration ready" if ready else "Discovery incomplete"
        self._set_discovery_status(status)

    def discover_nodes(self) -> None:
        """Queue one QNN request; PNN responses arrive independently by signal."""
        self._set_discovery_status("Discovering configuration…")
        self._discovery_window.start(response_timeout.RESPONSE_TIMEOUT_MS)
        # The guide specifies major priority bits 0b10 and minor priority
        # bits 0b11 for a starting query. GridConnect left-justifies CAN bits.
        header = (0x580 | self.can_id) << 5
        frame = f":S{header:04X}N0D;".encode("ascii")
        fields = {"layout": self.connection.layout_name, "can_id": self.can_id}
        trace(logger, "Sending QNN", extra={"fields": fields})
        try:
            self.connection.send(frame)
        except OSError:
            self._qnn_failed = True
            self._discovery_window.stop()
            self._update_discovery_status()
            logger.exception("Could not send QNN", extra={"fields": fields})
            raise
        trace(logger, "QNN queued", extra={"fields": fields})

    def request_parameter(self, node_number: int, parameter_index: int) -> None:
        """Queue one RQNPN request for an assigned node number."""
        if type(node_number) is not int or not 1 <= node_number <= 0xFFFF:
            raise ValueError("Node number must be between 1 and 65535")
        if type(parameter_index) is not int or not 0 <= parameter_index <= 0xFF:
            raise ValueError("Parameter index must be between 0 and 255")

        header = (0x580 | self.can_id) << 5
        frame = (f":S{header:04X}N73{node_number:04X}{parameter_index:02X};").encode(
            "ascii"
        )
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "parameter_index": parameter_index,
        }
        trace(logger, "Sending RQNPN", extra={"fields": fields})
        try:
            self.connection.send(frame)
        except OSError:
            logger.exception("Could not send RQNPN", extra={"fields": fields})
            raise
        trace(logger, "RQNPN queued", extra={"fields": fields})

    def writes_busy(self) -> bool:
        return bool(
            self.restore.active
            or self.nv_write.active
            or self.nv_write.refreshing
            or self.ev_write.active
            or self.ev_write.refreshing
        )

    def discovery_pending(self) -> bool:
        return bool(
            self._outstanding_request
            or self._request_queue
            or self.refreshing_node is not None
        )

    def check_presence(self, numbers) -> None:
        """Queue read-only RQNPN(3) checks without starting discovery."""
        if self._closed or self.connection.state != "Connected":
            raise ValueError("Presence checks require an active connection")
        if self.writes_busy() or self.discovery_pending():
            raise ValueError("Wait for discovery or configuration writes to finish")
        self._request_queue.extend(("presence", number, 3) for number in numbers)
        self._send_next_request()

    def cancel_presence_checks(self) -> None:
        """Drop unsent checks; let an in-flight read drain before reusing the wire."""
        self._request_queue = deque(
            request for request in self._request_queue if request[0] != "presence"
        )
        trace(
            logger,
            "Unsent presence checks cancelled",
            extra={"fields": {"layout": self.connection.layout_name}},
        )

    def rediscover_node(self, node_number: int) -> None:
        """Read the entire selected node afresh, retaining its confirmed identity."""
        if self._closed or self.connection.state != "Connected":
            raise ValueError("Rediscovery requires an active connection")
        if self.nv_write.active or self.ev_write.active:
            raise ValueError("Wait for hardware writes and learn-mode cleanup")
        state = self.node_states[node_number]
        self._request_queue = deque(
            r for r in self._request_queue if r[1] != node_number
        )
        state.parameters.clear()
        state.nv_values.clear()
        state.event_identities.clear()
        state.ev_values.clear()
        state.stored_event_count = None
        state.parameter_progress = state.nv_progress = DiscoveryProgress.NOT_STARTED
        state.event_progress = state.ev_progress = DiscoveryProgress.NOT_STARTED
        self._nv_started.pop(node_number, None)
        self._ev_started.discard(node_number)
        self.refreshing_node = node_number
        self._request_queue.append(("parameter", node_number, 0))
        trace(
            logger,
            "Full node rediscovery queued",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "node_number": node_number,
                }
            },
        )
        self.node_state_updated.emit(node_number)
        self._send_next_request()

    def write_nvs(
        self,
        node_number: int,
        values: dict[int, int],
        *,
        owner=None,
    ) -> None:
        """Validate one coordinator-owned NV transaction before transmission."""
        if owner is not self.restore or not self.restore.active:
            raise ValueError(
                "NV writes require active configuration application ownership"
            )
        state = self.node_states.get(node_number)
        if self._closed or self.connection.state != "Connected" or state is None:
            raise ValueError("NV editing requires a discovered, connected node")
        count = state.parameters.get(6)
        if state.nv_progress != DiscoveryProgress.COMPLETE or count is None:
            raise ValueError("NV discovery must be complete before editing")
        if (
            self.nv_write.active
            or self.nv_write.refreshing
            or self.ev_write.active
            or self.ev_write.refreshing
        ):
            raise ValueError("An NV Save is already in progress")
        if self.ev_write.blocked or any(
            node == node_number for node, _index in self.nv_write.unverified
        ):
            raise ValueError("Reconnect to rediscover this node before another NV Save")
        for index, value in values.items():
            if type(index) is not int or not 1 <= index <= min(count, 255):
                raise ValueError(
                    "NV index must be between 1 and the discovered NV count"
                )
            if type(value) is not int or not 0 <= value <= 255:
                raise ValueError("NV value must be between 0 and 255")
            if index not in state.nv_values:
                raise ValueError(f"NV {index} has no confirmed original value")
        # Preserve the coordinator's ascending pass: reread higher NVs only.
        self.nv_write.begin(
            node_number,
            values,
            refresh_from=next(iter(values)) + 1 if values else 1,
            refresh_events=False,
        )

    def write_evs(
        self,
        node_number: int,
        values: dict[tuple[int, int, int], int],
        *,
        owner=None,
        unlearn: tuple[int, int] | None = None,
    ) -> None:
        """Validate a coordinator-owned teaching or event reconstruction step."""
        if owner is not self.restore or not self.restore.active:
            raise ValueError(
                "EV writes require active configuration application ownership"
            )
        state = self.node_states.get(node_number)
        if self.connection.state != "Connected" or state is None:
            raise ValueError("EV Save requires a discovered, connected node")
        if (
            self.ev_write.active
            or self.ev_write.refreshing
            or self.nv_write.active
            or self.nv_write.refreshing
        ):
            raise ValueError("Another Save is in progress")
        if self.ev_write.blocked or self.nv_write.unverified:
            raise ValueError("Reconnect to rediscover before another Save")
        if (
            not node_number
            or not state.identity.is_flim
            or not state.identity.is_consumer
            or state.can_id is None
            or state.event_progress != DiscoveryProgress.COMPLETE
            or (values and not state.parameters.get(5))
        ):
            raise ValueError(
                "EV Save needs confirmed event identities, EV capacity and CAN ID on a FLiM consumer"
            )
        identities = set(state.event_identities.values())
        if unlearn is not None and unlearn not in identities:
            raise ValueError("Event unlearn requires a discovered event identity")
        for key, value in values.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 3
                or any(type(part) is not int for part in key)
            ):
                raise ValueError("EV address must be an event identity and EV index")
            event_node, event_number, ev = key
            if (
                not 0 <= event_node <= 65535
                or not 0 <= event_number <= 65535
                or not 1 <= ev <= state.parameters[5]
            ):
                raise ValueError("EV address is not confirmed by live discovery")
            if type(value) is not int or not 0 <= value <= 255:
                raise ValueError("EV value must be between 0 and 255")
        self.ev_write.begin(node_number, values, unlearn=unlearn)

    def request_nv(self, node_number: int, index: int) -> None:
        """Send NVRD for one numbered node variable (Developer's Guide 6b)."""
        if type(node_number) is not int or not 1 <= node_number <= 0xFFFF:
            raise ValueError("Node number must be between 1 and 65535")
        if type(index) is not int or not 1 <= index <= 0xFF:
            raise ValueError("NV index must be between 1 and 255")
        header = (0x580 | self.can_id) << 5
        frame = f":S{header:04X}N71{node_number:04X}{index:02X};".encode("ascii")
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "nv_index": index,
        }
        trace(logger, "Sending NVRD", extra={"fields": fields})
        try:
            self.connection.send(frame)
        except OSError:
            logger.exception("Could not send NVRD", extra={"fields": fields})
            raise
        trace(logger, "NVRD queued", extra={"fields": fields})

    def request_stored_event_count(self, node_number: int) -> None:
        """Send RQEVN for the stored count, distinct from parameter 4 capacity."""
        if type(node_number) is not int or not 1 <= node_number <= 0xFFFF:
            raise ValueError("Node number must be between 1 and 65535")
        header = (0x580 | self.can_id) << 5
        frame = f":S{header:04X}N58{node_number:04X};".encode("ascii")
        fields = {"layout": self.connection.layout_name, "node_number": node_number}
        trace(logger, "Sending RQEVN", extra={"fields": fields})
        try:
            self.connection.send(frame)
        except OSError:
            logger.exception("Could not send RQEVN", extra={"fields": fields})
            raise
        trace(logger, "RQEVN queued", extra={"fields": fields})

    def request_stored_events(self, node_number: int) -> None:
        """Send NERD to enumerate the node's stored event identities."""
        if type(node_number) is not int or not 1 <= node_number <= 0xFFFF:
            raise ValueError("Node number must be between 1 and 65535")
        header = (0x580 | self.can_id) << 5
        frame = f":S{header:04X}N57{node_number:04X};".encode("ascii")
        fields = {"layout": self.connection.layout_name, "node_number": node_number}
        trace(logger, "Sending NERD", extra={"fields": fields})
        try:
            self.connection.send(frame)
        except OSError:
            logger.exception("Could not send NERD", extra={"fields": fields})
            raise
        trace(logger, "NERD queued", extra={"fields": fields})

    def request_ev(self, node_number: int, event_index: int, ev_index: int) -> None:
        """Send REVAL using an internal index confirmed by ENRSP."""
        if type(node_number) is not int or not 1 <= node_number <= 0xFFFF:
            raise ValueError("Node number must be between 1 and 65535")
        if type(event_index) is not int or not 0 <= event_index <= 0xFF:
            raise ValueError("Event index must be between 0 and 255")
        if type(ev_index) is not int or not 1 <= ev_index <= 0xFF:
            raise ValueError("EV index must be between 1 and 255")
        header = (0x580 | self.can_id) << 5
        frame = f":S{header:04X}N9C{node_number:04X}{event_index:02X}{ev_index:02X};".encode(
            "ascii"
        )
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "event_index": event_index,
            "ev_index": ev_index,
        }
        trace(logger, "Sending REVAL", extra={"fields": fields})
        try:
            self.connection.send(frame)
        except OSError:
            logger.exception("Could not send REVAL", extra={"fields": fields})
            raise
        trace(logger, "REVAL queued", extra={"fields": fields})

    def record_nv(self, node_number: int, index: int, value: int) -> None:
        """Record a confirmed NV value without changing automatic progress."""
        state = self.node_states[node_number]
        if not 1 <= index <= 0xFF or not 0 <= value <= 0xFF:
            raise ValueError("NV index and value must be bytes; index starts at 1")
        if state.nv_values.get(index) == value and index in state.nv_values:
            return
        state.nv_values[index] = value
        trace(
            logger,
            "Confirmed NV recorded",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "node_number": node_number,
                    "nv_index": index,
                    "value": value,
                }
            },
        )
        self.node_state_updated.emit(node_number)

    def _set_progress(
        self, kind: str, node_number: int, progress: DiscoveryProgress
    ) -> None:
        if kind == "presence":
            return
        state = self.node_states[node_number]
        if kind == "parameter":
            if state.parameter_progress == progress:
                return
            state.parameter_progress = progress
        elif kind == "nv":
            # An interrupted or outdated pass cannot later become complete.
            if state.nv_progress == progress or (
                state.nv_progress == DiscoveryProgress.INCOMPLETE
                and progress != DiscoveryProgress.INCOMPLETE
            ):
                return
            state.nv_progress = progress
        elif kind == "ev":
            if state.ev_progress == progress or (
                state.ev_progress == DiscoveryProgress.INCOMPLETE
                and progress != DiscoveryProgress.INCOMPLETE
            ):
                return
            state.ev_progress = progress
        else:
            if state.event_progress == progress or (
                state.event_progress == DiscoveryProgress.INCOMPLETE
                and progress != DiscoveryProgress.INCOMPLETE
            ):
                return
            state.event_progress = progress
        trace(
            logger,
            "Discovery progress changed",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "node_number": node_number,
                    "kind": kind,
                    "progress": progress.value,
                }
            },
        )
        self.node_state_updated.emit(node_number)

        if (
            kind == "nv"
            and self.nv_write.refreshing
            and self.nv_write.refresh_events
            and node_number == self.nv_write.node_number
            and progress == DiscoveryProgress.COMPLETE
        ):
            self._restart_event_discovery(node_number)

    def _restart_event_discovery(self, node_number: int) -> None:
        """Discard pre-Save event slots: firmware may have rebuilt the table."""
        self._request_queue = deque(
            request
            for request in self._request_queue
            if not (request[1] == node_number and request[0] in ("event", "ev"))
        )
        state = self.node_states[node_number]
        state.stored_event_count = None
        state.event_identities.clear()
        state.ev_values.clear()
        state.event_progress = DiscoveryProgress.NOT_STARTED
        state.ev_progress = DiscoveryProgress.NOT_STARTED
        self._ev_started.discard(node_number)
        trace(
            logger,
            "Post-Save event state cleared; restarting discovery",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "node_number": node_number,
                }
            },
        )
        self.node_state_updated.emit(node_number)
        self._queue_event_count(node_number)

    def _receive_frame(self, frame: bytes) -> None:
        event = decode_event(frame)
        if event is not None:
            self.event_received.emit(event)
            return
        try:
            wrack = decode_wrack(frame)
            if wrack is not None:
                self.nv_write.acknowledge(wrack.node_number)
                self.ev_write.acknowledge(wrack.node_number)
                return
            self.ev_write.receive_frame(frame)
            pnn = decode_pnn(frame)
            paran = decode_paran(frame) if pnn is None else None
            nvans = decode_nvans(frame) if pnn is None and paran is None else None
            numev = (
                decode_numev(frame)
                if pnn is None and paran is None and nvans is None
                else None
            )
            enrsp = (
                decode_enrsp(frame)
                if pnn is None and paran is None and nvans is None and numev is None
                else None
            )
            neval = (
                decode_neval(frame)
                if all(reply is None for reply in (pnn, paran, nvans, numev, enrsp))
                else None
            )
            cmderr = (
                decode_cmderr(frame)
                if all(
                    reply is None for reply in (pnn, paran, nvans, numev, enrsp, neval)
                )
                else None
            )
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
            if paran is not None:
                self._receive_paran(
                    paran.node_number, paran.parameter_index, paran.parameter_value
                )
            elif nvans is not None:
                self._receive_nvans(nvans.node_number, nvans.nv_index, nvans.nv_value)
            elif numev is not None:
                self._receive_numev(numev.node_number, numev.stored_event_count)
            elif enrsp is not None:
                self._receive_enrsp(
                    enrsp.node_number,
                    enrsp.event_index,
                    enrsp.event_node_number,
                    enrsp.event_number,
                )
            elif neval is not None:
                self._receive_neval(
                    neval.node_number, neval.event_index, neval.ev_index, neval.value
                )
            elif cmderr is not None:
                self._receive_cmderr(cmderr.node_number, cmderr.code)
            return

        previous = self.nodes.get(pnn.node_number)
        # PNN identifies the sender; event node numbers may identify another node.
        can_id = (int(frame[2:6], 16) >> 5) & 0x7F
        state = self.node_states.get(pnn.node_number)
        if previous == pnn and state is not None and state.can_id == can_id:
            return
        is_new = previous is None
        self.nodes[pnn.node_number] = pnn
        state = self.node_states.get(pnn.node_number)
        if state is None:
            state = NodeState(pnn)
            self.node_states[pnn.node_number] = state
        else:
            state.identity = pnn
        state.can_id = can_id
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
                    "can_id": can_id,
                }
            },
        )
        if is_new:
            self._discovery_window.start(response_timeout.RESPONSE_TIMEOUT_MS)
            self._set_discovery_status("Discovering configuration…")
            self.node_discovered.emit(pnn)
            self.node_state_updated.emit(pnn.node_number)
            if pnn.node_number != 0:
                self._request_queue.append(("parameter", pnn.node_number, 0))
                trace(
                    logger,
                    "Automatic parameter count queued",
                    extra={
                        "fields": {
                            "layout": self.connection.layout_name,
                            "node_number": pnn.node_number,
                            "parameter_index": 0,
                        }
                    },
                )
                self._send_next_request()
        else:
            # A changed observed CAN ID also matters to metadata persistence.
            self.node_updated.emit(pnn)
            self.node_state_updated.emit(pnn.node_number)

    def _receive_paran(self, node_number: int, index: int, value: int) -> None:
        if index == 3 and self._outstanding_request == ("presence", node_number, 3):
            self._request_timer.stop()
            self._outstanding_request = None
            trace(
                logger,
                "Presence confirmed",
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                        "node_number": node_number,
                        "module_type": value,
                    }
                },
            )
            self.presence_checked.emit(node_number, True, value)
            self._send_next_request()
            return
        if self.ev_write.receive_mode(node_number, index, value):
            return
        state = self.node_states.get(node_number)
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "parameter_index": index,
            "parameter_value": value,
        }
        if state is None:
            trace(
                logger, "Ignoring PARAN for undiscovered node", extra={"fields": fields}
            )
            return

        # Membership matters: zero is a confirmed value, not an unknown parameter.
        changed = index not in state.parameters or state.parameters[index] != value
        if changed:
            previous = state.parameters.get(index)
            state.parameters[index] = value
            trace(
                logger,
                "Node parameter updated",
                extra={"fields": {**fields, "previous": previous}},
            )
            self.parameter_updated.emit(node_number, index, value)
            self.node_state_updated.emit(node_number)

        # Parameter 6 is the confirmed NV count. It may arrive outside our
        # automatic parameter sequence, so discovery starts on the reply itself.
        if index == 6:
            if node_number not in self._nv_started:
                self._start_nv_discovery(node_number, value)
            elif value != self._nv_started[node_number]:
                # The queued pass covers the first confirmed count. Keep it
                # moving, but do not call it complete for a different count.
                trace(
                    logger,
                    "NV count changed during discovery",
                    extra={
                        "fields": {
                            "layout": self.connection.layout_name,
                            "node_number": node_number,
                            "queued_count": self._nv_started[node_number],
                            "confirmed_count": value,
                        }
                    },
                )
                self._set_progress("nv", node_number, DiscoveryProgress.INCOMPLETE)

        if index == 5 and state.event_progress == DiscoveryProgress.COMPLETE:
            self._start_ev_discovery(node_number)

        if self._outstanding_request != ("parameter", node_number, index):
            trace(
                logger,
                "PARAN does not match outstanding automatic request",
                extra={"fields": {**fields, "outstanding": self._outstanding_request}},
            )
            return

        trace(logger, "Automatic PARAN received", extra={"fields": fields})
        if index == 0:
            # Parameter zero counts available indices, excluding itself. Keep the
            # existing UI/capability order, then read every other supported index.
            indices = list(PARAMETER_READ_ORDER) + [
                index
                for index in range(1, value + 1)
                if index not in PARAMETER_READ_ORDER
            ]
            self._request_queue.extend(
                ("parameter", node_number, requested)
                for requested in indices
                if requested <= value
            )
        self._finish_request("parameter", node_number)

    def _start_nv_discovery(
        self, node_number: int, count: int, *, first: int = 1
    ) -> None:
        self._nv_started[node_number] = count
        if self.nv_write.refreshing and self.nv_write.node_number == node_number:
            # Even an empty range has a new completion transition. This also
            # starts event refresh for a node with no NVs during final checking.
            self._set_progress("nv", node_number, DiscoveryProgress.IN_PROGRESS)
        if first > count:
            self._set_progress("nv", node_number, DiscoveryProgress.COMPLETE)
            return
        self._request_queue.extend(
            ("nv", node_number, index) for index in range(first, count + 1)
        )
        trace(
            logger,
            "Automatic NV discovery queued",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "node_number": node_number,
                    "count": count,
                    "first_index": first,
                }
            },
        )
        self._send_next_request()

    def _receive_nvans(self, node_number: int, index: int, value: int) -> None:
        if self.nv_write.receive_value(node_number, index, value):
            return
        if node_number not in self.node_states:
            trace(
                logger,
                "Ignoring NVANS for undiscovered node",
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                        "node_number": node_number,
                        "nv_index": index,
                    }
                },
            )
            return
        if self._outstanding_request != ("nv", node_number, index):
            trace(
                logger,
                "NVANS does not match outstanding automatic request",
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                        "node_number": node_number,
                        "nv_index": index,
                        "outstanding": self._outstanding_request,
                    }
                },
            )
            return
        if self._nv_read_recovery:
            trace(
                logger,
                "Automatic NV discovery read recovered",
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                        "node_number": node_number,
                        "nv_index": index,
                        "value": value,
                    }
                },
            )
        self.record_nv(node_number, index, value)
        self._finish_request("nv", node_number)

    def _receive_numev(self, node_number: int, count: int) -> None:
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "stored_event_count": count,
        }
        if self._outstanding_request != ("event", node_number, 0):
            trace(
                logger,
                "NUMEV does not match outstanding automatic request",
                extra={"fields": {**fields, "outstanding": self._outstanding_request}},
            )
            return
        state = self.node_states[node_number]
        state.stored_event_count = count
        trace(logger, "Stored event count confirmed", extra={"fields": fields})
        self.node_state_updated.emit(node_number)
        if count > 0:
            self._request_queue.append(("event", node_number, 1))
        self._finish_request("event", node_number)

    def _receive_enrsp(
        self, node_number: int, index: int, event_node: int, event_number: int
    ) -> None:
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "event_index": index,
            "event_node": event_node,
            "event_number": event_number,
        }
        if self._outstanding_request != ("event", node_number, 1):
            trace(
                logger,
                "ENRSP does not match outstanding NERD request",
                extra={"fields": {**fields, "outstanding": self._outstanding_request}},
            )
            return
        state = self.node_states[node_number]
        if index in state.event_identities:
            previous = state.event_identities[index]
            if previous == (event_node, event_number):
                trace(logger, "Duplicate ENRSP index ignored", extra={"fields": fields})
                return
            logger.warning(
                "Conflicting ENRSP identity; event discovery stopped",
                extra={"fields": {**fields, "confirmed_identity": previous}},
            )
            self._request_timer.stop()
            self._outstanding_request = None
            self._set_progress("event", node_number, DiscoveryProgress.INCOMPLETE)
            self._send_next_request()
            return
        state.event_identities[index] = (event_node, event_number)
        confirmed = len(state.event_identities)
        trace(
            logger,
            "Stored event identity confirmed",
            extra={"fields": {**fields, "confirmed": confirmed}},
        )
        self.node_state_updated.emit(node_number)
        if confirmed == state.stored_event_count:
            self._finish_request("event", node_number)
        else:
            # NERD has no final response; each new index extends the wait for more.
            self._request_timer.start(response_timeout.RESPONSE_TIMEOUT_MS)

    def _start_ev_discovery(self, node_number: int) -> None:
        if node_number in self._ev_started:
            return
        state = self.node_states[node_number]
        count = state.parameters.get(5)
        if state.stored_event_count == 0 or count == 0:
            self._ev_started.add(node_number)
            self._set_progress("ev", node_number, DiscoveryProgress.COMPLETE)
            return
        if count is None:
            trace(
                logger,
                "EV discovery waits for parameter 5",
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                        "node_number": node_number,
                    }
                },
            )
            return
        self._ev_started.add(node_number)
        for event_index in sorted(state.event_identities):
            self._request_queue.extend(
                ("ev", node_number, (event_index, ev_index))
                for ev_index in range(1, count + 1)
            )
        trace(
            logger,
            "Automatic EV reads queued",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "node_number": node_number,
                    "events": len(state.event_identities),
                    "ev_count": count,
                }
            },
        )
        self.node_state_updated.emit(node_number)
        self._send_next_request()

    def _receive_neval(
        self, node_number: int, event_index: int, ev_index: int, value: int
    ) -> None:
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "event_index": event_index,
            "ev_index": ev_index,
            "value": value,
        }
        if self._outstanding_request != ("ev", node_number, (event_index, ev_index)):
            trace(
                logger,
                "NEVAL does not match outstanding REVAL",
                extra={"fields": {**fields, "outstanding": self._outstanding_request}},
            )
            return
        self.node_states[node_number].ev_values.setdefault(event_index, {})[
            ev_index
        ] = value
        trace(logger, "EV value confirmed", extra={"fields": fields})
        self.node_state_updated.emit(node_number)
        self._finish_request("ev", node_number)

    def _receive_cmderr(self, node_number: int, code: int) -> None:
        if self.ev_write.reject(node_number, code):
            return
        if self.nv_write.reject(node_number, code):
            return
        if (
            code != 5
            or not self._outstanding_request
            or self._outstanding_request[:2] != ("ev", node_number)
        ):
            return
        state = self.node_states[node_number]
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "request": self._outstanding_request,
        }
        if vlcb_compatible(state.parameters.get(8)) is False:
            # Legacy CBUS assumption: the same-node CMDERR belongs to our
            # outstanding REVAL. CMDERR itself carries no event or EV index.
            event_index, ev_index = self._outstanding_request[2]
            state.ev_values.setdefault(event_index, {})[ev_index] = None
            trace(logger, "Legacy EV confirmed absent", extra={"fields": fields})
            self.node_state_updated.emit(node_number)
        else:
            logger.debug(
                "CMDERR 5 received with REVAL outstanding; EV remains unconfirmed",
                extra={"fields": fields},
            )
            self._set_progress("ev", node_number, DiscoveryProgress.INCOMPLETE)
        self._finish_request("ev", node_number)

    def _queue_event_count(self, node_number: int) -> None:
        if self.node_states[node_number].identity.is_consumer is False:
            trace(
                logger,
                "Automatic event discovery skipped: node is not a consumer",
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                        "node_number": node_number,
                    }
                },
            )
            self._set_progress("event", node_number, DiscoveryProgress.SKIPPED)
            self._set_progress("ev", node_number, DiscoveryProgress.SKIPPED)
            return
        self._request_queue.append(("event", node_number, 0))
        trace(
            logger,
            "Automatic stored event count queued",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "node_number": node_number,
                }
            },
        )

    def _finish_request(self, kind: str, node_number: int) -> None:
        """Advance the shared FIFO only after a matching reply."""
        self._request_timer.stop()
        self._outstanding_request = None
        self._nv_read_recovery = False
        if not any(
            queued_kind == kind and queued_node == node_number
            for queued_kind, queued_node, _index in self._request_queue
        ):
            self._set_progress(kind, node_number, DiscoveryProgress.COMPLETE)
            if kind == "parameter":
                self._queue_event_count(node_number)
            elif kind == "event":
                self._start_ev_discovery(node_number)
        self._send_next_request()

    def _send_next_request(self) -> None:
        self._status_update.start(0)
        if self._outstanding_request is not None:
            return
        if self.nv_write.active:
            self.nv_write.advance()
            return
        if self.ev_write.active:
            self.ev_write.advance()
            return
        self._finish_ev_refresh_if_idle()
        # Removal verification may resume the same writer for reconstruction.
        if self.ev_write.active:
            return
        self._finish_nv_refresh_if_idle()
        while self._request_queue:
            kind, node_number, index = self._request_queue.popleft()
            fields = {
                "layout": self.connection.layout_name,
                "node_number": node_number,
                "kind": kind,
            }
            if kind == "ev":
                event_index, ev_index = index
                fields.update(event_index=event_index, ev_index=ev_index)
            elif kind == "event":
                fields["request"] = "RQEVN" if index == 0 else "NERD"
            else:
                fields[
                    "parameter_index"
                    if kind in ("parameter", "presence")
                    else "nv_index"
                ] = index
            try:
                if kind in ("parameter", "presence"):
                    self.request_parameter(node_number, index)
                elif kind == "nv":
                    self.request_nv(node_number, index)
                elif kind == "ev":
                    self.request_ev(node_number, event_index, ev_index)
                elif index == 0:
                    self.request_stored_event_count(node_number)
                else:
                    self.request_stored_events(node_number)
            except OSError:
                # A failed send leaves confirmed values intact, but cannot hold the queue.
                self._request_queue = deque(
                    request
                    for request in self._request_queue
                    if request[:2] != (kind, node_number)
                )
                logger.error("Automatic requests stopped", extra={"fields": fields})
                self._set_progress(kind, node_number, DiscoveryProgress.INCOMPLETE)
                if kind == "presence":
                    self.presence_checked.emit(node_number, False, 0)
                if kind == "parameter":
                    self._queue_event_count(node_number)
                continue
            self._outstanding_request = (kind, node_number, index)
            self._nv_read_recovery = False
            self._set_progress(kind, node_number, DiscoveryProgress.IN_PROGRESS)
            self._request_timer.start(response_timeout.RESPONSE_TIMEOUT_MS)
            trace(logger, "Awaiting automatic reply", extra={"fields": fields})
            return

        self._finish_ev_refresh_if_idle()
        self._finish_nv_refresh_if_idle()
        if self.refreshing_node is not None:
            number = self.refreshing_node
            self.refreshing_node = None
            self.node_refresh_finished.emit(number)

    def _finish_ev_refresh_if_idle(self) -> None:
        writer = self.ev_write
        if writer.refreshing and not any(
            node == writer.node_number for _kind, node, _index in self._request_queue
        ):
            state = self.node_states[writer.node_number]
            writer.finish_refresh(
                state.event_progress == DiscoveryProgress.COMPLETE
                and state.ev_progress == DiscoveryProgress.COMPLETE
            )

    def _finish_nv_refresh_if_idle(self) -> None:
        """Report the result after this node has exhausted its shared queue work."""
        if self.nv_write.refreshing and not any(
            node == self.nv_write.node_number
            for _kind, node, _index in self._request_queue
        ):
            state = self.node_states[self.nv_write.node_number]
            # No queued or outstanding work remains for this node. Unknown EV
            # capacity or interrupted discovery must never imply success.
            if state.ev_progress == DiscoveryProgress.NOT_STARTED:
                self._set_progress(
                    "ev", self.nv_write.node_number, DiscoveryProgress.INCOMPLETE
                )
            complete = (DiscoveryProgress.COMPLETE, DiscoveryProgress.SKIPPED)
            self.nv_write.finish_refresh(
                state.nv_progress == DiscoveryProgress.COMPLETE
                and (
                    not self.nv_write.refresh_events
                    or (
                        state.event_progress in complete
                        and state.ev_progress in complete
                    )
                )
            )

    def _request_timed_out(self) -> None:
        if self._outstanding_request is None:
            return
        self._request_timer.stop()
        kind, node_number, index = self._outstanding_request
        if kind == "nv" and not self._nv_read_recovery:
            # Keep the same request owner/index: a delayed first reply may satisfy
            # this read, but cannot advance a subsequent, different NV request.
            self._nv_read_recovery = True
            fields = {
                "layout": self.connection.layout_name,
                "node_number": node_number,
                "nv_index": index,
            }
            logger.warning(
                "Automatic NV read timed out; requesting one recovery read",
                extra={"fields": fields},
            )
            try:
                self.request_nv(node_number, index)
            except OSError:
                logger.exception(
                    "Automatic NV recovery read send failed", extra={"fields": fields}
                )
            else:
                self._request_timer.start(response_timeout.RESPONSE_TIMEOUT_MS)
                return
        self._outstanding_request = None
        self._nv_read_recovery = False
        self._request_queue = deque(
            request
            for request in self._request_queue
            if request[:2] != (kind, node_number)
        )
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "kind": kind,
        }
        if kind == "ev":
            event_index, ev_index = index
            fields.update(event_index=event_index, ev_index=ev_index)
        elif kind == "event":
            fields["request"] = "RQEVN" if index == 0 else "NERD"
            if index == 1:
                fields["confirmed_events"] = len(
                    self.node_states[node_number].event_identities
                )
        else:
            fields[
                "parameter_index" if kind in ("parameter", "presence") else "nv_index"
            ] = index
        logger.warning(
            "Automatic request timed out; remaining requests of this kind abandoned",
            extra={"fields": fields},
        )
        self._set_progress(kind, node_number, DiscoveryProgress.INCOMPLETE)
        if kind == "presence":
            self.presence_checked.emit(node_number, False, 0)
        if kind == "parameter":
            self._queue_event_count(node_number)
        self._send_next_request()
