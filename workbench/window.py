import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from .diagnostics import Diagnostics
from .layout_settings import LayoutSettingsDialog
from .layout_view import LayoutView


class ConnectionStatusLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        if sys.platform == "linux":
            self.menuBar().setNativeMenuBar(False)

        self.setWindowTitle("CBUS Workbench")
        self.resize(1000, 700)

        self.layout_stack = QStackedWidget()
        self.layouts = {}
        self.layout_settings = {}

        for name in ("Home", "Test Layout"):
            view = LayoutView()
            self.layouts[name] = view
            self.layout_stack.addWidget(view)

            self.layout_settings[name] = {
                "name": name,
                "logical_layout": name.lower().replace(" ", "-"),
                "connection_type": "TCP/IP",
                "host": "",
                "port": 5550,
                "serial_port": "",
            }

        self.setCentralWidget(self.layout_stack)

        self.layout_status = QLabel("Home")
        self.connection_status = ConnectionStatusLabel("Disconnected")
        self.connection_status.setToolTip("Double-click to connect or disconnect")
        self.connection_status.double_clicked.connect(self.toggle_connection)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.statusBar().addPermanentWidget(self.layout_status)
        self.statusBar().addPermanentWidget(separator)
        self.statusBar().addPermanentWidget(self.connection_status)

        file_menu = self.menuBar().addMenu("&File")
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.layout_menu = self.menuBar().addMenu("&Layout")
        self.layout_group = QActionGroup(self)
        self.layout_group.setExclusive(True)
        self.layout_group.triggered.connect(self.select_layout)

        new_action = QAction("&New…", self)
        new_action.triggered.connect(self.new_layout)
        self.layout_menu.addAction(new_action)

        self.edit_action = QAction("&Edit…", self)
        self.edit_action.triggered.connect(self.edit_layout)
        self.layout_menu.addAction(self.edit_action)

        self.delete_action = QAction("&Delete…", self)
        self.delete_action.triggered.connect(self.delete_layout)
        self.layout_menu.addAction(self.delete_action)

        self.layout_menu.addSeparator()

        self.connect_action = QAction("&Connect", self)
        self.connect_action.triggered.connect(
            lambda: self.set_connection_state("Connected")
        )
        self.layout_menu.addAction(self.connect_action)

        self.disconnect_action = QAction("&Disconnect", self)
        self.disconnect_action.triggered.connect(
            lambda: self.set_connection_state("Disconnected")
        )
        self.layout_menu.addAction(self.disconnect_action)

        self.layout_menu.addSeparator()

        for name in ("Home", "Test Layout"):
            action = QAction(name, self)
            action.setCheckable(True)
            self.layout_group.addAction(action)
            self.layout_menu.addAction(action)

            if name == "Home":
                action.setChecked(True)

        self.connection_states = {name: "Disconnected" for name in self.layouts}

        self.diagnostics_dock = QDockWidget("Messages / Diagnostics", self)
        self.diagnostics_dock.setObjectName("DiagnosticsDock")
        self.diagnostics_dock.setWidget(Diagnostics())

        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea,
            self.diagnostics_dock,
        )

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.diagnostics_dock.toggleViewAction())

        help_menu = self.menuBar().addMenu("&Help")

        about_action = QAction("&About CBUS Workbench…", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        self.update_connection_actions()
        self.update_layout_actions()

    def set_connection_state(self, state):
        action = self.layout_group.checkedAction()

        if action is None:
            return

        name = action.text()
        self.connection_states[name] = state
        self.update_connection_actions()

        self.statusBar().showMessage(
            f"Layout '{name}': {state.lower()} (simulated)", 5000
        )

    def update_connection_actions(self):
        action = self.layout_group.checkedAction()

        if action is None:
            self.connect_action.setEnabled(False)
            self.disconnect_action.setEnabled(False)
            self.connection_status.setText("Disconnected")
            return

        state = self.connection_states[action.text()]

        self.connect_action.setEnabled(state in ("Disconnected", "Error"))
        self.disconnect_action.setEnabled(state in ("Connected", "Connecting"))
        self.connection_status.setText(state)

    def update_layout_actions(self):
        enabled = bool(self.layouts)
        self.edit_action.setEnabled(enabled)
        self.delete_action.setEnabled(enabled)

    def select_layout(self, action):
        name = action.text()
        self.layout_stack.setCurrentWidget(self.layouts[name])
        self.layout_status.setText(name)
        self.update_connection_actions()

    def validate_layout_settings(self, settings, current_name=None):
        name = settings["name"]

        if not name or not settings["logical_layout"]:
            self.statusBar().showMessage(
                "Layout name and logical layout are required", 5000
            )
            return False

        if any(
            existing.casefold() == name.casefold()
            for existing in self.layouts
            if existing != current_name
        ):
            self.statusBar().showMessage("A layout with that name already exists", 5000)
            return False

        return True

    def new_layout(self):
        dialog = LayoutSettingsDialog(
            self,
            logical_layouts=sorted(
                {
                    settings["logical_layout"]
                    for settings in self.layout_settings.values()
                }
            ),
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        settings = dialog.settings()
        name = settings["name"]

        if not self.validate_layout_settings(settings):
            return

        view = LayoutView(empty=True)
        self.layouts[name] = view
        self.layout_settings[name] = settings
        self.layout_stack.addWidget(view)

        action = QAction(name, self)
        action.setCheckable(True)
        self.layout_group.addAction(action)
        self.layout_menu.addAction(action)

        action.setChecked(True)
        self.connection_states[name] = "Disconnected"
        self.select_layout(action)
        self.update_layout_actions()

        self.statusBar().showMessage(f"Layout '{name}' created", 5000)

    def edit_layout(self):
        action = self.layout_group.checkedAction()

        if action is None:
            return

        old_name = action.text()
        current = self.layout_settings[old_name]

        dialog = LayoutSettingsDialog(
            self,
            **current,
            logical_layouts=sorted(
                {
                    settings["logical_layout"]
                    for settings in self.layout_settings.values()
                }
            ),
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        settings = dialog.settings()
        name = settings["name"]

        if not self.validate_layout_settings(settings, old_name):
            return

        if name != old_name:
            self.layouts[name] = self.layouts.pop(old_name)
            self.connection_states[name] = self.connection_states.pop(old_name)
            action.setText(name)
            self.layout_status.setText(name)

        del self.layout_settings[old_name]
        self.layout_settings[name] = settings

        self.statusBar().showMessage(f"Layout '{name}' updated", 5000)

    def delete_layout(self):
        action = self.layout_group.checkedAction()

        if action is None:
            return

        name = action.text()

        answer = QMessageBox.question(
            self,
            "Delete layout",
            f"Delete layout '{name}'? Its logical layout data will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        # Remove the layout and its menu action.
        view = self.layouts.pop(name)
        del self.layout_settings[name]
        del self.connection_states[name]

        self.layout_group.removeAction(action)
        self.layout_menu.removeAction(action)
        action.deleteLater()

        # removeWidget keeps the page parented; deleteLater frees it on event loop return.
        self.layout_stack.removeWidget(view)
        view.deleteLater()

        # Select another layout, if one remains.
        if self.layouts:
            next_name = next(iter(self.layouts))

            for remaining_action in self.layout_group.actions():
                if remaining_action.text() == next_name:
                    remaining_action.setChecked(True)
                    self.select_layout(remaining_action)
                    break
        else:
            self.layout_status.setText("No layout")

        self.update_layout_actions()
        self.update_connection_actions()

        self.statusBar().showMessage(f"Layout '{name}' deleted", 5000)

    def toggle_connection(self):
        action = self.layout_group.checkedAction()

        if action is None:
            return

        state = self.connection_states[action.text()]

        if state in ("Disconnected", "Error"):
            self.set_connection_state("Connected")
        elif state in ("Connected", "Connecting"):
            self.set_connection_state("Disconnected")

    def show_about(self):
        QMessageBox.about(
            self,
            "About CBUS Workbench",
            "<h3>CBUS Workbench</h3>"
            "<p>A desktop application for configuring and managing "
            "CBUS/VLCB model railway networks.</p>"
            "<p>Built with Python and PySide6.</p>",
        )
