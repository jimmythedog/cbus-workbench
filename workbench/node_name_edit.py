"""Contextual node-name editing from the read-only details label."""

import logging

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLayout,
    QLineEdit,
    QMessageBox,
)

from .annotation_dialog_size import size_annotation_dialog
from .logging_config import trace

logger = logging.getLogger("workbench.annotations")


class NodeNameEditor(QObject):
    def __init__(self, details):
        super().__init__(details)
        self.details = details
        self.dialog = None
        details.node_name.setToolTip("Double-click to edit the node name")
        details.node_name.installEventFilter(self)

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.MouseButtonDblClick
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.edit()
            return True
        return False

    def cancel(self):
        if self.dialog is not None:
            self.dialog.reject()

    def edit(self):
        details = self.details
        if not details.can_edit_annotations():
            return
        number = details.annotation_number()
        name = (
            details.annotations.load(number).get("name", "")
            if details.annotations
            else details.node.name
        )
        dialog = self.dialog = QDialog(details)
        dialog.setWindowTitle("Edit node name")
        layout = QFormLayout(dialog)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        editor = QLineEdit(name)
        editor.setAccessibleName("Node name")
        layout.addRow("Name:", editor)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addRow(buttons)
        buttons.rejected.connect(dialog.reject)

        def save():
            try:
                if details.annotations:
                    data = details.annotations.load(number)
                    data["name"] = editor.text().strip()
                    details.annotations.save(data, number)
                else:
                    details.node.name = editor.text().strip()
            except (OSError, ValueError, TypeError) as error:
                logger.exception(
                    "Cannot save node name layout=%s node=%s",
                    details.logical_layout,
                    number,
                )
                QMessageBox.warning(dialog, "Node name not saved", str(error))
                return  # Keep the dialog and draft available for retry or Cancel.
            dialog.accept()

        buttons.accepted.connect(save)
        trace(
            logger, "Edit node name layout=%s node=%s", details.logical_layout, number
        )
        details.annotation_editing = True
        try:
            size_annotation_dialog(dialog)
            dialog.exec()
        finally:
            details.annotation_editing = False
            self.dialog = None
            details.refresh_node_name()
            if details.live_state is not None:
                details.show_live_state(details.live_state, details.live_mdf)
            dialog.deleteLater()
