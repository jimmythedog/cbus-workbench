from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
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
from .node_snapshot import create_node_snapshot, restore_node_snapshot
from .node_variables import MdfNodeVariables, RawNodeVariables
from .pnn import Pnn

DEFAULT_NODE_TITLE = "Node details"


class NodeDetails(QWidget):
    editing_changed = Signal(bool)

    def __init__(self, events):
        super().__init__()

        self.node = None
        self.node_list_item = None
        self.editing_values = None
        self.editing_descriptions = None

        layout = QVBoxLayout(self)

        # Compact summary, always visible above the tabs.
        self.summary = QGroupBox(DEFAULT_NODE_TITLE)
        summary_layout = QHBoxLayout(self.summary)
        summary_layout.setSpacing(24)

        self.summary_can_id = QLabel()
        self.summary_firmware = QLabel()
        self.summary_mode = QLabel()
        self.summary_status = QLabel()

        summary_layout.addWidget(self.summary_can_id)
        summary_layout.addWidget(self.summary_firmware)
        summary_layout.addWidget(self.summary_mode)
        summary_layout.addWidget(self.summary_status)
        summary_layout.addStretch()

        layout.addWidget(self.summary)

        self.group = QWidget()

        form = QFormLayout(self.group)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.node_number = QLabel("-")
        self.node_name = QLabel("-")
        self.node_name_editor = QLineEdit()
        self.node_name_stack = QStackedWidget()
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

        self.details_page = QWidget()
        details_layout = QVBoxLayout(self.details_page)
        details_layout.addWidget(self.group, 1)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.details_page, "Node Details")

        self.details_buttons = QStackedLayout()
        self.details_edit_button = QPushButton("Edit")
        self.details_edit_button.setEnabled(False)
        self.details_edit_button.clicked.connect(self.start_name_editing)
        view_buttons = QWidget()
        view_buttons_layout = QHBoxLayout(view_buttons)
        view_buttons_layout.addStretch()
        view_buttons_layout.addWidget(self.details_edit_button)
        self.details_save_button = QPushButton("Save")
        self.details_save_button.clicked.connect(self.save_name_editing)
        self.details_cancel_button = QPushButton("Cancel")
        self.details_cancel_button.clicked.connect(self.cancel_name_editing)
        edit_buttons = QWidget()
        edit_buttons_layout = QHBoxLayout(edit_buttons)
        edit_buttons_layout.addStretch()
        edit_buttons_layout.addWidget(self.details_save_button)
        edit_buttons_layout.addWidget(self.details_cancel_button)
        self.details_buttons.addWidget(view_buttons)
        self.details_buttons.addWidget(edit_buttons)
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

        # Pages must match the tab order: currentChanged passes its index to this stack.
        self.action_area = QStackedWidget()
        details_actions = QWidget()
        details_actions_layout = QHBoxLayout(details_actions)
        details_actions_layout.addLayout(self.details_buttons)
        self.action_area.addWidget(details_actions)
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

    def start_name_editing(self):
        if self.node is None:
            return
        self.node_name_editor.setText(self.node.name)
        self.node_name_stack.setCurrentWidget(self.node_name_editor)
        self.set_name_editing_tabs(True)
        self.details_buttons.setCurrentIndex(1)
        self.editing_changed.emit(True)

    def save_name_editing(self):
        if self.node is None:
            return
        self.node.name = self.node_name_editor.text().strip()
        self.refresh_node_name()
        self.finish_name_editing()

    def cancel_name_editing(self):
        self.refresh_node_name()
        self.finish_name_editing()

    def finish_name_editing(self):
        self.node_name_stack.setCurrentWidget(self.node_name)
        self.set_name_editing_tabs(False)
        self.details_buttons.setCurrentIndex(0)
        self.editing_changed.emit(False)

    def set_name_editing_tabs(self, editing):
        for page in (
            self.variables_page,
            self.node_events,
            self.node_backups,
        ):
            self.tabs.setTabEnabled(self.tabs.indexOf(page), not editing)

    def refresh_node_name(self):
        self.node_name.setText((self.node.name or "-") if self.node else "-")
        if self.node is None:
            return
        title = f"Node {self.node.number} — {self.node.module_type}"
        if self.node.name:
            title += f" — {self.node.name}"
        self.summary.setTitle(title)
        current = self.node_list_item
        if current is not None:
            label = f"{self.node.number} - {self.node.module_type}"
            if self.node.name:
                label += f" — {self.node.name}"
            current.setText(label)

    def cancel_editing(self):
        self.editing_values = None
        self.editing_descriptions = None
        self.stop_editing()

    def start_editing(self):
        self.set_editing(True)
        self.editing_changed.emit(True)
        # Both views edit these copies; Save replaces the node data, Cancel discards them.
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
        self.tabs.setTabEnabled(self.tabs.indexOf(self.details_page), not editing)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_events), not editing)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_backups), not editing)

    def start_events_editing(self):
        self.node_events.begin_edit()
        self.events_buttons.setCurrentIndex(1)

        self.tabs.setTabEnabled(self.tabs.indexOf(self.details_page), False)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.variables_page), False)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_backups), False)

        self.editing_changed.emit(True)

    def cancel_events_editing(self):
        self.node_events.cancel_edit()
        self.finish_events_editing()

    def finish_events_editing(self):
        self.events_buttons.setCurrentIndex(0)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.details_page), True)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.variables_page), True)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_backups), True)

        self.editing_changed.emit(False)

    def save_events_editing(self):
        self.node_events.save_edit()
        self.finish_events_editing()

    def show_node(self, current):
        self.node_list_item = current
        self.details_buttons.setCurrentIndex(0)
        self.node = current.data(Qt.ItemDataRole.UserRole) if current else None
        live_identity = isinstance(self.node, Pnn)
        self.node_events.show_node(None if live_identity else self.node)
        self.node_backups.show_node(None if live_identity else self.node)
        self.backup_buttons["New"].setEnabled(
            self.node is not None and not live_identity
        )
        self.update_backup_buttons()

        enabled = current is not None
        self.edit_button.setEnabled(enabled and not live_identity)
        self.details_edit_button.setEnabled(enabled and not live_identity)
        self.events_edit_button.setEnabled(enabled and not live_identity)
        for page in (self.variables_page, self.node_events, self.node_backups):
            self.tabs.setTabEnabled(self.tabs.indexOf(page), not live_identity)
        if live_identity:
            self.tabs.setCurrentWidget(self.details_page)

        if current is None:
            self.node_number.setText("-")
            self.node_name.setText("-")
            self.can_id.setText("-")
            self.module_type.setText("-")
            self.firmware.setText("-")
            self.status.setText("-")
            self.flags.setText("-")
            self.variables.setCurrentIndex(0)
            for label in (
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

            self.summary.setTitle(DEFAULT_NODE_TITLE)
            self.summary_can_id.setText("CAN ID: -")
            self.summary_firmware.setText("Firmware: -")
            self.summary_mode.setText("Mode: -")
            self.summary_status.setText("Status: -")

            return

        node = current.data(Qt.ItemDataRole.UserRole)

        if isinstance(node, Pnn):
            self.node_number.setText(str(node.node_number))
            self.node_name.setText("-")
            self.can_id.setText("-")
            self.module_type.setText(str(node.module_type))
            self.firmware.setText("-")
            self.status.setText("-")
            self.manufacturer.setText(str(node.manufacturer))
            self.flags.setText(f"0x{node.flags:02X}")
            for label in (
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
            self.summary.setTitle(f"Node {node.node_number} — {node.module_type}")
            self.summary_can_id.setText("CAN ID: -")
            self.summary_firmware.setText("Firmware: -")
            self.summary_mode.setText("Mode: -")
            self.summary_status.setText("Status: -")
            return

        self.raw_values.show_node(node)
        self.mdf_values.show_node(node)

        number = node.number
        has_mdf = node.has_mdf

        self.variables.setCurrentIndex(1 if has_mdf else 0)
        self.node_number.setText(str(number))
        self.refresh_node_name()
        self.can_id.setText("126")
        self.module_type.setText("CANMIO")
        self.flags.setText("-")
        self.firmware.setText("3d")
        self.status.setText("Online")
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

        self.summary_can_id.setText(f"CAN ID: {node.can_id}")
        self.summary_firmware.setText(f"Firmware: {node.firmware}")
        self.summary_mode.setText("Mode: FLiM")
        self.summary_status.setText("Status: Online")

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

        restore_node_snapshot(self.node, contents)

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
