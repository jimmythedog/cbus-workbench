from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class LayoutRestoreDialog(QDialog):
    def __init__(self, node_numbers, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Restore layout backup")
        self.resize(350, 500)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select what to restore:"))

        self.events_checkbox = QCheckBox("Produced events")
        self.events_checkbox.setChecked(True)
        layout.addWidget(self.events_checkbox)

        self.node_checkboxes = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        container = QWidget()
        node_layout = QVBoxLayout(container)

        for number in sorted(node_numbers):
            checkbox = QCheckBox(f"Node {number}")
            checkbox.setChecked(True)
            node_layout.addWidget(checkbox)
            self.node_checkboxes[number] = checkbox

        node_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        restore_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        restore_button.setText("Restore selected")

        def update_button():
            restore_button.setEnabled(
                self.events_checkbox.isChecked()
                or any(
                    checkbox.isChecked() for checkbox in self.node_checkboxes.values()
                )
            )

        self.events_checkbox.toggled.connect(update_button)

        for checkbox in self.node_checkboxes.values():
            checkbox.toggled.connect(update_button)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_nodes(self):
        return {
            number
            for number, checkbox in self.node_checkboxes.items()
            if checkbox.isChecked()
        }

    def restore_events(self):
        return self.events_checkbox.isChecked()
