import logging
from copy import deepcopy
from pathlib import Path

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
from .event_description_edit import NodeEventNameEditor
from .logging_config import trace
from .mdf_tokens import substitute_tokens
from .mdfs import Mdf
from .node import Node
from .node_backup_files import load_node_backup, node_backup
from .node_backup_workflow import NodeBackupWorkflow
from .node_backups import NodeBackups
from .node_details_form import NodeDetailsForm
from .node_events import NodeEvents
from .node_failure_report import NodeFailureReport
from .node_name_edit import NodeNameEditor
from .node_variables import PROTOTYPE_MDF, MdfNodeVariables, RawNodeVariables
from .pnn import Pnn
from .token_label_edit import TokenLabelEditor

DEFAULT_NODE_TITLE = "Node details"
logger = logging.getLogger("workbench.ui")


class NodeDetails(QWidget):
    editing_changed = Signal(bool)

    def __init__(self, events):
        super().__init__()

        self.connected = False
        self.saved_metadata = {}
        self.live_state = None
        self.live_mdf = None
        self.logical_layout = None
        self.annotations = None
        self.annotation_editing = False
        self.node = None
        self.node_list_item = None
        self.cbus_service = None
        self.original_configuration = None
        self.desired_configuration = None
        self.editing_session = None
        self.failure_report = None
        self.saving_configuration = False
        self.saving_nvs = False
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
        self.token_label_editor = TokenLabelEditor(self)
        # Keep existing label access paths for callers and name-editing code.
        self.node_number = self.details_page.node_number
        self.node_name = self.details_page.node_name
        self.node_name_edit = NodeNameEditor(self)
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

        self.raw_values = RawNodeVariables()
        self.mdf_values = MdfNodeVariables()
        self.mdf_values.set_editing(False)
        self.raw_values.value_changed.connect(self.refresh_configuration_views)
        self.mdf_values.value_changed.connect(self.refresh_configuration_views)

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
        self.event_name_edit = NodeEventNameEditor(self)
        self.produced_events_page = self.node_events.produced_page
        self.consumed_events_page = self.node_events
        self.tabs.addTab(self.consumed_events_page, "Consumed Events")
        self.tabs.addTab(self.produced_events_page, "Produced Events")

        self.node_backups = NodeBackups()
        self.backup_workflow = NodeBackupWorkflow(
            self, self.node_backups, self.refresh_backup_displays
        )
        self.node_backups.itemSelectionChanged.connect(self.update_backup_buttons)
        self.tabs.addTab(self.node_backups, "Backups")

        # Pages must match the tab order: currentChanged passes its index to this stack.
        self.action_area = QStackedWidget()
        self.action_area.addWidget(QWidget())  # Node name is edited from its label.
        self.action_area.addWidget(variables_actions)
        self.action_area.addWidget(events_actions)
        self.action_area.addWidget(
            QWidget()
        )  # Produced descriptions are edited from their cells.

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

    def refresh_configuration_views(self):
        if self.desired_configuration is None:
            return
        self.raw_values.refresh_values()
        self.mdf_values.refresh_values()
        self.node_events.refresh_configuration_controls()

    def save_editing(self):
        """Save only the active NV session through its verified writer."""
        if self.editing_session != "nvs" or self.saving_configuration:
            return
        self.save_configuration()

    def save_configuration(self):
        number = self.desired_configuration["node"]
        self.saving_nvs = self.editing_session == "nvs"
        self.set_configuration_saving(True)
        self.show_configuration_result("Saving node configuration…")
        trace(
            logger,
            "Submitting NV editing Save"
            if self.saving_nvs
            else "Submitting event configuration",
            extra={"fields": {"node_number": number}},
        )
        try:
            if self.saving_nvs:
                self.cbus_service.nv_save.begin(
                    number,
                    self.desired_configuration,
                    pre_edit=self.original_configuration["nvs"],
                    mdf=self.live_mdf.data if self.live_mdf else None,
                )
            else:
                self.cbus_service.event_save.begin(
                    number,
                    self.desired_configuration,
                    original=self.original_configuration,
                )
        except ValueError as error:
            # Validation failed before application began. Keep the edits available
            # for review or Cancel; the coordinator owns the safety checks.
            self.set_configuration_saving(False)
            self.saving_nvs = False
            self.show_configuration_result(f"Node {number}: {error}")
            trace(
                logger,
                "Node configuration rejected",
                extra={"fields": {"node_number": number, "reason": str(error)}},
            )

    def set_configuration_saving(self, saving: bool) -> None:
        """Lock the active editor; the other tab remains readable."""
        self.saving_configuration = saving
        self.variables.setEnabled(not saving or self.editing_session != "nvs")
        self.node_events.setEnabled(not saving or self.editing_session != "events")
        self.produced_events_page.setEnabled(True)
        for button in (
            self.save_button,
            self.events_save_button,
            self.cancel_button,
            self.events_cancel_button,
        ):
            button.setEnabled(not saving)

    def show_configuration_result(self, message: str) -> None:
        result = (
            self.events_result if self.editing_session == "events" else self.nv_result
        )
        result.setText(message)

    def can_edit_configuration(self) -> bool:
        state = self.live_state
        service = self.cbus_service
        return bool(
            self.connected
            and self.desired_configuration is None
            and not self.annotation_editing
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
        """Use the existing editors with confirmed live NV data."""
        if self.live_state is None:
            return self.node
        if isinstance(self.node, Pnn):
            return Node(
                self.node.node_number,
                str(self.node.module_type),
                0,
                "",
                False,
                nv_values=self.live_state.nv_values,
            )
        self.node.nv_values = self.live_state.nv_values
        return self.node

    def can_edit_annotations(self):
        return (
            self.node is not None
            and self.desired_configuration is None
            and not (self.cbus_service is not None and self.cbus_service.writes_busy())
        )

    def annotation_number(self):
        if isinstance(self.node, int):
            return self.node
        return self.node.node_number if isinstance(self.node, Pnn) else self.node.number

    def refresh_annotations(self):
        if not self.annotations or self.node is None or self.annotation_editing:
            return
        data = self.annotations.load(self.annotation_number())
        name = data.get("name", "")
        self.node_name.setText(name or "-")
        title = (
            f"Node {self.annotation_number()}"
            if isinstance(self.node, int)
            else f"Node {self.annotation_number()} — {self.module_type.text()}"
        )
        if name:
            title += f" — {name}"
        self.summary.setTitle(title)
        if self.live_state is None and self.live_mdf and isinstance(self.node, int):
            definition = substitute_tokens(self.live_mdf.data, data.get("tokens", {}))
            self.mdf_values.set_definition(
                definition,
                source=self.live_mdf.data,
                token_editor=self.token_label_editor,
            )
            # Unknown hardware bytes stay blank/read-only; the labels are local.
            self.mdf_values.show_live_values(None, {})
            self.variables.setCurrentIndex(
                1 if self.mdf_values.pages.count() > 1 else 0
            )
        self.node_events.refresh_annotations(self.annotation_number())

    def refresh_node_name(self):
        if self.annotations:
            self.refresh_annotations()
            return
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
        if self.editing_session != "nvs":
            return
        self.cancel_configuration()

    def cancel_configuration(self):
        if self.saving_configuration:
            return
        if self.desired_configuration is not None:
            trace(
                logger,
                "Discarding active node configuration edits",
                extra={"fields": {"node_number": self.desired_configuration["node"]}},
            )
            self.editing_session = None
            self.original_configuration = None
            self.desired_configuration = None
            self.node_events.cancel_edit()
            self.events_buttons.setCurrentIndex(0)
        self.stop_editing()

    def start_editing(self):
        self.begin_configuration_edit("nvs")

    def begin_configuration_edit(self, session):
        if not self.can_edit_configuration() or self.desired_configuration is not None:
            return
        self.editing_session = session
        node = self.nv_display_node()
        self.show_configuration_result("")
        self.set_editing(True)
        self.editing_changed.emit(True)
        # Only the owning tab edits this snapshot; hardware values stay separate.
        trace(
            logger,
            f"Beginning {session} editing",
            extra={"fields": {"node_number": self.live_state.identity.node_number}},
        )
        self.original_configuration = node_backup(self.live_state)
        self.desired_configuration = deepcopy(self.original_configuration)
        self.edit_button.setEnabled(False)
        self.events_edit_button.setEnabled(False)
        if session == "events":
            self.node_events.begin_configuration_edit(self.desired_configuration)
            self.events_buttons.setCurrentIndex(1)
            self.events_save_button.setEnabled(True)
            self.events_save_button.setToolTip("")
            return
        self.save_button.setEnabled(True)
        self.save_button.setToolTip("")
        self.raw_values.show_node(node, self.desired_configuration["nvs"])
        self.mdf_values.show_node(node, self.desired_configuration["nvs"])
        self.raw_values.set_editing(True)
        self.mdf_values.set_editing(True)
        self.buttons.setCurrentIndex(1)

    def stop_editing(self):
        node = self.nv_display_node()
        self.raw_values.set_editing(False)
        self.mdf_values.set_editing(False)
        if self.live_state is not None:
            self.show_nv_values()
        elif node is not None:
            self.raw_values.show_node(node)
            self.mdf_values.show_node(node)

        self.buttons.setCurrentIndex(0)
        self.set_editing(False)
        self.editing_changed.emit(False)
        self.edit_button.setEnabled(self.can_edit_configuration())
        self.events_edit_button.setEnabled(self.can_edit_configuration())

    def set_editing(self, editing):
        self.tabs.setTabEnabled(self.tabs.indexOf(self.details_page), not editing)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.produced_events_page), True)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.consumed_events_page), True)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_backups), not editing)

    def start_events_editing(self):
        if self.live_state is not None:
            self.begin_configuration_edit("events")
            return
        self.events_result.clear()
        self.events_save_button.setEnabled(True)
        self.events_save_button.setToolTip("")
        self.node_events.begin_edit()
        self.events_buttons.setCurrentIndex(1)

        self.tabs.setTabEnabled(self.tabs.indexOf(self.details_page), False)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.variables_page), True)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_backups), False)

        self.editing_changed.emit(True)

    def cancel_events_editing(self):
        if self.live_state is not None:
            if self.editing_session == "events":
                self.cancel_configuration()
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
            if self.editing_session == "events" and not self.saving_configuration:
                self.save_configuration()
            return
        self.node_events.save_edit()
        self.finish_events_editing()

    def show_parameters(
        self, parameters: dict[int, int], module_name: str | None = None
    ) -> None:
        """Display confirmed PARAN values; absent indices remain unknown."""
        firmware = self.details_page.show_parameters(parameters)
        if module_name is not None:
            self.module_type.setText(module_name)
        self.summary_firmware.setText(f"Firmware: {firmware}")
        if isinstance(self.node, Pnn):
            self.summary.setTitle(
                f"Node {self.node.node_number} — {self.module_type.text()}"
            )
        is_can = parameters.get(10) == 1
        self.details_page.show_can_id(is_can)
        self.summary_can_id.setVisible(is_can)

    def show_live_state(
        self,
        state: NodeState,
        mdf: Mdf | None = None,
        *,
        module_name: str | None = None,
    ) -> None:
        """Refresh the selected identity from confirmed service values."""
        self.live_state = state
        # Freeze presentation during Edit just as we freeze its working copy.
        if self.desired_configuration is None:
            self.live_mdf = mdf
            try:
                definition = (
                    substitute_tokens(
                        mdf.data,
                        self.annotations.load(state.identity.node_number).get(
                            "tokens", {}
                        ),
                    )
                    if mdf and self.annotations
                    else mdf.data
                    if mdf
                    else None
                )
                self.mdf_values.set_definition(
                    definition,
                    source=mdf.data if mdf else None,
                    token_editor=self.token_label_editor if self.annotations else None,
                )
            except ValueError, KeyError, TypeError:
                logger.exception(
                    "Unsupported MDF presentation node=%s path=%s",
                    state.identity.node_number,
                    mdf.path,
                )
                self.live_mdf = None
            self.variables.setCurrentIndex(
                1 if self.live_mdf and self.mdf_values.pages.count() > 1 else 0
            )
        self.update_connection_details()
        self.update_backup_buttons()
        self.show_parameters(state.parameters, module_name)
        flags = state.parameters.get(8)
        if flags is None and state.identity_confirmed:
            flags = state.identity.flags
        mode = "-" if flags is None else "FLiM" if flags & 4 else "SLiM"
        self.summary_mode.setText(f"Mode: {mode}")
        self.details_page.stored_events.setText(
            "-" if state.stored_event_count is None else str(state.stored_event_count)
        )
        self.edit_button.setEnabled(self.can_edit_configuration())
        if self.editing_session != "nvs":
            self.show_nv_values()
        self.node_events.token_editor = (
            self.token_label_editor if self.annotations else None
        )
        self.node_events.source_mdf = mdf.data if mdf else None
        self.node_events.show_live_state(
            state,
            definition
            if self.desired_configuration is None
            else self.node_events.live_mdf,
        )
        self.refresh_annotations()
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

    def show_nv_values(self):
        """Both raw tables and MDF forms read the same confirmed live dictionary."""
        state = self.live_state
        self.raw_values.show_live_values(state.parameters.get(6), state.nv_values)
        self.mdf_values.show_live_values(state.parameters.get(6), state.nv_values)

    def show_node(self, current):
        if self.node_events.editing_values is not None:
            self.cancel_events_editing()
        if self.desired_configuration is not None:
            self.cancel_configuration()
        if self.annotation_editing:
            self.node_name_edit.cancel()
            self.event_name_edit.cancel()
        self.show_configuration_result("")
        selected_page = self.tabs.currentWidget()
        previous_live_node = (
            self.node.node_number if isinstance(self.node, Pnn) else None
        )
        self.node_list_item = current
        self.node = current.data(Qt.ItemDataRole.UserRole) if current else None
        live_identity = isinstance(self.node, Pnn)
        saved_node = isinstance(self.node, int)
        if not live_identity or self.node.node_number != previous_live_node:
            self.node_events.show_node(
                None if live_identity or saved_node else self.node
            )
        self.live_state = None
        self.live_mdf = None
        if (live_identity or saved_node) and self.logical_layout is not None:
            number = self.node if saved_node else self.node.node_number
            self.node_backups.show_live_node(self.logical_layout, number)
            if saved_node and self.node_backups.topLevelItemCount():
                latest = self.node_backups.topLevelItem(0).data(
                    0, Qt.ItemDataRole.UserRole
                )
                backup = load_node_backup(latest)
                self.node_events.offline_identities = {
                    f"{event['nodeNumber']}:{event['eventNumber']}"
                    for event in backup["events"]
                }
        else:
            self.node_backups.show_node(
                None if live_identity or saved_node else self.node
            )
        self.update_backup_buttons()

        enabled = current is not None and not saved_node
        self.edit_button.setEnabled(False)
        self.node_name.setEnabled(
            self.can_edit_annotations()
            and (self.annotations is not None or not live_identity and not saved_node)
        )
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
                self.summary.setTitle(f"Node {self.node}")
                self.node_events.show_produced_events(self.node)
        elif live_identity:
            self._show_live_identity(self.node)
        else:
            self._show_configured_node(self.node)
        self.update_connection_details()
        self.refresh_annotations()

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
        self.mdf_values.set_definition(None)
        self.variables.setCurrentIndex(0)
        self.raw_values.show_live_values(None, {})
        mode = "FLiM" if node.is_flim else "SLiM"
        self.details_page.show_live_identity(node, mode)
        self.summary.setTitle(f"Node {node.node_number} — -")
        self.summary_can_id.setText("CAN ID: -")
        self.summary_firmware.setText("Firmware: -")
        self.summary_mode.setText(f"Mode: {mode}")
        self.summary_status.setText("Status: -")

    def _show_configured_node(self, node) -> None:
        self.mdf_values.set_definition(PROTOTYPE_MDF)
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
            self.cancel_configuration()
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
        metadata = (
            self.saved_metadata.get(self.node, {}) if isinstance(self.node, int) else {}
        )
        parameters = {
            index: value
            for index, value in enumerate(metadata.get("parameters", []))
            if value is not None
        }
        if metadata and self.live_state is None:
            self.show_parameters(parameters)
            self.details_page.node_number.setText(str(self.node))
        is_can = (
            self.live_state.parameters.get(10) == 1
            if self.live_state is not None
            else parameters.get(10) == 1
        )
        self.details_page.show_can_id(is_can)
        self.summary_can_id.setVisible(is_can)
        can_id = (
            self.live_state.can_id
            if self.live_state is not None
            else metadata.get("canId")
        )
        status = "-"
        if self.node is not None:
            online = (
                self.connected
                and self.cbus_service is not None
                and self.cbus_service.presence.get(self.annotation_number(), False)
            )
            status = "Online" if online else "Offline"
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
        if self.annotations is not None:
            self.node_name.setEnabled(self.can_edit_annotations())

        live_node = self.node is not None and not isinstance(self.node, int)
        self.backup_buttons["New"].setEnabled(available and live_node)
        self.backup_buttons["View"].setEnabled(selected)
        self.backup_buttons["Compare"].setEnabled(available and selected)
        local_restore = False
        if selected and self.annotations is not None:
            backup = self.node_backups.selectedItems()[0].data(
                0, Qt.ItemDataRole.UserRole
            )
            if isinstance(backup, Path):
                backup = load_node_backup(backup)
            local_restore = "annotations" in backup
        self.backup_buttons["Restore"].setEnabled(
            (local_restore and not self.connected and not restoring)
            or available
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
        if self.annotations is not None and (
            not self.connected or isinstance(self.node, int)
        ):
            self.backup_workflow.restore_offline_annotations(self.node)
        elif isinstance(self.node, Pnn):
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
            if self.failure_report.coordinator in (
                self.cbus_service.nv_save,
                self.cbus_service.event_save,
            ):
                self.show_nv_values()
                self.node_events.show_live_state(
                    self.live_state, self.node_events.live_mdf
                )
        elif not success:
            if self.failure_report is not None:
                self.failure_report.dialog.close()
            self.failure_report = NodeFailureReport(self, self.cbus_service, message)
        if self.saving_configuration:
            trace(
                logger,
                "Node configuration application finished",
                extra={
                    "fields": {
                        "node_number": node_number,
                        "success": success,
                        "result": message,
                    }
                },
            )
            self.set_configuration_saving(False)
            self.show_configuration_result(f"Node {node_number}: {message}")
            self.cancel_configuration()
            self.events_edit_button.setEnabled(self.can_edit_configuration())
            self.update_backup_buttons()
            self.saving_nvs = False
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
