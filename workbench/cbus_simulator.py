"""Simulated CBUS nodes built from a logical layout's saved metadata (issue #90).

`CbusSimulator.handle()` takes one outgoing GridConnect frame and returns the
frames the simulated nodes reply with. It has no Qt dependency; the simulator
connection delivers the replies. Semantics follow legacy CBUS (MERG Developer's
Guide 6b and CBUSlib FliM.c, commit bec37f9) for every node, including nodes
whose saved parameter 8 advertises VLCB; VLCB-specific behaviour is out of scope.

Values are never invented. A node is simulated only when its saved metadata
identifies it honestly (CAN ID, manufacturer, module type and flags). Missing
capability parameters leave only the corresponding requests unanswered.
"""

import logging
import re
from dataclasses import dataclass, field

from .logging_config import trace
from .node_backup_files import saved_node_numbers
from .node_metadata import load_metadata

logger = logging.getLogger("workbench.simulator")

QNN = 0x0D
NNLRN = 0x53
NNULN = 0x54
NERD = 0x57
RQEVN = 0x58
WRACK = 0x59
CMDERR = 0x6F
NVRD = 0x71
RQNPN = 0x73
NUMEV = 0x74
EVULN = 0x95
NVSET = 0x96
NVANS = 0x97
PARAN = 0x9B
REVAL = 0x9C
REQEV = 0xB2
NEVAL = 0xB5
PNN = 0xB6
EVLRN = 0xD2
EVANS = 0xD3
ENRSP = 0xF2

# Requests carrying the addressed node's NN in the first two data bytes.
NODE_REQUESTS = (NNULN, NERD, RQEVN, NVRD, RQNPN, NVSET, REVAL)
# Requests carrying an event identity, acted on by every node in learn mode.
LEARN_REQUESTS = (EVULN, REQEV, EVLRN)

# Parameter 8 flag bits.
LEARN_FLAG = 0x20
VLCB_FLAG = 0x40

# CMDERR codes (Developer's Guide 6b).
TOO_MANY_EVENTS = 4
NO_EV = 5
INVALID_EV_INDEX = 6
INVALID_EVENT = 7
INVALID_PARAMETER_INDEX = 9
INVALID_NV_INDEX = 10

# Parameters needed to answer QNN with PNN(NN, manufacturer, module type, flags).
IDENTITY_PARAMETERS = {1: "manufacturer", 3: "module type", 8: "flags"}


@dataclass
class LearnedEvent:
    # (event NN, event number) exactly as taught; short events use NN 0.
    identity: tuple[int, int]
    # EV 1 is evs[0]. As in CBUSlib, EVs below the highest taught read as zero
    # and those above it are absent (CMDERR 5).
    evs: list[int]


@dataclass
class SimulatedNode:
    node_number: int
    can_id: int
    # Saved positional parameters, index 0 being the count; None is unknown.
    parameters: list[int | None]
    # NV 1 is nvs[0]. None when parameter 6 (NV count) is unknown.
    nvs: list[int] | None
    learning: bool = False
    # Event table keyed by 1-based slot (CBUSlib tableIndexToEvtIdx).
    events: dict[int, LearnedEvent] = field(default_factory=dict)

    def parameter(self, index: int) -> int | None:
        return self.parameters[index] if index < len(self.parameters) else None


def node_from_metadata(node_number: int, metadata: dict) -> SimulatedNode | str:
    """Return a simulated node, or the reason the metadata cannot identify one."""
    if not isinstance(metadata, dict):
        return "unreadable metadata"
    can_id = metadata.get("canId")
    if type(can_id) is not int or not 1 <= can_id <= 127:
        return "no saved CAN ID"
    parameters = metadata.get("parameters")
    if not isinstance(parameters, list) or not all(
        value is None or (type(value) is int and 0 <= value <= 255)
        for value in parameters
    ):
        return "no saved parameters"
    missing = [
        name
        for index, name in IDENTITY_PARAMETERS.items()
        if index >= len(parameters) or parameters[index] is None
    ]
    if missing:
        return f"missing {', '.join(missing)}"
    nv_count = parameters[6] if len(parameters) > 6 else None
    # Simulator initialisation rule, not a claim about firmware defaults.
    nvs = None if nv_count is None else [0] * nv_count
    return SimulatedNode(node_number, can_id, list(parameters), nvs)


def load_simulated_nodes(
    logical_layout: str,
) -> tuple[list[SimulatedNode], dict[int, str]]:
    """Return simulated nodes and {node number: reason} for skipped saved nodes."""
    nodes = []
    skipped = {}
    for number in saved_node_numbers(logical_layout):
        node = node_from_metadata(number, load_metadata(logical_layout, number))
        if isinstance(node, str):
            skipped[number] = node
            logger.warning(
                "Saved node not simulated: %s",
                node,
                extra={
                    "fields": {"logical_layout": logical_layout, "node_number": number}
                },
            )
            continue
        nodes.append(node)
        trace(
            logger,
            "Simulated node loaded",
            extra={
                "fields": {
                    "logical_layout": logical_layout,
                    "node_number": number,
                    "can_id": node.can_id,
                    "nv_count": None if node.nvs is None else len(node.nvs),
                }
            },
        )
    return nodes, skipped


def _frame(can_id: int, opcode: int, *data: int) -> bytes:
    # Same priority bits as Workbench's own requests; CBUS replies carry the
    # node's CAN ID in the low seven bits of the identifier.
    header = (0x580 | can_id) << 5
    payload = bytes((opcode, *data)).hex().upper()
    return f":S{header:04X}N{payload};".encode()


class CbusSimulator:
    def __init__(self, nodes: list[SimulatedNode]):
        self.nodes = {node.node_number: node for node in nodes}

    def handle(self, frame: bytes) -> list[bytes]:
        """Return reply frames for one outgoing frame; others are ignored."""
        match = re.fullmatch(rb":S([0-9A-Fa-f]{4})N([0-9A-Fa-f]{2,16});", frame)
        if match is None or int(match[1], 16) & 0x1F or len(match[2]) % 2:
            trace(logger, "Simulator ignored non-CBUS frame", extra=_fields(frame))
            return []
        payload = bytes.fromhex(match[2].decode("ascii"))
        opcode = payload[0]
        # The top three opcode bits give the number of data bytes.
        if len(payload) != 1 + (opcode >> 5):
            trace(logger, "Simulator ignored wrong-length frame", extra=_fields(frame))
            return []
        if opcode == QNN:
            replies = [
                _frame(
                    node.can_id,
                    PNN,
                    *node.node_number.to_bytes(2),
                    node.parameters[1],
                    node.parameters[3],
                    node.parameters[8],
                )
                for node in sorted(self.nodes.values(), key=lambda n: n.node_number)
            ]
        elif opcode == NNLRN:
            replies = []
            self._enter_learn_mode(int.from_bytes(payload[1:3]))
        elif opcode in NODE_REQUESTS:
            node = self.nodes.get(int.from_bytes(payload[1:3]))
            replies = [] if node is None else self._node_request(node, payload)
        elif opcode in LEARN_REQUESTS:
            identity = (int.from_bytes(payload[1:3]), int.from_bytes(payload[3:5]))
            replies = [
                reply
                for node in sorted(self.nodes.values(), key=lambda n: n.node_number)
                if node.learning
                for reply in self._learn_request(node, opcode, identity, payload[5:])
            ]
        else:
            replies = []
        trace(
            logger,
            "Simulator handled frame",
            extra=_fields(frame, replies=[reply.decode() for reply in replies]),
        )
        return replies

    def _node_request(self, node: SimulatedNode, payload: bytes) -> list[bytes]:
        opcode, data = payload[0], payload[3:]
        if opcode == RQNPN:
            return self._read_parameter(node, data[0])
        if opcode == NVRD:
            return self._read_nv(node, data[0])
        if opcode == NVSET:
            return self._write_nv(node, data[0], data[1])
        if opcode == NNULN:
            self._set_learning(node, False)
            return []  # NNULN has no acknowledgement.
        if opcode == RQEVN:
            return [self._reply(node, NUMEV, len(node.events))]
        if opcode == NERD:
            return [
                self._reply(node, ENRSP, *_identity_bytes(event.identity), slot)
                for slot, event in sorted(node.events.items())
            ]
        return self._read_ev_by_slot(node, data[0], data[1])

    def _enter_learn_mode(self, number: int) -> None:
        # CBUSlib FliM.c: a node already in learn mode leaves it when NNLRN
        # addresses another node. NNLRN has no acknowledgement.
        for node in self.nodes.values():
            self._set_learning(node, node.node_number == number)

    def _set_learning(self, node: SimulatedNode, learning: bool) -> None:
        if node.learning != learning:
            node.learning = learning
            trace(
                logger,
                "Simulated node entered learn mode"
                if learning
                else "Simulated node left learn mode",
                extra={"fields": {"node_number": node.node_number}},
            )

    def _learn_request(
        self,
        node: SimulatedNode,
        opcode: int,
        identity: tuple[int, int],
        data: bytes,
    ) -> list[bytes]:
        slot = next(
            (slot for slot, event in node.events.items() if event.identity == identity),
            None,
        )
        if opcode == EVULN:
            if slot is not None:
                trace(logger, "Simulated event removed", extra=_event(node, slot))
                del node.events[slot]
            return []  # EVULN has no acknowledgement (CBUSlib doEvuln).
        ev_count = node.parameter(5)
        if ev_count is None:
            # Without a confirmed EV count, EV indices cannot be validated.
            return []
        if opcode == REQEV:
            if slot is None:
                return [self._error(node, INVALID_EVENT)]
            if data[0] > ev_count:
                return [self._error(node, INVALID_EV_INDEX)]
            value = self._ev_value(node.events[slot], data[0])
            if value is None:
                return [self._error(node, NO_EV)]
            # The event's NN, as the VLCB Opcode specification defines EVANS.
            # CBUSlib doReqev sends the consumer's own NN instead.
            return [
                _frame(node.can_id, EVANS, *_identity_bytes(identity), data[0], value)
            ]
        return self._teach(node, slot, identity, data[0], data[1], ev_count)

    def _teach(
        self,
        node: SimulatedNode,
        slot: int | None,
        identity: tuple[int, int],
        ev_index: int,
        value: int,
        ev_count: int,
    ) -> list[bytes]:
        # Checked before creating the event, so a rejected request changes
        # nothing. CBUSlib addEvent creates the entry first.
        if not 1 <= ev_index <= ev_count:
            return [self._error(node, INVALID_EV_INDEX)]
        if slot is None:
            capacity = node.parameter(4)
            if capacity is None:
                # Without a confirmed table size, a new event cannot be placed.
                return []
            slot = next(
                (slot for slot in range(1, capacity + 1) if slot not in node.events),
                None,
            )
            if slot is None:
                return [self._error(node, TOO_MANY_EVENTS)]
            node.events[slot] = LearnedEvent(identity, [])
            trace(logger, "Simulated event created", extra=_event(node, slot))
        evs = node.events[slot].evs
        # Value validation and actions are module-specific; any byte is stored.
        evs.extend([0] * (ev_index - len(evs)))
        evs[ev_index - 1] = value
        trace(
            logger,
            "Simulated EV written",
            extra=_event(node, slot, ev_index=ev_index, value=value),
        )
        return [self._reply(node, WRACK)]

    def _read_ev_by_slot(
        self, node: SimulatedNode, slot: int, ev_index: int
    ) -> list[bytes]:
        ev_count = node.parameter(5)
        if ev_count is None:
            return []
        # CBUSlib doReval checks the EV index before the event slot.
        if ev_index > ev_count:
            return [self._error(node, INVALID_EV_INDEX)]
        if slot not in node.events:
            return [self._error(node, INVALID_EVENT)]
        value = self._ev_value(node.events[slot], ev_index)
        if value is None:
            return [self._error(node, NO_EV)]
        return [self._reply(node, NEVAL, slot, ev_index, value)]

    def _ev_value(self, event: LearnedEvent, ev_index: int) -> int | None:
        """EV 0 is the number of EVs (CBUSlib numEv); None means absent."""
        if ev_index == 0:
            return len(event.evs)
        return event.evs[ev_index - 1] if ev_index <= len(event.evs) else None

    def _read_parameter(self, node: SimulatedNode, index: int) -> list[bytes]:
        count = node.parameter(0)
        if count is not None and index > count:
            return [self._error(node, INVALID_PARAMETER_INDEX)]
        value = node.parameter(index)
        if value is None:
            # Unknown, not absent: a reply would invent a value.
            return []
        if index == 8 and value & VLCB_FLAG:
            # VLCB Event Teach reports learn mode in parameter 8 bit 5, and CW
            # requires that confirmation from VLCB nodes. Legacy CBUS nodes'
            # saved flags are reported unchanged; nothing is persisted.
            value = value & ~LEARN_FLAG | (LEARN_FLAG if node.learning else 0)
        return [self._reply(node, PARAN, index, value)]

    def _read_nv(self, node: SimulatedNode, index: int) -> list[bytes]:
        if node.nvs is None:
            # Without a confirmed NV count the node's NVs are unknown.
            return []
        if not 1 <= index <= len(node.nvs):
            return [self._error(node, INVALID_NV_INDEX)]
        return [self._reply(node, NVANS, index, node.nvs[index - 1])]

    def _write_nv(self, node: SimulatedNode, index: int, value: int) -> list[bytes]:
        if node.nvs is None:
            # Without a confirmed NV count there is no NV array to change.
            return []
        if not 1 <= index <= len(node.nvs):
            return [self._error(node, INVALID_NV_INDEX)]
        # Every byte is accepted: value validation and side effects on other
        # NVs are module-specific firmware behaviour (CBUSlib validateNV and
        # actUponNVchange), which the simulator does not invent.
        trace(
            logger,
            "Simulated NV written",
            extra={
                "fields": {
                    "node_number": node.node_number,
                    "nv_index": index,
                    "old_value": node.nvs[index - 1],
                    "value": value,
                }
            },
        )
        node.nvs[index - 1] = value
        return [self._reply(node, WRACK)]

    def _reply(self, node: SimulatedNode, opcode: int, *data: int) -> bytes:
        return _frame(node.can_id, opcode, *node.node_number.to_bytes(2), *data)

    def _error(self, node: SimulatedNode, code: int) -> bytes:
        return self._reply(node, CMDERR, code)


def _identity_bytes(identity: tuple[int, int]) -> bytes:
    return identity[0].to_bytes(2) + identity[1].to_bytes(2)


def _event(node: SimulatedNode, slot: int, **fields) -> dict:
    return {
        "fields": {
            "node_number": node.node_number,
            "slot": slot,
            "event": node.events[slot].identity,
            **fields,
        }
    }


def _fields(frame: bytes, **fields) -> dict:
    return {"fields": {"frame": frame.decode("ascii", errors="replace"), **fields}}
