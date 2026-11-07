import logging
from copy import deepcopy

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
from .node import Node
from .node_backup_files import node_backup
from .node_backup_workflow import NodeBackupWorkflow
from .node_backups import NodeBackups
from .node_details_form import NodeDetailsForm
from .node_events import NodeEvents
from .node_failure_report import NodeFailureReport
from .node_variables import MdfNodeVariables, RawNodeVariables
from .parameter_names import manufacturer_name, module_name
from .pnn import Pnn

DEFAULT_NODE_TITLE = "Node details"
logger = logging.getLogger("workbench.ui")


class NodeDetails(QWidget):
    editing_changed = Signal(bool)

    def __init__(self, events):
        super().__init__()

        self.connected = False
        self.live_state = None
        self.logical_layout = None
        self.node = None
        self.node_list_item = None
        self.editing_descriptions = None
        self.cbus_service = None
        self.original_configuration = None
        self.desired_configuration = None
        self.failure_report = None
        self.saving_configuration = False
        self.layout_restoring = False

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
        self.nv_result = QLabel()
        self.nv_result.setWordWrap(True)
        variables_layout.addWidget(self.nv_result)

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
        self.events_result = QLabel()
        self.events_result.setWordWrap(True)
        events_layout.addWidget(self.events_result, 1)
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
        self.restore_result = QLabel()
        self.restore_result.setWordWrap(True)
        backups_layout.addWidget(self.restore_result, 1)
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
        """Submit the whole desired configuration to the existing Restore path."""
        if self.desired_configuration is None or self.saving_configuration:
            return
        number = self.desired_configuration["node"]
        self.set_configuration_saving(True)
        self.show_configuration_result("Saving node configuration…")
        trace(
            logger,
            "Submitting shared node configuration",
            extra={"fields": {"node_number": number}},
        )
        try:
            self.cbus_service.restore.begin(number, self.desired_configuration)
        except ValueError as error:
            # Validation failed before application began. Keep the edits available
            # for review or Cancel; Restore remains responsible for all checks.
            self.set_configuration_saving(False)
            self.show_configuration_result(f"Node {number}: {error}")
            trace(
                logger,
                "Shared node configuration rejected",
                extra={"fields": {"node_number": number, "reason": str(error)}},
            )

    def set_configuration_saving(self, saving: bool) -> None:
        """Lock both editors until the coordinator's final completion."""
        self.saving_configuration = saving
        self.variables.setEnabled(not saving)
        self.node_events.setEnabled(not saving)
        for button in (
            self.save_button,
            self.events_save_button,
            self.cancel_button,
            self.events_cancel_button,
        ):
            button.setEnabled(not saving)

    def show_configuration_result(self, message: str) -> None:
        self.nv_result.setText(message)
        self.events_result.setText(message)

    def can_edit_configuration(self) -> bool:
        state = self.live_state
        service = self.cbus_service
        return bool(
            self.connected
            and service is not None
            and state is not None
            and state.identity.node_number
            and state.identity.is_flim
            and state.can_id is not None
            and not service.writes_busy()
            and not service.discovery_pending()
            and not service.ev_write.blocked
            and not service.nv_write.unverified
            and node_backup(state)["complete"]
        )

    def nv_display_node(self):
        """Use the existing editors with confirmed live data and local descriptions."""
        if self.live_state is None:
            return self.node
        if isinstance(self.node, Pnn):
            return Node(
                self.node.node_number,
                str(self.node.module_type),
                0,
                "",
                False,
                nv_values=self.live_state.nv_values.copy(),
            )
        self.node.nv_values = self.live_state.nv_values.copy()
        return self.node

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
        if self.saving_configuration:
            return
        if self.desired_configuration is not None:
            trace(
                logger,
                "Discarding shared node configuration edits",
                extra={"fields": {"node_number": self.desired_configuration["node"]}},
            )
            self.original_configuration = None
            self.desired_configuration = None
            self.node_events.cancel_edit()
            self.events_buttons.setCurrentIndex(0)
        self.editing_descriptions = None
        self.stop_editing()

    def start_editing(self):
        if not self.can_edit_configuration() or self.desired_configuration is not None:
            return
        node = self.nv_display_node()
        self.show_configuration_result("")
        self.set_editing(True)
        self.editing_changed.emit(True)
        # Both views share copies. Only verified readback changes live state.
        trace(
            logger,
            "Beginning shared node configuration editing",
            extra={"fields": {"node_number": self.live_state.identity.node_number}},
        )
        self.original_configuration = node_backup(self.live_state)
        self.desired_configuration = deepcopy(self.original_configuration)
        self.node_events.begin_configuration_edit(self.desired_configuration)
        self.events_buttons.setCurrentIndex(1)
        for button in (self.save_button, self.events_save_button):
            button.setEnabled(True)
            button.setToolTip("")
        self.editing_descriptions = node.nv_descriptions.copy()
        self.raw_values.show_node(
            node, self.desired_configuration["nvs"], self.editing_descriptions
        )
        self.mdf_values.show_node(
            node, self.desired_configuration["nvs"], self.editing_descriptions
        )
        self.raw_values.set_editing(True)
        self.mdf_values.set_editing(True)
        self.buttons.setCurrentIndex(1)

    def stop_editing(self):
        node = self.nv_display_node()
        self.raw_values.set_editing(False)
        if node is not None:
            self.raw_values.show_node(node)

        self.mdf_values.set_editing(False)
        if node is not None:
            self.mdf_values.show_node(node)

        self.buttons.setCurrentIndex(0)
        self.set_editing(False)
        self.editing_changed.emit(False)
        self.edit_button.setEnabled(self.can_edit_configuration())

    def set_editing(self, editing):
        self.tabs.setTabEnabled(self.tabs.indexOf(self.details_page), not editing)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.events_page), True)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_backups), not editing)

    def start_events_editing(self):
        if self.live_state is not None:
            self.start_editing()
            return
        self.events_result.clear()
        self.events_save_button.setEnabled(True)
        self.events_save_button.setToolTip("")
        self.node_events.begin_edit()
        self.events_buttons.setCurrentIndex(1)

        self.tabs.setTabEnabled(self.tabs.indexOf(self.details_page), False)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.variables_page), False)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_backups), False)

        self.editing_changed.emit(True)

    def cancel_events_editing(self):
        if self.desired_configuration is not None:
            self.cancel_editing()
            return
        self.node_events.cancel_edit()
        self.finish_events_editing()

    def finish_events_editing(self):
        self.events_buttons.setCurrentIndex(0)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.details_page), True)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.variables_page), True)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_backups), True)

        self.editing_changed.emit(False)

    def save_events_editing(self):
        if self.live_state is not None:
            self.save_editing()
            return
        self.node_events.save_edit()
        self.finish_events_editing()

    def show_parameters(self, parameters: dict[int, int]) -> None:
        """Display confirmed PARAN values; absent indices remain unknown."""
        firmware = self.details_page.show_parameters(parameters)
        self.summary_firmware.setText(f"Firmware: {firmware}")
        is_can = parameters.get(10) == 1
        self.details_page.show_can_id(is_can)
        self.summary_can_id.setVisible(is_can)

    def show_live_state(self, state: NodeState) -> None:
        """Refresh the selected identity from confirmed service values."""
        self.live_state = state
        self.details_page.show_module_identifier(
            state.identity.manufacturer, state.identity.module_type
        )
        self.manufacturer.setText(manufacturer_name(state.identity.manufacturer))
        self.module_type.setText(
            module_name(state.identity.manufacturer, state.identity.module_type)
        )
        self.summary.setTitle(
            f"Node {state.identity.node_number} — {self.module_type.text()}"
        )
        self.update_connection_details()
        self.update_backup_buttons()
        self.show_parameters(state.parameters)
        self.details_page.stored_events.setText(
            "-" if state.stored_event_count is None else str(state.stored_event_count)
        )
        self.edit_button.setEnabled(self.can_edit_configuration())
        if self.desired_configuration is None:
            node = self.nv_display_node()
            self.raw_values.show_live_values(state.parameters.get(6), state.nv_values)
            self.mdf_values.show_node(node)
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
                    "stored_event_count": state.stored_event_count,
                    "event_progress": state.event_progress.value,
                    "ev_progress": state.ev_progress.value,
                }
            },
        )

    def show_node(self, current):
        if self.node_events.editing_values is not None:
            self.cancel_events_editing()
        if self.desired_configuration is not None:
            self.cancel_editing()
        self.show_configuration_result("")
        selected_page = self.tabs.currentWidget()
        previous_live_node = (
            self.node.node_number if isinstance(self.node, Pnn) else None
        )
        self.node_list_item = current
        self.details_buttons.setCurrentIndex(0)
        self.node = current.data(Qt.ItemDataRole.UserRole) if current else None
        live_identity = isinstance(self.node, Pnn)
        saved_node = isinstance(self.node, int)
        if not live_identity or self.node.node_number != previous_live_node:
            self.node_events.show_node(
                None if live_identity or saved_node else self.node
            )
        self.live_state = None
        if (live_identity or saved_node) and self.logical_layout is not None:
            number = self.node if saved_node else self.node.node_number
            self.node_backups.show_live_node(self.logical_layout, number)
        else:
            self.node_backups.show_node(
                None if live_identity or saved_node else self.node
            )
        self.update_backup_buttons()

        enabled = current is not None and not saved_node
        self.edit_button.setEnabled(False)
        self.details_edit_button.setEnabled(enabled and not live_identity)
        self.events_edit_button.setEnabled(enabled and not live_identity)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.variables_page), True)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_backups), True)
        self.tabs.setCurrentWidget(
            selected_page
            if self.tabs.isTabEnabled(self.tabs.indexOf(selected_page))
            else self.details_page
        )

        if current is None or saved_node:
            self._show_no_node()
            if saved_node:
                self.summary.setTitle(f"Node {self.node} (offline)")
        elif live_identity:
            self._show_live_identity(self.node)
        else:
            self._show_configured_node(self.node)
        self.update_connection_details()

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
        self.summary.setTitle(
            f"Node {node.node_number} — {module_name(node.manufacturer, node.module_type)}"
        )
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
        self.summary_firmware.setText(f"Firmware: {node.firmware}")
        self.summary_mode.setText("Mode: FLiM")

    def update_connection_details(self) -> None:
        """Show discovery evidence for this connection, never configured guesses."""
        if (
            not self.connected
            and self.desired_configuration is not None
            and not self.saving_configuration
        ):
            self.cancel_editing()
            message = (
                "Connection ended; node configuration edits discarded without writing."
            )
            self.nv_result.setText(message)
            self.events_result.setText(message)
        self.edit_button.setEnabled(self.can_edit_configuration())
        if not self.connected and self.node_events.editing_values is not None:
            self.cancel_events_editing()
            self.events_result.setText(
                "Connection ended; EV edits discarded without writing."
            )
        if isinstance(self.node, Pnn) or self.live_state is not None:
            self.events_edit_button.setEnabled(self.can_edit_configuration())
            if (
                self.live_state is not None
                and self.live_state.parameters.get(5) is not None
                and self.events_result.text().startswith("EV editing unavailable:")
            ):
                self.events_result.clear()
            if (
                self.live_state is not None
                and not self.events_result.text()
                and self.live_state.parameters.get(5) is None
            ):
                self.events_result.setText(
                    "EV editing unavailable: EV capacity is unconfirmed."
                )
        is_can = self.live_state is not None and self.live_state.parameters.get(10) == 1
        self.details_page.show_can_id(is_can)
        self.summary_can_id.setVisible(is_can)
        can_id = self.live_state.can_id if self.live_state is not None else None
        status = "-"
        if self.node is not None:
            if not self.connected:
                status = "Offline"
            elif self.live_state is not None:
                status = "Online"
        text = str(can_id) if can_id is not None else "-"
        self.can_id.setText(text)
        self.summary_can_id.setText(f"CAN ID: {text}")
        self.status.setText(status)
        self.summary_status.setText(f"Status: {status}")

    def update_backup_buttons(self):
        selected = bool(self.node_backups.selectedItems())
        # Restore stays active between writer callbacks and through rediscovery.
        # Live-state refreshes must keep its actions disabled for that whole time.
        restoring = self.cbus_service is not None and self.cbus_service.restore.active
        available = self.connected and not restoring

        live_node = self.node is not None and not isinstance(self.node, int)
        self.backup_buttons["New"].setEnabled(available and live_node)
        self.backup_buttons["View"].setEnabled(selected)
        self.backup_buttons["Compare"].setEnabled(available and selected)
        self.backup_buttons["Restore"].setEnabled(
            available
            and selected
            and isinstance(self.node, Pnn)
            and self.live_state is not None
            and self.cbus_service is not None
            and not self.cbus_service.writes_busy()
        )
        self.backup_buttons["Delete"].setEnabled(False)

    def view_backup(self):
        self.backup_workflow.view(self.node)

    def compare_backup(self):
        if not self.connected or isinstance(self.node, int):
            return
        if isinstance(self.node, Pnn) and self.live_state is None:
            return
        self.backup_workflow.compare(self.node, self.live_state)

    def new_backup(self):
        if not self.connected or isinstance(self.node, int):
            return
        if isinstance(self.node, Pnn):
            if self.live_state is not None and self.logical_layout is not None:
                self.backup_workflow.create_live(self.live_state, self.logical_layout)
        else:
            self.backup_workflow.create(self.node)

    def restore_backup(self):
        if isinstance(self.node, Pnn):
            if (
                self.connected
                and self.live_state is not None
                and self.cbus_service is not None
            ):
                self.backup_workflow.restore_live(self.node, self.cbus_service)
        elif not isinstance(self.node, int):
            self.backup_workflow.restore(self.node)

    def show_restore_progress(self, node_number: int, message: str) -> None:
        if self.layout_restoring:
            return
        self.update_backup_buttons()
        saving = self.saving_configuration or (
            self.failure_report is not None
            and self.failure_report.running
            and self.failure_report.saving
        )
        if saving:
            message = message.replace("Restoring ", "Saving ")
        if self.saving_configuration:
            self.show_configuration_result(message)
            return
        self.restore_result.setText(message)
        self.editing_changed.emit(True)
        self.edit_button.setEnabled(False)
        self.events_edit_button.setEnabled(False)

    def finish_restore(self, node_number: int, success: bool, message: str) -> None:
        if self.layout_restoring:
            return
        saving = self.saving_configuration
        if self.failure_report is not None and self.failure_report.running:
            saving = self.failure_report.saving
        # The writer is shared; display the initiating action, including on Retry.
        action = "Save" if saving else "Restore"
        verb = "saved" if saving else "restored"
        message = message.replace(
            "Node configuration restored and fully verified.",
            f"Configuration {verb} and fully verified.",
        ).replace("Partial restoration:", f"Partial {action}:")
        message = message.replace("after restoration.", f"after {action}.")
        if self.failure_report is not None and self.failure_report.running:
            self.failure_report.completed(success, message)
        elif not success:
            if self.failure_report is not None:
                self.failure_report.dialog.close()
            self.failure_report = NodeFailureReport(self, self.cbus_service, message)
        if self.saving_configuration:
            trace(
                logger,
                "Shared node configuration application finished",
                extra={
                    "fields": {
                        "node_number": node_number,
                        "success": success,
                        "result": message,
                    }
                },
            )
            self.set_configuration_saving(False)
            self.cancel_editing()  # Replace both working views with confirmed state.
            self.show_configuration_result(f"Node {node_number}: {message}")
            self.events_edit_button.setEnabled(self.can_edit_configuration())
            self.update_backup_buttons()
            return
        self.restore_result.setText(f"Node {node_number}: {message}")
        self.editing_changed.emit(False)
        self.edit_button.setEnabled(self.can_edit_configuration())
        self.events_edit_button.setEnabled(self.can_edit_configuration())
        self.update_backup_buttons()

    def delete_backup(self):
        self.backup_workflow.delete(self.node)

    def refresh_backup_displays(self):
        """Refresh the configuration displays after a node backup restore."""
        self.raw_values.show_node(self.node)
        self.mdf_values.show_node(self.node)
        self.node_events.show_node(self.node)
