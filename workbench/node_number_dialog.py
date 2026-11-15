"""Dialog opened when a module in setup mode requests a node number."""

import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from .annotation_dialog_size import size_annotation_dialog
from .node_number import check_node_number, suggest_node_number
from .parameter_names import manufacturer_name, module_name

logger = logging.getLogger("workbench.cbus")


class NodeNumberDialog(QDialog):
    """Show the requesting module, propose a number and report the outcome.

    `known_nodes()` returns {node number: online} for nodes Workbench knows on
    this network; it is read again whenever the dialog revalidates.
    """

    def __init__(self, layout_name: str, assignment, known_nodes, parent=None):
        super().__init__(parent)
        self.assignment = assignment
        self.known_nodes = known_nodes
        self.layout_name = layout_name
        self.finished_outcome: tuple[bool, str] | None = None
        self.setWindowTitle(f"Assign Node Number — {layout_name}")

        current = assignment.current
        self.current_label = QLabel(
            "None (new module)" if current == 0 else str(current)
        )
        self.module_label = QLabel("Not reported")
        self.can_id_label = QLabel(str(assignment.can_id))
        self.number = QSpinBox()
        self.number.setRange(0, 65535)
        # A FLiM module reports its current number; offering it by default
        # means checking a module's number doesn't renumber it by accident.
        suggestion = current or suggest_node_number(known_nodes())
        self.number.setValue(suggestion if suggestion is not None else 0)
        self.reason = QLabel()
        self.reason.setWordWrap(True)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.buttons = QDialogButtonBox()
        self.assign_button = self.buttons.addButton(
            "Assign", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button = self.buttons.addButton(
            QDialogButtonBox.StandardButton.Cancel
        )

        form = QFormLayout()
        form.addRow("Current node number:", self.current_label)
        form.addRow("Module:", self.module_label)
        form.addRow("CAN ID:", self.can_id_label)
        form.addRow("New node number:", self.number)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("A module is requesting a node number."))
        layout.addLayout(form)
        layout.addWidget(self.reason)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)

        self.number.valueChanged.connect(self.refresh)
        self.assign_button.clicked.connect(self.assign)
        self.cancel_button.clicked.connect(self.reject)
        assignment.changed.connect(self.refresh)
        assignment.finished.connect(self.show_outcome)
        self.refresh()
        size_annotation_dialog(self)

    def refresh(self) -> None:
        if self.finished_outcome is not None:
            return
        parameters = self.assignment.parameters
        if parameters is not None:
            manufacturer, minor, module_type, *_rest, major = parameters
            # Parameter 2 is the minor version as an ASCII character.
            minor_text = chr(minor) if 32 < minor < 127 else str(minor)
            self.module_label.setText(
                f"{module_name(manufacturer, module_type)} "
                f"({manufacturer_name(manufacturer)}), version {major}{minor_text}"
            )
        known = self.known_nodes()
        number = self.number.value()
        reason = self.assignment.unavailable_reason(number, known)
        warning = check_node_number(number, self.assignment.current, known)[1]
        self.show_message(self.reason, reason or warning)
        self.assign_button.setEnabled(not reason)
        waiting = self.assignment.target is not None
        self.number.setEnabled(not waiting)
        self.cancel_button.setEnabled(not waiting)
        self.show_message(
            self.status,
            f"Waiting for the module to acknowledge node number {self.assignment.target}…"
            if waiting
            else "",
        )

    def show_message(self, label: QLabel, text: str) -> None:
        """Hide empty message lines so the dialog stays compact."""
        label.setText(text)
        label.setVisible(bool(text))
        # Keep the current width; wrapped messages only change the height.
        self.layout().activate()
        height = self.heightForWidth(self.width())
        self.resize(self.width(), height if height > 0 else self.sizeHint().height())

    def assign(self) -> None:
        # The Assign click in this dedicated dialog is the explicit confirmation.
        number = self.number.value()
        try:
            self.assignment.assign(number, self.known_nodes())
        except ValueError:
            pass  # refresh() shows the current reason.
        self.refresh()

    def show_outcome(self, success: bool, message: str) -> None:
        self.finished_outcome = (success, message)
        if success:
            self.accept()
            return
        self.show_message(self.status, message)
        self.show_message(self.reason, "")
        self.assign_button.hide()
        self.number.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Close")

    def reject(self) -> None:
        if self.assignment.target is not None:
            return  # The bounded NNACK wait decides the outcome.
        if self.finished_outcome is None:
            self.assignment.cancel()
            message = (
                "Cancelled. The module stays in setup mode until its button is "
                "pressed again."
            )
            self.finished_outcome = (False, message)
        super().reject()
