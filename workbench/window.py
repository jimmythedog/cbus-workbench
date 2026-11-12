import logging
import sys
import tomllib
from importlib import metadata
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from .annotations import Annotations
from .app_settings import (
    SettingsError,
    layout_settings_for_storage,
    layout_settings_for_ui,
    load_settings,
    save_settings,
    validate_layout_input,
)
from .application_directories_dialog import ApplicationDirectoriesDialog
from .cbus_service import CbusService, DiscoveryStatus
from .diagnostics import Diagnostics
from .layout_settings import LayoutSettingsDialog, collect_layout_settings
from .layout_view import LayoutView
from .logging_config import TRACE, trace
from .mmc_import_dialog import MmcImportDialog
from .node_metadata import save_metadata
from .observed_events import EventIdentity, ObservedEvents, decode_event
from .pnn import Pnn
from .send_event_dialog import SendEventDialog
from .send_frame_dialog import SendFrameDialog
from .serial_connection import SerialConnection
from .tcp_connection import TcpConnection
from .traffic import describe_frame
from .ui_errors import ErrorReporter

layout_logger = logging.getLogger("workbench.layouts")
connection_logger = logging.getLogger("workbench.connection")


class ConnectionStatusLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._closed = False
        self.error_reporter = ErrorReporter(self)

        if sys.platform == "linux":
            self.menuBar().setNativeMenuBar(False)

        self.setWindowTitle("CBUS Workbench")
        self.resize(1000, 700)

        self.layout_stack = QStackedWidget()
        self.layouts = {}
        self.observed_events = {}
        self.annotations = {}
        self.layout_settings = {}
        self.connections: dict[str, TcpConnection | SerialConnection] = {}
        self.cbus_services: dict[str, CbusService] = {}
        self.pending_ev_disconnects: set[str] = set()

        saved_settings = {"default_layout": None, "layouts": {}}

        def read_settings():
            nonlocal saved_settings
            saved_settings = load_settings()

        self.error_reporter.run("Could not load settings", read_settings)
        self.default_layout = saved_settings["default_layout"]
        self.layout_settings = layout_settings_for_ui(saved_settings["layouts"])

        for name in self.layout_settings:
            view = LayoutView(empty=True)
            self.layouts[name] = view
            self.bind_observed_events(name)
            self.layout_stack.addWidget(view)

        self.setCentralWidget(self.layout_stack)

        self.layout_status = QLabel("No layout")
        self.discovery_status = QLabel()
        self.connection_status = ConnectionStatusLabel("Disconnected")
        self.connection_status.setToolTip("Double-click to connect or disconnect")
        self.connection_status.double_clicked.connect(self.toggle_connection)

        self.discovery_separator = QFrame()
        connection_separator = QFrame()
        for separator in (self.discovery_separator, connection_separator):
            separator.setFrameShape(QFrame.Shape.VLine)
            separator.setFrameShadow(QFrame.Shadow.Sunken)
        for label in (
            self.layout_status,
            self.discovery_status,
            self.connection_status,
        ):
            label.setMargin(4)
        for widget in (
            self.layout_status,
            self.discovery_separator,
            self.discovery_status,
            connection_separator,
            self.connection_status,
        ):
            self.statusBar().addPermanentWidget(widget)
        self.discovery_status.hide()
        self.discovery_separator.hide()
        self.statusBar().setContentsMargins(0, 0, 12, 0)

        file_menu = self.menuBar().addMenu("&File")
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.layout_menu = self.menuBar().addMenu("&Layouts")
        self.layout_group = QActionGroup(self)
        self.layout_group.setExclusive(True)
        self.layout_group.triggered.connect(self.select_layout)

        new_action = QAction("&New…", self)
        new_action.triggered.connect(
            lambda: self.error_reporter.run("Could not create layout", self.new_layout)
        )
        self.layout_menu.addAction(new_action)

        import_action = self.layout_menu.addAction("Import MMC layouts…")
        import_action.triggered.connect(
            lambda: self.error_reporter.run(
                "Could not import MMC layouts", self.import_mmc_layouts
            )
        )

        self.edit_action = QAction("&Edit…", self)
        self.edit_action.triggered.connect(
            lambda: self.error_reporter.run("Could not update layout", self.edit_layout)
        )
        self.layout_menu.addAction(self.edit_action)

        self.delete_action = QAction("&Delete…", self)
        self.delete_action.triggered.connect(
            lambda: self.error_reporter.run(
                "Could not delete layout", self.delete_layout
            )
        )
        self.layout_menu.addAction(self.delete_action)

        self.set_default_action = QAction("Set as &default", self)
        self.set_default_action.triggered.connect(
            lambda: self.error_reporter.run(
                "Could not set default layout", self.set_selected_as_default
            )
        )
        self.layout_menu.addAction(self.set_default_action)

        self.layout_menu.addSeparator()

        self.connect_action = QAction("&Connect", self)
        self.connect_action.triggered.connect(self.connect_layout)
        self.layout_menu.addAction(self.connect_action)

        self.disconnect_action = QAction("&Disconnect", self)
        self.disconnect_action.triggered.connect(self.disconnect_layout)
        self.layout_menu.addAction(self.disconnect_action)

        self.refresh_layout_action = QAction("&Refresh", self)
        self.refresh_layout_action.triggered.connect(self.refresh_layout)
        self.layout_menu.addAction(self.refresh_layout_action)
        self.layout_menu.setToolTipsVisible(True)
        self.layout_menu.aboutToShow.connect(self.update_refresh_action)

        self.send_event_action = QAction("Send Event…", self)
        self.send_event_action.triggered.connect(self.show_send_event_dialog)
        self.layout_menu.addAction(self.send_event_action)
        self.send_frame_action = QAction("Send GridConnect Frame…", self)
        self.send_frame_action.triggered.connect(self.show_send_frame_dialog)
        self.layout_menu.addAction(self.send_frame_action)

        self.layout_menu.addSeparator()

        for name in self.layouts:
            action = QAction(name, self)
            action.setCheckable(True)
            action.setData(name)
            self.layout_group.addAction(action)
            self.layout_menu.addAction(action)

            if name == self.default_layout:
                action.setChecked(True)

        self.update_default_indicator()

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
        logging_menu = view_menu.addMenu("Logging Level")
        self.logging_group = QActionGroup(self)
        self.logging_group.setExclusive(True)
        self.logging_group.triggered.connect(self.change_logging_level)
        current_level = logging.getLogger("workbench").level
        for name, level in (
            ("Error", logging.ERROR),
            ("Warning", logging.WARNING),
            ("Info", logging.INFO),
            ("Debug", logging.DEBUG),
            ("Trace", TRACE),
        ):
            action = logging_menu.addAction(name)
            action.setCheckable(True)
            action.setData(level)
            self.logging_group.addAction(action)
            action.setChecked(level == current_level)

        help_menu = self.menuBar().addMenu("&Help")

        directories_action = QAction("Application Directories…", self)
        directories_action.triggered.connect(
            lambda: ApplicationDirectoriesDialog(self).exec()
        )
        help_menu.addAction(directories_action)

        about_action = QAction("&About CBUS Workbench…", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        self.update_connection_actions()
        self.update_layout_actions()
        selected = self.layout_group.checkedAction()
        if selected is not None:
            self.select_layout(selected)
        startup_layouts = tuple(
            name
            for name, settings in self.layout_settings.items()
            if settings["auto_connect"]
        )
        QTimer.singleShot(0, lambda: self.auto_connect_layouts(startup_layouts))

    def auto_connect_layouts(self, names: tuple[str, ...]) -> None:
        """Attempt each saved startup connection after the window is initialized."""
        if self._closed:
            return
        for name in names:
            self.error_reporter.run(
                f"Could not connect layout '{name}'",
                lambda name=name: self._connect_layout(name),
            )

    def change_logging_level(self, action: QAction) -> None:
        logger = logging.getLogger("workbench")
        previous_level = logger.level
        new_level = action.data()
        logger.setLevel(new_level)

        # Record the choice even when the new threshold would filter INFO.
        record = logger.makeRecord(
            logger.name,
            logging.INFO,
            __file__,
            0,
            "Logging level changed",
            (),
            None,
            extra={
                "fields": {
                    "previous_level": logging.getLevelName(previous_level),
                    "new_level": logging.getLevelName(new_level),
                }
            },
        )
        logger.handle(record)

    def set_connection_state(self, name: str, state: str) -> None:
        trace(
            connection_logger,
            "Entering set_connection_state",
            extra={"fields": {"layout": name, "state": state}},
        )
        previous_state = self.connection_states[name]
        self.connection_states[name] = state
        if (
            state == "Connected"
            and name in self.connections
            and name not in self.cbus_services
        ):
            self.start_cbus_service(name)
        elif state != "Connected":
            self.remove_cbus_service(name)
        self.layouts[name].set_connected(state == "Connected")
        self.update_connection_actions()
        self.update_layout_actions()
        if state == "Error":
            # Serial reports the error before closing its port.
            QTimer.singleShot(0, self.update_layout_actions)
        selected = self.layout_group.checkedAction()
        if selected is not None and selected.data() == name:
            self.statusBar().showMessage(f"Layout '{name}': {state.lower()}", 5000)
        fields = {
            "layout": name,
            "connection_type": self.layout_settings[name]["connection_type"],
            "previous_state": previous_state,
            "state": state,
        }
        if state != previous_state:
            connection_logger.info("Connection state changed", extra={"fields": fields})
        else:
            connection_logger.debug(
                "Connection state unchanged", extra={"fields": fields}
            )
        trace(
            connection_logger,
            "Leaving set_connection_state",
            extra={"fields": {"layout": name}},
        )

    def bind_observed_events(self, name: str) -> None:
        logical_layout = self.layout_settings[name]["logical_layout"]

        def bind():
            if logical_layout not in self.observed_events:
                self.observed_events[logical_layout] = ObservedEvents(logical_layout)
            self.layouts[name].set_observed_events(self.observed_events[logical_layout])
            if logical_layout not in self.annotations:
                self.annotations[logical_layout] = Annotations(logical_layout)
            self.layouts[name].set_annotations(self.annotations[logical_layout])

        self.error_reporter.run(f"Could not load observed events for '{name}'", bind)

    def start_cbus_service(self, name: str) -> None:
        connection = self.connections[name]
        service = CbusService(connection, self.layout_settings[name]["can_id"])
        service.event_received.connect(
            lambda identity: self.observe_event(name, identity)
        )
        service.node_discovered.connect(
            lambda node, layout=name: self.record_node_identity(layout, node)
        )
        service.node_updated.connect(
            lambda node, layout=name: self.record_node_identity(layout, node)
        )
        node_view = self.layouts[name].node_view
        service.set_node_poll_seconds(self.layout_settings[name]["node_poll_seconds"])
        service.presence = dict.fromkeys(node_view.saved_metadata, False)
        service.presence_changed.connect(node_view.refresh_presence)
        service.polling_allowed = lambda: (
            not node_view.editing
            and self.isEnabled()
            and QApplication.activeModalWidget() is None
        )
        node_view.details.cbus_service = service
        node_view.details.node_events.cbus_service = service
        self.layouts[name].layout_events.cbus_service = service
        service.restore.changed.connect(node_view.details.show_restore_progress)
        service.restore.finished.connect(node_view.details.finish_restore)
        node_view.details.logical_layout = self.layout_settings[name]["logical_layout"]
        node_view.state_lookup = lambda node_number: service.node_states.get(
            node_number
        )
        service.node_state_updated.connect(node_view.refresh_state)
        service.parameter_updated.connect(
            lambda number, _index, _value: (
                None
                if service.manual_refresh_node == number or service.refreshing_layout
                else self.error_reporter.run(
                    f"Could not save metadata for node {number} on layout '{name}'",
                    lambda: save_metadata(
                        self.layout_settings[name]["logical_layout"],
                        service.node_states[number],
                    ),
                )
            )
        )
        service.refresh_reported.connect(
            lambda number, outcome: self.statusBar().showMessage(
                f"Layout '{name}', node {number}: {outcome}", 10000
            )
        )
        service.layout_refresh_reported.connect(
            lambda outcome: self.statusBar().showMessage(
                f"Layout '{name}': {outcome}", 10000
            )
        )
        self.cbus_services[name] = service
        service.discovery_status_changed.connect(self.update_discovery_status)
        service.discovery_status_changed.connect(node_view.discovery_status_changed)
        service.discovery_status_changed.connect(
            lambda _status: self.update_refresh_action()
        )
        node_view.details.editing_changed.connect(
            lambda _editing: self.update_refresh_action()
        )
        self.layouts[name].discovery_states = lambda: (
            list(self.cbus_services[name].node_states.values())
            if name in self.cbus_services
            else []
        )

        self.error_reporter.run(
            f"Could not discover nodes on layout '{name}'", service.discover_nodes
        )

    def record_node_identity(self, name: str, node: Pnn) -> None:
        service = self.cbus_services[name]
        if (
            service.manual_refresh_node != node.node_number
            and not service.refreshing_layout
        ):
            self.error_reporter.run(
                f"Could not save metadata for node {node.node_number} on layout '{name}'",
                lambda: save_metadata(
                    self.layout_settings[name]["logical_layout"],
                    service.node_states[node.node_number],
                ),
            )
        self.layouts[name].node_view.show_identity(node)

    def observe_event(self, name: str, identity: EventIdentity) -> None:
        self.error_reporter.run(
            f"Could not save observed event on layout '{name}'",
            lambda: self.layouts[name].observed_events.observe(identity),
        )

    def record_frame(self, name: str, direction: str, frame: bytes) -> None:
        if direction == "TX":
            identity = decode_event(frame)
            if identity is not None:
                self.observe_event(name, identity)
        opcode, details = describe_frame(frame, name)
        self.diagnostics_dock.widget().add_message(direction, opcode, details)

    def remove_cbus_service(self, name: str) -> None:
        service = self.cbus_services.pop(name, None)
        if service is None:
            return
        details = self.layouts[name].node_view.details
        saving_configuration = details.saving_configuration
        service.close()
        # Closing the service completes an interrupted Save before rebuilding
        # selection. Keep its result through the resulting show_node() calls.
        save_result = details.nv_result.text() if saving_configuration else ""
        service.deleteLater()
        view = self.layouts[name]
        view.node_view.details.connected = False
        view.node_view.details.update_connection_details()
        view.node_view.details.cbus_service = None
        view.node_view.details.node_events.cbus_service = None
        view.layout_events.cbus_service = None
        view.node_view.clear_identities()
        logical_layout = self.layout_settings[name]["logical_layout"]
        view.node_view.details.logical_layout = logical_layout
        view.node_view.show_saved_nodes(logical_layout)
        if saving_configuration:
            details.show_configuration_result(save_result)
        connection_logger.info(
            "CBUS discovery state cleared", extra={"fields": {"layout": name}}
        )

    def connect_layout(self) -> None:
        action = self.layout_group.checkedAction()
        if action is None:
            return

        self._connect_layout(action.data())

    def _connect_layout(self, name: str) -> None:
        settings = self.layout_settings[name]
        serial = settings["connection_type"] == "Serial"
        endpoint = settings["serial_port"] if serial else settings["host"]
        if not endpoint:
            connection_logger.warning(
                "Connection skipped: endpoint is empty",
                extra={
                    "fields": {
                        "layout": name,
                        "connection_type": settings["connection_type"],
                    }
                },
            )
            QMessageBox.warning(
                self,
                "Connection failed",
                f"Set a {'serial device path' if serial else 'TCP host'} in Layout → Edit first.",
            )
            return

        connection = self.connections.get(name)
        if connection is None:
            connection = (
                SerialConnection(name, self) if serial else TcpConnection(name, self)
            )
            connection.state_changed.connect(
                lambda state, conn=connection: self.set_connection_state(
                    conn.layout_name, state
                )
            )
            connection.failed.connect(
                lambda message, conn=connection: self.connection_failed(conn, message)
            )
            connection.frame_sent.connect(
                lambda frame, conn=connection: self.record_frame(
                    conn.layout_name, "TX", frame
                )
            )
            connection.frame_received.connect(
                lambda frame, conn=connection: self.record_frame(
                    conn.layout_name, "RX", frame
                )
            )
            self.connections[name] = connection

        if serial:
            connection_logger.info(
                "Connecting to serial device",
                extra={"fields": {"layout": name, "device": endpoint}},
            )
            connection.connect(endpoint)
        else:
            connection_logger.info(
                "Connecting to TCP hub",
                extra={
                    "fields": {
                        "layout": name,
                        "host": endpoint,
                        "port": settings["port"],
                    }
                },
            )
            connection.connect(endpoint, settings["port"])

    def disconnect_layout(self) -> None:
        action = self.layout_group.checkedAction()
        if action is None:
            return
        name = action.data()
        connection = self.connections.get(name)
        if connection is not None:
            connection_logger.info(
                "Disconnecting layout", extra={"fields": {"layout": name}}
            )
            service = self.cbus_services.get(name)
            if service is not None and service.ev_write.active:
                if name in self.pending_ev_disconnects:
                    return
                self.pending_ev_disconnects.add(name)

                def disconnect_after_exit(_node, _success, _message):
                    service.ev_write.finished.disconnect(disconnect_after_exit)
                    self.pending_ev_disconnects.discard(name)
                    connection.disconnect()

                service.ev_write.finished.connect(disconnect_after_exit)
                service.ev_write.interrupt()
            else:
                connection.disconnect()

    def show_send_event_dialog(self) -> None:
        action = self.layout_group.checkedAction()
        service = self.cbus_services.get(action.data()) if action else None
        if service is not None and service.connection.state == "Connected":
            dialog = SendEventDialog(service, self)
            dialog.exec()
            dialog.deleteLater()

    def show_send_frame_dialog(self) -> None:
        action = self.layout_group.checkedAction()
        if action is None:
            return
        name = action.data()
        connection = self.connections.get(name)
        service = self.cbus_services.get(name)
        if service is not None and (
            service.restore.active
            or service.ev_write.active
            or service.ev_write.refreshing
        ):
            self.statusBar().showMessage(
                "Wait for Save or restore to finish before sending raw frames.", 5000
            )
            return
        if isinstance(connection, (TcpConnection, SerialConnection)):
            SendFrameDialog(name, connection, self).exec()

    def connection_failed(
        self, connection: TcpConnection | SerialConnection, message: str
    ) -> None:
        name = connection.layout_name
        settings = self.layout_settings[name]
        serial = settings["connection_type"] == "Serial"
        endpoint = (
            settings["serial_port"]
            if serial
            else f"{settings['host']}:{settings['port']}"
        )
        connection_logger.error(
            "%s connection failed: %s",
            settings["connection_type"],
            message,
            extra={"fields": {"layout": name, "endpoint": endpoint}},
        )
        QMessageBox.warning(
            self,
            "Connection failed",
            f"Connection for layout '{name}' to {endpoint} failed.\n\n{message}",
        )

    def update_discovery_status(self, _status: str = "") -> None:
        action = self.layout_group.checkedAction()
        service = self.cbus_services.get(action.data()) if action else None
        labels = {
            DiscoveryStatus.DISCOVERING: "Discovering…",
            DiscoveryStatus.READY: "Ready",
            DiscoveryStatus.INCOMPLETE: "Incomplete",
        }
        text = labels.get(service.discovery_status, "") if service else ""
        connected = (
            action is not None and self.connection_states[action.data()] == "Connected"
        )
        self.discovery_status.setText(text)
        self.discovery_status.setVisible(connected and bool(text))
        self.discovery_separator.setVisible(connected and bool(text))

    def update_refresh_action(self):
        action = self.layout_group.checkedAction()
        service = self.cbus_services.get(action.data()) if action else None
        reason = (
            service.refresh_unavailable_reason()
            if service
            else "Refresh requires a connected layout"
        )
        self.refresh_layout_action.setEnabled(not reason)
        self.refresh_layout_action.setToolTip(
            reason or "Reread this layout connection from hardware"
        )

    def refresh_layout(self):
        action = self.layout_group.checkedAction()
        service = self.cbus_services.get(action.data()) if action else None
        if service is not None:
            self.error_reporter.run("Could not refresh layout", service.refresh_layout)
        self.update_refresh_action()

    def update_connection_actions(self):
        self.update_discovery_status()
        self.update_refresh_action()
        action = self.layout_group.checkedAction()

        if action is None:
            self.connect_action.setEnabled(False)
            self.disconnect_action.setEnabled(False)
            self.send_frame_action.setEnabled(False)
            self.send_event_action.setEnabled(False)
            self.connection_status.setText("Disconnected")
            return

        state = self.connection_states[action.data()]

        self.connect_action.setEnabled(state in ("Disconnected", "Error"))
        self.disconnect_action.setEnabled(state in ("Connected", "Connecting"))
        self.send_frame_action.setEnabled(state == "Connected")
        self.send_event_action.setEnabled(state == "Connected")
        self.connection_status.setText(state)

    def update_layout_actions(self):
        action = self.layout_group.checkedAction()
        enabled = action is not None and self.layout_can_change(action.data())
        self.edit_action.setEnabled(action is not None)
        self.delete_action.setEnabled(enabled)
        self.set_default_action.setEnabled(
            action is not None and action.data() != self.default_layout
        )

    def update_default_indicator(self) -> None:
        for action in self.layout_group.actions():
            name = action.data()
            action.setText(f"{name} ★" if name == self.default_layout else name)

    def set_selected_as_default(self) -> None:
        action = self.layout_group.checkedAction()
        if action is None or action.data() == self.default_layout:
            return
        name = action.data()
        self.save_layouts(self.layout_settings, name)
        self.default_layout = name
        self.update_default_indicator()
        self.update_layout_actions()
        layout_logger.info("Default layout changed", extra={"fields": {"layout": name}})

    def layout_can_change(self, name: str) -> bool:
        state = self.connection_states[name]
        if state == "Disconnected":
            return True
        if state != "Error":
            return False
        connection = self.connections.get(name)
        if connection is None:
            return True
        if isinstance(connection, SerialConnection):
            return not connection.port.isOpen()
        return connection.socket.state() == QAbstractSocket.SocketState.UnconnectedState

    def save_layouts(self, layouts: dict, default_layout: str | None) -> None:
        """Write proposed layout settings before changing the window's state."""
        save_settings(
            {
                "default_layout": default_layout,
                "layouts": layout_settings_for_storage(layouts),
            }
        )

    def select_layout(self, action):
        name = action.data()
        previous_name = self.layout_status.text()
        trace(
            layout_logger, "Entering select_layout", extra={"fields": {"layout": name}}
        )
        self.bind_observed_events(name)
        self.layout_stack.setCurrentWidget(self.layouts[name])
        self.layouts[name].show_summary(name, self.layout_settings[name])
        self.layouts[name].show_live_layout(
            self.layout_settings[name]["logical_layout"],
            lambda: (
                list(self.cbus_services[name].node_states.values())
                if name in self.cbus_services
                else []
            ),
        )
        self.layouts[name].set_connected(self.connection_states[name] == "Connected")
        self.layout_status.setText(name)
        self.update_connection_actions()
        self.update_layout_actions()
        if name != previous_name:
            layout_logger.info(
                "Layout selected",
                extra={"fields": {"layout": name, "previous_layout": previous_name}},
            )
        else:
            layout_logger.debug(
                "Layout already selected", extra={"fields": {"layout": name}}
            )
        trace(
            layout_logger, "Leaving select_layout", extra={"fields": {"layout": name}}
        )

    def validate_layout_settings(self, settings, current_name=None):
        try:
            validate_layout_input(settings, self.layout_settings, current_name)
        except SettingsError as error:
            layout_logger.debug("Layout settings rejected: %s", error)
            self.statusBar().showMessage(str(error), 5000)
            return False
        return True

    def import_mmc_layouts(self):
        dialog = MmcImportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        plan = dialog.result_plan
        proposed = layout_settings_for_ui(plan.settings["layouts"])
        for name in tuple(self.layouts):
            if self.layout_settings[name] != proposed[name]:
                action = next(
                    action
                    for action in self.layout_group.actions()
                    if action.data() == name
                )
                self._apply_saved_layout_edit(
                    name, proposed[name], plan.settings["default_layout"], action
                )
                service = self.cbus_services.get(name)
                if service is not None:
                    service.set_node_poll_seconds(proposed[name]["node_poll_seconds"])
        self.layout_settings = proposed
        self.default_layout = plan.settings["default_layout"]
        for target in plan.targets:
            if target.new:
                self.add_saved_layout(target.name, self.layout_settings[target.name])
        # Notify all views sharing a destination, without starting any service.
        affected = {target.logical_layout for target in plan.targets}
        # The importer saved through its own ObservedEvents instances. Reload once
        # per destination, then bind every view sharing that logical layout.
        for logical_layout in affected:
            self.observed_events.pop(logical_layout, None)
        for name, settings in self.layout_settings.items():
            if settings["logical_layout"] in affected:
                self.bind_observed_events(name)
                self.layouts[name].node_view.details.logical_layout = settings[
                    "logical_layout"
                ]
                self.layouts[name].node_view.show_saved_nodes(
                    settings["logical_layout"]
                )
                self.layouts[name].annotations_changed(-1)
                for target in plan.targets:
                    if target.logical_layout == settings["logical_layout"]:
                        for number in target.source.nodes:
                            self.layouts[name].annotations_changed(number)
        self.update_default_indicator()
        if plan.targets:
            selected = next(
                action
                for action in self.layout_group.actions()
                if action.data() == plan.targets[-1].name
            )
            selected.setChecked(True)
            self.select_layout(selected)
        self.update_layout_actions()
        self.statusBar().showMessage(
            f"Imported {len(plan.targets)} MMC layout(s)", 5000
        )

    def add_saved_layout(self, name: str, settings: dict) -> QAction:
        """Register a successfully saved layout without opening a connection."""
        view = LayoutView(empty=True)
        self.layouts[name] = view
        self.layout_settings[name] = settings
        self.layout_stack.addWidget(view)
        self.connection_states[name] = "Disconnected"
        action = QAction(name, self)
        action.setCheckable(True)
        action.setData(name)
        self.layout_group.addAction(action)
        self.layout_menu.addAction(action)
        return action

    def new_layout(self):
        trace(layout_logger, "Entering new_layout")
        try:
            settings = collect_layout_settings(self, self.layout_settings)
        except SettingsError as error:
            layout_logger.debug("New layout rejected: %s", error)
            self.statusBar().showMessage(str(error), 5000)
            return
        if settings is None:
            return
        name = settings["name"]

        default_layout = self.default_layout if self.layouts else name
        proposed = self.layout_settings.copy()
        proposed[name] = settings
        self.save_layouts(proposed, default_layout)

        self.default_layout = default_layout
        action = self.add_saved_layout(name, settings)

        action.setChecked(True)
        self.select_layout(action)
        self.update_default_indicator()
        self.update_layout_actions()

        self.statusBar().showMessage(f"Layout '{name}' created", 5000)
        layout_logger.info(
            "Layout created",
            extra={
                "fields": {
                    "layout": name,
                    "connection_type": settings["connection_type"],
                    "can_id": settings["can_id"],
                }
            },
        )
        trace(layout_logger, "Leaving new_layout", extra={"fields": {"layout": name}})

    def edit_layout(self):
        trace(layout_logger, "Entering edit_layout")
        action = self.layout_group.checkedAction()

        if action is None:
            trace(layout_logger, "Edit layout skipped: no layout selected")
            return

        old_name = action.data()
        current = self.layout_settings[old_name]
        settings = self._edited_layout_settings(old_name, current)
        if settings is None:
            return
        name = settings["name"]

        if not self.layout_can_change(old_name):
            # Never rebuild the live view or change its endpoint/identity here.
            if any(
                settings[key] != current[key]
                for key in current
                if key != "node_poll_seconds"
            ):
                self.statusBar().showMessage(
                    "Disconnect before changing connection settings", 5000
                )
                return
            proposed = self.layout_settings.copy()
            proposed[old_name] = settings
            self.save_layouts(proposed, self.default_layout)
            self.layout_settings[old_name] = settings
            service = self.cbus_services.get(old_name)
            if service is not None:
                service.set_node_poll_seconds(settings["node_poll_seconds"])
            self._log_layout_edit(old_name, settings)
            self.statusBar().showMessage(f"Layout '{old_name}' updated", 5000)
            return

        proposed = self.layout_settings.copy()
        del proposed[old_name]
        proposed[name] = settings
        default_layout = (
            name if self.default_layout == old_name else self.default_layout
        )
        self.save_layouts(proposed, default_layout)

        self._apply_saved_layout_edit(old_name, settings, default_layout, action)
        self._log_layout_edit(old_name, settings)
        trace(layout_logger, "Leaving edit_layout", extra={"fields": {"layout": name}})

    def _edited_layout_settings(self, old_name: str, current: dict) -> dict | None:
        """Collect valid dialog settings, returning to the form after a declined change."""

        dialog = LayoutSettingsDialog(
            self,
            **current,
            connection_active=not self.layout_can_change(old_name),
            logical_layouts=sorted(
                {
                    settings["logical_layout"]
                    for settings in self.layout_settings.values()
                }
            ),
        )

        while True:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                trace(
                    layout_logger,
                    "Edit layout cancelled",
                    extra={"fields": {"layout": old_name}},
                )
                return

            settings = dialog.settings()

            if not self.validate_layout_settings(settings, old_name):
                trace(
                    layout_logger,
                    "Edit layout rejected",
                    extra={"fields": {"layout": old_name}},
                )
                return

            logical_layout_changed = (
                settings["logical_layout"] != current["logical_layout"]
            )
            if logical_layout_changed and not self._confirm_logical_layout_change(
                old_name
            ):
                continue
            return settings

    def _confirm_logical_layout_change(self, old_name: str) -> bool:
        answer = QMessageBox.question(
            self,
            "Change logical layout",
            "This layout will use a different stored node configuration and "
            "backup directory. Existing data will not be moved or deleted. "
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            layout_logger.info(
                "Logical layout change cancelled",
                extra={"fields": {"layout": old_name}},
            )
            return False
        return True

    def _apply_saved_layout_edit(
        self, old_name: str, settings: dict, default_layout: str, action: QAction
    ) -> None:
        """Update connection and window state only after the settings save succeeds."""
        current = self.layout_settings[old_name]
        name = settings["name"]

        old_endpoint = (
            current["serial_port"]
            if current["connection_type"] == "Serial"
            else (current["host"], current["port"])
        )
        new_endpoint = (
            settings["serial_port"]
            if settings["connection_type"] == "Serial"
            else (settings["host"], settings["port"])
        )
        if (
            current["connection_type"] != settings["connection_type"]
            or old_endpoint != new_endpoint
        ):
            # A changed endpoint must not keep the old connection open.
            self.close_layout_connection(old_name)

        if name != old_name:
            self.layouts[name] = self.layouts.pop(old_name)
            self.connection_states[name] = self.connection_states.pop(old_name)
            if old_name in self.connections:
                connection = self.connections.pop(old_name)
                connection.layout_name = name
                self.connections[name] = connection
            action.setData(name)
            self.layout_status.setText(name)

        self.default_layout = default_layout
        self.update_default_indicator()
        del self.layout_settings[old_name]
        self.layout_settings[name] = settings
        self.layouts[name].show_summary(name, settings)
        self.bind_observed_events(name)
        self.layouts[name].show_live_layout(
            settings["logical_layout"],
            lambda: (
                list(self.cbus_services[name].node_states.values())
                if name in self.cbus_services
                else []
            ),
        )
        self.update_connection_actions()

        self.statusBar().showMessage(f"Layout '{name}' updated", 5000)

    def _log_layout_edit(self, old_name: str, settings: dict) -> None:
        name = settings["name"]
        if name != old_name:
            layout_logger.info(
                "Layout renamed",
                extra={
                    "fields": {
                        "old_layout": old_name,
                        "layout": name,
                        "connection_type": settings["connection_type"],
                        "can_id": settings["can_id"],
                        "node_poll_seconds": settings["node_poll_seconds"],
                    }
                },
            )
        else:
            layout_logger.debug(
                "Layout name unchanged", extra={"fields": {"layout": name}}
            )
            layout_logger.info(
                "Layout settings updated",
                extra={
                    "fields": {
                        "layout": name,
                        "connection_type": settings["connection_type"],
                        "can_id": settings["can_id"],
                        "node_poll_seconds": settings["node_poll_seconds"],
                    }
                },
            )

    def delete_layout(self):
        trace(layout_logger, "Entering delete_layout")
        action = self.layout_group.checkedAction()

        if action is None:
            trace(layout_logger, "Delete layout skipped: no layout selected")
            return

        name = action.data()
        if not self.layout_can_change(name):
            layout_logger.info(
                "Delete layout skipped: connection is active",
                extra={"fields": {"layout": name}},
            )
            return

        answer = QMessageBox.question(
            self,
            "Delete layout",
            f"Delete layout '{name}'? Its logical layout data will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            trace(
                layout_logger,
                "Delete layout cancelled",
                extra={"fields": {"layout": name}},
            )
            return

        if not self.layout_can_change(name):
            layout_logger.info(
                "Delete layout skipped: connection became active",
                extra={"fields": {"layout": name}},
            )
            return

        proposed = self.layout_settings.copy()
        del proposed[name]
        default_layout = (
            next(iter(proposed), None)
            if self.default_layout == name
            else self.default_layout
        )
        self.save_layouts(proposed, default_layout)

        self.close_layout_connection(name)
        self.default_layout = default_layout

        # Remove the layout and its menu action.
        view = self.layouts.pop(name)
        del self.layout_settings[name]
        del self.connection_states[name]

        self.layout_group.removeAction(action)
        self.layout_menu.removeAction(action)
        action.deleteLater()
        self.update_default_indicator()

        # removeWidget keeps the page parented; deleteLater frees it on event loop return.
        self.layout_stack.removeWidget(view)
        view.deleteLater()

        # Select another layout, if one remains.
        if self.layouts:
            next_name = next(iter(self.layouts))

            for remaining_action in self.layout_group.actions():
                if remaining_action.data() == next_name:
                    remaining_action.setChecked(True)
                    self.select_layout(remaining_action)
                    break
        else:
            self.layout_status.setText("No layout")

        self.update_layout_actions()
        self.update_connection_actions()

        self.statusBar().showMessage(f"Layout '{name}' deleted", 5000)
        layout_logger.info("Layout deleted", extra={"fields": {"layout": name}})
        trace(
            layout_logger, "Leaving delete_layout", extra={"fields": {"layout": name}}
        )

    def toggle_connection(self):
        trace(connection_logger, "Entering toggle_connection")
        action = self.layout_group.checkedAction()

        if action is None:
            trace(connection_logger, "Toggle connection skipped: no layout selected")
            return

        state = self.connection_states[action.data()]

        if state in ("Disconnected", "Error"):
            self.connect_layout()
        elif state in ("Connected", "Connecting"):
            self.disconnect_layout()
        trace(
            connection_logger,
            "Leaving toggle_connection",
            extra={"fields": {"layout": action.data()}},
        )

    def close_layout_connection(self, name: str) -> None:
        self.remove_cbus_service(name)
        connection = self.connections.pop(name, None)
        if connection is not None:
            connection.disconnect()
            connection.deleteLater()

    def closeEvent(self, event) -> None:
        self._closed = True
        for name in tuple(self.connections):
            self.close_layout_connection(name)
        super().closeEvent(event)

    def show_about(self):
        try:
            version = metadata.version("cbus-workbench")
        except metadata.PackageNotFoundError:
            # Direct source runs (including NixOS) need no installation.
            source_config = Path(__file__).resolve().parents[1] / "pyproject.toml"
            try:
                with source_config.open("rb") as config:
                    version = tomllib.load(config)["project"]["version"]
            except OSError, tomllib.TOMLDecodeError, KeyError:
                version = "Development"
        trace(logging.getLogger("workbench"), "Showing About: version=%s", version)
        QMessageBox.about(
            self,
            "About CBUS Workbench",
            "<h3>CBUS Workbench</h3>"
            f"<p>Version: {version}</p>"
            "<p>A desktop application for configuring and managing "
            "CBUS/VLCB model railway networks.</p>"
            "<p>Built with Python and PySide6.</p>",
        )
