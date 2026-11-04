"""Construction of the node identity and details form."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .parameter_names import cpu_name, firmware_version, transport_name, vlcb_compatible


class NodeDetailsForm(QWidget):
    """The details tab's form and its display labels."""

    def __init__(self):
        super().__init__()

        self.group = QWidget()
        form = QFormLayout(self.group)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.node_number = QLabel("-")
        self.node_name = QLabel("-")
        self.node_name_editor = QLineEdit()
        self.node_name_stack = QStackedWidget()
        # The stack must not absorb the form's spare vertical space.
        name_policy = self.node_name_stack.sizePolicy()
        name_policy.setVerticalPolicy(QSizePolicy.Policy.Maximum)
        self.node_name_stack.setSizePolicy(name_policy)
        self.node_name_stack.addWidget(self.node_name)
        self.node_name_stack.addWidget(self.node_name_editor)
        self.can_id = QLabel("-")
        self.module_type = QLabel("-")
        self.firmware = QLabel("-")
        self.status = QLabel("-")
        self.manufacturer = QLabel("-")
        self.flags = QLabel("-")
        self.module_identifier = QLabel("-")
        self.node_mode = QLabel("-")
        self.vlcb = QLabel("-")
        self.nv_count = QLabel("-")
        self.event_count = QLabel("-")
        self.ev_count = QLabel("-")
        self.cpu_name = QLabel("-")
        self.interface = QLabel("-")
        self.module_descriptor = QLabel("-")
        self.producer = QLabel("-")
        self.consumer = QLabel("-")
        self.consumes_own_events = QLabel("-")
        self.supports_bootloading = QLabel("-")
        self.stored_events = QLabel("-")

        # Identity
        form.addRow("Name:", self.node_name_stack)
        form.addRow("Node number:", self.node_number)
        form.addRow("CAN ID:", self.can_id)
        form.addRow("Status:", self.status)

        # Module
        form.addRow("Manufacturer:", self.manufacturer)
        form.addRow("Module type:", self.module_type)
        form.addRow("Flags:", self.flags)
        form.addRow("Module identifier:", self.module_identifier)
        form.addRow("Firmware:", self.firmware)

        # Capabilities
        form.addRow("Node mode:", self.node_mode)
        form.addRow("VLCB:", self.vlcb)
        form.addRow("Producer:", self.producer)
        form.addRow("Consumer:", self.consumer)
        form.addRow("Consumes own events:", self.consumes_own_events)
        form.addRow("Supports bootloading:", self.supports_bootloading)
        form.addRow("Node variables:", self.nv_count)
        form.addRow("Events currently stored:", self.stored_events)
        form.addRow("Events supported:", self.event_count)
        form.addRow("Event variables:", self.ev_count)

        # Hardware
        form.addRow("CPU name:", self.cpu_name)
        form.addRow("Interface:", self.interface)

        # Definition
        form.addRow("Module descriptor:", self.module_descriptor)

        details_layout = QVBoxLayout(self)
        details_layout.addWidget(self.group, 1)

    def show_node_name(self, node) -> None:
        self.node_name.setText((node.name or "-") if node else "-")

    def show_no_node(self) -> None:
        for label in (
            self.node_number,
            self.node_name,
            self.can_id,
            self.module_type,
            self.firmware,
            self.status,
            self.flags,
            self.manufacturer,
            self.module_identifier,
            self.node_mode,
            self.vlcb,
            self.producer,
            self.consumer,
            self.consumes_own_events,
            self.supports_bootloading,
            self.nv_count,
            self.stored_events,
            self.event_count,
            self.ev_count,
            self.cpu_name,
            self.interface,
            self.module_descriptor,
        ):
            label.setText("-")

    def show_live_identity(self, node, mode: str) -> None:
        self.node_number.setText(str(node.node_number))
        self.node_name.setText("-")
        self.can_id.setText("-")
        self.module_type.setText(str(node.module_type))
        self.firmware.setText("-")
        self.status.setText("-")
        self.manufacturer.setText(str(node.manufacturer))
        self.flags.setText(f"0x{node.flags:02X}")
        self.node_mode.setText(mode)
        for enabled, label in (
            (node.is_producer, self.producer),
            (node.is_consumer, self.consumer),
            (node.consumes_own_events, self.consumes_own_events),
            (node.supports_bootloading, self.supports_bootloading),
        ):
            label.setText("Yes" if enabled else "No")
        for label in (
            self.module_identifier,
            self.vlcb,
            self.nv_count,
            self.stored_events,
            self.event_count,
            self.ev_count,
            self.cpu_name,
            self.interface,
            self.module_descriptor,
        ):
            label.setText("-")

    def show_configured_node(self, node) -> None:
        self.node_number.setText(str(node.number))
        self.can_id.setText("-")
        self.module_type.setText("CANMIO")
        self.flags.setText("-")
        self.firmware.setText("3d")
        self.status.setText("-")
        self.manufacturer.setText("MERG")
        self.module_identifier.setText("A520")
        self.node_mode.setText("FLiM")
        self.vlcb.setText("No")
        self.producer.setText("Yes")
        self.consumer.setText("Yes")
        self.consumes_own_events.setText("Yes")
        self.supports_bootloading.setText("Yes")
        self.nv_count.setText("127")
        self.stored_events.setText(str(len(node.consumed_events)))
        self.event_count.setText("255")
        self.ev_count.setText("20")
        self.cpu_name.setText("P18F25K80")
        self.interface.setText("CAN")
        self.module_descriptor.setText("CANMIO-A520-3d.json (System definitions)")

    def show_parameters(self, parameters: dict[int, int]) -> str:
        """Display confirmed PARAN values and return the formatted firmware."""
        vlcb = vlcb_compatible(parameters.get(8))
        self.vlcb.setText("-" if vlcb is None else "Yes" if vlcb else "No")
        firmware = firmware_version(parameters) or "-"
        self.firmware.setText(firmware)
        self.interface.setText(transport_name(parameters.get(10)) or "-")
        self.cpu_name.setText(cpu_name(parameters.get(19), parameters.get(9)) or "-")
        for index, label in (
            (4, self.event_count),
            (5, self.ev_count),
            (6, self.nv_count),
        ):
            label.setText(str(parameters[index]) if index in parameters else "-")
        return firmware
