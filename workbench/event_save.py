"""Apply explicit EV edits through the existing event planner and writer.

Edits may include new event identities, which are taught like Restore's missing
events. Deleting one consumed event uses the same writer and rediscovery.
"""

import logging
from copy import deepcopy

from PySide6.QtCore import QObject, QTimer, Signal

from .cbus_service import DiscoveryProgress
from .logging_config import trace
from .node_backup_files import node_backup, validate_backup
from .node_restore_events import (
    EventRestoreStep,
    event_step_matches,
    plan_event_restore,
)

logger = logging.getLogger("workbench.cbus")


class EventSave(QObject):
    changed = Signal(int, str)
    finished = Signal(int, bool, str)
    # Delete Event results go to the Consumed Events view, not the Save editor
    # or Restore failure report, which are both connected to finished.
    delete_finished = Signal(int, bool, str)
    refreshed = Signal(int)

    def __init__(self, service):
        super().__init__(service)
        self.service = service
        self.active = False
        self.refreshing = False
        self.node_number = 0
        self.deleting = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        service.ev_write.finished.connect(self.written)

    def check(self, number, backup=None):
        if backup is not None:
            validate_backup(backup)
        service = self.service
        state = service.node_states.get(number)
        if (
            service._closed
            or service.connection.state != "Connected"
            or state is None
            or not number
            or not state.identity.is_flim
            or not state.identity.is_consumer
            or state.can_id is None
            or service.nodes.get(number) != state.identity
            or backup is not None
            and backup["node"] != number
        ):
            raise ValueError(
                "Events Save requires a matching connected FLiM consumer and CAN ID."
            )
        if service.writes_busy() or service.discovery_pending():
            raise ValueError(
                "Wait for discovery or the current Save/restore to finish."
            )
        if service.ev_write.blocked or service.nv_write.unverified:
            raise ValueError("Protocol safety unresolved; no further Save is allowed.")
        if any(
            n.identity.flags & 0x20 or n.parameters.get(8, 0) & 0x20
            for n in service.node_states.values()
        ):
            raise ValueError("A node reports learn mode; no Events Save is allowed.")
        # A resolved failed teach may leave one EV unknown. Retry refreshes it;
        # requiring complete EV data here would prevent that recovery.
        if (
            state.event_progress != DiscoveryProgress.COMPLETE
            or not state.parameters.get(5)
        ):
            raise ValueError(
                "Events Save requires confirmed event identities and EV capacity."
            )
        if backup is not None and any(
            len(e["eventVariables"]) > state.parameters[5] for e in backup["events"]
        ):
            raise ValueError("EV indices exceed the confirmed capacity.")

    def check_complete(self, number, backup=None):
        """Events Save checks plus complete discovery, as required for editing."""
        self.check(number, backup)
        state = self.service.node_states[number]
        if (
            state.ev_progress != DiscoveryProgress.COMPLETE
            or not node_backup(state)["complete"]
        ):
            raise ValueError("Complete discovery is required before Events Save.")

    def begin(self, number, backup, *, original=None, edits=None):
        self.check_complete(number, backup)
        state = self.service.node_states[number]
        before = original if original is not None else node_backup(state)
        edits = deepcopy(edits) if edits is not None else event_edits(before, backup)
        # A new identity is taught like a missing event in Restore. Some nodes
        # acknowledge a zero EVLRN without creating the event, so require a
        # nonzero EV; the writer teaches it first (Restore planning).
        live = set(state.event_identities.values())
        requested = {(e["nodeNumber"], e["eventNumber"]) for e in backup["events"]}
        for identity in sorted(requested - live):
            if not any(edits.get(key) for key in edits if key[:2] == identity):
                raise ValueError(
                    f"New event {label(identity)} needs at least one nonzero EV before Save."
                )
        self.edits = edits
        # Their other EVs keep the node's own defaults, so verify only the
        # configured EVs of new events after teaching.
        self.new_identities = requested - live
        self.backup = requested_events(state, backup, self.edits)
        self.identity = (
            state.identity.manufacturer,
            state.identity.module_type,
            state.can_id,
        )
        self.node_number = number
        self.pending = list(dict.fromkeys(key[:2] for key in self.edits))
        self.verified = 0
        self.step = None
        self.deleting = False
        self.active = True
        self.log("Events Save accepted", edits=self.edits)
        self.timer.start(0)

    def delete_event(self, number, identity):
        """Unlearn one consumed event; rediscovery must then show it absent.

        Uses the Events Save checks, writer ownership and learn-mode handling.
        The result is emitted through delete_finished, possibly before this
        method returns if the first transmission fails, so connect first.
        """
        self.check_complete(number)
        state = self.service.node_states[number]
        if identity not in state.event_identities.values():
            raise ValueError(f"Node {number} does not consume event {label(identity)}.")
        self.step = EventRestoreStep(identity, {}, True, None)
        self.deleting = True
        self.node_number = number
        self.identity = (
            state.identity.manufacturer,
            state.identity.module_type,
            state.can_id,
        )
        self.edits = {}
        self.pending = []
        self.verified = 0
        self.active = True
        self.log("Event delete accepted", identity=identity)
        try:
            self.service.write_evs(number, {}, owner=self, unlearn=identity)
        except ValueError:
            self.active = False
            self.deleting = False
            raise
        # Only once writing has started: a new request object tells any open
        # failure report that its Retry request is replaced, as a new Save would.
        self.backup = node_backup(state)

    def advance(self):
        if not self.active:
            return
        state = self.service.node_states[self.node_number]
        try:
            if self.identity != (
                state.identity.manufacturer,
                state.identity.module_type,
                state.can_id,
            ):
                raise ValueError("Target identity changed during Events Save.")
            while self.pending:
                identity = self.pending.pop(0)
                # Earlier reconstruction can refresh other events. Preserve their
                # fresh untouched values before planning this event.
                self.backup.update(requested_events(state, self.backup, self.edits))
                event = next(
                    e
                    for e in self.backup["events"]
                    if (e["nodeNumber"], e["eventNumber"]) == identity
                )
                steps = plan_event_restore(state, {**self.backup, "events": [event]})
                if not steps:
                    continue
                self.step = steps[0]
                self.log(
                    "Applying event edits",
                    identity=identity,
                    reconstruct=self.step.unlearn,
                    values=self.step.values,
                )
                self.changed.emit(
                    self.node_number, f"Saving event {identity[0]}:{identity[1]}…"
                )
                self.service.write_evs(
                    self.node_number,
                    {(*identity, i): v for i, v in self.step.values.items()},
                    owner=self,
                    unlearn=identity if self.step.unlearn else None,
                )
                return
            self.finish(True, "Event changes saved and verified.")
        except ValueError as error:
            self.finish(False, str(error))

    def written(self, number, success, message):
        if self.refreshing and number == self.node_number:
            self.refreshing = False
            self.refreshed.emit(number)
            return
        if not self.active or number != self.node_number or self.step is None:
            return
        self.verified += self.service.ev_write.verified
        state = self.service.node_states[number]
        if self.deleting and not success:
            # The writer's message may say "Changes saved" when only the
            # refresh failed; removal is unconfirmed either way.
            self.finish(False, f"Not confirmed by hardware. {message}")
        elif not success:
            self.finish(False, message)
        elif self.deleting:
            if event_step_matches(state, self.step, False):
                self.finish(True, "Verified by rediscovery.")
            else:
                self.finish(False, "Rediscovery still shows the event.")
        elif not event_step_matches(
            state, self.step, self.step.identity not in self.new_identities
        ):
            self.finish(False, "Event did not match after reconstruction.")
        else:
            self.step = None
            self.timer.start(0)

    def refresh_for_retry(self, number):
        """Read fresh event membership and EVs without touching NVs or parameters."""
        # The report owns polling permission, so use the same idle/safety check
        # as check(), rather than requiring UI polling permission here.
        self.check(number, self.backup)
        if self.service._discovery_window.isActive():
            raise ValueError("Wait for discovery to finish.")
        self.node_number = number
        self.refreshing = True
        self.log("Refreshing event state before Retry")
        self.service.ev_write.refresh_for_retry(number)

    def disconnect(self):
        if self.active:
            if self.step is not None:
                self.verified += self.service.ev_write.verified
            self.finish(
                False,
                "Connection ended during Events Save; check learn mode before reconnecting.",
            )

    def finish(self, success, message):
        self.timer.stop()
        self.active = False
        if self.deleting:
            self.deleting = False
            identity = label(self.step.identity)
            message = (
                f"Event {identity} deleted from node {self.node_number}. {message}"
                if success
                else f"Could not delete event {identity} on node {self.node_number}. {message}"
            )
            self.log("Event delete finished", success=success, result=message)
            # Refresh views first, so Consumed Events matches the reported result.
            self.service.node_state_updated.emit(self.node_number)
            self.delete_finished.emit(self.node_number, success, message)
            return
        if not success:
            message = f"Partial Save: {self.verified} EV writes verified. {message} No rollback was performed."
        self.log("Events Save finished", success=success, result=message)
        self.finished.emit(self.node_number, success, message)
        self.service.node_state_updated.emit(self.node_number)

    def log(self, message, **fields):
        trace(
            logger,
            message,
            extra={
                "fields": {
                    "layout": self.service.connection.layout_name,
                    "node_number": self.node_number,
                    **fields,
                }
            },
        )


def label(identity):
    return f"{identity[0]}:{identity[1]}"


def event_edits(original, desired):
    """Retain changed EV positions, including explicit absence and numeric zero."""
    previous = {
        (e["nodeNumber"], e["eventNumber"]): e["eventVariables"]
        for e in original["events"]
    }
    changes = {}
    for event in desired["events"]:
        identity = (event["nodeNumber"], event["eventNumber"])
        old = previous.get(identity, [])  # A new event starts with no EVs.
        new = event["eventVariables"]
        for i in range(max(len(old), len(new))):
            before = old[i] if i < len(old) else None
            after = new[i] if i < len(new) else None
            if before != after:
                changes[(*identity, i + 1)] = after
    return changes


def requested_events(state, requested, edits):
    """Overlay only explicit changes on fresh hardware; retain reconstruction data."""
    result = node_backup(state)
    live = {(e["nodeNumber"], e["eventNumber"]): e for e in result["events"]}
    saved = {(e["nodeNumber"], e["eventNumber"]): e for e in requested["events"]}
    for (nn, en, index), value in edits.items():
        identity = (nn, en)
        if identity not in live:
            live[identity] = deepcopy(saved[identity])
            result["events"].append(live[identity])
        values = live[identity]["eventVariables"]
        values.extend([None] * (index - len(values)))
        values[index - 1] = value
        while values and values[-1] is None:
            values.pop()
    return result
