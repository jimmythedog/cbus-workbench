from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QFrame, QLabel, QMainWindow

from .layout_view import LayoutView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("CBUS Workbench")
        self.resize(1000, 700)

        self.setCentralWidget(LayoutView())

        self.layout_status = QLabel("Home")
        self.connection_status = QLabel("Disconnected")

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.statusBar().addPermanentWidget(self.layout_status)
        self.statusBar().addPermanentWidget(separator)
        self.statusBar().addPermanentWidget(self.connection_status)

        layout_menu = self.menuBar().addMenu("Layout")
        layout_group = QActionGroup(self)
        layout_group.setExclusive(True)
        layout_group.triggered.connect(self.select_layout)

        for name in ("Home", "Test Layout"):
            action = QAction(name, self)
            action.setCheckable(True)
            layout_group.addAction(action)
            layout_menu.addAction(action)

            if name == "Home":
                action.setChecked(True)

    def select_layout(self, action):
        self.layout_status.setText(action.text())
