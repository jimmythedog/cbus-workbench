"""Save/Restore reporting and caller-owned, bounded retry through NodeRestore."""

import logging
from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer

from .backup_compare import BackupCompare
from .configuration_compare import ComparisonValue, NodeComparison, ValueState
from .logging_config import trace
from .node_backup_diff import compare_live_configuration


class NodeFailureReport(QObject):
    def __init__(self, parent, service, message):
        super().__init__(parent)
        self.service = service
        self.saving = parent.saving_configuration
        self.number = service.restore.node_number
        self.operation_backup = service.restore.backup
        self.requested = deepcopy(self.operation_backup)
        self.succeeded = False
        self.identity = service.restore.identity
        self.original_reason = message
        self.last_message = message
        self.running = False
        self.refreshing = False
        self.dialog = BackupCompare(
            service.node_states[self.number],
            self.requested,
            parent,
            headings=("Requested", "Actual"),
            comparison=self.comparison(),
            message=self.description(message),
            retry_action=self.retry,
        )
        self.dialog.setWindowTitle(f"Node {self.number} — Requested configuration")
        # Only defer the write handoff; closing the report cancels this timer.
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.begin_retry)
        self.connections = (
            (service.node_refresh_finished, self.refreshed),
            (service.node_state_updated, self.update_retry),
            (service.discovery_status_changed, self.update_retry),
            (service.restore.changed, self.update_retry),
            (service.connection.state_changed, self.update_retry),
        )
        for signal, slot in self.connections:
            signal.connect(slot)
        self.dialog.finished.connect(self.dispose)
        self.update_retry()
        self.dialog.show()

    def description(self, message):
        outcome = "" if message == self.original_reason else f"\n\n{message}"
        return (
            f"Original failure: {self.original_reason}{outcome}\n"
            "Independent changes were attempted while safe; blocked or dependent work may remain. "
            "A write may have succeeded even if verification failed. No rollback was performed."
        )

    def comparison(self):
        service = self.service
        state = service.node_states[self.number]
        result = compare_live_configuration(state, self.requested)
        if service._closed or service.connection.state != "Connected":
            # Retain last-confirmed evidence, but never hide it as a current match.
            rows = [
                replace(row, right=ComparisonValue(ValueState.UNKNOWN, row.right.value))
                for row in result.rows
                if row.section != "Node details"
            ]
            return NodeComparison(rows, True)
        return result

    def unavailable(self):
        service = self.service
        if self.succeeded:
            return "Requested configuration verified; no Retry needed."
        if service.restore.backup is not self.operation_backup:
            return "Another configuration operation has replaced this request."
        state = service.node_states.get(self.number)
        if state is None or self.identity != (
            state.identity.manufacturer,
            state.identity.module_type,
            state.can_id,
        ):
            return "Target identity changed; inspect the node before retrying."
        # Reuse the learn flag already interpreted by EvWrite. A known learner
        # anywhere on this connection makes broadcast teaching unsafe.
        if any(
            node.identity.flags & 0x20 or node.parameters.get(8, 0) & 0x20
            for node in service.node_states.values()
        ):
            return "A node reports learn mode; leave learn mode and rediscover before Retry."
        try:
            service.restore.check(self.number, self.requested)
        except ValueError as error:
            return str(error)
        return ""

    def dispose(self):
        """Detach observers and cancel a Retry that has not reached the writer."""
        self.timer.stop()
        self.running = self.refreshing = False
        for signal, slot in self.connections:
            signal.disconnect(slot)
        if self.parent().failure_report is self:
            self.parent().failure_report = None
        self.dialog.deleteLater()
        self.deleteLater()

    def update_retry(self, *_args):
        connected = (
            not self.service._closed and self.service.connection.state == "Connected"
        )
        if not connected:
            self.dialog.show_result(
                self.comparison(), self.description(self.last_message)
            )
        reason = "Retry in progress." if self.running else self.unavailable()
        self.dialog.retry_button.setEnabled(not reason)
        self.dialog.retry_button.setToolTip(reason)
        self.dialog.retry_status.setText(reason)
        self.dialog.retry_status.setVisible(bool(reason))
        if self.running and not connected and not self.service.restore.active:
            self.completed(
                False, "Connection ended during Retry; reconnect and compare."
            )

    def retry(self):
        reason = self.unavailable()
        if self.running or reason:
            self.dialog.message.setText(
                self.description(reason or "Retry in progress.")
            )
            self.update_retry()
            return
        trace(
            logging.getLogger("workbench.ui"),
            "Retry refreshing target",
            extra={"fields": {"node_number": self.number}},
        )
        self.running = self.refreshing = True
        self.update_retry()
        self.dialog.message.setText(
            self.description("Refreshing hardware before Retry…")
        )
        try:
            self.service.rediscover_node(self.number)
        except ValueError as error:
            self.completed(False, str(error))

    def refreshed(self, number):
        if self.refreshing and number == self.number:
            self.refreshing = False
            # Let discovery release the wire before asking the shared writer to own it.
            self.timer.start(0)

    def begin_retry(self):
        if not self.running:
            return
        reason = self.unavailable()
        if reason:
            self.completed(False, reason)
            return
        try:
            self.service.restore.begin(
                self.number,
                self.requested,
                allow_incomplete=not self.requested["complete"],
            )
            self.operation_backup = self.service.restore.backup
        except ValueError as error:
            self.completed(False, str(error))

    def completed(self, success, message):
        self.timer.stop()
        self.last_message = message
        self.succeeded = success
        self.running = self.refreshing = False
        trace(
            logging.getLogger("workbench.ui"),
            "Retry finished",
            extra={
                "fields": {
                    "node_number": self.number,
                    "success": success,
                    "reason": message,
                }
            },
        )
        self.dialog.show_result(self.comparison(), self.description(message))
        self.update_retry()
