from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .node_backup_diff import compare_node


class LayoutBackupCompare(QDialog):
    def __init__(self, backup, nodes, events, node_backups, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Layout backup — Compare with current")
        self.resize(750, 500)

        layout = QVBoxLayout(self)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Item", "Backup", "Current"])
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tree.setColumnWidth(0, 250)
        layout.addWidget(tree)

        # Compare node membership.
        saved_nodes = set(backup["nodeNumbers"])
        current_nodes = {node.number for node in nodes}

        node_section = QTreeWidgetItem(["Nodes"])

        for number in sorted(saved_nodes | current_nodes):
            if (number in saved_nodes) != (number in current_nodes):
                QTreeWidgetItem(
                    node_section,
                    [
                        f"Node {number}",
                        "Not found" if number not in saved_nodes else "",
                        "Not found" if number not in current_nodes else "",
                    ],
                )

        if node_section.childCount():
            tree.addTopLevelItem(node_section)
            node_section.setExpanded(True)

        # Compare configurations in the associated node snapshots.
        configuration_section = QTreeWidgetItem(["Node configurations"])
        timestamp = backup.get("timestamp")

        if timestamp is not None:
            for node in nodes:
                if node.number not in saved_nodes:
                    continue

                snapshots = node_backups.backups_by_node.get(node.number, [])

                snapshot = next(
                    (
                        item
                        for item in snapshots
                        if item.get("partOfLayoutBackup")
                        and item.get("timestamp") == timestamp
                    ),
                    None,
                )

                if snapshot is None:
                    continue

                differences = compare_node(node, snapshot)

                if not differences:
                    continue

                node_item = QTreeWidgetItem([f"Node {node.number}"])
                configuration_section.addChild(node_item)
                node_item.setExpanded(True)

                sections = {}

                for section_name, item_name, old, new in differences:
                    if section_name.startswith("Consumed events/"):
                        event_id = section_name.split("/", 1)[1]

                        parent = sections.get("Consumed events")
                        if parent is None:
                            parent = QTreeWidgetItem(node_item, ["Consumed events"])
                            sections["Consumed events"] = parent
                            parent.setExpanded(True)

                        event_key = f"event:{event_id}"
                        section = sections.get(event_key)

                        if section is None:
                            section = QTreeWidgetItem(parent, [event_id])
                            sections[event_key] = section
                            section.setExpanded(True)
                    else:
                        section = sections.get(section_name)

                        if section is None:
                            section = QTreeWidgetItem(node_item, [section_name])
                            sections[section_name] = section
                            section.setExpanded(True)

                    QTreeWidgetItem(
                        section,
                        [
                            item_name,
                            str(old) if old is not None else "—",
                            str(new) if new is not None else "—",
                        ],
                    )

        if configuration_section.childCount():
            tree.addTopLevelItem(configuration_section)
            configuration_section.setExpanded(True)
        # Compare produced event descriptions.
        event_section = QTreeWidgetItem(["Produced events"])

        saved_events = backup["eventCatalogue"]

        for node_number in sorted(saved_events.keys() | events.keys()):
            saved = saved_events.get(node_number, {})
            current = events.get(node_number, {})

            node_item = QTreeWidgetItem([f"Node {node_number}"])

            for event_number in sorted(saved.keys() | current.keys()):
                old = saved.get(event_number)
                new = current.get(event_number)

                # Current events store their descriptions in dictionaries.
                if isinstance(new, dict):
                    new = new.get("description", "")

                if old != new:
                    QTreeWidgetItem(
                        node_item,
                        [
                            f"Event {event_number}",
                            str(old) if old is not None else "—",
                            str(new) if new is not None else "—",
                        ],
                    )

            if node_item.childCount():
                event_section.addChild(node_item)
                node_item.setExpanded(True)

        if event_section.childCount():
            tree.addTopLevelItem(event_section)
            event_section.setExpanded(True)

        if tree.topLevelItemCount() == 0:
            QTreeWidgetItem(tree, ["No differences found"])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
