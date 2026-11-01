from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .backup_diff_tree import add_node_differences
from .node_backup_diff import compare_node


class BackupCompare(QDialog):
    def __init__(self, node, backup, parent=None):
        super().__init__(parent)

        self.setWindowTitle(f"Node {node.number} — Compare with current")
        self.resize(650, 450)

        layout = QVBoxLayout(self)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Item", "Backup", "Current"])
        tree.setColumnWidth(0, 250)
        layout.addWidget(tree)

        add_node_differences(tree, compare_node(node, backup))

        if tree.topLevelItemCount() == 0:
            QTreeWidgetItem(tree, ["No differences found"])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
