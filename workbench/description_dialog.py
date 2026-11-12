"""The contextual Save/Cancel editor for a single description."""

import logging

import yaml
from PySide6.QtCore import Qt
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

logger = logging.getLogger(__name__)


class DescriptionDialog(QDialog):
    def __init__(self, parent, kind, identity, description, save_description):
        super().__init__(parent)
        self.setWindowTitle(f"Edit {kind} description")
        layout = QFormLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        context = QLabel(identity)
        context.setTextFormat(Qt.TextFormat.PlainText)
        layout.addRow(f"{kind.capitalize()}:", context)
        editor = QLineEdit(description)
        editor.setAccessibleName(f"{kind.capitalize()} description")
        layout.addRow("Description:", editor)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addRow(buttons)
        buttons.rejected.connect(self.reject)

        def save():
            try:
                save_description(editor.text())
            except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
                logger.exception(
                    "Cannot save %s description identity=%s", kind, identity
                )
                QMessageBox.warning(self, "Description not saved", str(error))
                return  # Retain the draft for retry or Cancel.
            self.accept()

        buttons.accepted.connect(save)
        size_annotation_dialog(self)
