"""Construction of the node identity and details form."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .parameter_names import (
    cpu_name,
    firmware_version,
    manufacturer_name,
    module_name,
    transport_name,
    vlcb_compatible,
)


class NodeDetailsForm(QWidget):
    """The details tab's form and its display labels."""

    def __init__(self):
        super().__init__()

        self.group = QWidget()
        form = QFormLayout(self.group)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        # Preserve font-based row heights when the viewport is shorter than the form.
        form.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        self.node_number = QLabel("-")
        self.node_name = QLabel("-")
        self.node_name.setTextFormat(Qt.TextFormat.PlainText)
        self.can_id = QLabel("-")
        self.module_type = QLabel("-")
        self.firmware = QLabel("-")
        self.status = QLabel("-")
        self.manufacturer = QLabel("-")
        self.module_identifier = QLabel("-")
        self.node_mode = QLabel("-")
        self.vlcb = QLabel("-")
        self.nv_count = QLabel("-")
        self.event_count = QLabel("-")
        self.ev_count = QLabel("-")
        self.cpu_name = QLabel("-")
        self.interface = QLabel("-")
        self.module_descriptor = QLabel("None")
        self.producer = QLabel("-")
        self.consumer = QLabel("-")
        self.consumes_own_events = QLabel("-")
        self.supports_bootloading = QLabel("-")
        self.stored_events = QLabel("-")

        # Identity
        form.addRow("Name:", self.node_name)
        form.addRow("Node number:", self.node_number)
        form.addRow("Status:", self.status)

        # Module
        form.addRow("Manufacturer:", self.manufacturer)
        form.addRow("Module type:", self.module_type)
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
        form.addRow("CAN ID:", self.can_id)

        # Definition
        form.addRow("Module descriptor:", self.module_descriptor)

        details_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.group)
        details_layout.addWidget(scroll, 1)

    def show_module_identifier(
        self, manufacturer: int | None, module_type: int | None
    ) -> None:
        """Use only confirmed identity bytes, never module names or descriptors."""
        confirmed = (
            manufacturer is not None
            and module_type is not None
            and 0 <= manufacturer <= 255
            and 0 <= module_type <= 255
        )
        self.module_identifier.setText(
            f"{manufacturer:02X}{module_type:02X}" if confirmed else "-"
        )

    def show_can_id(self, visible: bool) -> None:
        """Hide the whole form row, including its caption and spacing."""
        self.group.layout().setRowVisible(self.can_id, visible)

    def show_node_name(self, node) -> None:
        self.node_name.setText((node.name or "-") if node else "-")

    def show_module_descriptor(self, text: str = "None", tooltip: str = "") -> None:
        """Display the navigator's lookup result without interpreting MDF identity."""
        self.module_descriptor.setText(text)
        self.module_descriptor.setToolTip(tooltip)

    def show_no_node(self) -> None:
        for label in (
            self.node_number,
            self.node_name,
            self.can_id,
            self.module_type,
            self.firmware,
            self.status,
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
        ):
            label.setText("-")
        self.show_module_descriptor()

    def show_live_identity(self, node, mode: str) -> None:
        self.node_number.setText(str(node.node_number))
        self.node_name.setText("-")
        self.can_id.setText("-")
        self.module_type.setText("-")
        self.firmware.setText("-")
        self.status.setText("-")
        self.manufacturer.setText("-")
        self.show_module_identifier(None, None)
        self.node_mode.setText(mode)
        for enabled, label in (
            (node.is_producer, self.producer),
            (node.is_consumer, self.consumer),
            (node.consumes_own_events, self.consumes_own_events),
            (node.supports_bootloading, self.supports_bootloading),
        ):
            label.setText("Yes" if enabled else "No")
        for label in (
            self.vlcb,
            self.nv_count,
            self.stored_events,
            self.event_count,
            self.ev_count,
            self.cpu_name,
            self.interface,
        ):
            label.setText("-")
        self.show_module_descriptor()

    def show_configured_node(self, node) -> None:
        self.node_number.setText(str(node.number))
        self.can_id.setText("-")
        self.module_type.setText("CANMIO")
        self.firmware.setText("3d")
        self.status.setText("-")
        self.manufacturer.setText("MERG")
        self.module_identifier.setText("-")
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
        self.show_module_descriptor()

    def show_parameters(self, parameters: dict[int, int]) -> str:
        """Display confirmed PARAN values and return the formatted firmware."""
        manufacturer = parameters.get(1)
        module_type = parameters.get(3)
        self.manufacturer.setText(
            manufacturer_name(manufacturer) if manufacturer is not None else "-"
        )
        self.module_type.setText(module_name(manufacturer, module_type))
        self.show_module_identifier(manufacturer, module_type)
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
