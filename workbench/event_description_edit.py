"""Contextual editing of layout and node-owned event descriptions."""

import logging

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
)

from .annotation_dialog_size import size_annotation_dialog
from .logging_config import trace

logger = logging.getLogger("workbench.annotations")


class EventDescriptionDialog(QDialog):
    """A missing node number selects layout names; a number selects that node."""

    def __init__(self, parent, annotations, identity, number=None):
        super().__init__(parent)
        data = annotations.load(number)
        self.key = "events" if number is None else "consumedEvents"
        self.setWindowTitle("Edit event description")
        layout = QFormLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        context = QLabel(identity)
        context.setTextFormat(Qt.TextFormat.PlainText)
        layout.addRow("Event:", context)
        editor = QLineEdit(data.get(self.key, {}).get(identity, ""))
        editor.setAccessibleName("Event description")
        layout.addRow("Description:", editor)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addRow(buttons)
        buttons.rejected.connect(self.reject)

        def save():
            try:
                current = annotations.load(number)
                current.setdefault(self.key, {})[identity] = editor.text()
                annotations.save(current, number)
            except (OSError, ValueError, TypeError) as error:
                logger.exception(
                    "Cannot save event description layout=%s node=%s event=%s",
                    annotations.logical_layout,
                    number,
                    identity,
                )
                QMessageBox.warning(self, "Description not saved", str(error))
                return  # Keep the draft for retry or Cancel; hardware is untouched.
            self.accept()

        buttons.accepted.connect(save)
        trace(
            logger,
            "Edit event description layout=%s node=%s event=%s",
            annotations.logical_layout,
            number,
            identity,
        )
        size_annotation_dialog(self)


class NodeEventNameEditor(QObject):
    def __init__(self, details):
        super().__init__(details)
        self.details = details
        self.dialog = None
        details.node_events.consumed_table.itemDoubleClicked.connect(self.edit_consumed)
        details.node_events.produced_table.cellDoubleClicked.connect(self.edit_produced)

    def cancel(self):
        if self.dialog is not None:
            self.dialog.reject()

    def edit_consumed(self, item, column):
        if column == 1 and item.parent() is None and self.details.node is not None:
            self.edit(item.text(0), self.details.annotation_number())

    def edit_produced(self, row, column):
        if column == 1:
            item = self.details.node_events.produced_table.item(row, 0)
            if item is not None:
                self.edit(item.text())

    def edit(self, identity, number=None):
        details = self.details
        if not details.annotations or not details.can_edit_annotations():
            return
        dialog = self.dialog = EventDescriptionDialog(
            details, details.annotations, identity, number
        )
        details.annotation_editing = True
        try:
            dialog.exec()
        finally:
            details.annotation_editing = False
            self.dialog = None
            details.refresh_annotations()
            if details.live_state is not None:
                details.show_live_state(details.live_state, details.live_mdf)
            dialog.deleteLater()
