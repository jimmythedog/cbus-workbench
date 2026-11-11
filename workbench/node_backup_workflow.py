"""Actions for the selected node backup, using NodeDetails as the dialog parent."""

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from .annotations import load_annotations, save_annotations
from .backup_compare import BackupCompare
from .backup_view import BackupView, backup_contents
from .cbus_service import NodeState
from .logging_config import trace
from .node_backup_files import load_node_backup, node_backup, save_backup
from .node_backups import NodeBackups
from .node_snapshot import create_node_snapshot, restore_node_snapshot
from .pnn import Pnn

logger = logging.getLogger("workbench.ui")


class NodeBackupWorkflow:
    def __init__(
        self,
        parent: QWidget,
        backups: NodeBackups,
        refresh_displays: Callable[[], None],
    ) -> None:
        self.parent = parent
        self.backups = backups
        self.refresh_displays = refresh_displays

    def _selected_backup(self, node):
        if node is None:
            return None
        selected = self.backups.selectedItems()
        backup = selected[0].data(0, Qt.ItemDataRole.UserRole) if selected else None
        if isinstance(backup, Path):
            backup = load_node_backup(backup)
        return backup

    @staticmethod
    def _is_layout_backup(backup):
        return (
            backup.get("partOfLayoutBackup") is True
            or backup.get("description") == "Layout backup"
        )

    def _show_status(self, message):
        window = self.parent.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage(message, 5000)

    def view(self, node):
        backup = self._selected_backup(node)
        if backup is None:
            return
        trace(
            logger,
            "Viewing node backup",
            extra={
                "fields": {
                    "node_number": node.node_number
                    if isinstance(node, Pnn)
                    else node
                    if isinstance(node, int)
                    else node.number
                }
            },
        )
        BackupView(node, backup, self.parent).exec()

    def compare(self, node, state=None):
        backup = self._selected_backup(node)
        if backup is None:
            return
        trace(
            logger,
            "Comparing node backup",
            extra={
                "fields": {
                    "node_number": node.node_number
                    if isinstance(node, Pnn)
                    else node
                    if isinstance(node, int)
                    else node.number
                }
            },
        )
        BackupCompare(state if state is not None else node, backup, self.parent).exec()

    def create_live(self, state: NodeState, logical_layout: str) -> None:
        backup = node_backup(state)
        backup["annotations"] = load_annotations(
            logical_layout, state.identity.node_number
        )
        if not backup["complete"]:
            dialog = QMessageBox(self.parent)
            dialog.setWindowTitle("Incomplete node discovery")
            dialog.setText(
                "Discovery is incomplete. Save the confirmed configuration anyway?"
            )
            dialog.addButton(QMessageBox.StandardButton.Cancel)
            save = dialog.addButton("Save Anyway", QMessageBox.ButtonRole.AcceptRole)
            dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
            dialog.exec()
            if dialog.clickedButton() is not save:
                trace(logger, "Incomplete node backup cancelled")
                return
        description, accepted = QInputDialog.getText(
            self.parent, "New node backup", "Description (optional):"
        )
        if not accepted:
            trace(logger, "Node backup creation cancelled")
            return
        if description.strip():
            backup["description"] = description.strip()
        path = save_backup(logical_layout, backup)
        self.backups.show_live_node(logical_layout, state.identity.node_number)
        self._show_status(f"Node backup saved: {path}")

    def create(self, node):
        if node is None:
            return

        description, accepted = QInputDialog.getText(
            self.parent,
            "New node backup",
            "Description (optional):",
        )
        if not accepted:
            trace(logger, "Node backup creation cancelled")
            return

        backup = create_node_snapshot(node)
        backup["created"] = datetime.now().strftime("%d %b %Y, %H:%M")
        backup["description"] = description.strip()
        self.backups.add_backup(node, backup)
        trace(
            logger,
            "Node backup created",
            extra={"fields": {"node_number": node.number}},
        )
        self._show_status("Node backup created")

    def restore_live(self, node, service) -> None:
        number = node.node_number
        try:
            backup = self._selected_backup(node)
            if backup is None:
                return
            target = service.node_states.get(number)
            identity = (target.identity, target.can_id) if target else None
            message = (
                f"Restore this backup to live node {number}?\n\n"
                "Backup NVs are compared in ascending order and written only when different. "
                "Firmware may reset dependent configuration. Missing events will be taught, "
                "events may be reconstructed to remove EVs, and events absent from the backup "
                "will be removed. There is no rollback. Do not use another "
                "configuration tool during restoration.\n\n"
                "The backup records a node number, not its manufacturer or firmware; "
                "confirm that this backup belongs to the connected module."
            )
            if not backup["complete"]:
                message += (
                    "\n\nWARNING: This backup is incomplete. Replacement may remove "
                    "configuration that was not captured. Unknown NV/EV values will not "
                    "be written as zero, but dependent values may be reset. "
                    "Full equivalence to this backup cannot be established. "
                    "Continue with this destructive partial restore?"
                )
            if backup["partOfLayoutBackup"]:
                message += (
                    "\n\nThis backup is part of a layout backup. Restoring this "
                    "node independently may leave it inconsistent with other nodes."
                )
            answer, configuration, annotations = self.confirm_restore(message, backup)
            if answer != QMessageBox.StandardButton.Yes:
                trace(
                    logger,
                    "Live node restore declined",
                    extra={"fields": {"node_number": number}},
                )
                return
            if configuration:
                # Validate only hardware restoration. Annotation-only restore must
                # also work with incomplete discovery or an unavailable target.
                service.restore.check(number, backup)
                target = service.node_states[number]
                if identity != (target.identity, target.can_id):
                    raise ValueError(
                        "Target identity changed while confirming restoration."
                    )
            if annotations and "annotations" in backup:
                self.restore_annotations(number, backup)
            if configuration:
                service.restore.begin(
                    number, backup, allow_incomplete=not backup["complete"]
                )
        except ValueError as error:
            trace(
                logger,
                "Live node restore rejected",
                extra={"fields": {"node_number": number, "reason": str(error)}},
            )
            QMessageBox.warning(self.parent, "Cannot restore node backup", str(error))

    def confirm_restore(self, message, backup, *, configuration_available=True):
        dialog = QMessageBox(self.parent)
        dialog.setWindowTitle("Restore node backup")
        dialog.setText(message)
        configuration = QCheckBox("Restore configuration", dialog)
        configuration.setChecked(True)
        annotations = QCheckBox("Restore annotations", dialog)
        annotations.setChecked(True)
        if "annotations" not in backup:
            annotations.setToolTip(
                "This backup contains no annotations; current annotations will be kept."
            )
        dialog.setCheckBox(annotations)
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        restore = dialog.button(QMessageBox.StandardButton.Yes)
        restore.setText("Restore")
        layout = dialog.layout()
        # Keep both choices above the existing confirmation buttons.
        buttons = dialog.findChild(QDialogButtonBox)
        row, column, row_span, column_span = layout.getItemPosition(
            layout.indexOf(buttons)
        )
        layout.removeWidget(buttons)
        layout.addWidget(configuration, row, 0, 1, layout.columnCount())
        layout.addWidget(buttons, row + 1, column, row_span, column_span)

        def update_button():
            restore.setEnabled(
                (configuration.isChecked() or annotations.isChecked())
                and (configuration_available or not configuration.isChecked())
            )

        configuration.toggled.connect(update_button)
        annotations.toggled.connect(update_button)
        update_button()
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        answer = dialog.exec()
        trace(
            logger,
            "Node backup restore choices",
            extra={
                "fields": {
                    "node_number": backup["node"],
                    "accepted": answer == QMessageBox.StandardButton.Yes,
                    "configuration": configuration.isChecked(),
                    "annotations": annotations.isChecked(),
                }
            },
        )
        return answer, configuration.isChecked(), annotations.isChecked()

    def restore_annotations(self, number, backup):
        try:
            annotations = self.parent.annotations
            if annotations is not None:
                annotations.save(backup["annotations"], number)
            else:
                save_annotations(
                    self.parent.logical_layout, backup["annotations"], number
                )
        except (OSError, ValueError, TypeError) as error:
            logger.exception(
                "Annotation restore failed layout=%s node=%s",
                self.parent.logical_layout,
                number,
            )
            QMessageBox.warning(
                self.parent,
                "Annotations not restored",
                f"Local annotations could not be saved: {error}\n\nHardware configuration restoration is separate.",
            )
            return False
        self.parent.refresh_annotations()
        return True

    def restore_offline_annotations(self, node):
        backup = self._selected_backup(node)
        if backup is None:
            return
        number = node if isinstance(node, int) else node.node_number
        answer, configuration, annotations = self.confirm_restore(
            f"Restore backup for node {number}? Uncheck Restore configuration to restore local annotations offline. Configuration requires a connected, discovered node.",
            backup,
            configuration_available=False,
        )
        if (
            answer == QMessageBox.StandardButton.Yes
            and not configuration
            and annotations
            and "annotations" in backup
        ):
            self.restore_annotations(number, backup)

    def restore(self, node):
        if isinstance(node, Pnn):
            return
        backup = self._selected_backup(node)
        if backup is None:
            return

        if self._is_layout_backup(backup):
            message = (
                "This backup is part of a layout backup.\n\n"
                f"Restoring node {node.number} independently may leave "
                "its configuration inconsistent with other nodes.\n\n"
                "Do you want to continue?"
            )
        else:
            message = f"Restore '{backup['description']}' to node {node.number}?"

        answer = QMessageBox.question(
            self.parent,
            "Restore node backup",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            trace(
                logger,
                "Node backup restore declined",
                extra={"fields": {"node_number": node.number}},
            )
            return

        contents = backup_contents(backup)
        restore_node_snapshot(node, contents)
        self.refresh_displays()
        trace(
            logger,
            "Node backup restored",
            extra={"fields": {"node_number": node.number}},
        )
        self._show_status("Node backup restored successfully")

    def delete(self, node):
        if isinstance(node, Pnn):
            return
        backup = self._selected_backup(node)
        if backup is None:
            return

        if self._is_layout_backup(backup):
            trace(
                logger,
                "Individual layout backup deletion blocked",
                extra={"fields": {"node_number": node.number}},
            )
            QMessageBox.information(
                self.parent,
                "Delete node backup",
                "This backup belongs to a layout backup and cannot be deleted individually.",
            )
            return

        answer = QMessageBox.question(
            self.parent,
            "Delete node backup",
            f"Delete '{backup['description']}' for node {node.number}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            trace(
                logger,
                "Node backup deletion declined",
                extra={"fields": {"node_number": node.number}},
            )
            return

        self.backups.delete_backup(node, backup)
        trace(
            logger,
            "Node backup deleted",
            extra={"fields": {"node_number": node.number}},
        )
        self._show_status("Node backup deleted")
