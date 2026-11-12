import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLayout,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)

from .app_settings import validate_layout_input
from .logging_config import trace

logger = logging.getLogger("workbench.layouts")


def collect_layout_settings(
    parent,
    layouts: dict,
    initial: dict | None = None,
    *,
    allow_auto_connect=True,
    allow_existing=False,
) -> dict | None:
    """Collect and validate settings without saving a layout or annotations."""
    dialog = LayoutSettingsDialog(
        parent,
        logical_layouts=sorted({value["logical_layout"] for value in layouts.values()}),
        **(initial or {}),
    )
    if not allow_auto_connect:
        dialog.auto_connect_check.setEnabled(False)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        trace(logger, "Layout settings cancelled")
        return None
    settings = dialog.settings()
    current_name = (
        next(
            (
                name
                for name in layouts
                if name.casefold() == settings["name"].casefold()
            ),
            None,
        )
        if allow_existing
        else None
    )
    if not allow_auto_connect and current_name is None:
        settings["auto_connect"] = False
    validate_layout_input(settings, layouts, current_name)
    if current_name is not None:
        settings["name"] = current_name
    trace(
        logger,
        "Layout settings collected name=%s id=%s",
        settings["name"],
        settings["logical_layout"],
    )
    return settings


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
        node_poll_seconds=10,
        connection_active=False,
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

        self.node_poll_spin = QSpinBox()
        self.node_poll_spin.setRange(0, 300)
        self.node_poll_spin.setSingleStep(5)
        self.node_poll_spin.setValue(node_poll_seconds)
        self.node_poll_spin.setToolTip(
            "Seconds between node reachability checks. Zero disables periodic polling."
        )

        # QLineEdit's default hint fits only a short string. Give names and
        # endpoints room for a full hostname, measured in the current font rather
        # than fixed pixels. minimumSizeHint includes the field's frame/margins.
        for field in (self.name_edit, self.host_edit, self.serial_port_edit):
            field.setSizePolicy(
                QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed
            )
            field.setMinimumWidth(
                field.fontMetrics().horizontalAdvance(
                    "my-railway-gridconnect-hub.example.com"
                )
                + field.minimumSizeHint().width()
            )

        layout_form = QFormLayout()
        layout_form.addRow("Name:", self.name_edit)
        layout_form.addRow("Logical layout:", self.logical_layout_combo)
        self.auto_connect_check = QCheckBox("Auto-connect on startup")
        self.auto_connect_check.setChecked(auto_connect)
        layout_form.addRow(self.auto_connect_check)

        connection_group = QGroupBox("Connection")
        self.connection_form = QFormLayout(connection_group)
        self.connection_form.addRow("Type:", self.connection_type_combo)
        self.connection_form.addRow("Host:", self.host_edit)
        self.connection_form.addRow("Port:", self.port_spin)
        self.connection_form.addRow("Port:", self.serial_port_edit)
        self.connection_form.addRow("CAN ID:", self.can_id_spin)

        advanced_group = QGroupBox("Advanced")
        advanced_form = QFormLayout(advanced_group)
        advanced_form.addRow("Node polling (seconds):", self.node_poll_spin)
        for form in (layout_form, self.connection_form, advanced_form):
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
            )

        if connection_active:
            # Only the polling interval can change while the transport is active.
            for field in (
                self.name_edit,
                self.logical_layout_combo,
                self.auto_connect_check,
                self.connection_type_combo,
                self.host_edit,
                self.port_spin,
                self.serial_port_edit,
                self.can_id_spin,
            ):
                field.setEnabled(False)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        main_layout = QVBoxLayout(self)
        main_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        main_layout.addLayout(layout_form)
        main_layout.addWidget(connection_group)
        main_layout.addWidget(advanced_group)
        main_layout.addStretch()
        main_layout.addWidget(buttons)

        self.connection_type_combo.currentTextChanged.connect(
            self.update_connection_fields
        )
        self.update_connection_fields(connection_type)

    def update_connection_fields(self, connection_type):
        # Unlike a stack, hidden form rows contribute neither height nor spacing.
        tcp = connection_type == "TCP/IP"
        self.connection_form.setRowVisible(self.host_edit, tcp)
        self.connection_form.setRowVisible(self.port_spin, tcp)
        self.connection_form.setRowVisible(self.serial_port_edit, not tcp)
        self.adjustSize()

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
            "node_poll_seconds": self.node_poll_spin.value(),
        }
