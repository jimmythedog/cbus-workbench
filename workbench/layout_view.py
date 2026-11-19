import logging
from datetime import datetime
from pathlib import Path

import yaml
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .annotations import Annotations
from .backup_view import backup_contents
from .configuration_load import load_online_configuration
from .event_consumers import find_consumers
from .layout_backup_compare import LayoutBackupCompare
from .layout_backup_view import LayoutBackupView
from .layout_backup_workflow import create_layout_backup
from .layout_backups import LayoutBackups
from .layout_events import LayoutEvents
from .layout_restore_dialog import LayoutRestoreDialog
from .layout_restore_selection import LayoutRestoreSelection
from .layout_restore_workflow import LayoutRestoreWorkflow
from .logging_config import trace
from .mdf_tokens import substitute_tokens
from .node_snapshot import create_node_snapshot, restore_node_snapshot
from .node_view import NodeView, node_number

logger = logging.getLogger("workbench.ui")


class LayoutSummaryLabel(QLabel):
    """Keep Qt's tab-corner size hint compact even for long endpoint names."""

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(min(hint.width(), 480), hint.height())

    def minimumSizeHint(self):
        return QSize(0, self.sizeHint().height())


class LayoutView(QWidget):
    def __init__(self, empty=False):
        super().__init__()

        self.connected = False
        self.logical_layout = None
        self.discovery_states = list
        self.tab_before_discovery = 0

        layout = QVBoxLayout(self)

        if not empty:
            self.events = {
                0: {
                    30001: {},
                    30002: {},
                },
                256: {
                    1: {},
                    2: {},
                    302: {"description": "turnout1 reached mid point"},
                },
                259: {
                    1: {},
                },
            }
        else:
            self.events = {}

        self.tabs = QTabWidget()
        self.layout_summary = LayoutSummaryLabel()
        self.layout_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.layout_summary.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.layout_summary.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.tabs.setCornerWidget(self.layout_summary, Qt.Corner.TopRightCorner)
        self.node_view = NodeView(self.events)
        self.tabs.addTab(self.node_view, "Nodes")

        self.layout_events = LayoutEvents([], self.events)
        self.layout_events.teach_requested.connect(self.teach_event)

        self.tabs.addTab(self.layout_events, "Events")

        self.layout_backups = LayoutBackups(empty=empty)
        self.node_view.details.node_backups.layout_backups = self.layout_backups

        self.backups_page = QWidget()
        backups_layout = QVBoxLayout(self.backups_page)
        backups_layout.addWidget(self.layout_backups, 1)

        actions = QHBoxLayout()
        actions.addStretch()

        self.backup_buttons = {}

        for name in ("New", "View", "Compare", "Restore", "Delete"):
            button = QPushButton(name)
            button.setEnabled(name == "New")
            actions.addWidget(button)
            self.backup_buttons[name] = button

        self.backup_buttons["View"].clicked.connect(self.view_backup)
        self.backup_buttons["Compare"].clicked.connect(self.compare_backup)
        self.backup_buttons["New"].clicked.connect(self.new_backup)
        self.backup_buttons["Delete"].clicked.connect(self.delete_backup)
        self.backup_buttons["Restore"].clicked.connect(self.restore_backup)

        backups_layout.addLayout(actions)

        self.layout_backups.itemSelectionChanged.connect(self.update_backup_buttons)

        self.tabs.addTab(self.backups_page, "Backups")

        layout.addWidget(self.tabs)

        for consumers in self.consumer_trees():
            consumers.lookup = self.find_consumers
            consumers.open_node = self.open_consumer
            consumers.mdf_lookup = self.consumer_mdf

        self.node_view.details.editing_changed.connect(self.on_editing_changed)
        self.node_view.discovering_changed.connect(self.on_discovering_changed)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.update_backup_buttons()

    def set_observed_events(self, observations):
        """Bind both live event panes to the same layout collection."""
        previous = getattr(self, "observed_events", None)
        if previous is observations:
            return
        if previous is not None:
            previous.changed.disconnect(self.refresh_observed_events)
        self.observed_events = observations
        self.layout_events.observed_events = observations
        self.node_view.details.node_events.observed_events = observations
        observations.changed.connect(self.refresh_observed_events)
        self.refresh_observed_events()

    def set_annotations(self, annotations):
        previous = getattr(self, "annotations", None)
        if previous is annotations:
            return
        if previous is not None:
            previous.changed.disconnect(self.annotations_changed)
        self.annotations = annotations
        self.layout_events.annotations = annotations
        self.node_view.details.annotations = annotations
        self.node_view.details.node_events.annotations = annotations
        annotations.changed.connect(self.annotations_changed)
        self.annotations_changed(-1)

    def annotations_changed(self, number):
        # Consumer rows reuse the navigator's names, so refresh those first.
        self.node_view.refresh_annotation_names(number)
        if number == -1:
            self.refresh_observed_events()
        else:
            # A node or token rename changes expanded consumers' labels.
            for consumers in self.consumer_trees():
                consumers.refresh(rebuild=True)
        details = self.node_view.details
        if (
            details.live_state is not None
            and number == details.annotation_number()
            and not details.annotation_editing
            and details.desired_configuration is None
        ):
            details.show_live_state(details.live_state, details.live_mdf)

    def refresh_observed_events(self):
        self.layout_events.refresh()
        details = self.node_view.details
        if details.node is not None:
            details.node_events.show_produced_events(node_number(details.node))

    def show_summary(self, name, settings):
        """Show configured values independently of the connection's current status."""
        if settings["connection_type"] == "Serial":
            device = "Auto" if settings["auto_select"] else settings["serial_port"]
            endpoint = f"Device: {device}"
        else:
            endpoint = f"Host: {settings['host']}  Port: {settings['port']}"
        summary = f"{name} — {endpoint}  CAN ID: {settings['can_id']}"
        self.layout_summary.setText(summary)
        self.layout_summary.setToolTip(summary)

    def show_live_layout(self, logical_layout, discovery_states):
        if self.logical_layout is not None and self.logical_layout != logical_layout:
            self.node_view.clear_identities()
        self.logical_layout = logical_layout
        if (
            getattr(self, "annotations", None) is None
            or self.annotations.logical_layout != logical_layout
        ):
            self.set_annotations(Annotations(logical_layout))
        self.discovery_states = discovery_states
        self.node_view.details.logical_layout = logical_layout
        self.node_view.show_saved_nodes(logical_layout)
        self.layout_backups.show_live_layout(logical_layout)
        self.update_backup_buttons()

    def nodes(self):
        return [
            self.node_view.node_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.node_view.node_list.count())
        ]

    def on_tab_changed(self, index):
        if index == self.tabs.indexOf(self.backups_page) and self.logical_layout:
            self.layout_backups.show_live_layout(self.logical_layout)
        # finish_discovery() restores selection; a suspended (empty) selection
        # must not blank the details when a disabled tab returns focus to Nodes.
        if (
            index == self.tabs.indexOf(self.node_view)
            and not self.node_view.discovering
        ):
            self.node_view.show_selected_node(self.node_view.node_list.currentItem())

    def select_node(self, number) -> bool:
        self.tabs.setCurrentWidget(self.node_view)
        node_list = self.node_view.node_list
        for index in range(node_list.count()):
            item = node_list.item(index)
            if node_number(item.data(Qt.ItemDataRole.UserRole)) == number:
                node_list.setCurrentItem(item)
                return True
        return False

    def teach_event(self, number, identity):
        """Open the target node's Consumed Events editor with a pending event."""
        self.select_node(number)
        self.node_view.details.start_new_event(number, identity)

    def consumer_trees(self):
        return (
            self.layout_events.consumers,
            self.node_view.details.node_events.produced_consumers,
        )

    def find_consumers(self, identity):
        """This connection's discovery, plus saved nodes as undetermined (#87)."""
        node_list = self.node_view.node_list
        names = {
            node_number(item.data(Qt.ItemDataRole.UserRole)): item.display_label
            for item in (node_list.item(row) for row in range(node_list.count()))
        }
        return find_consumers(identity, self.node_view.details.cbus_service, names)

    def consumer_mdf(self, number):
        """A consumer's MDF as Consumed Events presents it, or None for raw EVs.

        Selected from the same confirmed identity and parameters, with the
        node's token renames; never from saved or observed data.
        """
        service = self.node_view.details.cbus_service
        state = service.node_states.get(number) if service is not None else None
        if state is None or not state.identity_confirmed:
            return None
        try:
            mdf = self.node_view.mdf_repository.lookup(state.identity, state.parameters)
            if mdf is None:
                return None
            annotations = getattr(self, "annotations", None)
            if annotations is None:
                return mdf.data
            return substitute_tokens(
                mdf.data, annotations.load(number).get("tokens", {})
            )
        except ValueError, KeyError, TypeError, OSError, yaml.YAMLError:
            # MdfError is a ValueError; annotation reads can fail with OS or
            # YAML errors. The node keeps its raw EVs.
            logger.exception(
                "Consumer MDF unavailable",
                extra={
                    "fields": {"layout": self.logical_layout, "node_number": number}
                },
            )
            return None

    def refresh_consumers(self, *_args):
        """Consumed-event discovery, Save or Restore changed; presence changed."""
        for consumers in self.consumer_trees():
            consumers.refresh()

    def open_consumer(self, number, identity):
        """Show a consuming node's Consumed Events with the event selected."""
        # Node selection is suspended while editing or discovering.
        unavailable = self.node_view.editing or self.node_view.discovering
        if unavailable or not self.select_node(number):
            trace(
                logger,
                "Open consuming node ignored",
                extra={
                    "fields": {
                        "layout": self.logical_layout,
                        "node": number,
                        "selection_unavailable": unavailable,
                    }
                },
            )
            window = self.window()
            if isinstance(window, QMainWindow):
                window.statusBar().showMessage(f"Cannot open node {number} now", 5000)
            return
        details = self.node_view.details
        details.tabs.setCurrentWidget(details.consumed_events_page)
        details.node_events.select_event(identity)
        trace(
            logger,
            "Opened consuming node",
            extra={
                "fields": {
                    "layout": self.logical_layout,
                    "node": number,
                    "identity": identity,
                    "selected": details.node_events.selected_identity(),
                }
            },
        )

    def on_editing_changed(self, _editing):
        self.update_tab_availability()

    def on_discovering_changed(self, discovering):
        """Show this layout as busy while its node selection is suspended."""
        # A widget cursor (not an application override) is scoped to this layout,
        # so other layouts, menus and Disconnect stay usable and nothing can leak.
        if discovering:
            # Disabling the current tab makes Qt move to Nodes; return afterwards.
            self.tab_before_discovery = self.tabs.currentIndex()
            self.setCursor(Qt.CursorShape.WaitCursor)
        else:
            self.unsetCursor()
        self.update_tab_availability()
        if not discovering and self.tabs.isTabEnabled(self.tab_before_discovery):
            self.tabs.setCurrentIndex(self.tab_before_discovery)
        trace(
            logger,
            "Layout busy cursor changed",
            extra={
                "fields": {
                    "layout": self.logical_layout,
                    "discovering": discovering,
                    "tab": self.tabs.currentIndex(),
                }
            },
        )

    def update_tab_availability(self):
        # Events (Teach) and Backups would navigate or read nodes mid-discovery.
        available = not (self.node_view.editing or self.node_view.discovering)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.layout_events), available)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.backups_page), available)

    def update_backup_buttons(self):
        selected = bool(self.layout_backups.selectedItems())

        self.backup_buttons["New"].setEnabled(self.connected)
        self.backup_buttons["View"].setEnabled(selected)
        self.backup_buttons["Compare"].setEnabled(self.connected and selected)
        self.backup_buttons["Restore"].setEnabled(selected)
        self.backup_buttons["Delete"].setEnabled(False)

    def set_connected(self, connected):
        self.connected = connected
        self.node_view.details.connected = connected
        self.node_view.details.update_connection_details()
        self.node_view.details.update_backup_buttons()
        self.update_backup_buttons()
        self.refresh_consumers()

    def view_backup(self):
        selected = self.layout_backups.selectedItems()
        if not selected:
            return

        backup = selected[0].data(0, Qt.ItemDataRole.UserRole)

        manifest_path = backup if isinstance(backup, Path) else None
        if isinstance(backup, Path):
            with backup.open(encoding="utf-8") as stream:
                backup = yaml.safe_load(stream)
        dialog = LayoutBackupView(backup, self, manifest_path=manifest_path)
        dialog.exec()

    def load_live_configuration(self) -> bool:
        """Backups and comparisons cover whole nodes; False if disconnected."""
        service = self.node_view.details.cbus_service
        return service is None or load_online_configuration(self, service)

    def compare_backup(self):
        if not self.connected:
            return
        selected = self.layout_backups.selectedItems()
        if not selected:
            return

        backup = selected[0].data(0, Qt.ItemDataRole.UserRole)

        manifest_path = backup if isinstance(backup, Path) else None
        if manifest_path is not None:
            if not self.load_live_configuration():
                return
            with manifest_path.open(encoding="utf-8") as stream:
                backup = yaml.safe_load(stream)

        dialog = LayoutBackupCompare(
            backup,
            self.discovery_states() if manifest_path is not None else self.nodes(),
            self.events,
            self.node_view.details.node_backups,
            self,
            manifest_path=manifest_path,
        )
        dialog.exec()

    def new_backup(self):
        if not self.connected:
            return
        if self.logical_layout is not None:
            if not self.load_live_configuration():
                return
            path = create_layout_backup(
                self, self.logical_layout, self.discovery_states()
            )
            if path is not None:
                self.layout_backups.show_live_layout(self.logical_layout)
                window = self.window()
                if isinstance(window, QMainWindow):
                    window.statusBar().showMessage(f"Layout backup saved: {path}", 5000)
            return
        description, accepted = QInputDialog.getText(
            self,
            "New layout backup",
            "Description (optional):",
        )

        if not accepted:
            return

        nodes = self.nodes()

        now = datetime.now()
        timestamp = now.strftime("%Y%m%dT%H%M%S%f")

        backup = {
            "timestamp": timestamp,
            "created": now.strftime("%d %b %Y, %H:%M"),
            "description": description.strip(),
            "nodeNumbers": [node.number for node in nodes],
            "eventCatalogue": {
                node_number: {
                    event_number: details.get("description", "")
                    for event_number, details in events.items()
                }
                for node_number, events in self.events.items()
            },
        }
        node_backups = self.node_view.details.node_backups

        for node in nodes:
            snapshot = create_node_snapshot(node)
            snapshot["timestamp"] = timestamp
            snapshot["created"] = backup["created"]
            snapshot["partOfLayoutBackup"] = True

            node_backups.add_backup(node, snapshot)

        self.layout_backups.add_backup(backup)
        node_backups.show_node(self.node_view.details.node)

        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage("Layout backup created", 5000)

    def delete_backup(self):
        selected = self.layout_backups.selectedItems()
        if not selected:
            return

        backup = selected[0].data(0, Qt.ItemDataRole.UserRole)

        answer = QMessageBox.question(
            self,
            "Delete layout backup",
            f"Delete layout backup '{backup['description']}' and its associated node backups?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        timestamp = backup.get("timestamp")
        node_backups = self.node_view.details.node_backups

        if timestamp is not None:
            node_backups.delete_layout_snapshots(timestamp)

        self.layout_backups.delete_backup(backup)
        node_backups.show_node(self.node_view.details.node)

        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage("Layout backup deleted", 5000)

    def restore_backup(self):
        selected = self.layout_backups.selectedItems()
        path = selected[0].data(0, Qt.ItemDataRole.UserRole) if selected else None
        if isinstance(path, Path):
            service = self.node_view.details.cbus_service
            try:
                selection = LayoutRestoreSelection(self, service, path)
                try:
                    selection.start()
                    accepted = selection.dialog.exec() == QDialog.DialogCode.Accepted
                    chosen = selection.dialog.selected_nodes()
                    selection.dispose()
                    if accepted and (
                        chosen or selection.dialog.annotations_checkbox.isChecked()
                    ):
                        LayoutRestoreWorkflow(
                            self,
                            service,
                            {number: selection.backups[number] for number in chosen},
                            annotations=self.annotations
                            if selection.dialog.annotations_checkbox.isChecked()
                            else None,
                            layout_annotations=selection.manifest.get("annotations"),
                            restore_configuration=selection.dialog.configuration_checkbox.isChecked(),
                            configuration_nodes=selection.dialog.selected_configuration_nodes(),
                        ).run()
                finally:
                    selection.dispose()
                    selection.dialog.deleteLater()
                    selection.deleteLater()
            except (ValueError, OSError, yaml.YAMLError) as error:
                logging.getLogger("workbench.ui").exception(
                    "Layout restore selection failed",
                    extra={
                        "fields": {"path": str(path), "layout": self.logical_layout}
                    },
                )
                QMessageBox.warning(self, "Cannot check layout backup", str(error))
            return
        self.restore_prototype_backup()

    def restore_prototype_backup(self):
        selected = self.layout_backups.selectedItems()
        if not selected:
            return

        backup = selected[0].data(0, Qt.ItemDataRole.UserRole)
        timestamp = backup.get("timestamp")

        if timestamp is None:
            QMessageBox.information(
                self,
                "Restore layout backup",
                "This dummy backup has no associated node snapshots and cannot be restored.",
            )
            return

        dialog = LayoutRestoreDialog(backup["nodeNumbers"], self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected_nodes = dialog.selected_nodes()
        restore_events = dialog.restore_events()

        node_backups = self.node_view.details.node_backups

        nodes = self.nodes()

        # Locate snapshots only for the selected nodes.
        snapshots = {}

        for node in nodes:
            if node.number not in selected_nodes:
                continue

            snapshot = node_backups.layout_snapshot(node.number, timestamp)
            if snapshot is not None:
                snapshots[node.number] = snapshot

        if set(snapshots) != selected_nodes:
            QMessageBox.warning(
                self,
                "Restore layout backup",
                "Some selected node snapshots are missing. Nothing has been restored.",
            )
            return

        # Restore the selected node configurations.
        for node in nodes:
            snapshot = snapshots.get(node.number)
            if snapshot is None:
                continue

            contents = backup_contents(snapshot)

            restore_node_snapshot(node, contents)

        # Restore produced events independently.
        if restore_events:
            self.events.clear()

            for node_number, events in backup["eventCatalogue"].items():
                self.events[node_number] = {
                    event_number: {"description": description}
                    for event_number, description in events.items()
                }

            self.layout_events.refresh()

        # Refresh the currently displayed node, if any.
        current_node = self.node_view.details.node

        if current_node is not None:
            self.node_view.details.raw_values.show_node(current_node)
            self.node_view.details.mdf_values.show_node(current_node)
            self.node_view.details.node_events.show_node(current_node)

        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage("Layout backup restored successfully", 5000)
