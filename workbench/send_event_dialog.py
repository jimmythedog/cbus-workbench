"""Native controls for repeated event testing on one explicitly chosen layout."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from .annotation_dialog_size import size_annotation_dialog


class SendEventDialog(QDialog):
    def __init__(self, service, parent=None, identity=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Send Event")
        self.long_radio = QRadioButton("Long", self)
        self.short_radio = QRadioButton("Short", self)
        self.long_radio.setChecked(True)
        event_types = QHBoxLayout()
        event_types.addWidget(self.long_radio)
        event_types.addWidget(self.short_radio)
        event_types.addStretch()
        self.node_number = QSpinBox()
        self.node_number.setRange(0, 65535)
        self.event_number = QSpinBox()
        self.event_number.setRange(0, 65535)
        self.node_label = QLabel()
        form = QFormLayout()
        form.addRow("Layout:", QLabel(service.connection.layout_name))
        form.addRow("Type:", event_types)
        form.addRow(self.node_label, self.node_number)
        form.addRow("Event number:", self.event_number)
        self.status = QLabel()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.on_button = buttons.addButton(
            "Send ON", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.off_button = buttons.addButton(
            "Send OFF", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.on_button.clicked.connect(lambda: self.send(True))
        self.off_button.clicked.connect(lambda: self.send(False))
        buttons.rejected.connect(self.reject)
        self.short_radio.toggled.connect(self.update_event_type)
        self.node_number.valueChanged.connect(self.update_controls)
        service.connection.state_changed.connect(self.update_controls)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status)
        layout.addWidget(buttons)
        self.update_event_type()
        if identity is not None:
            nn, en = identity
            self.short_radio.setChecked(nn == 0)
            self.node_number.setValue(nn)
            self.event_number.setValue(en)
        self.update_controls()
        size_annotation_dialog(self)

    def update_event_type(self, *_args):
        short = self.short_radio.isChecked()
        self.node_label.setText("Event node number:")
        self.node_number.setEnabled(not short)
        self.node_number.setValue(0 if short else next(iter(self.service.nodes), 0))
        self.update_controls()

    def update_controls(self, *_args):
        short = self.short_radio.isChecked()
        enabled = self.service.connection.state == "Connected" and (
            short or self.node_number.value() > 0
        )
        self.on_button.setEnabled(enabled)
        self.off_button.setEnabled(enabled)

    def send(self, on):
        try:
            self.service.send_event(
                "Short" if self.short_radio.isChecked() else "Long",
                self.node_number.value(),
                self.event_number.value(),
                on,
            )
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Cannot send event", str(error))
            return
        self.status.setText("ON frame sent" if on else "OFF frame sent")


def event_menu(table, position, service, identity, extra_actions=()):
    """Show send actions for an event row, followed by any view actions."""
    if identity is None and not extra_actions:
        return
    menu = QMenu(table)
    if identity is not None:
        for on in (True, False):
            action = menu.addAction("Send ON" if on else "Send OFF")
            action.setEnabled(
                service is not None and service.connection.state == "Connected"
            )
            action.triggered.connect(
                lambda _checked=False, on=on: send_existing(
                    table, service, identity, on
                )
            )
    if extra_actions:
        menu.addSeparator()
        menu.addActions(list(extra_actions))
    menu.exec(table.viewport().mapToGlobal(position))


def send_existing(parent, service, identity, on):
    nn, en = identity
    try:
        service.send_event("Short" if nn == 0 else "Long", nn, en, on)
    except (ValueError, OSError) as error:
        QMessageBox.warning(parent, "Cannot send event", str(error))
