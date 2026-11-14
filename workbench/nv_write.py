"""One node's edited NVs, written sequentially and confirmed by readback.

MERG Developer's Guide 6b, teaching/readback of NVs:
https://www.merg.org.uk/merg_wiki/lib/exe/fetch.php?media=public%3Acbuspublic%3Adeveloper_6b.pdf
"""

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from . import response_timeout
from .logging_config import trace

logger = logging.getLogger("workbench.cbus")


class NvWrite(QObject):
    # Transaction and rediscovery completion advance the configuration coordinator.
    write_finished = Signal(int, bool, str)
    discovery_finished = Signal(int, str)

    def __init__(self, service):
        super().__init__(service)
        self.service = service
        self.active = False
        self.refreshing = False
        self.refresh_events = True
        self.stage = ""
        self.node_number = 0
        self.changes = []
        self.verified = 0
        self.recovered = 0
        self.resolved = False
        # Late readbacks after failure must not silently confirm a failed write.
        self.unverified: set[tuple[int, int]] = set()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timed_out)

    def begin(
        self,
        node_number: int,
        changes: dict[int, int],
        *,
        refresh_from: int = 1,
        refresh_events: bool = True,
        refresh_indices: list[int] | None = None,
    ) -> None:
        self.refresh_indices = refresh_indices
        self.refresh_from = refresh_from
        self.refresh_events = refresh_events
        self.node_number = node_number
        self.changes = sorted(changes.items())
        self.verified = 0
        self.recovered = 0
        self.resolved = False
        self.total = len(self.changes)
        self.active = True
        self.stage = "waiting for discovery reply"
        self.log("NV Save accepted", changes=self.changes)
        # The service finishes its current request before yielding the wire.
        self.service._send_next_request()

    def advance(self) -> None:
        if self.stage != "waiting for discovery reply":
            return
        if not self.changes:
            self.finish(True, "No changed NVs.")
            return
        index, value = self.changes[0]
        self.unverified.add((self.node_number, index))
        self.stage = "WRACK"
        self.timer.start(response_timeout.RESPONSE_TIMEOUT_MS)
        header = (0x580 | self.service.can_id) << 5
        frame = (
            f":S{header:04X}N96{self.node_number:04X}{index:02X}{value:02X};".encode()
        )
        self.log("Sending NVSET", nv_index=index, value=value)
        try:
            self.service.connection.send(frame)
        except OSError:
            logger.exception("NVSET send failed")
            self.finish(False, f"NV {index}: could not transmit write.")

    def acknowledge(self, node_number: int) -> None:
        if not self.active or node_number != self.node_number or self.stage != "WRACK":
            return
        index, _value = self.changes[0]
        self.log("WRACK received; verifying NV", nv_index=index)
        self.stage = "NVANS"
        self.timer.start(response_timeout.RESPONSE_TIMEOUT_MS)
        try:
            self.service.request_nv(node_number, index)
        except OSError:
            logger.exception("NV readback send failed")
            self.finish(False, f"NV {index}: could not request verification.")

    def receive_value(self, node_number: int, index: int, value: int) -> bool:
        """Consume unverified write replies before normal discovery records them."""
        # Failure rediscovery may confirm physical state without resolving an
        # ambiguous transaction; rereading cannot clear its uncertainty marker.
        if (
            not self.active
            and (
                self.service.refreshing_node == node_number
                or self.service.refreshing_layout
            )
            and self.service._outstanding_request == ("nv", node_number, index)
        ):
            return False
        if (node_number, index) not in self.unverified:
            return False
        if (
            self.active
            and node_number == self.node_number
            and self.stage in ("NVANS", "recovery NVANS")
            and index == self.changes[0][0]
        ):
            expected = self.changes[0][1]
            self.log(
                "NV readback received", nv_index=index, value=value, expected=expected
            )
            if value != expected:
                # Recovery sent a second NVRD: its response may still arrive.
                self.resolved = self.stage != "recovery NVANS"
                if self.resolved:
                    self.unverified.remove((node_number, index))
                self.service.record_nv(node_number, index, value)
                self.finish(
                    False, f"NV {index}: readback was {value}, expected {expected}."
                )
            else:
                self.timer.stop()
                if self.stage == "recovery NVANS":
                    self.recovered += 1
                    self.log("NV verification recovered", nv_index=index)
                self.unverified.remove((node_number, index))
                self.service.record_nv(node_number, index, value)
                self.verified += 1
                self.changes.pop(0)
                if self.changes:
                    self.stage = "waiting for discovery reply"
                    self.advance()
                else:
                    self.refreshing = True
                    self.service._start_nv_discovery(
                        self.node_number,
                        self.service.node_states[self.node_number].parameters[6],
                        first=self.refresh_from,
                        indices=self.refresh_indices,
                    )
                    self.finish(True, "Saving changes…")
        else:
            self.log("Ignoring unverified NV reply", nv_index=index, value=value)
        return True

    def reject(self, node_number: int, code: int) -> bool:
        if (
            not self.active
            or node_number != self.node_number
            or self.stage not in ("WRACK", "NVANS", "recovery NVANS")
        ):
            return False
        index = self.changes[0][0]
        # A recovery read can leave a second unindexed CMDERR outstanding.
        self.resolved = self.stage != "recovery NVANS"
        if self.resolved:
            self.unverified.remove((node_number, index))
        self.finish(
            False, f"NV {index}: node rejected {self.stage} with CMDERR {code}."
        )
        return True

    def timed_out(self) -> None:
        index = self.changes[0][0]
        if self.stage == "NVANS":
            # WRACK confirmed acceptance. Retry only the read, retaining wire
            # ownership and the uncertainty marker until a matching value arrives.
            self.stage = "recovery NVANS"
            self.log(
                "NV verification timed out; requesting one recovery read",
                nv_index=index,
            )
            self.timer.start(response_timeout.RESPONSE_TIMEOUT_MS)
            try:
                self.service.request_nv(self.node_number, index)
            except OSError:
                logger.exception("NV recovery read send failed")
                self.finish(
                    False, f"NV {index}: could not request recovery verification."
                )
            return
        self.finish(False, f"NV {index}: timed out waiting for {self.stage}.")

    def disconnect(self) -> None:
        if self.refreshing:
            self.finish_refresh(False, "Connection ended.")
        if self.active:
            self.finish(False, "Connection ended during NV Save.", resume=False)

    def finish_refresh(self, success: bool, reason: str = "") -> None:
        self.refreshing = False
        message = (
            "Changes saved successfully."
            if success
            else "Changes saved, but some values could not be refreshed."
        )
        self.log("Post-Save discovery finished", success=success, reason=reason)
        self.discovery_finished.emit(self.node_number, message)

    def finish(self, success: bool, message: str, *, resume: bool = True) -> None:
        self.timer.stop()
        self.active = False
        self.log(
            "NV Save writes finished",
            success=success,
            result=message,
            verified=self.verified,
            total=self.total,
        )
        if not success:
            if self.verified:
                message = f"{self.verified} of {self.total} changes saved. {message}"
            else:
                index = self.changes[0][0]
                reason = message.removeprefix(f"NV {index}: ")
                message = f"NV {index} could not be saved. {reason}"
        self.write_finished.emit(self.node_number, success, message)
        if resume:
            self.service._send_next_request()

    def log(self, message: str, **fields) -> None:
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
