from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)


class RawNodeVariables(QTableWidget):
    def __init__(self):
        super().__init__(0, 3)

        self.setHorizontalHeaderLabels(["NV", "Value", "Description"])
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)

        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.values = None
        self.itemChanged.connect(self.update_value)

    def show_node(self, node, values=None, descriptions=None):
        self.values = values if values is not None else node.nv_values
        self.descriptions = (
            descriptions if descriptions is not None else node.nv_descriptions
        )
        self.setRowCount(len(self.values))

        # setItem() emits itemChanged; rows must be complete before update_value runs.
        self.blockSignals(True)
        for row, (number, value) in enumerate(sorted(self.values.items())):
            number_item = QTableWidgetItem(str(number))
            number_item.setFlags(number_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 0, number_item)
            self.setItem(row, 1, QTableWidgetItem(str(value)))
            self.setItem(row, 2, QTableWidgetItem(self.descriptions.get(number, "")))
        self.blockSignals(False)

    def show_live_values(self, count: int | None, values: dict[int, int]) -> None:
        """Show confirmed live NVs; absent values within a known count stay unknown."""
        self.set_editing(False)
        self.values = None  # Live state must never be changed through this table.
        indices = range(1, count + 1) if count is not None else sorted(values)
        current = [self.item(row, 0).text() for row in range(self.rowCount())]
        rebuild = current != [str(index) for index in indices]

        self.blockSignals(True)
        if rebuild:
            self.setRowCount(len(indices))
        for row, index in enumerate(indices):
            if rebuild:
                number_item = QTableWidgetItem(str(index))
                number_item.setFlags(number_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.setItem(row, 0, number_item)
                self.setItem(row, 2, QTableWidgetItem(""))
            value = str(values[index]) if index in values else "-"
            item = self.item(row, 1)
            if item is None or item.text() != value:
                item = QTableWidgetItem(value)
                self.setItem(row, 1, item)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.blockSignals(False)

    def set_editing(self, editing):
        triggers = (
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            if editing
            else QTableWidget.EditTrigger.NoEditTriggers
        )
        self.setEditTriggers(triggers)

    def update_value(self, item):
        if self.values is None:
            return

        number = int(self.item(item.row(), 0).text())

        if item.column() == 2:
            self.descriptions[number] = item.text()
            return

        if item.column() == 1:
            try:
                value = int(item.text())
            except ValueError:
                value = -1

            if 0 <= value <= 255:
                self.values[number] = value
            else:
                item.setText(str(self.values[number]))


class GlobalSettings(QWidget):
    def __init__(self):
        super().__init__()

        self.values = None

        layout = QFormLayout(self)
        layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        mode = QComboBox()
        mode.addItems(["Normal", "Advanced", "Diagnostic"])

        self.startup_delay = QSpinBox()
        self.startup_delay.setRange(0, 255)
        self.startup_delay.setSuffix(" seconds")
        self.startup_delay.valueChanged.connect(self.update_startup_delay)

        diagnostics = QCheckBox()
        diagnostics.setChecked(True)

        layout.addRow("Module mode:", mode)
        layout.addRow("Startup delay:", self.startup_delay)
        layout.addRow("Enable diagnostics:", diagnostics)

        self.node = None

    def show_node(self, node, values=None):
        self.node = node
        self.values = values if values is not None else node.nv_values

        self.startup_delay.blockSignals(True)
        self.startup_delay.setValue(self.values.get(2, 0))
        self.startup_delay.blockSignals(False)

    def update_startup_delay(self, value):
        if self.values is not None:
            self.values[2] = value


class ChannelSettings(QWidget):
    def __init__(self):
        super().__init__()

        layout = QFormLayout(self)
        layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        mode = QComboBox()
        mode.addItems(["Input", "Output", "Servo"])
        layout.addRow("I/O type:", mode)

        on_delay = QSpinBox()
        on_delay.setRange(0, 255)
        on_delay.setSuffix(" ms")
        layout.addRow("ON delay:", on_delay)

        off_delay = QSpinBox()
        off_delay.setRange(0, 255)
        off_delay.setSuffix(" ms")
        layout.addRow("OFF delay:", off_delay)

        invert = QCheckBox()
        layout.addRow("Invert output:", invert)

        pulse_duration = QSpinBox()
        pulse_duration.setRange(0, 255)
        pulse_duration.setSuffix(" ms")
        layout.addRow("Pulse duration:", pulse_duration)

        on_position = QSpinBox()
        on_position.setRange(0, 255)
        layout.addRow("ON position:", on_position)

        off_position = QSpinBox()
        off_position.setRange(0, 255)
        layout.addRow("OFF position:", off_position)

        def update_mode(index):
            layout.setRowVisible(on_delay, index == 0)
            layout.setRowVisible(off_delay, index == 0)

            layout.setRowVisible(invert, index == 1)
            layout.setRowVisible(pulse_duration, index == 1)

            layout.setRowVisible(on_position, index == 2)
            layout.setRowVisible(off_position, index == 2)

        mode.currentIndexChanged.connect(update_mode)
        update_mode(mode.currentIndex())


class MdfNodeVariables(QSplitter):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)

        self.node = None
        self.values = None

        self.global_settings = GlobalSettings()
        self.channel_settings = ChannelSettings()

        navigation = QListWidget()
        pages = QStackedWidget()
        self.raw_values = RawNodeVariables()

        sections = [
            ("Raw Values", self.raw_values),
            ("Globals", self.global_settings),
            ("Channel 1", self.channel_settings),
            ("Channel 2", QLabel("Channel 2 settings will go here")),
        ]

        for name, page in sections:
            navigation.addItem(name)
            pages.addWidget(page)

        navigation.currentRowChanged.connect(pages.setCurrentIndex)
        navigation.currentRowChanged.connect(self.refresh_raw_values)
        navigation.setCurrentRow(0)

        self.addWidget(navigation)
        self.addWidget(pages)
        self.setSizes([200, 800])

    def show_node(self, node, values=None, descriptions=None):
        self.node = node
        self.values = values if values is not None else node.nv_values
        self.descriptions = (
            descriptions if descriptions is not None else node.nv_descriptions
        )

        self.raw_values.show_node(node, self.values, self.descriptions)
        self.global_settings.show_node(node, self.values)

    def refresh_raw_values(self, index):
        if self.node is None:
            return

        if index == 0:
            self.raw_values.show_node(self.node, self.values, self.descriptions)
        elif index == 1:
            self.global_settings.show_node(self.node, self.values)

    def set_editing(self, editing):
        self.global_settings.setEnabled(editing)
        self.channel_settings.setEnabled(editing)
        self.raw_values.set_editing(editing)
