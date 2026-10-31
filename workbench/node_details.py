from copy import deepcopy
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedLayout,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .backup_compare import BackupCompare
from .backup_view import BackupView, backup_contents
from .node_backups import NodeBackups
from .node_events import NodeEvents
from .node_snapshot import create_node_snapshot
from .node_variables import MdfNodeVariables, RawNodeVariables

DEFAULT_NODE_TITLE = "Node details"


class NodeDetails(QWidget):
    editing_changed = Signal(bool)

    def __init__(self, events):
        super().__init__()

        self.node = None
        self.editing_values = None
        self.editing_descriptions = None

        layout = QVBoxLayout(self)

        self.group = QGroupBox(DEFAULT_NODE_TITLE)
        form = QFormLayout(self.group)

        self.node_number = QLabel("-")
        self.can_id = QLabel("-")
        self.module_type = QLabel("-")
        self.firmware = QLabel("-")
        self.status = QLabel("-")

        form.addRow("Node number:", self.node_number)
        form.addRow("CAN ID:", self.can_id)
        form.addRow("Module type:", self.module_type)
        form.addRow("Firmware:", self.firmware)
        form.addRow("Status:", self.status)

        layout.addWidget(self.group)

        self.tabs = QTabWidget()
        self.raw_values = RawNodeVariables()
        self.mdf_values = MdfNodeVariables()
        self.mdf_values.set_editing(False)

        self.variables = QStackedWidget()
        self.variables.addWidget(self.raw_values)
        self.variables.addWidget(self.mdf_values)

        self.variables_page = QWidget()
        variables_layout = QVBoxLayout(self.variables_page)

        buttons = QStackedLayout()

        self.edit_button = QPushButton("Edit")
        self.edit_button.setEnabled(False)
        self.edit_button.clicked.connect(self.start_editing)

        view_buttons = QWidget()
        view_layout = QHBoxLayout(view_buttons)
        view_layout.addStretch()
        view_layout.addWidget(self.edit_button)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_editing)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_editing)

        edit_buttons = QWidget()
        edit_layout = QHBoxLayout(edit_buttons)
        edit_layout.addStretch()
        edit_layout.addWidget(self.save_button)
        edit_layout.addWidget(self.cancel_button)

        buttons.addWidget(view_buttons)
        buttons.addWidget(edit_buttons)

        self.buttons = buttons

        # Node Variables page
        variables_layout.addWidget(self.variables, 1)

        variables_actions = QWidget()
        variables_actions.setLayout(buttons)

        # Events action buttons
        events_actions = QWidget()
        events_layout = QHBoxLayout(events_actions)

        events_buttons = QStackedLayout()

        self.events_edit_button = QPushButton("Edit")
        self.events_edit_button.setEnabled(False)
        self.events_edit_button.clicked.connect(self.start_events_editing)

        view_buttons = QWidget()
        view_layout = QHBoxLayout(view_buttons)
        view_layout.addStretch()
        view_layout.addWidget(self.events_edit_button)

        self.events_save_button = QPushButton("Save")
        self.events_save_button.clicked.connect(self.save_events_editing)

        self.events_cancel_button = QPushButton("Cancel")
        self.events_cancel_button.clicked.connect(self.cancel_events_editing)

        edit_buttons = QWidget()
        edit_layout = QHBoxLayout(edit_buttons)
        edit_layout.addStretch()
        edit_layout.addWidget(self.events_save_button)
        edit_layout.addWidget(self.events_cancel_button)

        events_buttons.addWidget(view_buttons)
        events_buttons.addWidget(edit_buttons)

        self.events_buttons = events_buttons
        events_layout.addLayout(events_buttons)

        # Tabs
        self.tabs.addTab(self.variables_page, "Node Variables")

        self.node_events = NodeEvents(events)
        self.tabs.addTab(self.node_events, "Events")

        self.node_backups = NodeBackups()
        self.node_backups.itemSelectionChanged.connect(self.update_backup_buttons)
        self.tabs.addTab(self.node_backups, "Backups")

        # Shared bottom action area
        self.action_area = QStackedWidget()
        self.action_area.addWidget(variables_actions)
        self.action_area.addWidget(events_actions)

        # Backups action buttons
        backups_actions = QWidget()
        backups_layout = QHBoxLayout(backups_actions)
        backups_layout.addStretch()

        self.backup_buttons = {}

        for name in ("New", "View", "Compare", "Restore", "Delete"):
            button = QPushButton(name)
            button.setEnabled(False)
            backups_layout.addWidget(button)
            self.backup_buttons[name] = button

        self.backup_buttons["View"].clicked.connect(self.view_backup)
        self.backup_buttons["Compare"].clicked.connect(self.compare_backup)
        self.backup_buttons["New"].clicked.connect(self.new_backup)
        self.backup_buttons["Restore"].clicked.connect(self.restore_backup)
        self.backup_buttons["Delete"].clicked.connect(self.delete_backup)

        self.action_area.addWidget(backups_actions)

        self.tabs.currentChanged.connect(self.action_area.setCurrentIndex)

        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.action_area)

    def save_editing(self):
        self.node.nv_values = self.editing_values
        self.editing_values = None

        self.node.nv_descriptions = self.editing_descriptions
        self.editing_descriptions = None

        self.stop_editing()

    def cancel_editing(self):
        self.editing_values = None
        self.editing_descriptions = None
        self.stop_editing()

    def start_editing(self):
        self.set_editing(True)
        self.editing_changed.emit(True)
        self.editing_values = self.node.nv_values.copy()
        self.editing_descriptions = self.node.nv_descriptions.copy()
        self.raw_values.show_node(
            self.node, self.editing_values, self.editing_descriptions
        )
        self.mdf_values.show_node(
            self.node, self.editing_values, self.editing_descriptions
        )
        self.raw_values.set_editing(True)
        self.mdf_values.set_editing(True)
        self.buttons.setCurrentIndex(1)

    def stop_editing(self):
        self.raw_values.set_editing(False)
        self.raw_values.show_node(self.node)

        self.mdf_values.set_editing(False)
        self.mdf_values.show_node(self.node)

        self.buttons.setCurrentIndex(0)
        self.set_editing(False)
        self.editing_changed.emit(False)

    def set_editing(self, editing):
        self.tabs.setTabEnabled(1, not editing)  # Events
        self.tabs.setTabEnabled(2, not editing)  # Backups

    def start_events_editing(self):
        self.node_events.begin_edit()
        self.events_buttons.setCurrentIndex(1)

        self.tabs.setTabEnabled(0, False)  # Node Variables
        self.tabs.setTabEnabled(2, False)  # Backups
        self.editing_changed.emit(True)

    def cancel_events_editing(self):
        self.node_events.cancel_edit()
        self.finish_events_editing()

    def finish_events_editing(self):
        self.events_buttons.setCurrentIndex(0)
        self.tabs.setTabEnabled(0, True)
        self.tabs.setTabEnabled(2, True)
        self.editing_changed.emit(False)

    def save_events_editing(self):
        self.node_events.save_edit()
        self.finish_events_editing()

    def show_node(self, current):
        self.node = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.node_events.show_node(self.node)
        self.node_backups.show_node(self.node)
        self.backup_buttons["New"].setEnabled(self.node is not None)
        self.update_backup_buttons()

        enabled = current is not None
        self.edit_button.setEnabled(enabled)
        self.events_edit_button.setEnabled(enabled)

        if current is None:
            self.group.setTitle(DEFAULT_NODE_TITLE)
            self.node_number.setText("-")
            self.can_id.setText("-")
            self.module_type.setText("-")
            self.firmware.setText("-")
            self.status.setText("-")
            self.variables.setCurrentIndex(0)
            return

        node = current.data(Qt.ItemDataRole.UserRole)

        self.raw_values.show_node(node)
        self.mdf_values.show_node(node)

        number = node.number
        has_mdf = node.has_mdf

        self.variables.setCurrentIndex(1 if has_mdf else 0)
        self.group.setTitle(f"Node {number} — CANMIO")
        self.node_number.setText(str(number))
        self.can_id.setText("126")
        self.module_type.setText("CANMIO")
        self.firmware.setText("3d")
        self.status.setText("Online")

    def update_backup_buttons(self):
        selected = bool(self.node_backups.selectedItems())

        for name, button in self.backup_buttons.items():
            if name != "New":
                button.setEnabled(selected)

    def view_backup(self):
        if self.node is None:
            return

        selected = self.node_backups.selectedItems()
        if not selected:
            return

        backup = selected[0].data(0, Qt.ItemDataRole.UserRole)

        dialog = BackupView(self.node, backup, self)
        dialog.exec()

    def compare_backup(self):
        if self.node is None:
            return

        selected = self.node_backups.selectedItems()
        if not selected:
            return

        backup = selected[0].data(0, Qt.ItemDataRole.UserRole)

        dialog = BackupCompare(self.node, backup, self)
        dialog.exec()

    def new_backup(self):
        if self.node is None:
            return

        description, accepted = QInputDialog.getText(
            self,
            "New node backup",
            "Description (optional):",
        )

        if not accepted:
            return

        backup = create_node_snapshot(self.node)
        backup["created"] = datetime.now().strftime("%d %b %Y, %H:%M")
        backup["description"] = description.strip()

        self.node_backups.add_backup(self.node, backup)

        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage("Node backup created", 5000)

    def restore_backup(self):
        if self.node is None:
            return

        selected = self.node_backups.selectedItems()
        if not selected:
            return

        backup = selected[0].data(0, Qt.ItemDataRole.UserRole)

        is_layout_backup = (
            backup.get("partOfLayoutBackup", False)
            or backup.get("description") == "Layout backup"
        )

        if is_layout_backup:
            message = (
                "This backup is part of a layout backup.\n\n"
                f"Restoring node {self.node.number} independently may leave "
                "its configuration inconsistent with other nodes.\n\n"
                "Do you want to continue?"
            )
        else:
            message = f"Restore '{backup['description']}' to node {self.node.number}?"

        answer = QMessageBox.question(
            self,
            "Restore node backup",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        contents = backup_contents(backup)

        self.node.nv_values = deepcopy(contents["nv_values"])
        self.node.nv_descriptions = deepcopy(contents["nv_descriptions"])
        self.node.consumed_events = deepcopy(contents["consumed_events"])
        self.node.ev_values = deepcopy(contents["ev_values"])

        # Refresh the node configuration displays.
        self.raw_values.show_node(self.node)
        self.mdf_values.show_node(self.node)
        self.node_events.show_node(self.node)

        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage("Node backup restored successfully", 5000)

    def delete_backup(self):
        if self.node is None:
            return

        selected = self.node_backups.selectedItems()
        if not selected:
            return

        backup = selected[0].data(0, Qt.ItemDataRole.UserRole)

        if (
            backup.get("partOfLayoutBackup", False)
            or backup.get("description") == "Layout backup"
        ):
            QMessageBox.information(
                self,
                "Delete node backup",
                "This backup belongs to a layout backup and cannot be deleted individually.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Delete node backup",
            f"Delete '{backup['description']}' for node {self.node.number}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.node_backups.delete_backup(self.node, backup)
        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage("Node backup deleted", 5000)
