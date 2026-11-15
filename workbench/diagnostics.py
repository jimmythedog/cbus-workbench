import logging
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .logging_config import trace
from .traffic import decode_can_frame

logger = logging.getLogger("workbench.diagnostics")

# Group decoded rows by their generic labels; opcode fields fall into "Message".
_DATA_LABELS = {"Data bytes", "Data length"}
_HEADER_LABELS = {"Major priority", "Minor priority", "CAN ID"}


class Diagnostics(QWidget):
    def __init__(self):
        super().__init__()

        self.table = QTableWidget(0, 4)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setHorizontalHeaderLabels(["Time", "Direction", "Opcode", "Details"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.show_raw_message)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)

    def add_message(self, direction, opcode, details, raw=None):
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
        # Keep the raw frame with its row so double-click can show it untruncated.
        self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, raw)

        self.table.scrollToBottom()

    def show_raw_message(self, row, _column):
        raw = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if raw is None:
            trace(
                logger,
                "No raw diagnostics message to show",
                extra={"fields": {"row": row}},
            )
            return
        direction = self.table.item(row, 1).text()
        trace(
            logger,
            "Show raw diagnostics message",
            extra={"fields": {"row": row, "direction": direction, "frame": raw}},
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(f"{direction} raw message")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        text = QLineEdit(raw)
        text.setReadOnly(True)
        # Fit the whole frame; the extra pixels allow for the field's frame and margins.
        text.setMinimumWidth(text.fontMetrics().horizontalAdvance(raw) + 24)
        text.selectAll()
        # Decimal breakdown below the copyable raw text, as recorded.
        sections = {
            "Raw frame": QFormLayout(),
            "Message": QFormLayout(),
            "CAN header": QFormLayout(),
        }
        sections["Raw frame"].addRow("Raw:", text)
        fields = decode_can_frame(raw.encode("ascii", errors="replace"))
        for label, value in fields:
            value_label = QLabel(value)
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            if label in _DATA_LABELS:
                section = "Raw frame"
            elif label in _HEADER_LABELS:
                section = "CAN header"
            else:
                section = "Message"
            sections[section].addRow(f"{label}:", value_label)
        layout = QVBoxLayout(dialog)
        for title, form in sections.items():
            if form.rowCount():
                box = QGroupBox(title)
                box.setLayout(form)
                layout.addWidget(box)
        if not fields:
            layout.addWidget(QLabel("Not a standard CBUS data frame; not decoded."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.open()
