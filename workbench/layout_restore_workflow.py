"""Sequential layout restore using the existing service and single-node engine."""

import logging

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .layout_backup_compare import LayoutBackupCompare
from .logging_config import trace

logger = logging.getLogger("workbench.ui")


class LayoutRestoreWorkflow:
    def __init__(
        self,
        parent,
        service,
        snapshots,
        *,
        annotations=None,
        layout_annotations=None,
        restore_configuration=True,
        configuration_nodes=None,
    ):
        self.parent = parent
        self.annotations = annotations
        self.layout_annotations = layout_annotations
        self.service = service
        self.restore_configuration = restore_configuration
        # These original desired dictionaries are never replaced with readback data.
        self.annotation_snapshots = dict(sorted(snapshots.items()))
        # Only positively eligible, selected nodes enter hardware comparison and
        # Retry. Annotation-only targets must never become hardware work later.
        self.snapshots = {
            number: snapshot
            for number, snapshot in self.annotation_snapshots.items()
            if restore_configuration
            and (configuration_nodes is None or number in configuration_nodes)
        }
        self.identities = (
            {number: self.identity(number) for number in self.snapshots}
            if restore_configuration
            else {}
        )
        self.results = dict.fromkeys(self.snapshots, "Not attempted")
        self.actual = {}
        self.offline = set()

    def identity(self, number):
        state = self.service.node_states.get(number)
        return (state.identity, state.can_id) if state is not None else None

    def wait_for(self, signal, start, matches):
        """Keep Qt responsive until this operation replies or the connection ends.

        The caller disables its window to prevent another user operation.
        Signals are detached before returning; no callback owns the next node.
        """
        loop = QEventLoop()
        received = None

        def completed(*args):
            nonlocal received
            if matches(*args):
                received = args
                loop.quit()

        def disconnected(state):
            if state != "Connected":
                loop.quit()

        signal.connect(completed)
        self.service.connection.state_changed.connect(disconnected)
        try:
            if self.service._closed or self.service.connection.state != "Connected":
                raise ValueError("Connection ended; operation not attempted")
            start()
            if received is None:
                loop.exec()
            if received is None:
                raise ValueError("Connection ended; resulting configuration is unknown")
            return received
        finally:
            signal.disconnect(completed)
            self.service.connection.state_changed.disconnect(disconnected)

    def read_target(self, number):
        service = self.service
        # Selection can close while its final lightweight read is still draining.
        if service.discovery_pending():
            self.wait_for(
                service.presence_checked,
                lambda: None,
                lambda *_: not service.discovery_pending(),
            )
        if self.identity(number) != self.identities[number]:
            raise ValueError("Target identity changed since selection")
        _, online, module_type = self.wait_for(
            service.presence_checked,
            lambda: service.check_presence([number]),
            lambda node, *_: node == number,
        )
        if not online:
            self.offline.add(number)
            raise ValueError("Offline; current configuration could not be read")
        self.offline.discard(number)
        if (
            self.identities[number] is None
            or module_type != self.identities[number][0].module_type
        ):
            raise ValueError("Target module type changed since selection")
        self.wait_for(
            service.node_refresh_finished,
            lambda: service.rediscover_node(number),
            lambda node: node == number,
        )
        if self.identity(number) != self.identities[number]:
            raise ValueError("Target identity changed during discovery")
        # rediscover_node clears old configuration first. Partial reads therefore
        # contain only fresh evidence; the comparison engine marks unread data unknown.
        return service.node_states[number]

    def comparison(self):
        states = list(self.actual.values())
        if self.service._closed or self.service.connection.state != "Connected":
            states = []
            self.offline.update(self.snapshots)
        return LayoutBackupCompare(
            {},
            states,
            {},
            None,
            self.parent,
            snapshots=self.snapshots,
            offline=self.offline,
            headings=("Desired", "Actual"),
            message=self.safety_warning(),
            retry_available=self.retry_available,
            retry_signals=(
                self.service.node_state_updated,
                self.service.discovery_status_changed,
                self.service.restore.changed,
            ),
            connection=self.service.connection,
        )

    def safety_warning(self):
        warning = ""
        if self.service.ev_write.blocked or self.service.nv_write.unverified:
            warning = "Protocol safety unresolved; resolve transaction and learn-mode uncertainty before further writes. Once safe, use Layouts → Refresh to reread hardware state; refreshing does not retry failed writes or clear this safety block."
        if any(
            s.identity.flags & 0x20 or s.parameters.get(8, 0) & 0x20
            for s in self.service.node_states.values()
        ):
            warning += " A node reports learn mode; leave learn mode and rediscover."
        return warning.strip()

    def retry_available(self):
        service = self.service
        return (
            not service._closed
            and service.connection.state == "Connected"
            and not self.safety_warning()
            and not service.writes_busy()
            and not service.discovery_pending()
        )

    def confirm(self):
        message = (
            "Restore the selected nodes to the desired configuration?\n\n"
            "Events absent from the backup may be removed; dependent configuration may reset. "
            "There is no rollback. Do not use another configuration tool during restoration. "
            "Backups do not identify manufacturer or firmware: confirm they belong to these modules."
        )
        if not self.restore_configuration or not self.snapshots:
            message = "Restore layout event names and annotations for the selected nodes from this backup?"
        if self.restore_configuration and any(
            not snapshot["complete"] for snapshot in self.snapshots.values()
        ):
            message += (
                "\n\nIncomplete backups are included. Replacement may remove uncaptured "
                "configuration. Unknown values will not be written as zero; full equivalence "
                "cannot be verified. Continue with destructive partial restoration?"
            )
        return (
            QMessageBox.question(
                self.parent,
                "Confirm layout restore",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def restore_node(self, number, desired):
        try:
            self.read_target(number)
            # NodeRestore.check remains authoritative after fresh discovery,
            # including when an earlier node left a connection safety blocker.
            _, success, reason = self.wait_for(
                self.service.restore.finished,
                lambda: self.service.restore.begin(
                    number, desired, allow_incomplete=not desired["complete"]
                ),
                lambda node, *_: node == number,
            )
            self.results[number] = (
                "Verified at restore completion: " if success else "Failed: "
            ) + reason
        except ValueError as error:
            self.results[number] = f"Not restored: {error}"
            logger.exception(
                "Layout node restore could not proceed",
                extra={
                    "fields": {
                        "layout": self.service.connection.layout_name,
                        "node_number": number,
                    }
                },
            )
        self.log(
            "Layout node restore result",
            node_number=number,
            result=self.results[number],
        )

    def log(self, message, **fields):
        trace(
            logger,
            message,
            extra={"fields": {"layout": self.parent.logical_layout, **fields}},
        )

    def run(self):
        if self.annotations is None and (
            not self.restore_configuration or not self.snapshots
        ):
            return
        if not self.confirm():
            return
        self.log(
            "Layout restore confirmed",
            selected_nodes=list(self.annotation_snapshots),
            configuration_nodes=list(self.snapshots),
            configuration=self.restore_configuration,
            annotations=self.annotations is not None,
        )
        if self.annotations is not None:
            # Apply local names once. NV/EV reconciliation and Retry stay unchanged.
            try:
                if self.layout_annotations is not None:
                    self.annotations.save(self.layout_annotations)
                for number, snapshot in self.annotation_snapshots.items():
                    if "annotations" in snapshot:
                        self.annotations.save(snapshot["annotations"], number)
            except (OSError, ValueError, TypeError) as error:
                logger.exception("Layout annotation restoration failed")
                QMessageBox.warning(
                    self.parent,
                    "Annotations not fully restored",
                    f"Some local annotations could not be saved: {error}\n\nHardware configuration restoration is separate.",
                )
        # Local names are applied once, outside hardware comparison and Retry.
        if not self.restore_configuration or not self.snapshots:
            return
        self.restore_selected()
        while True:
            report = self.comparison()
            requested = report.exec()
            report.deleteLater()
            if requested != QDialog.DialogCode.Accepted:
                return
            if self.retry_available():
                self.log(
                    "Layout restore Retry requested",
                    selected_nodes=list(self.snapshots),
                )
                self.restore_selected()
            else:
                self.log("Layout restore Retry blocked; showing updated report")

    def restore_selected(self):
        """One shared pass for the initial restore and every user-requested Retry."""
        self.actual.clear()
        window = self.parent.window()
        was_enabled = window.isEnabled()
        window.setEnabled(False)
        # Qt shows no widget cursor over a disabled window, so the layout's own
        # discovery cursor is invisible here. No dialog opens before `finally`.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        details = self.parent.node_view.details
        details.layout_restoring = True
        try:
            for number, desired in self.snapshots.items():
                self.restore_node(number, desired)

            for number in self.snapshots:
                try:
                    self.actual[number] = self.read_target(number)
                except ValueError as error:
                    self.results[number] += f" Final read unavailable: {error}"
                self.log(
                    "Layout restore final read completed",
                    node_number=number,
                    available=number in self.actual,
                    result=self.results[number],
                )
        finally:
            details.layout_restoring = False
            details.update_backup_buttons()
            QApplication.restoreOverrideCursor()
            window.setEnabled(was_enabled)
