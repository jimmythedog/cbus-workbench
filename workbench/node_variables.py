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

    def show_node(self, node):
        self.setRowCount(len(node.nv_values))

        for row, (number, value) in enumerate(sorted(node.nv_values.items())):
            self.setItem(row, 0, QTableWidgetItem(str(number)))
            self.setItem(row, 1, QTableWidgetItem(str(value)))
            self.setItem(row, 2, QTableWidgetItem(""))


class GlobalSettings(QWidget):
    def __init__(self):
        super().__init__()

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

    def show_node(self, node):
        self.node = node
        self.startup_delay.setValue(node.nv_values.get(2, 0))

    def update_startup_delay(self, value):
        if self.node is not None:
            self.node.nv_values[2] = value


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

        self.global_settings = GlobalSettings()

        navigation = QListWidget()
        pages = QStackedWidget()
        self.raw_values = RawNodeVariables()

        sections = [
            ("Raw Values", self.raw_values),
            ("Globals", self.global_settings),
            ("Channel 1", ChannelSettings()),
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

    def show_node(self, node):
        self.raw_values.show_node(node)
        self.global_settings.show_node(node)

    def refresh_raw_values(self, index):
        if index == 0 and self.global_settings.node is not None:
            self.raw_values.show_node(self.global_settings.node)
