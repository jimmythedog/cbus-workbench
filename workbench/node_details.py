import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .cbus_service import NodeState
from .logging_config import trace
from .node_backup_workflow import NodeBackupWorkflow
from .node_backups import NodeBackups
from .node_details_form import NodeDetailsForm
from .node_events import NodeEvents
from .node_variables import MdfNodeVariables, RawNodeVariables
from .pnn import Pnn

DEFAULT_NODE_TITLE = "Node details"
logger = logging.getLogger("workbench.ui")


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

        self.details_page = NodeDetailsForm()
        # Keep existing label access paths for callers and name-editing code.
        self.node_number = self.details_page.node_number
        self.node_name = self.details_page.node_name
        self.node_name_editor = self.details_page.node_name_editor
        self.node_name_stack = self.details_page.node_name_stack
        self.can_id = self.details_page.can_id
        self.module_type = self.details_page.module_type
        self.firmware = self.details_page.firmware
        self.status = self.details_page.status
        self.manufacturer = self.details_page.manufacturer
        self.flags = self.details_page.flags
        self.node_mode = self.details_page.node_mode
        self.nv_count = self.details_page.nv_count
        self.event_count = self.details_page.event_count
        self.ev_count = self.details_page.ev_count
        self.cpu_name = self.details_page.cpu_name
        self.interface = self.details_page.interface
        self.producer = self.details_page.producer
        self.consumer = self.details_page.consumer
        self.consumes_own_events = self.details_page.consumes_own_events
        self.supports_bootloading = self.details_page.supports_bootloading
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
        self.events_page = self.node_events
        self.tabs.addTab(self.events_page, "Events")

        self.node_backups = NodeBackups()
        self.backup_workflow = NodeBackupWorkflow(
            self, self.node_backups, self.refresh_backup_displays
        )
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
            self.events_page,
            self.node_backups,
        ):
            self.tabs.setTabEnabled(self.tabs.indexOf(page), not editing)

    def refresh_node_name(self):
        self.details_page.show_node_name(self.node)
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
        self.tabs.setTabEnabled(self.tabs.indexOf(self.events_page), not editing)
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

    def show_parameters(self, parameters: dict[int, int]) -> None:
        """Display confirmed PARAN values; absent indices remain unknown."""
        firmware = self.details_page.show_parameters(parameters)
        self.summary_firmware.setText(f"Firmware: {firmware}")

    def show_live_state(self, state: NodeState) -> None:
        """Refresh the selected identity from confirmed service values."""
        self.show_parameters(state.parameters)
        self.raw_values.show_live_values(state.parameters.get(6), state.nv_values)
        self.node_events.show_live_state(state)
        trace(
            logger,
            "Live node values displayed",
            extra={
                "fields": {
                    "node_number": state.identity.node_number,
                    "nv_count": state.parameters.get(6),
                    "confirmed_nv_indices": sorted(state.nv_values),
                    "event_indices": sorted(state.event_identities),
                    "event_progress": state.event_progress.value,
                    "ev_progress": state.ev_progress.value,
                }
            },
        )

    def show_node(self, current):
        selected_page = self.tabs.currentWidget()
        previous_live_node = (
            self.node.node_number if isinstance(self.node, Pnn) else None
        )
        self.node_list_item = current
        self.details_buttons.setCurrentIndex(0)
        self.node = current.data(Qt.ItemDataRole.UserRole) if current else None
        live_identity = isinstance(self.node, Pnn)
        if not live_identity or self.node.node_number != previous_live_node:
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
        self.tabs.setTabEnabled(self.tabs.indexOf(self.variables_page), True)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_backups), not live_identity)
        self.tabs.setCurrentWidget(
            selected_page
            if self.tabs.isTabEnabled(self.tabs.indexOf(selected_page))
            else self.details_page
        )

        if current is None:
            self._show_no_node()
        elif live_identity:
            self._show_live_identity(self.node)
        else:
            self._show_configured_node(self.node)

    def _show_no_node(self) -> None:
        self.variables.setCurrentIndex(0)
        self.raw_values.show_live_values(None, {})
        self.details_page.show_no_node()
        self.summary.setTitle(DEFAULT_NODE_TITLE)
        self.summary_can_id.setText("CAN ID: -")
        self.summary_firmware.setText("Firmware: -")
        self.summary_mode.setText("Mode: -")
        self.summary_status.setText("Status: -")

    def _show_live_identity(self, node) -> None:
        self.variables.setCurrentIndex(0)
        self.raw_values.show_live_values(None, {})
        mode = "FLiM" if node.is_flim else "SLiM"
        self.details_page.show_live_identity(node, mode)
        self.summary.setTitle(f"Node {node.node_number} — {node.module_type}")
        self.summary_can_id.setText("CAN ID: -")
        self.summary_firmware.setText("Firmware: -")
        self.summary_mode.setText(f"Mode: {mode}")
        self.summary_status.setText("Status: -")

    def _show_configured_node(self, node) -> None:
        self.raw_values.show_node(node)
        self.mdf_values.show_node(node)

        self.variables.setCurrentIndex(1 if node.has_mdf else 0)
        self.details_page.show_configured_node(node)
        self.refresh_node_name()
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
        self.backup_workflow.view(self.node)

    def compare_backup(self):
        self.backup_workflow.compare(self.node)

    def new_backup(self):
        self.backup_workflow.create(self.node)

    def restore_backup(self):
        self.backup_workflow.restore(self.node)

    def delete_backup(self):
        self.backup_workflow.delete(self.node)

    def refresh_backup_displays(self):
        """Refresh the configuration displays after a node backup restore."""
        self.raw_values.show_node(self.node)
        self.mdf_values.show_node(self.node)
        self.node_events.show_node(self.node)
