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
from .node_snapshot import create_node_snapshot, restore_node_snapshot
from .node_view import NodeView


class LayoutView(QWidget):
    def __init__(self, empty=False):
        super().__init__()

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
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.node_view = NodeView(self.events)
        self.tabs.addTab(self.node_view, "Nodes")

        self.layout_events = LayoutEvents([], self.events)

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

        self.node_view.details.editing_changed.connect(self.on_editing_changed)
        self.layout_events.editing_changed.connect(self.on_layout_events_editing)

    def nodes(self):
        return [
            self.node_view.node_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.node_view.node_list.count())
        ]

    def on_tab_changed(self, index):
        if index == self.tabs.indexOf(self.node_view):
            node_events = self.node_view.details.node_events
            node_events.show_node(node_events.node)

    def on_editing_changed(self, editing):
        self.tabs.setTabEnabled(self.tabs.indexOf(self.layout_events), not editing)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.backups_page), not editing)

    def on_layout_events_editing(self, editing):
        self.tabs.setTabEnabled(self.tabs.indexOf(self.node_view), not editing)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.backups_page), not editing)

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

        dialog = LayoutBackupCompare(
            backup,
            self.nodes(),
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
