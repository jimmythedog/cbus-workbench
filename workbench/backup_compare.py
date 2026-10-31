from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

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

        sections = {}

        for section_name, item_name, old, new in compare_node(node, backup):
            if section_name not in sections and not section_name.startswith(
                "Consumed events/"
            ):
                section = QTreeWidgetItem([section_name])
                tree.addTopLevelItem(section)
                section.setExpanded(True)
                sections[section_name] = section

            section = sections.get(section_name)

            # Preserve the event grouping within consumed events.
            if section_name.startswith("Consumed events/"):
                event_id = section_name.split("/", 1)[1]
                parent = sections.get("Consumed events")

                if parent is None:
                    parent = QTreeWidgetItem(["Consumed events"])
                    tree.addTopLevelItem(parent)
                    parent.setExpanded(True)
                    sections["Consumed events"] = parent

                event_key = f"event:{event_id}"
                event = sections.get(event_key)

                if event is None:
                    event = QTreeWidgetItem([event_id])
                    parent.addChild(event)
                    event.setExpanded(True)
                    sections[event_key] = event

                section = event

            QTreeWidgetItem(
                section,
                [
                    item_name,
                    str(old) if old is not None else "—",
                    str(new) if new is not None else "—",
                ],
            )

        if tree.topLevelItemCount() == 0:
            QTreeWidgetItem(tree, ["No differences found"])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
