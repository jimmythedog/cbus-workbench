from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .node_variables import MdfNodeVariables, RawNodeVariables

DEFAULT_NODE_TITLE = "Node details"


class NodeDetails(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.group = QGroupBox(DEFAULT_NODE_TITLE)
        form = QFormLayout(self.group)

        self.node_number = QLabel("-")
        self.can_id = QLabel("-")
        self.module_type = QLabel("-")
        self.firmware = QLabel("-")
        self.status = QLabel("-")

        form.addRow("Node number:", self.node_number)
        form.addRow("CAN ID:", self.can_id)
        form.addRow("Module type:", self.module_type)
        form.addRow("Firmware:", self.firmware)
        form.addRow("Status:", self.status)

        layout.addWidget(self.group)

        tabs = QTabWidget()
        self.raw_values = RawNodeVariables()
        self.mdf_values = MdfNodeVariables()

        self.variables = QStackedWidget()
        self.variables.addWidget(self.raw_values)
        self.variables.addWidget(self.mdf_values)

        tabs.addTab(self.variables, "Node Variables")

        tabs.addTab(QLabel("Consumed events will go here"), "Events")
        tabs.addTab(QLabel("Node backups will go here"), "Backups")

        layout.addWidget(tabs)

    def show_node(self, current):
        if current is None:
            self.group.setTitle(DEFAULT_NODE_TITLE)
            self.node_number.setText("-")
            self.can_id.setText("-")
            self.module_type.setText("-")
            self.firmware.setText("-")
            self.status.setText("-")
            self.variables.setCurrentIndex(0)
            return

        node = current.data(Qt.ItemDataRole.UserRole)

        self.raw_values.show_node(node)
        self.mdf_values.show_node(node)

        number = node.number
        has_mdf = node.has_mdf

        self.variables.setCurrentIndex(1 if has_mdf else 0)
        self.group.setTitle(f"Node {number} — CANMIO")
        self.node_number.setText(str(number))
        self.can_id.setText("126")
        self.module_type.setText("CANMIO")
        self.firmware.setText("3d")
        self.status.setText("Online")
