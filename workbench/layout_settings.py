from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class LayoutSettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        name="",
        logical_layout="",
        logical_layouts=(),
        connection_type="TCP/IP",
        host="",
        port=5550,
        serial_port="/dev/ttyACM0",
        can_id=126,
        auto_connect=False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Layout settings")

        self.name_edit = QLineEdit(name)

        self.logical_layout_combo = QComboBox()
        self.logical_layout_combo.setEditable(True)
        self.logical_layout_combo.addItems(logical_layouts)
        self.logical_layout_combo.setCurrentText(logical_layout)

        self.connection_type_combo = QComboBox()
        self.connection_type_combo.addItems(["TCP/IP", "Serial"])
        self.connection_type_combo.setCurrentText(connection_type)

        self.host_edit = QLineEdit(host)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(port)

        self.serial_port_edit = QLineEdit(serial_port)

        self.can_id_spin = QSpinBox()
        self.can_id_spin.setRange(100, 127)
        self.can_id_spin.setValue(can_id)

        layout_form = QFormLayout()
        layout_form.addRow("Name:", self.name_edit)
        layout_form.addRow("Logical layout:", self.logical_layout_combo)
        self.auto_connect_check = QCheckBox("Auto-connect on startup")
        self.auto_connect_check.setChecked(auto_connect)
        layout_form.addRow(self.auto_connect_check)

        connection_group = QGroupBox("Connection")
        connection_form = QFormLayout(connection_group)
        connection_form.addRow("Type:", self.connection_type_combo)

        self.tcp_fields = QWidget()
        tcp_form = QFormLayout(self.tcp_fields)
        tcp_form.setContentsMargins(0, 0, 0, 0)
        tcp_form.addRow("Host:", self.host_edit)
        tcp_form.addRow("Port:", self.port_spin)

        self.serial_fields = QWidget()
        serial_form = QFormLayout(self.serial_fields)
        serial_form.setContentsMargins(0, 0, 0, 0)
        serial_form.addRow("Port:", self.serial_port_edit)

        self.connection_fields = QStackedWidget()
        self.connection_fields.addWidget(self.tcp_fields)
        self.connection_fields.addWidget(self.serial_fields)

        connection_form.addRow(self.connection_fields)
        connection_form.addRow("CAN ID:", self.can_id_spin)

        self.connection_type_combo.currentTextChanged.connect(
            self.update_connection_fields
        )
        self.update_connection_fields(connection_type)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(layout_form)
        main_layout.addWidget(connection_group)
        main_layout.addWidget(buttons)

    def update_connection_fields(self, connection_type):
        self.connection_fields.setCurrentIndex(0 if connection_type == "TCP/IP" else 1)

    def settings(self):
        return {
            "name": self.name_edit.text().strip(),
            "logical_layout": self.logical_layout_combo.currentText().strip(),
            "connection_type": self.connection_type_combo.currentText(),
            "host": self.host_edit.text().strip(),
            "port": self.port_spin.value(),
            "serial_port": self.serial_port_edit.text().strip(),
            "can_id": self.can_id_spin.value(),
            "auto_connect": self.auto_connect_check.isChecked(),
        }
