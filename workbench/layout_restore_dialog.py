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
    def __init__(self, node_numbers, parent=None, *, presence=None):
        """Presence maps backup node numbers to display statuses; only Online is eligible."""
        super().__init__(parent)

        self.setWindowTitle("Restore layout backup")
        self.resize(500, 500)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select nodes to restore:"))

        self.include_events = presence is None
        self.events_checkbox = QCheckBox("Produced events", self)
        self.events_checkbox.setChecked(True)
        # Keep the existing demo caller working until the live workflow is wired.
        self.events_checkbox.setVisible(presence is None)
        if presence is None:
            layout.addWidget(self.events_checkbox)

        self.node_checkboxes = {}

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
            checkbox.setEnabled(status == "Online")
            checkbox.setChecked(status == "Online")
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
        restore_button.setText("Restore selected")

        def select_nodes(selected):
            for checkbox in self.node_checkboxes.values():
                if checkbox.isEnabled():
                    checkbox.setChecked(selected)

        select_all.clicked.connect(lambda: select_nodes(True))
        select_none.clicked.connect(lambda: select_nodes(False))

        for checkbox in self.node_checkboxes.values():
            checkbox.toggled.connect(self.update_button)

        self.update_button()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def update_button(self):
        self.restore_button.setEnabled(bool(self.selected_nodes()))

    def show_presence(self, number, status, reasons=()):
        """Display supported compatibility reasons without making them selectable."""
        checkbox = self.node_checkboxes[number]
        text = status
        if reasons:
            text = (
                reasons[0]
                if len(reasons) == 1
                else f"Incompatible ({len(reasons)} issues)"
            )
        checkbox.setText(f"Node {number} — {text}")
        checkbox.setToolTip("\n".join(reasons) if reasons else text)
        checkbox.setEnabled(status == "Online" and not reasons)
        checkbox.setChecked(checkbox.isEnabled())
        self.update_button()

    def selected_nodes(self):
        return {
            number
            for number, checkbox in self.node_checkboxes.items()
            if checkbox.isEnabled() and checkbox.isChecked()
        }

    def restore_events(self):
        return self.include_events and self.events_checkbox.isChecked()
