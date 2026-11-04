import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .backup_diff_tree import add_node_differences
from .cbus_service import NodeState
from .logging_config import trace
from .node_backup_diff import compare_live_node, compare_node


class BackupCompare(QDialog):
    def __init__(self, node, backup, parent=None):
        super().__init__(parent)

        number = (
            node.identity.node_number
            if isinstance(node, NodeState)
            else getattr(node, "number", backup.get("node"))
        )
        self.setWindowTitle(f"Node {number} — Compare with current")
        self.resize(650, 450)

        layout = QVBoxLayout(self)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Item", "Backup", "Current"])
        tree.setColumnWidth(0, 250)
        layout.addWidget(tree)

        if "format_version" in backup:
            if isinstance(node, NodeState):
                differences, inconclusive = compare_live_node(node, backup)
            else:
                differences, inconclusive = [], True
        else:
            differences, inconclusive = compare_node(node, backup), False
        add_node_differences(tree, differences)
        if inconclusive:
            QTreeWidgetItem(tree, ["Comparison inconclusive: some values are unknown"])
        trace(
            logging.getLogger("workbench.backups"),
            "Node backup compared",
            extra={
                "fields": {
                    "node_number": number,
                    "differences": len(differences),
                    "inconclusive": inconclusive,
                }
            },
        )

        if tree.topLevelItemCount() == 0:
            QTreeWidgetItem(tree, ["No differences found"])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
