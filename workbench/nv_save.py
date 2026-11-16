"""Apply NV edits, refresh MDF-linked NVs, then rediscover stored events."""

import logging
from copy import deepcopy

from PySide6.QtCore import QObject, QTimer, Signal

from .cbus_service import DiscoveryProgress
from .logging_config import trace
from .node_backup_files import node_backup, validate_backup

logger = logging.getLogger("workbench.cbus")


class NvSave(QObject):
    changed = Signal(int, str)
    finished = Signal(int, bool, str)

    def __init__(self, service):
        super().__init__(service)
        self.service = service
        self.active = False
        self.node_number = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        service.nv_write.write_finished.connect(self.written)
        service.nv_write.discovery_finished.connect(self.refreshed)

    def check(self, number: int, backup: dict) -> None:
        """Keep the existing connection, discovery and protocol safety gates."""
        validate_backup(backup)
        service = self.service
        state = service.node_states.get(number)
        if (
            service._closed
            or service.connection.state != "Connected"
            or state is None
            or not number
            or not state.identity.is_flim
            or state.can_id is None
            or service.nodes.get(number) != state.identity
            or backup["node"] != number
        ):
            raise ValueError(
                "NV Save requires a matching discovered FLiM node and CAN ID on an active connection."
            )
        if service.writes_busy() or service.discovery_pending():
            raise ValueError(
                "Wait for discovery or the current Save/restore to finish."
            )
        if service.ev_write.blocked or service.nv_write.unverified:
            raise ValueError(
                "Protocol safety unresolved; no further Save is allowed. Refresh Node does not retry failed writes or clear this safety block."
            )
        if not node_backup(state)["complete"]:
            raise ValueError("Complete target discovery is required before saving.")
        if len(backup["nvs"]) != state.parameters.get(6) or any(
            type(value) is not int or not 0 <= value <= 255 for value in backup["nvs"]
        ):
            raise ValueError("NV Save requires one byte value for every discovered NV.")

    def begin(
        self,
        number: int,
        backup: dict,
        *,
        pre_edit: list[int] | None = None,
        user_edited: set[int] | None = None,
        mdf: dict | None = None,
        refresh_events: bool = True,
    ) -> None:
        self.check(number, backup)
        state = self.service.node_states[number]
        self.mdf = deepcopy(mdf or {})
        self.refresh_events = refresh_events
        self.failure_reason = ""
        self.event_refresh = False
        self.events_refreshed = False
        self.backup = deepcopy(backup)
        self.edited = list(backup["nvs"])
        self.pre_edit = (
            list(pre_edit) if pre_edit is not None else list(node_backup(state)["nvs"])
        )
        self.user_edited = (
            {
                index
                for index, value in enumerate(self.edited)
                if value != self.pre_edit[index]
            }
            if user_edited is None
            else set(user_edited)
        )
        # Retry compares against fresh hardware, but retains the original edit
        # intentions. Untouched values follow hardware, including its refresh.
        for index in range(len(self.edited)):
            if index not in self.user_edited:
                self.edited[index] = self.pre_edit[index]
                self.backup["nvs"][index] = self.pre_edit[index]
        self.identity = (
            state.identity.manufacturer,
            state.identity.module_type,
            state.can_id,
        )
        self.node_number = number
        self.next_index = 0
        self.verified = self.recovered = 0
        self.active = True
        self.log(
            "NV editing Save accepted",
            user_edited=sorted(i + 1 for i in self.user_edited),
        )
        self.timer.start(0)

    def advance(self) -> None:
        if not self.active:
            return
        state = self.service.node_states[self.node_number]
        try:
            if self.identity != (
                state.identity.manufacturer,
                state.identity.module_type,
                state.can_id,
            ):
                raise ValueError("Target identity changed during NV Save.")
            while self.next_index < len(self.edited):
                index = self.next_index
                self.next_index += 1
                if self.edited[index] == self.pre_edit[index]:
                    continue
                self.linked_indices = linked_nvs(self.mdf, index + 1, len(self.edited))
                self.changed.emit(self.node_number, f"Saving NV {index + 1}…")
                self.service.write_nvs(
                    self.node_number, {index + 1: self.edited[index]}, owner=self
                )
                return
            self.finish(True, "NV changes saved successfully.")
        except ValueError as error:
            self.finish(False, str(error))

    def written(self, number: int, success: bool, message: str) -> None:
        if not self.active or number != self.node_number:
            return
        self.verified += self.service.nv_write.verified
        self.recovered += self.service.nv_write.recovered
        if not success:
            self.finish(False, message)
            return
        self.pre_edit[self.next_index - 1] = self.edited[self.next_index - 1]
        self.changed.emit(number, "Reading MDF-linked NVs…")

    def refreshed(self, number: int, message: str) -> None:
        if not self.active or number != self.node_number:
            return
        state = self.service.node_states[number]
        if self.event_refresh:
            self.event_refresh = False
            complete = (DiscoveryProgress.COMPLETE, DiscoveryProgress.SKIPPED)
            success, result = self.pending_result
            if (
                state.event_progress not in complete
                or state.ev_progress not in complete
            ):
                success = False
                result += " Stored event/EV refresh incomplete."
            self.finish(success, result)
            return
        # Explicit edits retain their desired value while live state follows hardware.
        for nv_index in self.linked_indices:
            index = nv_index - 1
            actual = state.nv_values.get(index + 1)
            if actual is None:
                continue
            if actual != self.pre_edit[index]:
                self.log(
                    "Linked NV refreshed",
                    nv_index=index + 1,
                    actual=actual,
                    user_edited=index in self.user_edited,
                )
                self.pre_edit[index] = actual
                if index not in self.user_edited:
                    self.edited[index] = actual
                    self.backup["nvs"][index] = actual
        if state.nv_progress != DiscoveryProgress.COMPLETE:
            self.finish(
                False, "Linked NV reads incomplete; remaining edits were not written."
            )
            return
        self.timer.start(0)

    def disconnect(self) -> None:
        if self.active:
            self.finish(False, "Connection ended during NV Save.")

    def finish(self, success: bool, message: str) -> None:
        self.timer.stop()
        service = self.service
        if not success:
            self.failure_reason = message
        # A resolved rejection/mismatch leaves the wire safe for read-only event
        # discovery. An ambiguous write keeps its existing protocol safety block.
        safe = (
            not service._closed
            and service.connection.state == "Connected"
            and not service.nv_write.unverified
            and not service.ev_write.blocked
            and not any(
                state.identity.flags & 0x20 or state.parameters.get(8, 0) & 0x20
                for state in service.node_states.values()
            )
        )
        if self.verified and self.refresh_events and not self.events_refreshed:
            self.events_refreshed = True
            if safe:
                self.pending_result = success, message
                self.event_refresh = True
                service.nv_write.refreshing = True
                service.nv_write.refresh_events = True
                self.changed.emit(self.node_number, "Refreshing stored events and EVs…")
                self.log(
                    "Refreshing stored events after verified NV writes", success=success
                )
                service._restart_event_discovery(self.node_number)
                service._send_next_request()
                return
            message += " Stored events were not refreshed because discovery is unsafe or the connection ended."
        self.active = False
        if not success:
            message = f"Partial Save: {self.verified} NV writes verified. {message} No rollback was performed. Use Refresh Node when safe to reread hardware; refreshing does not retry failed writes or clear protocol safety blocks."
        if self.recovered:
            message += (
                f" Verification required recovery for {self.recovered} NV write(s)."
            )
        self.log("NV editing Save finished", success=success, result=message)
        self.finished.emit(self.node_number, success, message)
        self.service._status_update.start(0)

    def log(self, message: str, **fields) -> None:
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


def linked_nvs(mdf: dict, written: int, count: int) -> list[int]:
    """Find links in the existing nested MDF presentation; never infer dependencies."""
    result = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("nodeVariableIndex") == written:
                for index in value.get("linkedVariables", {}).get("NV", []):
                    if type(index) is not int or not 1 <= index <= count:
                        raise ValueError(f"Invalid MDF-linked NV index: {index}")
                    if index != written and index not in result:
                        result.append(index)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(mdf.get("nodeVariables", []))
    return result
