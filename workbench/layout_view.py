from copy import deepcopy
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .backup_view import backup_contents
from .layout_backup_compare import LayoutBackupCompare
from .layout_backup_view import LayoutBackupView
from .layout_backups import LayoutBackups
from .layout_events import LayoutEvents
from .layout_restore_dialog import LayoutRestoreDialog
from .node_snapshot import create_node_snapshot
from .node_view import NodeView


class LayoutView(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

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

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.node_view = NodeView(self.events)
        self.tabs.addTab(self.node_view, "Nodes")

        nodes = [
            self.node_view.node_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.node_view.node_list.count())
        ]

        self.layout_events = LayoutEvents(nodes, self.events)

        self.tabs.addTab(self.layout_events, "Events")

        self.layout_backups = LayoutBackups()
        self.node_view.details.node_backups.layout_backups = self.layout_backups

        backups_page = QWidget()
        backups_layout = QVBoxLayout(backups_page)
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

        self.tabs.addTab(backups_page, "Backups")

        layout.addWidget(self.tabs)

        self.node_view.details.editing_changed.connect(self.on_editing_changed)
        self.layout_events.editing_changed.connect(self.on_layout_events_editing)

    def on_tab_changed(self, index):
        if index == 0:  # Nodes tab
            node_events = self.node_view.details.node_events
            node_events.show_node(node_events.node)

    def on_editing_changed(self, editing):
        self.tabs.setTabEnabled(1, not editing)  # Events
        self.tabs.setTabEnabled(2, not editing)  # Backups

    def on_layout_events_editing(self, editing):
        self.tabs.setTabEnabled(0, not editing)  # Nodes
        self.tabs.setTabEnabled(2, not editing)  # Backups

    def update_backup_buttons(self):
        selected = bool(self.layout_backups.selectedItems())

        for name, button in self.backup_buttons.items():
            if name != "New":
                button.setEnabled(selected)

    def view_backup(self):
        selected = self.layout_backups.selectedItems()
        if not selected:
            return

        backup = selected[0].data(0, Qt.ItemDataRole.UserRole)

        dialog = LayoutBackupView(backup, self)
        dialog.exec()

    def compare_backup(self):
        selected = self.layout_backups.selectedItems()
        if not selected:
            return

        backup = selected[0].data(0, Qt.ItemDataRole.UserRole)

        nodes = [
            self.node_view.node_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.node_view.node_list.count())
        ]

        dialog = LayoutBackupCompare(
            backup,
            nodes,
            self.events,
            self.node_view.details.node_backups,
            self,
        )
        dialog.exec()

    def new_backup(self):
        description, accepted = QInputDialog.getText(
            self,
            "New layout backup",
            "Description (optional):",
        )

        if not accepted:
            return

        nodes = [
            self.node_view.node_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.node_view.node_list.count())
        ]

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
            for backups in node_backups.backups_by_node.values():
                backups[:] = [
                    snapshot
                    for snapshot in backups
                    if not (
                        snapshot.get("partOfLayoutBackup")
                        and snapshot.get("timestamp") == timestamp
                    )
                ]

        self.layout_backups.delete_backup(backup)
        node_backups.show_node(self.node_view.details.node)

        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage("Layout backup deleted", 5000)

    def restore_backup(self):
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

        nodes = [
            self.node_view.node_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.node_view.node_list.count())
        ]

        # Locate snapshots only for the selected nodes.
        snapshots = {}

        for node in nodes:
            if node.number not in selected_nodes:
                continue

            for snapshot in node_backups.backups_by_node.get(node.number, []):
                if (
                    snapshot.get("partOfLayoutBackup")
                    and snapshot.get("timestamp") == timestamp
                ):
                    snapshots[node.number] = snapshot
                    break

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

            node.nv_values = deepcopy(contents["nv_values"])
            node.nv_descriptions = deepcopy(contents["nv_descriptions"])
            node.consumed_events = deepcopy(contents["consumed_events"])
            node.ev_values = deepcopy(contents["ev_values"])

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
