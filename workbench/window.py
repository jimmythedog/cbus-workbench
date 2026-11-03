import logging
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from .app_settings import load_settings, save_settings
from .diagnostics import Diagnostics
from .layout_settings import LayoutSettingsDialog
from .layout_view import LayoutView
from .logging_config import TRACE, trace
from .send_frame_dialog import SendFrameDialog
from .serial_connection import SerialConnection
from .tcp_connection import TcpConnection
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
        self.layout_settings = {}
        self.connections: dict[str, TcpConnection | SerialConnection] = {}

        saved_settings = {"default_layout": None, "layouts": {}}

        def read_settings():
            nonlocal saved_settings
            saved_settings = load_settings()

        self.error_reporter.run("Could not load settings", read_settings)
        self.default_layout = saved_settings["default_layout"]

        for name, saved in saved_settings["layouts"].items():
            view = LayoutView(empty=True)
            self.layouts[name] = view
            self.layout_stack.addWidget(view)

            connection = saved["connection"]
            self.layout_settings[name] = {
                "name": name,
                "logical_layout": saved["logical_layout"],
                "connection_type": connection["type"],
                "host": connection["host"],
                "port": connection["port"],
                "serial_port": connection["serial_port"],
                "auto_connect": saved["auto_connect"],
            }

        self.setCentralWidget(self.layout_stack)

        self.layout_status = QLabel("No layout")
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
        new_action.triggered.connect(
            lambda: self.error_reporter.run("Could not create layout", self.new_layout)
        )
        self.layout_menu.addAction(new_action)

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
            for name, saved in saved_settings["layouts"].items()
            if saved["auto_connect"]
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
            connection.disconnect()

    def show_send_frame_dialog(self) -> None:
        action = self.layout_group.checkedAction()
        if action is None:
            return
        name = action.data()
        connection = self.connections.get(name)
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

    def update_connection_actions(self):
        action = self.layout_group.checkedAction()

        if action is None:
            self.connect_action.setEnabled(False)
            self.disconnect_action.setEnabled(False)
            self.send_frame_action.setEnabled(False)
            self.connection_status.setText("Disconnected")
            return

        state = self.connection_states[action.data()]

        self.connect_action.setEnabled(state in ("Disconnected", "Error"))
        self.disconnect_action.setEnabled(state in ("Connected", "Connecting"))
        self.send_frame_action.setEnabled(state == "Connected")
        self.connection_status.setText(state)

    def update_layout_actions(self):
        action = self.layout_group.checkedAction()
        enabled = action is not None and self.layout_can_change(action.data())
        self.edit_action.setEnabled(enabled)
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
        stored = {
            name: {
                "logical_layout": settings["logical_layout"],
                "auto_connect": settings["auto_connect"],
                "connection": {
                    "type": settings["connection_type"],
                    "host": settings["host"],
                    "port": settings["port"],
                    "serial_port": settings["serial_port"],
                },
            }
            for name, settings in layouts.items()
        }
        save_settings({"default_layout": default_layout, "layouts": stored})

    def select_layout(self, action):
        name = action.data()
        previous_name = self.layout_status.text()
        trace(
            layout_logger, "Entering select_layout", extra={"fields": {"layout": name}}
        )
        self.layout_stack.setCurrentWidget(self.layouts[name])
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
        name = settings["name"]

        if not name or not settings["logical_layout"]:
            layout_logger.debug(
                "Layout settings rejected: required field missing",
                extra={"fields": {"layout": name}},
            )
            self.statusBar().showMessage(
                "Layout name and logical layout are required", 5000
            )
            return False

        if any(
            existing.casefold() == name.casefold()
            for existing in self.layouts
            if existing != current_name
        ):
            layout_logger.debug(
                "Layout settings rejected: duplicate name",
                extra={"fields": {"layout": name}},
            )
            self.statusBar().showMessage("A layout with that name already exists", 5000)
            return False

        return True

    def new_layout(self):
        trace(layout_logger, "Entering new_layout")
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
            trace(layout_logger, "New layout cancelled")
            return

        settings = dialog.settings()
        name = settings["name"]

        if not self.validate_layout_settings(settings):
            trace(
                layout_logger, "New layout rejected", extra={"fields": {"layout": name}}
            )
            return

        default_layout = self.default_layout if self.layouts else name
        proposed = self.layout_settings.copy()
        proposed[name] = settings
        self.save_layouts(proposed, default_layout)

        view = LayoutView(empty=True)
        self.default_layout = default_layout
        self.layouts[name] = view
        self.layout_settings[name] = settings
        self.layout_stack.addWidget(view)

        action = QAction(name, self)
        action.setCheckable(True)
        action.setData(name)
        self.layout_group.addAction(action)
        self.layout_menu.addAction(action)

        action.setChecked(True)
        self.connection_states[name] = "Disconnected"
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
        if not self.layout_can_change(old_name):
            layout_logger.info(
                "Edit layout skipped: connection is active",
                extra={"fields": {"layout": old_name}},
            )
            return
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

        while True:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                trace(
                    layout_logger,
                    "Edit layout cancelled",
                    extra={"fields": {"layout": old_name}},
                )
                return

            settings = dialog.settings()
            name = settings["name"]

            if not self.validate_layout_settings(settings, old_name):
                trace(
                    layout_logger,
                    "Edit layout rejected",
                    extra={"fields": {"layout": old_name}},
                )
                return

            if settings["logical_layout"] != current["logical_layout"]:
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
                    continue
            break

        if not self.layout_can_change(old_name):
            layout_logger.info(
                "Edit layout skipped: connection became active",
                extra={"fields": {"layout": old_name}},
            )
            return

        proposed = self.layout_settings.copy()
        del proposed[old_name]
        proposed[name] = settings
        default_layout = (
            name if self.default_layout == old_name else self.default_layout
        )
        self.save_layouts(proposed, default_layout)

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
        self.update_connection_actions()

        self.statusBar().showMessage(f"Layout '{name}' updated", 5000)
        if name != old_name:
            layout_logger.info(
                "Layout renamed",
                extra={
                    "fields": {
                        "old_layout": old_name,
                        "layout": name,
                        "connection_type": settings["connection_type"],
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
                    }
                },
            )
        trace(layout_logger, "Leaving edit_layout", extra={"fields": {"layout": name}})

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
        QMessageBox.about(
            self,
            "About CBUS Workbench",
            "<h3>CBUS Workbench</h3>"
            "<p>A desktop application for configuring and managing "
            "CBUS/VLCB model railway networks.</p>"
            "<p>Built with Python and PySide6.</p>",
        )
