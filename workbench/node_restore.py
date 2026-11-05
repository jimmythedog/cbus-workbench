"""Apply node configurations through the verified NV and EV writers."""

import logging
from copy import deepcopy

from PySide6.QtCore import QObject, QTimer, Signal

from .logging_config import trace
from .node_backup_diff import compare_live_node
from .node_backup_files import node_backup, validate_backup
from .node_restore_events import (
    event_step_matches,
    extra_event_steps,
    known_backup_verified,
    plan_event_restore,
)

logger = logging.getLogger("workbench.cbus")


class NodeRestore(QObject):
    changed = Signal(int, str)
    finished = Signal(int, bool, str)

    def __init__(self, service):
        super().__init__(service)
        self.service = service
        self.active = False
        self.node_number = 0
        self.stage = ""
        self.failure = ""
        self.nvs_verified = 0
        self.evs_verified = 0
        # Advance outside writer completion callbacks: their queue cleanup must
        # finish before another write or a new discovery pass can begin.
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        service.nv_write.write_finished.connect(self.nv_finished)
        service.nv_write.discovery_finished.connect(self.nv_refreshed)
        service.ev_write.finished.connect(self.ev_finished)
        service.node_refresh_finished.connect(self.refreshed)

    def check(self, node_number: int, backup: dict) -> None:
        """Reject unsafe inputs before confirmation and again before any writes."""
        validate_backup(backup)
        service = self.service
        state = service.node_states.get(node_number)
        if (
            service.connection.state != "Connected"
            or service._closed
            or state is None
            or not node_number
            or not state.identity.is_flim
            or state.can_id is None
            or service.nodes.get(node_number) != state.identity
            or backup["node"] != node_number
        ):
            raise ValueError(
                "Restore requires the matching discovered FLiM node and CAN ID on an active connection."
            )
        if service.writes_busy() or service.discovery_pending():
            raise ValueError(
                "Wait for discovery or the current Save/restore to finish."
            )
        if service.ev_write.blocked or service.nv_write.unverified:
            raise ValueError("Reconnect to rediscover before restoring.")
        if backup["complete"] and any(v is None for v in backup["nvs"]):
            raise ValueError("A complete backup cannot contain unknown NVs.")
        if not node_backup(state)["complete"]:
            raise ValueError("Complete target discovery is required before restoring.")
        if len(backup["nvs"]) > state.parameters.get(6) or (
            backup["complete"] and len(backup["nvs"]) != state.parameters.get(6)
        ):
            raise ValueError("Backup NV count does not match the discovered node.")
        if len(backup["nvs"]) > 255 or any(
            v is not None and not 0 <= v <= 255 for v in backup["nvs"]
        ):
            raise ValueError(
                "Backup NV indices and values must fit the hardware's byte range."
            )
        for event in backup["events"]:
            if (
                not state.identity.is_consumer
                or not 0 <= event["nodeNumber"] <= 65535
                or not 0 <= event["eventNumber"] <= 65535
                or len(event["eventVariables"]) > state.parameters.get(5, 0)
                or any(
                    v is not None and not 0 <= v <= 255 for v in event["eventVariables"]
                )
            ):
                raise ValueError(
                    "Backup event addresses or EV values exceed the target's confirmed capabilities."
                )

    def begin(
        self, node_number: int, backup: dict, *, allow_incomplete: bool = False
    ) -> None:
        self.check(node_number, backup)
        if not backup["complete"] and not allow_incomplete:
            raise ValueError(
                "Incomplete backup replacement may remove uncaptured configuration; explicit confirmation is required."
            )
        self.backup = deepcopy(backup)
        self.desired_nvs = self.backup["nvs"]
        self.pending_events = list(self.backup["events"])
        self.start(node_number)

    def start(self, node_number: int) -> None:
        state = self.service.node_states[node_number]
        self.identity = (
            state.identity.manufacturer,
            state.identity.module_type,
            state.can_id,
        )
        self.node_number = node_number
        self.active = True
        self.failure = ""
        self.nvs_verified = self.evs_verified = 0
        self.nvs_recovered = 0
        self.removals_transmitted = 0
        self.events_removed = 0
        self.event_steps = []
        self.next_nv = 1
        self.extras_planned = False
        self.schedule("writing NVs")

    def schedule(self, stage: str) -> None:
        self.stage = stage
        self.log("Configuration application stage changed")
        self.changed.emit(
            self.node_number, f"Restoring node {self.node_number}: {stage}…"
        )
        self.timer.start(0)

    def advance(self) -> None:
        if not self.active:
            return
        try:
            state = self.service.node_states[self.node_number]
            if self.stage != "rediscovering final configuration" and self.identity != (
                state.identity.manufacturer,
                state.identity.module_type,
                state.can_id,
            ):
                raise ValueError(
                    "Target identity changed during configuration application."
                )
            if self.stage == "writing NVs":
                self.restore_next_nv(state)
            elif self.stage == "verifying NVs":
                writer = self.service.nv_write
                writer.node_number = self.node_number
                writer.refreshing = True
                writer.refresh_events = True
                self.service._start_nv_discovery(self.node_number, state.parameters[6])
                # Zero NVs can still have event discovery queued by completion.
                self.service._send_next_request()
            elif self.stage == "checking NVs":
                if not self.nv_discovery_complete(state):
                    raise ValueError(
                        "Discovery after NV writes is incomplete; no further writes will be made."
                    )
                if any(
                    v is not None and state.nv_values.get(i) != v
                    for i, v in enumerate(self.desired_nvs, 1)
                ):
                    raise ValueError(
                        "NV verification after rediscovery differs from the desired configuration; no further writes will be made."
                    )
                self.schedule("restoring events")
            elif self.stage == "restoring events":
                self.restore_evs(state)
            elif self.stage == "rediscovering final configuration":
                self.service.rediscover_node(self.node_number)
        except ValueError as error:
            self.fail(str(error))

    def nv_discovery_complete(self, state) -> bool:
        return node_backup(state)["complete"]

    def restore_next_nv(self, state) -> None:
        """Visit each saved index once; earlier side effects fail final verification."""
        if not self.nv_discovery_complete(state):
            raise ValueError(
                "NV discovery is incomplete; no further writes will be made."
            )
        while self.next_nv <= len(self.desired_nvs):
            index = self.next_nv
            value = self.desired_nvs[index - 1]
            self.next_nv += 1
            if value is None:
                continue
            live = state.nv_values.get(index)
            self.log("Comparing desired NV", nv_index=index, desired=value, live=live)
            if live is None:
                raise ValueError(f"NV {index} has no confirmed live value.")
            if live != value:
                self.service.write_nvs(self.node_number, {index: value}, owner=self)
                return
        self.schedule("verifying NVs")

    def restore_evs(self, state) -> None:
        # Free event-table capacity before teaching missing backed-up events.
        # Each removal still uses the ordinary writer and verified rediscovery.
        if not self.extras_planned:
            self.extras_planned = True
            self.event_steps = extra_event_steps(state, self.backup)
        # Compare each backed-up event against the latest refresh before any of
        # its writes. A matching event needs no learn-mode transaction.
        while not self.event_steps and self.pending_events:
            event = self.pending_events.pop(0)
            self.event_steps = plan_event_restore(
                state, {**self.backup, "events": [event]}
            )
        if not self.event_steps:
            self.schedule("rediscovering final configuration")
            return
        step = self.event_steps[0]
        self.stage = "writing EVs"
        self.log(
            "Applying event replacement step",
            identity=step.identity,
            unlearn=step.unlearn,
            values=step.values,
        )
        self.changed.emit(
            self.node_number, f"Restoring event {step.identity[0]}:{step.identity[1]}…"
        )
        values = {(*step.identity, i): v for i, v in step.values.items()}
        self.service.write_evs(
            self.node_number,
            values,
            owner=self,
            unlearn=step.identity if step.unlearn else None,
        )

    def nv_finished(self, number: int, success: bool, message: str) -> None:
        if not self.active or number != self.node_number or self.stage != "writing NVs":
            return
        self.nvs_verified += self.service.nv_write.verified
        self.nvs_recovered += self.service.nv_write.recovered
        if not success:
            self.fail(message)

    def nv_refreshed(self, number: int, message: str) -> None:
        if self.active and number == self.node_number and self.stage == "writing NVs":
            self.schedule("writing NVs")
        elif (
            self.active and number == self.node_number and self.stage == "verifying NVs"
        ):
            self.schedule("checking NVs")

    def ev_finished(self, number: int, success: bool, message: str) -> None:
        if not self.active or number != self.node_number or self.stage != "writing EVs":
            return
        self.evs_verified += self.service.ev_write.verified
        self.removals_transmitted += self.service.ev_write.removals_transmitted
        self.events_removed += self.service.ev_write.removed
        if not success:
            self.fail(message)
            return
        step = self.event_steps[0]
        state = self.service.node_states[number]
        if not event_step_matches(state, step, self.backup["complete"]):
            self.fail(
                f"Event {step.identity[0]}:{step.identity[1]} did not match after rediscovery; no further events written."
            )
            return
        self.event_steps.pop(0)
        self.schedule("restoring events")

    def fail(self, reason: str) -> None:
        self.failure = reason
        self.log(
            "Configuration application stopped; refreshing resulting configuration",
            reason=reason,
        )
        if self.stage == "rediscovering final configuration":
            self.finish(False, reason)
        else:
            self.schedule("rediscovering final configuration")

    def refreshed(self, number: int) -> None:
        if not self.active or number != self.node_number:
            return
        state = self.service.node_states[number]
        differences, inconclusive = compare_live_node(state, self.backup)
        self.log(
            "Final restore comparison",
            differences=differences,
            inconclusive=inconclusive,
        )
        identity_matches = self.identity == (
            state.identity.manufacturer,
            state.identity.module_type,
            state.can_id,
        )
        success = (
            not self.failure
            and not differences
            and node_backup(state)["complete"]
            and known_backup_verified(state, self.backup)
            and (not inconclusive or not self.backup["complete"])
            and identity_matches
        )
        reason = self.failure or (
            "Configuration differs from the known backup data after restoration."
            if differences
            else "Final configuration could not be completely verified."
        )
        if success:
            reason = "Node configuration restored and fully verified."
            if not self.backup["complete"]:
                reason = (
                    "Known backup values and event membership restored and verified. "
                    "Backup is incomplete: unknown or uncaptured configuration cannot be verified; "
                    "full equivalence is not established."
                )
        self.finish(success, reason)

    def disconnect(self) -> None:
        if self.active:
            if self.stage == "writing NVs" and self.service.nv_write.active:
                self.nvs_verified += self.service.nv_write.verified
            elif self.stage == "writing EVs":
                self.evs_verified += self.service.ev_write.verified
                self.removals_transmitted += self.service.ev_write.removals_transmitted
                self.events_removed += self.service.ev_write.removed
            self.finish(
                False,
                "Connection ended; resulting configuration could not be fully verified. Check learn mode if EV teaching was interrupted.",
            )

    def finish(self, success: bool, message: str) -> None:
        self.timer.stop()
        self.active = False
        if not success:
            message = f"Partial restoration: {self.nvs_verified} NV writes and {self.evs_verified} EV writes verified; {self.removals_transmitted} event removals transmitted, {self.events_removed} event removals verified. {message} Reconnect and compare before retrying."
        if self.nvs_recovered:
            message += (
                f" Verification required recovery for {self.nvs_recovered} NV write(s)."
            )
        self.log("Restore finished", success=success, result=message)
        self.finished.emit(self.node_number, success, message)
        self.service.node_state_updated.emit(self.node_number)

    def log(self, message: str, **fields) -> None:
        trace(
            logger,
            message,
            extra={
                "fields": {
                    "layout": self.service.connection.layout_name,
                    "node_number": self.node_number,
                    "stage": self.stage,
                    "operation": "Configuration application",
                    **fields,
                }
            },
        )
