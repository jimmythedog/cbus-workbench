"""Sequential EV teaching, identity-based verification, and bounded learn exit.

MERG Developer's Guide 6b §7.2.7 and VLCB Event Teach / Opcode specifications:
https://github.com/Versatile-LCB/VLCB-documents
NNLRN/NNULN have no acknowledgement. The learn flag is proposed in CBUS 6c,
but specified by VLCB Event Teach §14.1. A legacy clear bit proves neither mode.
WRACK plus matching EVANS verifies teaching even without a reported mode.
REQEV/EVANS use the event identity; EVANS identifies its sender by CAN ID.
VLCB Opcode §3.7.9 specifies the event NN in EVANS. Legacy CBUSlib
FliM.c doReqev() uses cbusSendOpcMyNN(), substituting the consumer NN.
For short events only, accept that consumer NN as well as the specified zero.
"""

import logging
import re

from PySide6.QtCore import QObject, QTimer, Signal

from . import response_timeout
from .logging_config import trace

logger = logging.getLogger("workbench.cbus")


class EvWrite(QObject):
    finished = Signal(int, bool, str)

    def __init__(self, service):
        super().__init__(service)
        self.service = service
        self.active = False
        self.refreshing = False
        self.blocked = False  # An uncertain write/exit requires a new connection.
        self.stage = ""
        self.node_number = 0
        self.changes = []
        self.unlearn = None
        self.removals_transmitted = 0
        self.removed = 0
        self.verified = 0
        self.learn_requested = False
        self.failure = ""
        self.resolved = False
        self.flag_reliable = False
        self.exit_confirmed = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timed_out)

    def begin(
        self,
        node_number: int,
        changes: dict[tuple[int, int, int], int],
        *,
        unlearn=None,
    ) -> None:
        self.node_number = node_number
        self.changes = sorted(changes.items())
        self.unlearn = unlearn
        existing = set(self.service.node_states[node_number].event_identities.values())
        creating = {key[:2] for key in changes if key[:2] not in existing}
        if unlearn is not None:
            creating.add(unlearn)
        # A zero EVLRN can be acknowledged without creating the identity. Move
        # one saved nonzero EV first; its normal WRACK/REQEV/EVANS verification
        # must finish before teaching the remaining values (including zeros).
        for identity in sorted(creating):
            nonzero = next(
                (
                    i
                    for i, (key, value) in enumerate(self.changes)
                    if key[:2] == identity and value != 0
                ),
                None,
            )
            if nonzero is not None:
                first = next(
                    i for i, (key, _) in enumerate(self.changes) if key[:2] == identity
                )
                self.changes.insert(first, self.changes.pop(nonzero))
        self.identity_established = not creating
        self.removals_transmitted = 0
        self.removed = 0
        self.total = len(self.changes)
        self.verified = 0
        self.failure = ""
        self.resolved = False
        self.learn_requested = False
        flags = self.service.node_states[node_number].parameters.get(8, 0)
        # VLCB specifies the flag; a CBUS set bit is also positive evidence.
        # A legacy clear bit says nothing about whether the flag is implemented.
        self.flag_reliable = bool(flags & (0x40 | 0x20))
        self.exit_confirmed = False
        self.active = True
        self.stage = "waiting for discovery reply"
        self.log("EV Save accepted", changes=self.changes)
        self.service._send_next_request()

    def advance(self):
        if self.stage != "waiting for discovery reply":
            return
        if not self.changes and self.unlearn is None:
            self.finish(True, "No changed EVs.")
            return
        # Sending NNLRN requests entry; only replies provide evidence. Probe a
        # known flags parameter, otherwise use standard WRACK/EVANS verification.
        self.learn_requested = True
        if self.send(f"53{self.node_number:04X}", "entering learn mode"):
            if 8 in self.service.node_states[self.node_number].parameters:
                self.check_mode("confirming learn mode")
            else:
                self.write_next()

    def send(self, payload, stage, *, expect_response=True):
        self.stage = stage
        if expect_response:
            self.timer.start(response_timeout.RESPONSE_TIMEOUT_MS)
        else:
            self.timer.stop()
        header = (0x580 | self.service.can_id) << 5
        self.log("Sending EV operation", payload=payload)
        try:
            self.service.connection.send(f":S{header:04X}N{payload};".encode())
            return True
        except OSError:
            logger.exception("EV operation transmission failed")
            if stage in ("leaving learn mode", "confirming learn-mode exit"):
                self.finish(
                    False, self.exit_uncertain("Could not transmit learn-mode exit.")
                )
            else:
                self.fail(f"Could not transmit while {stage}.")
            return False

    def check_mode(self, stage):
        self.send(f"73{self.node_number:04X}08", stage)

    def receive_mode(self, node_number: int, index: int, value: int) -> bool:
        if not self.active or node_number != self.node_number or index != 8:
            return False
        if self.stage not in ("confirming learn mode", "confirming learn-mode exit"):
            return False
        self.timer.stop()
        self.log("Learn-mode flags received", flags=value)
        if self.stage == "confirming learn mode":
            if value & 0x20:
                self.flag_reliable = True
            elif self.flag_reliable:
                self.identity_established = False
                self.fail(
                    "Node did not confirm learn mode; no EVs written.", resolved=True
                )
                return True
            self.log("Starting teaching", learn_flag_reliable=self.flag_reliable)
            self.write_next()
        elif value & 0x20:
            self.finish(False, self.exit_uncertain("Node still reports learn mode."))
        else:
            self.exit_confirmed = True
            self.complete_exit()
        return True

    def write_next(self):
        if self.unlearn is not None:
            event_node, event_number = self.unlearn
            # EVULN has no specified acknowledgement. Exit learn mode and use
            # event rediscovery to prove absence before any replacement EVLRN.
            if self.send(
                f"95{event_node:04X}{event_number:04X}",
                "unlearning event",
                expect_response=False,
            ):
                self.removals_transmitted = 1
                self.log(
                    "EVULN transmitted; removal not yet verified", identity=self.unlearn
                )
                self.leave_learn()
            return
        (event_node, event_number, ev), value = self.changes[0]
        # Once teaching is attempted, the old value is no longer evidence of
        # physical state. Missing keys already mean unknown to backups/Compare.
        state = self.service.node_states[self.node_number]
        for slot, identity in state.event_identities.items():
            if identity == (event_node, event_number):
                state.ev_values.get(slot, {}).pop(ev, None)
        self.log("Invalidating cached EV before teaching", identity=self.changes[0][0])
        self.send(f"D2{event_node:04X}{event_number:04X}{ev:02X}{value:02X}", "WRACK")

    def acknowledge(self, node_number):
        if not self.active or self.stage != "WRACK":
            return
        if node_number != self.node_number:
            # A second learner may have accepted this broadcast write. Stop and
            # release both nodes, as recommended by the developer's guide.
            header = (0x580 | self.service.can_id) << 5
            self.log("Releasing unexpected learner", unexpected_node=node_number)
            try:
                self.service.connection.send(
                    f":S{header:04X}N54{node_number:04X};".encode()
                )
            except OSError:
                logger.exception("Could not release unexpected learner")
            self.fail(
                "Another node acknowledged the write; its learn-mode exit is unconfirmed. Check both nodes before retrying."
            )
            return
        (event_node, event_number, ev), _value = self.changes[0]
        self.log("EV write acknowledged; requesting identity-based readback")
        self.send(f"B2{event_node:04X}{event_number:04X}{ev:02X}", "EVANS")

    def receive_frame(self, frame: bytes) -> None:
        """Handle EVANS only after an acknowledged write and from this node."""
        if not self.active or self.stage != "EVANS":
            return
        match = re.fullmatch(
            rb":S([0-9A-Fa-f]{4})N(D3[0-9A-Fa-f]{12});", frame, re.IGNORECASE
        )
        if match is None or int(match[1], 16) & 0x1F:
            return
        can_id = (int(match[1], 16) >> 5) & 0x7F
        state = self.service.node_states[self.node_number]
        payload = bytes.fromhex(match[2].decode())
        key = (int.from_bytes(payload[1:3]), int.from_bytes(payload[3:5]), payload[5])
        expected_key, expected = self.changes[0]
        # Do not ignore NN generally: only a requested short event permits the
        # legacy consumer-NN reply. Source CAN ID, EN and EV remain mandatory.
        short_reply = expected_key[0] == 0 and key[0] == self.node_number
        if (
            can_id != state.can_id
            or key[1:] != expected_key[1:]
            or (key[0] != expected_key[0] and not short_reply)
        ):
            self.log("Ignoring unrelated EVANS", can_id=can_id, identity=key)
            return
        value = payload[6]
        self.log("EV readback received", identity=key, value=value, expected=expected)
        if value != expected:
            self.fail(
                f"EV {key[2]}: readback mismatch (received {value}, expected {expected}).",
                resolved=True,
            )
            return
        self.timer.stop()
        # Resolve the slot from current live discovery; never retain it in edits.
        slot = next(
            (
                i
                for i, event in state.event_identities.items()
                if event == expected_key[:2]
            ),
            None,
        )
        # A new/reconstructed event has no discovered slot yet. Its EVANS still
        # verifies this identity/value; the normal refresh will find its new slot.
        if slot is not None:
            state.ev_values.setdefault(slot, {})[key[2]] = value
        self.identity_established = True
        self.verified += 1
        self.changes.pop(0)
        self.service.node_state_updated.emit(self.node_number)
        if self.changes:
            self.write_next()
        else:
            self.leave_learn()

    def reject(self, node_number: int, code: int) -> bool:
        if (
            not self.active
            or node_number != self.node_number
            or self.stage == "waiting for discovery reply"
        ):
            return False
        self.log("EV operation rejected", code=code)
        if self.stage in ("leaving learn mode", "confirming learn-mode exit"):
            self.finish(
                False,
                self.exit_uncertain("Node rejected learn-mode exit confirmation."),
            )
        else:
            if self.stage == "confirming learn mode":
                self.identity_established = False
            self.fail(
                "Node rejected event unlearn."
                if self.unlearn is not None
                else "Node rejected the EV write."
                if self.stage == "WRACK"
                else "Node rejected EV verification or learn-mode entry.",
                resolved=True,
            )
        return True

    def fail(self, reason, *, resolved=False):
        # A reply resolves an individual operation; safe exit is still required.
        self.resolved = resolved
        self.failure = reason
        self.blocked = True
        self.log("EV Save failed; attempting learn-mode exit", reason=reason)
        if self.learn_requested:
            self.leave_learn()
        else:
            self.finish(False, reason)

    def leave_learn(self):
        if self.send(f"54{self.node_number:04X}", "leaving learn mode"):
            if self.flag_reliable:
                self.check_mode("confirming learn-mode exit")
            else:
                self.complete_exit()

    def complete_exit(self):
        """Resume discovery after cleanup; retain any lack of exit evidence."""
        self.timer.stop()
        self.log("Learn-mode exit attempted", confirmed=self.exit_confirmed)
        if self.failure:
            message = self.failure
            if not self.exit_confirmed:
                message += " Learn-mode exit cannot be confirmed by this node."
            self.finish(False, message)
            return
        self.active = False
        self.refreshing = True
        self.stage = "refreshing events"
        self.service._restart_event_discovery(self.node_number)
        self.service._send_next_request()

    def exit_uncertain(self, reason):
        self.resolved = False
        return f"{self.failure or 'EV writes verified.'} {reason} Learn-mode exit is unconfirmed; check the node before reconnecting."

    def timed_out(self):
        if self.stage == "confirming learn-mode exit":
            self.finish(False, self.exit_uncertain("Timed out confirming exit."))
        else:
            description = {
                "WRACK": "write acknowledgement",
                "EVANS": "EV readback",
            }.get(self.stage, self.stage)
            self.fail(f"Timed out waiting for {description}.")

    def interrupt(self):
        """Stop further writes, but keep the connection open for bounded cleanup."""
        if self.refreshing and self.unlearn is not None:
            # Let the outstanding discovery finish, but never resume teaching.
            self.failure = "Save interrupted during event verification."
            self.log("EV refresh interrupted; pending teaching cancelled")
        elif self.active:
            self.fail(
                "Save interrupted; remaining changes were not confirmed."
                if self.unlearn is not None or self.verified < self.total
                else "EV writes verified; Save interrupted before refresh."
            )

    def disconnect(self):
        if self.active:
            self.failure = "Connection ended during EV Save."
            if self.learn_requested:
                # Unexpected disconnect may already have closed the transport.
                # Try once; there can be no confirmation on a closed connection.
                header = (0x580 | self.service.can_id) << 5
                self.log("Attempting learn exit after connection interruption")
                try:
                    self.service.connection.send(
                        f":S{header:04X}N54{self.node_number:04X};".encode()
                    )
                except OSError:
                    logger.exception(
                        "Learn-mode exit could not be sent after disconnect"
                    )
                self.failure = self.exit_uncertain("Connection unavailable.")
            self.finish(False, self.failure, resume=False)
        elif self.refreshing:
            self.finish_refresh(False)

    def finish_refresh(self, success):
        self.refreshing = False
        if self.unlearn is not None:
            state = self.service.node_states[self.node_number]
            absent = success and self.unlearn not in state.event_identities.values()
            self.log(
                "Event removal verification finished",
                identity=self.unlearn,
                discovery_complete=success,
                absent=absent,
            )
            if absent:
                self.removed = 1
            if self.failure or not absent:
                self.resolved = success and not self.failure
                self.identity_established = False
                self.finish(
                    False,
                    self.failure
                    or "Event removal could not be confirmed by rediscovery; no further EVs written.",
                    resume=False,
                )
                return
            self.unlearn = None
            self.identity_established = False
            if self.changes:
                # Keep write ownership across verification. Re-enter learn mode
                # only after absence is proven; ordinary teaching is unchanged.
                self.active = True
                self.exit_confirmed = False
                self.stage = "waiting for discovery reply"
                self.advance()
                return
        if self.failure:
            self.finish(False, self.failure, resume=False)
            return
        message = (
            "Changes saved successfully."
            if success
            else "Changes saved, but the displayed configuration may be incomplete (refresh failed)."
        )
        self.finish(success, message, resume=False)

    def finish(self, success, message, *, resume=True):
        self.timer.stop()
        self.active = False
        if not success:
            self.blocked = not (self.resolved and self.exit_confirmed)
            if self.verified:
                message = f"{self.verified} of {self.total} changes verified. {message}"
            if self.blocked:
                message += " Protocol safety unresolved; no further Save is allowed. Refresh Node, when safe, rereads hardware state; it does not retry failed writes or clear this safety block."
        self.log(
            "EV Save finished", success=success, verified=self.verified, result=message
        )
        self.finished.emit(self.node_number, success, message)
        if resume:
            self.service._send_next_request()

    def log(self, message, **fields):
        trace(
            logger,
            message,
            extra={
                "fields": {
                    "layout": self.service.connection.layout_name,
                    "node_number": self.node_number,
                    "stage": self.stage,
                    **fields,
                }
            },
        )
