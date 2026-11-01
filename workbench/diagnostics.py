from datetime import datetime

from PySide6.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class Diagnostics(QWidget):
    def __init__(self):
        super().__init__()

        self.table = QTableWidget(0, 4)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setHorizontalHeaderLabels(["Time", "Direction", "Opcode", "Details"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)

        # Sample messages until real CBUS diagnostics are available.
        self.add_message("TX", "QNN", "Query all nodes")
        self.add_message("RX", "PNN", "Node 256 - CANMIO")
        self.add_message("RX", "PNN", "Node 258 - CANACE8C")
        self.add_message("TX", "RQNP", "Request node parameters")

    def add_message(self, direction, opcode, details):
        row = self.table.rowCount()
        self.table.insertRow(row)

        values = [
            datetime.now().strftime("%H:%M:%S"),
            direction,
            opcode,
            details,
        ]

        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(value))

        self.table.scrollToBottom()
