"""Live CBUS node identities and configuration for one GridConnect connection."""

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from . import response_timeout
from .cmderr import decode_cmderr
from .enrsp import decode_enrsp
from .ev_write import EvWrite
from .logging_config import trace
from .neval import decode_neval
from .node_number import NodeNumberAssignment
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

if TYPE_CHECKING:
    # Annotation only: the simulator loads saved metadata, which imports this module.
    from .simulator_connection import SimulatorConnection

logger = logging.getLogger("workbench.cbus")
PARAMETER_READ_ORDER = (2, 4, 5, 6, 7, 8, 10, 20, 19, 9, 1, 3)
RequestIndex = int | tuple[int, int]


class DiscoveryStatus(StrEnum):
    """Aggregate discovery lifecycle; values retain the UI and signal messages."""

    DISCONNECTED = "Disconnected"
    DISCOVERING = "Discovering configuration…"
    READY = "Configuration ready"
    INCOMPLETE = "Discovery incomplete"


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
    # PNN normally confirms identity; manual reads need fresh parameters 1/3/8.
    identity_confirmed: bool = True


class CbusService(QObject):
    presence_changed = Signal(int, bool)
    presence_checked = Signal(int, bool, int)  # Node, responded, module type.
    node_refresh_finished = Signal(int)
    refresh_reported = Signal(int, str)
    layout_refresh_reported = Signal(str)
    discovery_status_changed = Signal(str)
    node_discovered = Signal(Pnn)
    node_updated = Signal(Pnn)
    parameter_updated = Signal(int, int, int)  # Node number, index, value.
    # Observers read the current state by node number, including progress changes.
    node_state_updated = Signal(int)
    event_received = Signal(object)

    def __init__(
        self,
        connection: TcpConnection | SerialConnection | SimulatorConnection,
        can_id: int,
    ):
        """Use a unique PC CAN ID (100–127) assigned for this network."""
        if not 100 <= can_id <= 127:
            raise ValueError("PC CAN ID must be between 100 and 127")
        super().__init__(connection)
        self.connection = connection
        self.can_id = can_id
        self.presence: dict[int, bool] = {}
        self.polling_allowed = lambda: True
        self._poll_pending: deque[int] = deque()
        self._poll_timer = QTimer(self)
        self.node_poll_seconds = 10
        self._poll_timer.setInterval(self.node_poll_seconds * 1000)
        self._poll_timer.timeout.connect(self.poll_presence)
        self.nodes: dict[int, Pnn] = {}
        self.node_states: dict[int, NodeState] = {}
        self._request_queue: deque[tuple[str, int, RequestIndex]] = deque()
        self._outstanding_request: tuple[str, int, RequestIndex] | None = None
        self._nv_read_recovery = False
        self._nv_started: dict[int, int] = {}
        self._ev_started: set[int] = set()
        # Connecting reads identities and parameters only; NVs and events load on
        # demand. Explicit refreshes (and restores) read these nodes in full.
        self._full_discovery: set[int] = set()
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.timeout.connect(self._request_timed_out)
        self.discovery_status = DiscoveryStatus.DISCONNECTED
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
        self.node_number = NodeNumberAssignment(self)
        self.refreshing_node = None
        self.manual_refresh_node: int | None = None
        self.refreshing_layout = False
        # Import after the service types are defined; serializers also use them.
        from .event_save import EventSave
        from .node_restore import NodeRestore
        from .nv_save import NvSave

        self.restore = NodeRestore(self)
        self.nv_save = NvSave(self)
        self.event_save = EventSave(self)
        connection.frame_received.connect(self._receive_frame)

    def close(self) -> None:
        """Stop observing frames when this connection's live state ends."""
        self._closed = True
        if self.refreshing_layout:
            self.refreshing_layout = False
            self.layout_refresh_reported.emit(
                "Refresh Layout interrupted: disconnected"
            )
        if self.manual_refresh_node is not None:
            number = self.manual_refresh_node
            self.manual_refresh_node = None
            self.refreshing_node = None
            self.refresh_reported.emit(number, "Refresh Node interrupted: disconnected")
        self._poll_timer.stop()
        self._poll_pending.clear()
        for number in self.presence:
            self.set_presence(number, False)
        self._discovery_window.stop()
        self._status_update.stop()
        self._set_discovery_status(DiscoveryStatus.DISCONNECTED)
        self.connection.frame_received.disconnect(self._receive_frame)
        self.restore.disconnect()
        self.nv_save.disconnect()
        self.event_save.disconnect()
        self.nv_write.disconnect()
        self.ev_write.disconnect()
        self.node_number.close()
        self._request_timer.stop()
        self._request_queue.clear()
        self._outstanding_request = None
        self._nv_read_recovery = False
        self._nv_started.clear()
        self._ev_started.clear()
        self._full_discovery.clear()
        trace(
            logger,
            "Automatic discovery work cleared",
            extra={"fields": {"layout": self.connection.layout_name}},
        )

    def _set_discovery_status(self, status: DiscoveryStatus) -> None:
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
            or (
                self._outstanding_request is not None
                and self._outstanding_request[0] != "poll"
            )
            or self._request_queue
            or self.restore.active
            or self.nv_save.active
            or self.event_save.active
            or self.nv_write.active
            or self.nv_write.refreshing
            or self.ev_write.active
            or self.ev_write.refreshing
        ):
            status = DiscoveryStatus.DISCOVERING
        else:
            complete = (DiscoveryProgress.COMPLETE, DiscoveryProgress.SKIPPED)
            ready = (
                bool(self.node_states)
                and not self._qnn_failed
                and (
                    not self.refreshing_layout
                    or all(number in self.nodes for number in self.presence)
                )
                and all(
                    state.parameter_progress in complete
                    and all(
                        progress in complete
                        # Not yet loaded on demand is not a failure.
                        or progress == DiscoveryProgress.NOT_STARTED
                        and number not in self._full_discovery
                        for progress in (
                            state.nv_progress,
                            state.event_progress,
                            state.ev_progress,
                        )
                    )
                    for number, state in self.node_states.items()
                )
            )
            status = DiscoveryStatus.READY if ready else DiscoveryStatus.INCOMPLETE
        if self.refreshing_layout and status != DiscoveryStatus.DISCOVERING:
            missing = set(self.presence) - self.nodes.keys()
            for number in missing:
                self.set_presence(number, False)
            self.refreshing_layout = False
            outcome = (
                "Refresh Layout complete"
                if status == DiscoveryStatus.READY
                else f"Refresh Layout incomplete ({len(missing)} nodes did not respond)"
            )
            trace(
                logger,
                outcome,
                extra={"fields": {"layout": self.connection.layout_name}},
            )
            self.layout_refresh_reported.emit(outcome)
        self._set_discovery_status(status)

    def send_event(
        self, event_type: str, node_number: int, event_number: int, on: bool
    ) -> None:
        """Send an event identity using this layout's connection and CAN ID.

        Short events use NN zero on ASON/ASOF frames. The CAN header still
        uses this layout's configured CAN ID, independently of the event NN.
        """
        fields = {
            "layout": self.connection.layout_name,
            "event_type": event_type,
            "node_number": node_number,
            "event_number": event_number,
            "on": on,
        }
        trace(logger, "Send event requested", extra={"fields": fields})
        try:
            if event_type not in ("Long", "Short") or type(on) is not bool:
                raise ValueError("Choose Long or Short and ON or OFF")
            minimum = 0 if event_type == "Short" else 1
            if type(node_number) is not int or not minimum <= node_number <= 65535:
                raise ValueError(
                    f"Event node number must be between {minimum} and 65535"
                )
            if event_type == "Short" and node_number != 0:
                raise ValueError("Short event identity must use node number 0")
            if type(event_number) is not int or not 0 <= event_number <= 65535:
                raise ValueError("Event number must be between 0 and 65535")
            if self._closed or self.connection.state != "Connected":
                raise ConnectionError("Cannot send event: layout is not connected")
            opcode = (0x90 if event_type == "Long" else 0x98) + (not on)
            header = (0x580 | self.can_id) << 5
            frame = f":S{header:04X}N{opcode:02X}{node_number:04X}{event_number:04X};".encode(
                "ascii"
            )
            self.connection.send(frame)
        except ValueError, OSError:
            logger.exception("Could not send event", extra={"fields": fields})
            raise
        trace(logger, "Event frame queued", extra={"fields": fields})

    def discover_nodes(self) -> None:
        """Queue one QNN request; PNN responses arrive independently by signal."""
        if self.node_poll_seconds:
            self._poll_timer.start()
        self._set_discovery_status(DiscoveryStatus.DISCOVERING)
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
            or self.nv_save.active
            or self.event_save.active
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
            or self.refreshing_layout
        )

    def set_presence(self, number: int, online: bool) -> None:
        """Record runtime evidence independently of discovery/configuration data."""
        previous = self.presence.get(number, False)
        self.presence[number] = online
        if previous != online:
            trace(
                logger,
                "Node presence changed",
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                        "node_number": number,
                        "online": online,
                    }
                },
            )
            self.presence_changed.emit(number, online)

    def set_node_poll_seconds(self, seconds: int) -> None:
        """Apply a layout's interval without interrupting an in-flight read."""
        if type(seconds) is not int or not 0 <= seconds <= 300:
            raise ValueError("Node polling seconds must be from 0 to 300")
        self.node_poll_seconds = seconds
        self._poll_timer.stop()
        if seconds:
            self._poll_timer.setInterval(seconds * 1000)
            if not self._closed:
                self._poll_timer.start()
        else:
            self._poll_pending.clear()
        trace(
            logger,
            "Node polling interval changed",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "seconds": seconds,
                }
            },
        )

    def poll_presence(self) -> None:
        """Start at most one bounded pass; busy periods skip this opportunity."""
        if self._poll_pending:
            self._send_next_poll()
            return
        if not self._poll_idle():
            trace(
                logger,
                "Presence polling deferred",
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                    }
                },
            )
            return
        self._poll_pending.extend(sorted(self.presence))
        self._send_next_poll()

    def _poll_idle(self) -> bool:
        return (
            not self._closed
            and self.node_poll_seconds > 0
            and self.connection.state == "Connected"
            and not self._discovery_window.isActive()
            and not self.discovery_pending()
            and not self.writes_busy()
            and self.polling_allowed()
        )

    def _send_next_poll(self) -> None:
        # Keep only one poll on the shared wire. Critical work always goes first.
        if self._poll_pending and self._poll_idle():
            number = self._poll_pending.popleft()
            if number not in self.presence:
                self._send_next_poll()
                return
            self._request_queue.append(("poll", number, 3))
            self._send_next_request()

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

    def refresh_unavailable_reason(self) -> str:
        """Manual refresh must acquire the same idle wire used by discovery."""
        if self._closed or self.connection.state != "Connected":
            return "Refresh Node requires a connected layout"
        if (
            self.writes_busy()
            or self.discovery_pending()
            or self._discovery_window.isActive()
            or not self.polling_allowed()
            or any(
                state.identity.flags & 0x20 or state.parameters.get(8, 0) & 0x20
                for state in self.node_states.values()
            )
        ):
            return (
                "Wait for discovery, polling, writes, restores and learn mode to finish"
            )
        return ""

    def refresh_layout(self) -> None:
        """Repeat full discovery on this connection, keeping local inventory."""
        reason = self.refresh_unavailable_reason()
        if reason:
            trace(
                logger,
                "Refresh Layout refused: %s",
                reason,
                extra={"fields": {"layout": self.connection.layout_name}},
            )
            raise ValueError(reason)
        # Keep addresses for missing nodes, but no previous configuration is
        # evidence for this pass. PNN will initiate the ordinary discovery FIFO.
        self.node_states = {
            number: NodeState(state.identity, identity_confirmed=False)
            for number, state in self.node_states.items()
        }
        self.nodes.clear()
        self._nv_started.clear()
        self._ev_started.clear()
        self._qnn_failed = False
        self.refreshing_layout = True
        trace(
            logger,
            "Refresh Layout started",
            extra={"fields": {"layout": self.connection.layout_name}},
        )
        self.layout_refresh_reported.emit("Refreshing Layout…")
        self.discover_nodes()

    def refresh_node(self, node_number: int) -> None:
        """Reread one node without QNN, transport changes or persisted values."""
        reason = self.refresh_unavailable_reason()
        if reason:
            trace(
                logger,
                "Refresh Node refused: %s",
                reason,
                extra={
                    "fields": {
                        "layout": self.connection.layout_name,
                        "node_number": node_number,
                    }
                },
            )
            raise ValueError(reason)
        if type(node_number) is not int or not 1 <= node_number <= 65535:
            raise ValueError("Node number must be between 1 and 65535")
        # A remembered node may have no live identity. This provisional carrier
        # supplies only its address; flags/capabilities come from fresh PARANs.
        identity = self.nodes.get(node_number, Pnn(node_number, 0, 0, 0))
        self.node_states[node_number] = NodeState(identity, identity_confirmed=False)
        self.presence.setdefault(node_number, False)
        self.manual_refresh_node = node_number
        self.refresh_reported.emit(node_number, "Refreshing Node…")
        self.rediscover_node(node_number)

    def rediscover_node(self, node_number: int) -> None:
        """Read the entire selected node afresh, retaining its confirmed identity."""
        if self._closed or self.connection.state != "Connected":
            raise ValueError("Rediscovery requires an active connection")
        if (
            self.nv_save.active
            or self.event_save.active
            or self.nv_write.active
            or self.ev_write.active
        ):
            raise ValueError("Wait for hardware writes and learn-mode cleanup")
        state = self.node_states[node_number]
        self._set_discovery_status(DiscoveryStatus.DISCOVERING)
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
        self._full_discovery.add(node_number)
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

    def load_nvs(self, node_number: int) -> bool:
        """Read one node's NVs on demand, once per connection.

        Only a section never started is read. A failed or partial read stays
        incomplete until Refresh Node, so revisiting a tab cannot loop on a
        node that does not answer. Returns True when reads were queued.
        """
        state = self.node_states.get(node_number)
        if state is None or state.nv_progress != DiscoveryProgress.NOT_STARTED:
            return False
        if node_number in self._nv_started:
            return False
        fields = {"layout": self.connection.layout_name, "node_number": node_number}
        if self._closed or self.connection.state != "Connected" or self.writes_busy():
            trace(logger, "On-demand NV read deferred", extra={"fields": fields})
            return False
        count = state.parameters.get(6)
        if count is None:
            # Unknown NV count: only Refresh Node can establish it.
            trace(
                logger,
                "On-demand NV read unavailable: parameter 6 unknown",
                extra={"fields": fields},
            )
            return False
        trace(logger, "On-demand NV read requested", extra={"fields": fields})
        self._start_nv_discovery(node_number, count)
        return state.nv_progress != DiscoveryProgress.COMPLETE

    def load_events(self, node_number: int) -> bool:
        """Read one node's stored events and EVs on demand, once per connection.

        Returns True when reads were queued (not for a skipped non-consumer).
        """
        state = self.node_states.get(node_number)
        if (
            state is None
            or state.event_progress != DiscoveryProgress.NOT_STARTED
            or any(r[:2] == ("event", node_number) for r in self._request_queue)
        ):
            return False
        fields = {"layout": self.connection.layout_name, "node_number": node_number}
        if self._closed or self.connection.state != "Connected" or self.writes_busy():
            trace(logger, "On-demand event read deferred", extra={"fields": fields})
            return False
        trace(logger, "On-demand event read requested", extra={"fields": fields})
        self._queue_event_count(node_number)
        self._send_next_request()
        return state.event_progress != DiscoveryProgress.SKIPPED

    def load_online_configuration(self, *, consumers_only: bool = False) -> list[int]:
        """Start loading every online node never loaded; return those now reading.

        Layout-wide operations (backups, Teach) need whole nodes. Offline nodes
        and those that cannot load keep the caller's incomplete handling.
        """
        started = []
        for number, state in sorted(self.node_states.items()):
            if not self.presence.get(number) or (
                consumers_only and not state.identity.is_consumer
            ):
                continue
            nvs = self.load_nvs(number)
            if self.load_events(number) or nvs:
                started.append(number)
        trace(
            logger,
            "Online configuration load requested",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "consumers_only": consumers_only,
                    "started": started,
                }
            },
        )
        return started

    def _parameters_finished(self, node_number: int) -> None:
        """Full discovery continues to events; otherwise load_events() is awaited."""
        if node_number in self._full_discovery:
            self._queue_event_count(node_number)
            return
        trace(
            logger,
            "Parameters read; NVs and events load on demand",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "node_number": node_number,
                }
            },
        )

    def write_nvs(
        self,
        node_number: int,
        values: dict[int, int],
        *,
        owner=None,
    ) -> None:
        """Validate one coordinator-owned NV transaction before transmission."""
        if owner not in (self.restore, self.nv_save) or not owner.active:
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
            raise ValueError(
                "Protocol safety unresolved; no further Save is allowed. Refresh Node, when safe, rereads hardware state; it does not retry failed writes or clear this safety block."
            )
        for index, value in values.items():
            if type(index) is not int or not 1 <= index <= min(count, 255):
                raise ValueError(
                    "NV index must be between 1 and the discovered NV count"
                )
            if type(value) is not int or not 0 <= value <= 255:
                raise ValueError("NV value must be between 0 and 255")
            if index not in state.nv_values:
                raise ValueError(f"NV {index} has no confirmed original value")
        # Editing Save uses MDF links; Node Restore retains its complete checking.
        self.nv_write.begin(
            node_number,
            values,
            refresh_from=next(iter(values)) + 1 if values else 1,
            refresh_events=False,
            refresh_indices=owner.linked_indices if owner is self.nv_save else None,
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
        if owner not in (self.restore, self.event_save) or not owner.active:
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
            raise ValueError(
                "Protocol safety unresolved; no further Save is allowed. Refresh Node, when safe, rereads hardware state; it does not retry failed writes or clear this safety block."
            )
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
        self.ev_write.begin(
            node_number,
            values,
            unlearn=unlearn,
            refresh_events=owner is self.restore
            or unlearn is not None
            or any(key[:2] not in identities for key in values),
        )

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
        if kind in ("presence", "poll"):
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
        self._set_discovery_status(DiscoveryStatus.DISCOVERING)
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
            self.node_number.receive_frame(frame)
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
        # Unsolicited identities must not start unrelated discovery during a
        # targeted refresh. Other received events remain observable as usual.
        if self.manual_refresh_node is not None and pnn is not None:
            return
        if self.manual_refresh_node is not None:
            reply = next(
                (
                    value
                    for value in (paran, nvans, numev, enrsp, neval, cmderr)
                    if value is not None
                ),
                None,
            )
            if reply is not None and reply.node_number != self.manual_refresh_node:
                return
        if pnn is None:
            if paran is not None:
                if (
                    self.manual_refresh_node == paran.node_number
                    and self._outstanding_request
                    != ("parameter", paran.node_number, paran.parameter_index)
                ):
                    return
                if self.manual_refresh_node == paran.node_number:
                    self.node_states[paran.node_number].can_id = (
                        int(frame[2:6], 16) >> 5
                    ) & 0x7F

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

        if pnn.node_number == 0:
            # NN 0 means a module without a node number (SLiM or setup mode).
            # It belongs to commissioning via RQNN, never to the node inventory.
            trace(
                logger,
                "Ignoring PNN from node number 0",
                extra={"fields": {"layout": self.connection.layout_name}},
            )
            return
        self.set_presence(pnn.node_number, True)
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
        state.identity_confirmed = True
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
            if self.refreshing_layout:
                self._full_discovery.add(pnn.node_number)
            self._discovery_window.start(response_timeout.RESPONSE_TIMEOUT_MS)
            self._set_discovery_status(DiscoveryStatus.DISCOVERING)
            self.node_discovered.emit(pnn)
            self.node_state_updated.emit(pnn.node_number)
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
        if index == 3 and self._outstanding_request in (
            ("presence", node_number, 3),
            ("poll", node_number, 3),
        ):
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
            self.set_presence(node_number, True)
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

        if self.manual_refresh_node == node_number:
            self.set_presence(node_number, True)
            if all(key in state.parameters for key in (1, 3, 8)):
                state.identity = Pnn(
                    node_number,
                    state.parameters[1],
                    state.parameters[3],
                    state.parameters[8],
                )
                state.identity_confirmed = True
                if self.nodes.get(node_number) != state.identity:
                    self.nodes[node_number] = state.identity
                    self.node_updated.emit(state.identity)

        # Parameter 6 is the confirmed NV count. It may arrive outside our
        # automatic parameter sequence, so discovery starts on the reply itself.
        if index == 6:
            if node_number not in self._nv_started:
                if node_number in self._full_discovery:
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
        self,
        node_number: int,
        count: int,
        *,
        first: int = 1,
        indices: list[int] | None = None,
    ) -> None:
        self._set_discovery_status(DiscoveryStatus.DISCOVERING)
        self._nv_started[node_number] = count
        if self.nv_write.refreshing and self.nv_write.node_number == node_number:
            # Even an empty range has a new completion transition. This also
            # starts event refresh for a node with no NVs during final checking.
            self._set_progress("nv", node_number, DiscoveryProgress.IN_PROGRESS)
        requested = range(first, count + 1) if indices is None else indices
        if not requested:
            self._set_progress("nv", node_number, DiscoveryProgress.COMPLETE)
            return
        self._request_queue.extend(("nv", node_number, index) for index in requested)
        trace(
            logger,
            "Automatic NV discovery queued",
            extra={
                "fields": {
                    "layout": self.connection.layout_name,
                    "node_number": node_number,
                    "count": count,
                    "first_index": first,
                    "indices": indices,
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
            self._observe_nvans(node_number, index, value)
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

    def _observe_nvans(self, node_number: int, index: int, value: int) -> None:
        """Refresh an already-confirmed NV from a reply another application caused.

        The reply never completes our own request. It only replaces a value we
        already confirmed, so unknown NVs stay unknown. It is ignored while a
        write owns the wire (the writer verifies its own readbacks) and while
        this node's NV pass is running (late duplicates belong to that pass).
        """
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "nv_index": index,
            "value": value,
            "outstanding": self._outstanding_request,
        }
        state = self.node_states[node_number]
        if self.writes_busy():
            reason = "configuration write in progress"
        elif state.nv_progress == DiscoveryProgress.IN_PROGRESS:
            reason = "NV discovery in progress"
        elif index not in state.nv_values:
            reason = "NV has no confirmed value"
        else:
            trace(logger, "Observed NVANS accepted", extra={"fields": fields})
            self.record_nv(node_number, index, value)
            return
        trace(
            logger,
            "Observed NVANS ignored: %s",
            reason,
            extra={"fields": fields},
        )

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
            self._check_observed_enrsp(node_number, index, (event_node, event_number))
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

    def _check_observed_enrsp(
        self, node_number: int, index: int, identity: tuple[int, int]
    ) -> None:
        """Stop trusting a slot map that another application's NERD contradicts.

        NEVAL identifies an event only by slot. A different identity in a known
        slot, or an unknown slot, means the table changed since our discovery.
        Observed traffic never rewrites the event list; the node is marked
        incomplete so passive EV updates stop until Refresh Node rereads it.
        """
        state = self.node_states.get(node_number)
        if (
            state is None
            or state.event_progress != DiscoveryProgress.COMPLETE
            or state.event_identities.get(index) == identity
        ):
            return
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "event_index": index,
            "observed_identity": identity,
            "confirmed_identity": state.event_identities.get(index),
        }
        if self.writes_busy():
            # Outside traffic must not change an in-flight write's outcome.
            # Limitation: a conflict seen only during a write is not retained.
            trace(
                logger,
                "Conflicting observed ENRSP ignored during configuration write",
                extra={"fields": fields},
            )
            return
        logger.warning(
            "Observed ENRSP conflicts with discovered events; Refresh Node required",
            extra={"fields": fields},
        )
        self._set_progress("event", node_number, DiscoveryProgress.INCOMPLETE)

    def _start_ev_discovery(self, node_number: int) -> None:
        if node_number in self._ev_started:
            return
        self._set_discovery_status(DiscoveryStatus.DISCOVERING)
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
            self._observe_neval(node_number, event_index, ev_index, value)
            return
        self.node_states[node_number].ev_values.setdefault(event_index, {})[
            ev_index
        ] = value
        trace(logger, "EV value confirmed", extra={"fields": fields})
        self.node_state_updated.emit(node_number)
        self._finish_request("ev", node_number)

    def _observe_neval(
        self, node_number: int, event_index: int, ev_index: int, value: int
    ) -> None:
        """Refresh an already-known EV from a reply another application caused.

        Attribution relies on our discovered slot map, so it must still be
        complete (see _check_observed_enrsp) and the slot/EV must already be
        known. A confirmed-absent EV (None) is known and may become a value.
        """
        fields = {
            "layout": self.connection.layout_name,
            "node_number": node_number,
            "event_index": event_index,
            "ev_index": ev_index,
            "value": value,
            "outstanding": self._outstanding_request,
        }
        state = self.node_states.get(node_number)
        if state is None:
            reason = "node not discovered"
        elif self.writes_busy():
            reason = "configuration write in progress"
        elif state.event_progress != DiscoveryProgress.COMPLETE:
            reason = "event slots not confirmed by complete discovery"
        elif state.ev_progress == DiscoveryProgress.IN_PROGRESS:
            reason = "EV discovery in progress"
        elif (
            event_index not in state.event_identities
            or ev_index not in state.ev_values.get(event_index, {})
        ):
            reason = "EV is not already known"
        else:
            trace(logger, "Observed NEVAL accepted", extra={"fields": fields})
            if state.ev_values[event_index][ev_index] != value:
                state.ev_values[event_index][ev_index] = value
                self.node_state_updated.emit(node_number)
            return
        trace(logger, "Observed NEVAL ignored: %s", reason, extra={"fields": fields})

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
        state = self.node_states[node_number]
        consumer = state.identity.is_consumer
        if not state.identity_confirmed:
            consumer = bool(state.parameters[8] & 1) if 8 in state.parameters else None
        if consumer is False:
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
                self._parameters_finished(node_number)
            elif kind == "event":
                self._start_ev_discovery(node_number)
        self._send_next_request()

    def _send_next_request(self) -> None:
        # Starts are synchronous so UI work cannot delay the first reply's next
        # request. Completion stays deferred until chained operations have queued.
        if not self._closed and (
            any(kind != "poll" for kind, *_ in self._request_queue)
            or self.writes_busy()
        ):
            self._set_discovery_status(DiscoveryStatus.DISCOVERING)
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
                    if kind in ("parameter", "presence", "poll")
                    else "nv_index"
                ] = index
            try:
                if kind in ("parameter", "presence", "poll"):
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
                if kind in ("presence", "poll"):
                    self.set_presence(node_number, False)
                    self.presence_checked.emit(node_number, False, 0)
                if kind == "parameter":
                    self._parameters_finished(node_number)
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
            if self.manual_refresh_node == number:
                state = self.node_states[number]
                self.set_presence(
                    number,
                    bool(state.parameters) or state.stored_event_count is not None,
                )
                if not state.identity_confirmed:
                    self._set_progress(
                        "parameter", number, DiscoveryProgress.INCOMPLETE
                    )
                complete = (DiscoveryProgress.COMPLETE, DiscoveryProgress.SKIPPED)
                ready = all(
                    progress in complete
                    for progress in (
                        state.parameter_progress,
                        state.nv_progress,
                        state.event_progress,
                        state.ev_progress,
                    )
                )
                outcome = (
                    "Refresh Node complete"
                    if ready
                    else "Refresh Node incomplete"
                    if self.presence.get(number, False)
                    else "Refresh Node: node did not respond (Offline)"
                )
                trace(
                    logger,
                    outcome,
                    extra={
                        "fields": {
                            "layout": self.connection.layout_name,
                            "node_number": number,
                        }
                    },
                )
                self.manual_refresh_node = None
                self.refresh_reported.emit(number, outcome)
            self.node_refresh_finished.emit(number)

        self._send_next_poll()

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
                "parameter_index"
                if kind in ("parameter", "presence", "poll")
                else "nv_index"
            ] = index
        logger.warning(
            "Automatic request timed out; remaining requests of this kind abandoned",
            extra={"fields": fields},
        )
        self._set_progress(kind, node_number, DiscoveryProgress.INCOMPLETE)
        if kind in ("presence", "poll"):
            self.set_presence(node_number, False)
            self.presence_checked.emit(node_number, False, 0)
        if kind == "parameter":
            self._parameters_finished(node_number)
        self._send_next_request()
