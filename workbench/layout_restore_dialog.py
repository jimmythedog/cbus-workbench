from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class LayoutRestoreDialog(QDialog):
    def __init__(
        self,
        node_numbers,
        parent=None,
        *,
        presence=None,
        has_annotations=False,
        configuration_available=True,
        annotation_nodes=(),
    ):
        """Hardware eligibility and backed-up annotations independently allow selection."""
        super().__init__(parent)

        self.setWindowTitle("Restore layout backup")
        self.resize(500, 500)

        layout = QVBoxLayout(self)

        self.include_events = presence is None
        self.events_checkbox = QCheckBox("Produced events", self)
        self.events_checkbox.setChecked(True)
        # Keep the existing demo caller working until the live workflow is wired.
        self.events_checkbox.setVisible(presence is None)
        if presence is None:
            layout.addWidget(self.events_checkbox)

        self.annotations_checkbox = QCheckBox("Restore annotations")
        self.annotations_checkbox.setChecked(True)
        if not has_annotations:
            self.annotations_checkbox.setToolTip(
                "This backup contains no annotations; current annotations will be kept."
            )
        layout.addWidget(self.annotations_checkbox)
        self.node_checkboxes = {}
        self.configuration_available = configuration_available
        self.annotation_nodes = set(annotation_nodes)
        self.presence = {}
        self.configuration_checkbox = QCheckBox("Restore configuration")
        self.configuration_checkbox.setChecked(True)
        layout.insertWidget(0, self.configuration_checkbox)
        layout.addWidget(QLabel("Select nodes to restore:"))

        selection_buttons = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_none = QPushButton("Select None")
        selection_buttons.addWidget(select_all)
        selection_buttons.addWidget(select_none)
        selection_buttons.addStretch()
        layout.addLayout(selection_buttons)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        node_layout = QVBoxLayout(container)

        for number in sorted(node_numbers):
            status = (
                presence.get(number, "Checking") if presence is not None else "Online"
            )
            checkbox = QCheckBox(f"Node {number} — {status}")
            checkbox.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.presence[number] = (status, ())
            selectable = (
                configuration_available and status == "Online"
            ) or number in self.annotation_nodes
            checkbox.setEnabled(selectable)
            checkbox.setChecked(selectable)
            node_layout.addWidget(checkbox)
            self.node_checkboxes[number] = checkbox

        node_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        self.restore_button = restore_button = buttons.button(
            QDialogButtonBox.StandardButton.Ok
        )
        restore_button.setText("Restore")

        def select_nodes(selected):
            for checkbox in self.node_checkboxes.values():
                if checkbox.isEnabled():
                    checkbox.setChecked(selected)

        select_all.clicked.connect(lambda: select_nodes(True))
        select_none.clicked.connect(lambda: select_nodes(False))

        for checkbox in self.node_checkboxes.values():
            checkbox.toggled.connect(self.update_button)

        self.configuration_checkbox.toggled.connect(self.configuration_changed)
        self.annotations_checkbox.toggled.connect(self.configuration_changed)
        self.update_button()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def update_button(self):
        self.restore_button.setEnabled(
            bool(self.selected_configuration_nodes())
            or self.annotations_checkbox.isChecked()
        )

    def configuration_changed(self):
        for number in self.node_checkboxes:
            self.refresh_row(number)
        self.update_button()

    def hardware_eligible(self, number):
        status, reasons = self.presence[number]
        return self.configuration_available and status == "Online" and not reasons

    def refresh_row(self, number):
        checkbox = self.node_checkboxes[number]
        status, reasons = self.presence[number]
        configuration = self.configuration_checkbox.isChecked()
        if configuration:
            text = status
            if reasons:
                text = (
                    reasons[0]
                    if len(reasons) == 1
                    else f"Incompatible ({len(reasons)} issues)"
                )
            checkbox.setText(f"Node {number} — {text}")
            checkbox.setToolTip("\n".join(reasons) if reasons else text)
        else:
            checkbox.setText(f"Node {number}")
            checkbox.setToolTip("Restore local node annotations")
        checkbox.setEnabled(
            (configuration and self.hardware_eligible(number))
            or (
                self.annotations_checkbox.isChecked()
                and number in self.annotation_nodes
            )
        )

    def show_presence(self, number, status, reasons=()):
        """Update eligibility without discarding an annotation selection."""
        checkbox = self.node_checkboxes[number]
        was_enabled = checkbox.isEnabled()
        self.presence[number] = (status, reasons)
        self.refresh_row(number)
        # Newly eligible hardware rows retain the original default selection.
        # Already selectable annotation rows keep the user's checked/unchecked choice.
        if not was_enabled and checkbox.isEnabled() and self.hardware_eligible(number):
            checkbox.setChecked(True)
        self.update_button()

    def selected_configuration_nodes(self):
        if not self.configuration_checkbox.isChecked():
            return set()
        return {
            number for number in self.selected_nodes() if self.hardware_eligible(number)
        }

    def selected_nodes(self):
        return {
            number
            for number, checkbox in self.node_checkboxes.items()
            if checkbox.isEnabled() and checkbox.isChecked()
        }

    def restore_events(self):
        return self.include_events and self.events_checkbox.isChecked()
