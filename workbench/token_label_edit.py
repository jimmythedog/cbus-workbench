"""Edit only user-name tokens from their existing MDF labels."""

import logging

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from .annotation_dialog_size import size_annotation_dialog
from .logging_config import trace
from .mdf_tokens import token_defaults

logger = logging.getLogger("workbench.annotations")


def editable_tokens(template):
    """Structural placeholders have no numbered user-name identity."""
    return list(token_defaults({"displayTitle": template}))


class TokenLabelEditor(QObject):
    """Attach a contextual text editor without changing hardware controls."""

    def __init__(self, details):
        super().__init__(details)
        self.details = details

    def bind(self, widget, template):
        if not isinstance(template, str) or not editable_tokens(template):
            return
        widget.setProperty("mdfTokenTemplate", template)
        widget.setToolTip(
            "Double-click to edit token names. Blank uses the MDF default."
        )
        widget.installEventFilter(self)

    def bind_page(self, item, template):
        if editable_tokens(template):
            item.setData(Qt.ItemDataRole.UserRole, template)
            item.setToolTip("Double-click to edit token names")

    def bind_tabs(self, tabs, templates):
        """Nested MDF tab titles edit like navigation pages, by double-click."""
        bar = tabs.tabBar()
        for index, template in enumerate(templates):
            if editable_tokens(template):
                bar.setTabData(index, template)
                bar.setTabToolTip(index, "Double-click to edit token names")
        # A double-click outside any tab gives index -1 and no data: edit() ignores it.
        tabs.tabBarDoubleClicked.connect(
            lambda index: self.edit(bar.tabData(index), bar.tabText(index))
        )

    def bind_choices(self, widget, options):
        templates = [option.get("label", "") for option in options]
        if any(isinstance(text, str) and editable_tokens(text) for text in templates):
            widget.setProperty("mdfTokenChoices", templates)
            widget.setToolTip("Right-click to edit the displayed token name.")
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if isinstance(watched, QComboBox):
            if event.type() != QEvent.Type.ContextMenu:
                return False
            choices = watched.property("mdfTokenChoices") or []
            index = watched.currentIndex()
            if 0 <= index < len(choices):
                self.edit(choices[index], watched.currentText())
                return True
        elif (
            event.type() == QEvent.Type.MouseButtonDblClick
            and event.button() == Qt.MouseButton.LeftButton
        ):
            # A group owns its whole rectangle; only its heading is a label.
            if (
                isinstance(watched, QGroupBox)
                and event.position().y() > watched.fontMetrics().height() + 8
            ):
                return False
            text = watched.title() if isinstance(watched, QGroupBox) else watched.text()
            self.edit(watched.property("mdfTokenTemplate"), text)
            return True
        return False

    def edit(self, template, rendered):
        details = self.details
        keys = editable_tokens(template or "")
        if not keys or not details.annotations or not details.can_edit_annotations():
            return
        number = details.annotation_number()
        data = details.annotations.load(number)
        defaults = token_defaults(details.live_mdf.data)
        trace(
            logger,
            "Edit MDF label tokens layout=%s node=%s identifiers=%s",
            details.logical_layout,
            number,
            keys,
        )
        dialog = QDialog(details)
        dialog.setWindowTitle("Edit token names")
        layout = QVBoxLayout(dialog)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        context = QLabel(rendered)
        context.setTextFormat(Qt.TextFormat.PlainText)
        context.setWordWrap(True)
        layout.addWidget(context)
        form = QFormLayout()
        layout.addLayout(form)
        editors = {}
        for name, token_number in keys:
            editor = QLineEdit(
                data.get("tokens", {}).get(name, {}).get(token_number, "")
            )
            editor.setAccessibleName(name + token_number)
            editor.setPlaceholderText(
                defaults.get((name, token_number), name + token_number)
            )
            form.addRow(name + token_number + ":", editor)
            editors[(name, token_number)] = editor
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)

        def save():
            # Merge into current annotations; a token edit owns only these keys.
            selected_page = details.mdf_values.navigation.currentRow()
            try:
                current = details.annotations.load(number)
                for (name, token_number), editor in editors.items():
                    current.setdefault("tokens", {}).setdefault(name, {})[
                        token_number
                    ] = editor.text()
                details.annotations.save(current, number)
            except (OSError, ValueError, TypeError) as error:
                logger.exception("Cannot save MDF token names node=%s", number)
                QMessageBox.warning(dialog, "Token names not saved", str(error))
                return  # Retain the draft and allow Save or Cancel again.
            details.mdf_values.navigation.setCurrentRow(
                min(selected_page, details.mdf_values.navigation.count() - 1)
            )
            dialog.accept()

        buttons.accepted.connect(save)
        size_annotation_dialog(dialog)
        dialog.exec()
        dialog.deleteLater()
