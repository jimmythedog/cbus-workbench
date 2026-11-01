from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class NodeBackups(QTreeWidget):
    def __init__(self):
        super().__init__()

        self.setHeaderLabels(["Created", "Description"])
        self.setColumnWidth(0, 200)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.backups_by_node = {}
        self.layout_backups = None

    def show_node(self, node):
        self.clear()

        if node is None:
            return

        # Dummy backups until persistence is implemented.
        # Each backup contains its own saved configuration.
        backups = [
            {
                "created": "31 Oct 2026, 14:30",
                "description": "Before servo changes",
                "node_details": {
                    "number": node.number,
                    "module_type": node.module_type,
                    "can_id": 125,
                    "firmware": node.firmware,
                },
                "nv_values": {1: 0, 2: 5, 3: 128, 4: 10, 5: 1},
                "consumed_events": {
                    "256:302": "Turnout reached midpoint",
                },
                "ev_values": {
                    "256:302": {1: 3, 2: 10},
                },
                "nv_descriptions": {
                    2: "Servo configuration",
                },
                "annotations": {
                    "name": "Goods Yard",
                },
            },
            {
                "created": "29 Oct 2026, 10:15",
                "description": "Initial configuration",
                "node_details": {
                    "number": node.number,
                    "module_type": node.module_type,
                    "can_id": node.can_id,
                    "firmware": node.firmware,
                },
                "nv_values": {1: 0, 2: 0, 3: 128, 4: 10, 5: 1},
                "consumed_events": {
                    "256:302": "Turnout reached midpoint",
                },
                "ev_values": {
                    "256:302": {1: 3, 2: 10},
                },
                "nv_descriptions": {
                    2: "Servo configuration",
                },
                "annotations": {
                    "name": "Goods Yard",
                },
            },
            {
                "created": "25 Oct 2026, 15:25",
                "description": "Layout backup",
                "node_details": {
                    "number": node.number,
                    "module_type": node.module_type,
                    "can_id": node.can_id,
                    "firmware": node.firmware,
                },
                "nv_values": {1: 0, 2: 0, 3: 100, 4: 10, 5: 1},
                "consumed_events": {
                    "256:302": "Turnout reached midpoint",
                },
                "ev_values": {
                    "256:302": {1: 2, 2: 10},
                },
                "nv_descriptions": {
                    2: "Original servo configuration",
                },
                "annotations": {
                    "name": "Goods Yard",
                },
            },
        ]

        if node.number not in self.backups_by_node:
            self.backups_by_node[node.number] = backups

        backups = self.backups_by_node[node.number]

        for backup in backups:
            description = backup.get("description", "")

            if backup.get("partOfLayoutBackup") and self.layout_backups is not None:
                timestamp = backup.get("timestamp")

                for index in range(self.layout_backups.topLevelItemCount()):
                    layout_item = self.layout_backups.topLevelItem(index)
                    layout_backup = layout_item.data(0, Qt.ItemDataRole.UserRole)

                    if layout_backup.get("timestamp") == timestamp:
                        description = layout_backup.get("description", "")
                        break

            item = QTreeWidgetItem(self, [backup["created"], description])
            item.setData(0, Qt.ItemDataRole.UserRole, backup)

    def add_backup(self, node, backup):
        if node.number not in self.backups_by_node:
            self.show_node(node)

        backups = self.backups_by_node[node.number]
        backups.insert(0, backup)

        if self.isVisible():
            self.show_node(node)
            item = self.topLevelItem(0)
            if item is not None:
                self.setCurrentItem(item)

    def delete_backup(self, node, backup):
        backups = self.backups_by_node[node.number]
        backups.remove(backup)
        self.show_node(node)

    def layout_snapshot(self, node_number, timestamp):
        for snapshot in self.backups_by_node.get(node_number, []):
            if (
                snapshot.get("partOfLayoutBackup")
                and snapshot.get("timestamp") == timestamp
            ):
                return snapshot

        return None

    def delete_layout_snapshots(self, timestamp):
        for backups in self.backups_by_node.values():
            backups[:] = [
                snapshot
                for snapshot in backups
                if not (
                    snapshot.get("partOfLayoutBackup")
                    and snapshot.get("timestamp") == timestamp
                )
            ]
