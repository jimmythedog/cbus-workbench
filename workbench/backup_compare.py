import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .backup_diff_tree import add_node_differences, set_comparison_headings
from .cbus_service import NodeState
from .configuration_compare import NodeComparison
from .logging_config import trace
from .node_backup_diff import compare_live_configuration, compare_node


class BackupCompare(QDialog):
    def __init__(
        self,
        node,
        backup,
        parent=None,
        *,
        headings=("Backup", "Current"),
        comparison=None,
        message="",
        retry_action=None,
    ):
        super().__init__(parent)

        number = (
            node.identity.node_number
            if isinstance(node, NodeState)
            else getattr(node, "number", backup.get("node"))
        )
        self.setWindowTitle(f"Node {number} — Compare with current")
        self.resize(650, 450)

        layout = QVBoxLayout(self)

        self.message = QLabel(message)
        self.message.setWordWrap(True)
        self.message.setVisible(bool(message))
        layout.addWidget(self.message)

        tree = self.tree = QTreeWidget()
        set_comparison_headings(tree, headings)
        tree.setColumnWidth(0, 250)
        layout.addWidget(tree)

        if comparison is not None:
            differences, inconclusive = comparison, comparison.inconclusive
        elif "format_version" in backup:
            if isinstance(node, NodeState):
                differences = compare_live_configuration(node, backup)
                inconclusive = differences.inconclusive
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
                    "differences": sum(
                        row.outcome == "different" for row in differences.rows
                    )
                    if isinstance(differences, NodeComparison)
                    else len(differences),
                    "inconclusive": inconclusive,
                }
            },
        )

        if tree.topLevelItemCount() == 0:
            QTreeWidgetItem(tree, ["No differences found"])

        self.retry_status = QLabel()
        self.retry_status.setWordWrap(True)
        self.retry_status.hide()
        layout.addWidget(self.retry_status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.retry_button = None
        if retry_action is not None:
            self.retry_button = buttons.addButton(
                "Retry", QDialogButtonBox.ButtonRole.ActionRole
            )
            self.retry_button.clicked.connect(retry_action)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def show_result(self, comparison, message):
        """Replace presentation data; the caller retains all operation ownership."""
        self.message.setText(message)
        self.message.show()
        self.tree.clear()
        add_node_differences(self.tree, comparison)
        if comparison.inconclusive:
            QTreeWidgetItem(
                self.tree, ["Comparison inconclusive: some values are unknown"]
            )
        elif self.tree.topLevelItemCount() == 0:
            QTreeWidgetItem(self.tree, ["No differences found"])
