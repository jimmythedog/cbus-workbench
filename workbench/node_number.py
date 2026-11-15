"""Assign a node number to a module in setup mode (Developer's Guide 6b §7.2).

A module enters setup mode from its pushbutton, self-enumerates its CAN ID and
sends RQNN with its current node number (0 for a new module). The tool may read
parameters 1–7 with RQNP/PARAMS, then sends SNN; the module replies NNACK.
RQNP and SNN carry no node number, so every module in setup mode would act on
them. Any sign of a second module in setup mode therefore blocks assignment.
"""

import logging
import re

from PySide6.QtCore import QObject, QTimer, Signal

from . import response_timeout
from .cmderr import decode_cmderr
from .logging_config import trace

logger = logging.getLogger("workbench.cbus")

RQNP = 0x10
SNN = 0x42
RQNN = 0x50
NNACK = 0x52
PARAMS = 0xEF
SUGGESTION_BASE = 256

# Node numbers the Developer's Guide 6b §7.2.2 says must not be taught.
_RESERVED = (
    (0, 0, "Node number 0 is used by modules in SLiM"),
    (100, 125, "Node numbers 100–125 are reserved for modules with fixed numbers"),
    (126, 126, "Node number 126 is used by CAN_RS modules"),
    (127, 127, "Node number 127 is used by CAN_USB modules"),
    (65534, 65534, "Node number 65534 is used by the command station"),
    (65535, 65535, "Node number 65535 is used by CABs"),
)


def reserved_reason(number: int) -> str:
    """Return why a node number may not be assigned, or ""."""
    for first, last, reason in _RESERVED:
        if first <= number <= last:
            return reason
    return ""


def check_node_number(
    number: int, current: int, known: dict[int, bool]
) -> tuple[str, str]:
    """Return (blocking reason, warning) for assigning a number.

    `known` maps node numbers Workbench knows on this network to whether they
    are currently online. An offline node may have been replaced, so reusing
    its number is allowed with a warning.
    """
    reason = reserved_reason(number)
    if reason:
        return reason, ""
    if number == current:
        return "", ""
    if known.get(number):
        return f"Node {number} is online on this network", ""
    if number in known:
        return "", (
            f"Node {number} is known but offline. If it is still on the network, "
            "both modules will share this number."
        )
    return "", ""


def suggest_node_number(known) -> int | None:
    """Return the lowest unused, unreserved number, preferring 256 upwards."""
    for number in (*range(SUGGESTION_BASE, 65534), *range(1, SUGGESTION_BASE)):
        if number not in known and not reserved_reason(number):
            return number
    return None


def _payload(frame: bytes) -> tuple[int, bytes]:
    """Return the sender CAN ID and payload of a standard GridConnect frame."""
    match = re.fullmatch(rb":S([0-9A-Fa-f]{4})N([0-9A-Fa-f]{0,16});", frame)
    if match is None or int(match.group(1), 16) & 0x1F:
        raise ValueError("Expected one standard GridConnect data frame")
    payload_hex = match.group(2)
    if len(payload_hex) % 2:
        raise ValueError("GridConnect payload must contain whole bytes")
    return (int(match.group(1), 16) >> 5) & 0x7F, bytes.fromhex(
        payload_hex.decode("ascii")
    )


class NodeNumberAssignment(QObject):
    """One connection's node-number request, from RQNN to NNACK or failure."""

    requested = Signal()  # A new RQNN arrived with no request already open.
    changed = Signal()
    finished = Signal(bool, str)  # Acknowledged, user-facing outcome.

    def __init__(self, service):
        super().__init__(service)
        self.service = service
        self.current: int | None = None  # NN reported by RQNN; None: no request.
        self.can_id: int | None = None
        self.parameters: bytes | None = None  # PARAMS 1–7, when reported.
        self.ambiguous = ""
        self.target: int | None = None  # SNN sent and awaiting NNACK.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timed_out)

    def _fields(self, **extra) -> dict:
        return {
            "fields": {
                "layout": self.service.connection.layout_name,
                "current_node_number": self.current,
                "can_id": self.can_id,
                "target": self.target,
                **extra,
            }
        }

    def _send(self, opcode: int, data: str = "") -> None:
        # Minor priority 3, as the guide's format for RQNP and SNN.
        header = (0x580 | self.service.can_id) << 5
        self.service.connection.send(f":S{header:04X}N{opcode:02X}{data};".encode())

    def receive_frame(self, frame: bytes) -> None:
        """Observe setup-mode traffic; raise ValueError for malformed replies."""
        can_id, payload = _payload(frame)
        if not payload:
            return
        opcode = payload[0]
        if opcode == RQNN and len(payload) == 3:
            self._receive_rqnn((payload[1] << 8) | payload[2], can_id)
        elif opcode == PARAMS and len(payload) == 8 and self.current is not None:
            self._receive_params(payload[1:], can_id)
        elif opcode == NNACK and len(payload) == 3 and self.target is not None:
            if (payload[1] << 8) | payload[2] == self.target:
                self._acknowledged(can_id)
        elif opcode in (RQNN, PARAMS, NNACK):
            raise ValueError(f"Opcode 0x{opcode:02X} has the wrong payload length")
        elif self.target is not None:
            cmderr = decode_cmderr(frame)
            if cmderr is not None and cmderr.node_number in (self.current, self.target):
                self._finish(
                    False,
                    f"The module reported error {cmderr.code} instead of "
                    f"acknowledging node number {self.target}.\n\n"
                    + self._uncertain_advice(),
                )

    def _receive_rqnn(self, number: int, can_id: int) -> None:
        trace(logger, "RQNN received", extra=self._fields(rqnn=number, sender=can_id))
        if self.current is None:
            self.current, self.can_id = number, can_id
            logger.info("Node number requested", extra=self._fields())
            self.requested.emit()
        elif (number, can_id) != (self.current, self.can_id) and not self.ambiguous:
            self._set_ambiguous(
                f"Another module (CAN ID {can_id}, node number {number}) is also "
                "requesting a node number."
            )

    def _receive_params(self, parameters: bytes, can_id: int) -> None:
        if can_id != self.can_id:
            self._set_ambiguous(
                f"A module with CAN ID {can_id} also answered as being in setup mode."
            )
            return
        self.parameters = bytes(parameters)
        trace(logger, "PARAMS received", extra=self._fields(params=list(parameters)))
        self.changed.emit()

    def _set_ambiguous(self, reason: str) -> None:
        # SNN would reach every module in setup mode, so stop rather than guess.
        self.ambiguous = reason
        logger.warning(
            "Node number request ambiguous: %s", reason, extra=self._fields()
        )
        self.changed.emit()

    def request_parameters(self) -> None:
        """Ask the module in setup mode for parameters 1–7 (optional)."""
        trace(logger, "Sending RQNP", extra=self._fields())
        try:
            self._send(RQNP)
        except OSError:
            logger.exception("Could not send RQNP", extra=self._fields())

    def unavailable_reason(self, number: int, known: dict[int, bool]) -> str:
        """Return why Assign is not allowed now, or ""."""
        if self.current is None:
            return "No module is waiting for a node number"
        if self.service._closed or self.service.connection.state != "Connected":
            return "The layout is not connected"
        if self.ambiguous:
            return self.ambiguous
        if self.target is not None:
            return "Waiting for the module to acknowledge"
        if self.service.writes_busy() or self.service.manual_refresh_node is not None:
            return "Wait for writes, restores or Refresh Node to finish"
        return check_node_number(number, self.current, known)[0]

    def assign(self, number: int, known: dict[int, bool]) -> None:
        """Send SNN once; the outcome arrives through `finished`."""
        reason = self.unavailable_reason(number, known)
        if reason:
            raise ValueError(reason)
        self.target = number
        logger.info("Sending SNN", extra=self._fields())
        try:
            self._send(SNN, f"{number:04X}")
        except OSError as error:
            logger.exception("Could not send SNN", extra=self._fields())
            # The frame may not have left the PC, so the module is unchanged
            # unless the transport failed after transmission.
            self._finish(False, f"Could not send the node number: {error}")
            return
        self._timer.start(response_timeout.RESPONSE_TIMEOUT_MS)
        self.changed.emit()

    def _acknowledged(self, can_id: int) -> None:
        number = self.target
        if can_id != self.can_id:
            # The requester self-enumerated before RQNN (guide §7.2.1), so its
            # CAN ID is fixed; another sender may be a module already using NN.
            self._finish(
                False,
                f"Node number {number} was acknowledged by CAN ID {can_id}, not by "
                f"the requesting module (CAN ID {self.can_id}).\n\n"
                + self._uncertain_advice(),
            )
            return
        if self.ambiguous:
            self._finish(
                False,
                f"Node number {number} was acknowledged, but another module was "
                "also in setup mode, so it is uncertain which module took it. "
                "Use Layouts → Refresh to check.",
            )
            return
        self._finish(True, f"Node number {number} assigned")
        try:
            if number in self.service.node_states:
                # Live values for this number may describe whatever used it
                # before; reread it through the existing per-node path. Other
                # nodes keep their state.
                self.service.rediscover_node(number)
            # QNN: the module's PNN supplies its identity; a new number starts
            # ordinary discovery and unchanged PNNs from other nodes are ignored.
            self.service.discover_nodes()
        except ValueError, OSError:
            logger.exception(
                "Discovery after node number assignment did not start",
                extra=self._fields(node_number=number),
            )

    def _timed_out(self) -> None:
        self._finish(
            False,
            f"The module did not acknowledge node number {self.target}.\n\n"
            + self._uncertain_advice(),
        )

    def _uncertain_advice(self) -> str:
        return (
            "It may or may not have taken the new number. A steady yellow LED "
            "usually means it has a node number; a flashing one means it is still "
            "in setup mode. Use Layouts → Refresh to check, or press the module's "
            "button again to retry."
        )

    def cancel(self) -> None:
        """Forget the request before SNN; the module stays in setup mode."""
        if self.target is not None:
            raise ValueError("Wait for the module to acknowledge")
        if self.current is not None:
            logger.info("Node number request cancelled", extra=self._fields())
        self._clear()

    def close(self) -> None:
        """Connection ended: never report an unacknowledged assignment as done."""
        if self.target is not None:
            self._finish(
                False,
                f"Disconnected before node number {self.target} was acknowledged.\n\n"
                + self._uncertain_advice(),
            )
        elif self.current is not None:
            self._finish(False, "Disconnected. The module is still in setup mode.")

    def _finish(self, success: bool, message: str) -> None:
        (logger.info if success else logger.warning)(
            "Node number assignment finished: %s", message, extra=self._fields()
        )
        self._clear()
        self.finished.emit(success, message)

    def _clear(self) -> None:
        self._timer.stop()
        self.current = self.can_id = self.parameters = self.target = None
        self.ambiguous = ""
