from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .backup_view import add_configuration_items, backup_contents
from .node_backup_files import load_layout_node


class LayoutBackupView(QDialog):
    def __init__(self, backup, parent=None, *, manifest_path=None):
        super().__init__(parent)

        self.setWindowTitle("Layout backup contents")
        self.resize(750, 500)

        layout = QVBoxLayout(self)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Item", "Value"])
        tree.setColumnWidth(0, 300)
        layout.addWidget(tree)

        if manifest_path is not None:
            QTreeWidgetItem(
                tree, ["Discovery", "Complete" if backup["complete"] else "Incomplete"]
            )
            for number in backup["nodeNumbers"]:
                node = load_layout_node(manifest_path, number)
                item = QTreeWidgetItem(
                    tree,
                    [
                        f"Node {node['node']}",
                        "Complete" if node["complete"] else "Incomplete",
                    ],
                )
                add_configuration_items(item, backup_contents(node))
                item.setExpanded(True)
        else:
            self._show_prototype(tree, backup)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_prototype(self, tree, backup):
        details = QTreeWidgetItem(tree, ["Backup"])
        QTreeWidgetItem(details, ["Created", backup["created"]])
        QTreeWidgetItem(details, ["Description", backup["description"]])
        details.setExpanded(True)

        nodes = QTreeWidgetItem(tree, ["Nodes"])

        for number in backup["nodeNumbers"]:
            QTreeWidgetItem(nodes, [f"Node {number}"])

        nodes.setExpanded(True)

        events = QTreeWidgetItem(tree, ["Produced events"])

        for node_number, node_events in backup["eventCatalogue"].items():
            node_item = QTreeWidgetItem(events, [f"Node {node_number}"])

            for event_number, description in node_events.items():
                QTreeWidgetItem(
                    node_item,
                    [f"Event {event_number}", description],
                )

        events.setExpanded(True)
