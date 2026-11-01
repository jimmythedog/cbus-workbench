import sys

from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from .layout_view import LayoutView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        if sys.platform == "linux":
            self.menuBar().setNativeMenuBar(False)

        self.setWindowTitle("CBUS Workbench")
        self.resize(1000, 700)

        self.layout_stack = QStackedWidget()
        self.layouts = {}

        for name in ("Home", "Test Layout"):
            view = LayoutView()
            self.layouts[name] = view
            self.layout_stack.addWidget(view)

        self.setCentralWidget(self.layout_stack)

        self.layout_status = QLabel("Home")
        self.connection_status = QLabel("Disconnected")

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

        self.rename_action = QAction("&Rename…", self)
        self.rename_action.triggered.connect(self.rename_layout)
        self.layout_menu.addAction(self.rename_action)

        self.delete_action = QAction("&Delete…", self)
        self.delete_action.triggered.connect(self.delete_layout)
        self.layout_menu.addAction(self.delete_action)

        self.layout_menu.addSeparator()

        for name in ("Home", "Test Layout"):
            action = QAction(name, self)
            action.setCheckable(True)
            self.layout_group.addAction(action)
            self.layout_menu.addAction(action)

            if name == "Home":
                action.setChecked(True)

    def update_layout_actions(self):
        enabled = bool(self.layouts)
        self.rename_action.setEnabled(enabled)
        self.delete_action.setEnabled(enabled)

    def select_layout(self, action):
        name = action.text()
        self.layout_stack.setCurrentWidget(self.layouts[name])
        self.layout_status.setText(name)

    def new_layout(self):
        name, accepted = QInputDialog.getText(
            self,
            "New layout",
            "Layout name:",
        )

        if not accepted:
            return

        name = name.strip()

        if not name:
            return

        if any(existing.casefold() == name.casefold() for existing in self.layouts):
            self.statusBar().showMessage("A layout with that name already exists", 5000)
            return

        view = LayoutView(empty=True)
        self.layouts[name] = view
        self.layout_stack.addWidget(view)

        action = QAction(name, self)
        action.setCheckable(True)
        self.layout_group.addAction(action)
        self.layout_menu.addAction(action)

        action.setChecked(True)
        self.select_layout(action)
        self.update_layout_actions()

        self.statusBar().showMessage(f"Layout '{name}' created", 5000)

    def rename_layout(self):
        action = self.layout_group.checkedAction()

        if action is None:
            return

        old_name = action.text()

        name, accepted = QInputDialog.getText(
            self,
            "Rename layout",
            "Layout name:",
            text=old_name,
        )

        if not accepted:
            return

        name = name.strip()

        if not name or name == old_name:
            return

        if any(
            existing.casefold() == name.casefold()
            for existing in self.layouts
            if existing != old_name
        ):
            self.statusBar().showMessage("A layout with that name already exists", 5000)
            return

        self.layouts[name] = self.layouts.pop(old_name)
        action.setText(name)
        self.layout_status.setText(name)

        self.statusBar().showMessage(f"Layout '{old_name}' renamed to '{name}'", 5000)

    def delete_layout(self):
        action = self.layout_group.checkedAction()

        if action is None:
            return

        name = action.text()

        answer = QMessageBox.question(
            self,
            "Delete layout",
            f"Delete layout '{name}' and all its nodes, events and backups?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        # Remove the layout and its menu action.
        view = self.layouts.pop(name)

        self.layout_group.removeAction(action)
        self.layout_menu.removeAction(action)
        action.deleteLater()

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

        self.statusBar().showMessage(f"Layout '{name}' deleted", 5000)
