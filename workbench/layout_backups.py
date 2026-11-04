from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyle, QTreeWidget, QTreeWidgetItem

from .node_backup_files import list_backups


class LayoutBackups(QTreeWidget):
    def __init__(self, empty=False):
        super().__init__()

        self.setHeaderLabels(["Created", "Description"])
        self.setColumnWidth(0, 200)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)

        # Dummy layout backups until persistence is implemented.
        backups = [
            {
                "created": "31 Oct 2026, 14:30",
                "description": "Before layout changes",
                "nodeNumbers": [256, 258, 259, 261],
                "eventCatalogue": {
                    0: {
                        30001: "Yard lighting",
                        30002: "Platform lighting",
                    },
                    256: {
                        1: "Main line signal",
                        302: "Turnout reached midpoint",
                    },
                    259: {
                        1: "Accessory command",
                    },
                },
            },
            {
                "created": "29 Oct 2026, 10:15",
                "description": "Initial configuration",
                "nodeNumbers": [256, 258, 259, 261],
                "eventCatalogue": {
                    0: {
                        30001: "Yard lighting",
                        30002: "Platform lighting",
                    },
                    256: {
                        1: "Main line signal",
                        302: "Turnout reached midpoint",
                    },
                    259: {
                        1: "Accessory command",
                    },
                },
            },
            {
                "created": "25 Oct 2026, 15:25",
                "description": "Full layout backup",
                "nodeNumbers": [256, 258, 259, 261],
                "eventCatalogue": {
                    0: {
                        30001: "Yard lighting",
                        30002: "Platform lighting",
                    },
                    256: {
                        1: "Main line signal",
                        302: "Turnout reached midpoint",
                    },
                    259: {
                        1: "Accessory command",
                    },
                },
            },
        ]

        if not empty:
            for backup in backups:
                item = QTreeWidgetItem(self, [backup["created"], backup["description"]])
                item.setData(0, Qt.ItemDataRole.UserRole, backup)

    def show_live_layout(self, logical_layout):
        self.clear()
        self.setHeaderLabels(["Filename", "Description"])
        self.setColumnWidth(0, 340)
        for path, complete, description in list_backups(logical_layout):
            item = QTreeWidgetItem(self, [path.name, description])
            item.setToolTip(0, str(path))
            if not complete:
                item.setIcon(
                    0,
                    self.style().standardIcon(
                        QStyle.StandardPixmap.SP_MessageBoxWarning
                    ),
                )
                item.setToolTip(
                    0,
                    "Configuration discovery was incomplete when this backup was created.",
                )
            item.setData(0, Qt.ItemDataRole.UserRole, path)

    def add_backup(self, backup):
        item = QTreeWidgetItem(
            self,
            [backup["created"], backup["description"]],
        )
        item.setData(0, Qt.ItemDataRole.UserRole, backup)
        self.insertTopLevelItem(
            0, self.takeTopLevelItem(self.indexOfTopLevelItem(item))
        )
        self.setCurrentItem(item)

    def delete_backup(self, backup):
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)

            if item.data(0, Qt.ItemDataRole.UserRole) == backup:
                self.takeTopLevelItem(index)
                break
