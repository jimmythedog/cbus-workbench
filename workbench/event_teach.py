"""Native dialogs for adding and deleting consumed events.

New Event and Teach to Node choose an identity (and target) only; the node's
existing Events Edit/Save workflow then configures, teaches and verifies it.
Delete Event is an immediate, confirmed EventSave.delete_event() operation.
"""

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from .annotation_dialog_size import size_annotation_dialog
from .logging_config import trace
from .parameter_names import module_name

logger = logging.getLogger("workbench.events")


class TeachEventDialog(QDialog):
    """Choose a long/short event identity and, optionally, a target node.

    With no target choices the node is already known (Node → Consumed Events)
    and the identity is edited. With choices (Layout → Observed Events) the
    identity is fixed and shown read-only; only the target node is chosen.
    """

    def __init__(self, parent, title, identity=None, targets=None, consumed=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        # Unparented until laid out: Teach to Node shows no identity controls.
        self.long_radio = QRadioButton("Long")
        self.short_radio = QRadioButton("Short")
        self.long_radio.setChecked(True)
        event_types = QHBoxLayout()
        event_types.addWidget(self.long_radio)
        event_types.addWidget(self.short_radio)
        event_types.addStretch()
        self.node_number = QSpinBox()
        self.node_number.setRange(1, 65535)
        self.event_number = QSpinBox()
        self.event_number.setRange(0, 65535)
        form = QFormLayout()
        self.fixed_identity = identity if targets is not None else None
        if self.fixed_identity is None:
            form.addRow("Type:", event_types)
            form.addRow("Event node number:", self.node_number)
            form.addRow("Event number:", self.event_number)
        else:
            nn, en = identity
            kind = "short" if nn == 0 else "long"
            form.addRow("Event:", QLabel(f"{nn}:{en} ({kind})"))
        self.target = None
        self.consumed = consumed or set()
        if targets is not None:
            # targets: [(node number, display text, consumed identities)]
            self.targets = targets
            self.target = QComboBox()
            for number, text, _consumed in targets:
                self.target.addItem(text, number)
            form.addRow("Teach to node:", self.target)
            self.target.currentIndexChanged.connect(self.update_controls)
        self.message = QLabel()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addWidget(self.buttons)
        self.short_radio.toggled.connect(self.update_controls)
        self.node_number.valueChanged.connect(self.update_controls)
        self.event_number.valueChanged.connect(self.update_controls)
        if identity is not None:
            self.short_radio.setChecked(identity[0] == 0)
            if identity[0]:
                self.node_number.setValue(identity[0])
            self.event_number.setValue(identity[1])
        self.update_controls()
        size_annotation_dialog(self)

    def identity(self) -> tuple[int, int]:
        """Short events use event NN 0 (CBUS Developer's Guide 6b, ASON)."""
        if self.fixed_identity is not None:
            return self.fixed_identity
        short = self.short_radio.isChecked()
        return (0 if short else self.node_number.value(), self.event_number.value())

    def target_number(self) -> int | None:
        return None if self.target is None else self.target.currentData()

    def update_controls(self, *_args):
        self.node_number.setEnabled(not self.short_radio.isChecked())
        message = ""
        consumed = self.consumed
        if self.target is not None:
            if self.target.count() == 0:
                message = "No online node in this layout can be taught now."
            else:
                consumed = self.targets[self.target.currentIndex()][2]
        if not message and self.identity() in consumed:
            message = "This node already consumes this event."
        self.message.setText(message)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not message)


def teach_targets(service, annotations):
    """Online nodes that meet the teaching preconditions, by name or module type."""
    targets = []
    for number, state in sorted(service.node_states.items()):
        if not service.presence.get(number, False):
            continue
        try:
            # The same checks Events Save applies when it starts.
            service.event_save.check_complete(number)
        except ValueError:
            continue
        identity = state.identity
        name = annotations.load(number).get("name", "") if annotations else ""
        text = name or module_name(identity.manufacturer, identity.module_type)
        consumed = set(state.event_identities.values())
        targets.append((number, f"{number} — {text}", consumed))
    return targets


def start_delete_event(parent, service, number, identity, *, finished):
    """Start unlearning; finished(success, message) reports the verified result.

    Success is reported by the caller's status area and refreshed display;
    failures also show a warning.
    """

    def report(_number, success, message):
        finished(success, message)
        if not success:
            # The result arrives inside service frame/disconnect handling. Show
            # the modal box afterwards so that handling (learn exit) is not delayed.
            QTimer.singleShot(
                0, parent, lambda: QMessageBox.warning(parent, "Delete event", message)
            )

    trace(
        logger,
        "Event delete requested",
        extra={
            "fields": {
                "layout": service.connection.layout_name,
                "node_number": number,
                "identity": identity,
            }
        },
    )
    # Connect first: a transmission failure can finish before the call returns.
    service.event_save.delete_finished.connect(
        report, Qt.ConnectionType.SingleShotConnection
    )
    try:
        service.event_save.delete_event(number, identity)
    except ValueError as error:
        service.event_save.delete_finished.disconnect(report)
        trace(
            logger,
            "Event delete rejected",
            extra={"fields": {"node_number": number, "reason": str(error)}},
        )
        QMessageBox.warning(parent, "Delete event", str(error))
        return False
    return True


def confirm_delete(parent, number, identity) -> bool:
    answer = QMessageBox.question(
        parent,
        "Delete event",
        f"Unlearn event {identity[0]}:{identity[1]} from node {number}?\n\n"
        "All of this event's EVs on the node are removed.",
    )
    return answer == QMessageBox.StandardButton.Yes
