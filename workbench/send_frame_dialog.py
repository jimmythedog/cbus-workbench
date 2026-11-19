"""Send raw GridConnect frames on a connected layout."""

import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from .serial_connection import SerialConnection
from .simulator_connection import SimulatorConnection
from .tcp_connection import TcpConnection

logger = logging.getLogger("workbench.connection")


class SendFrameDialog(QDialog):
    def __init__(
        self,
        layout_name: str,
        connection: TcpConnection | SerialConnection | SimulatorConnection,
        parent=None,
    ):
        super().__init__(parent)
        self.connection = connection
        self.setWindowTitle("Send GridConnect Frame")

        self.frame_edit = QLineEdit()
        form = QFormLayout()
        form.addRow("Layout:", QLabel(layout_name))
        form.addRow("Frame:", self.frame_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.send_button = buttons.addButton(
            "Send", QDialogButtonBox.ButtonRole.AcceptRole
        )
        # Keep the dialog open so another frame can be sent.
        self.send_button.clicked.connect(self.send_frame)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.status_label = QLabel("")
        self.frame_edit.textChanged.connect(self.status_label.clear)
        layout.addWidget(self.status_label)
        layout.addWidget(buttons)
        self.send_count = 0

    def send_frame(self) -> None:
        try:
            frame = self.frame_edit.text().strip()

            if not frame.startswith(":"):
                frame = ":" + frame
            if not frame.endswith(";"):
                frame += ";"

            self.connection.send(frame.encode("ascii"))
        except (ValueError, UnicodeError, ConnectionError, OSError) as error:
            if isinstance(error, (ConnectionError, OSError)):
                logger.error(
                    "Could not send GridConnect frame: %s",
                    error,
                    extra={
                        "fields": {
                            "layout": self.connection.layout_name,
                            "operation": "send_frame",
                        }
                    },
                )
            QMessageBox.warning(self, "Cannot send frame", str(error))
            return

        self.send_count += 1
        self.status_label.setText(f"Frame sent ({self.send_count})")
