from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSplitter

from .node_details import NodeDetails
from .pnn import Pnn


class NodeView(QSplitter):
    def __init__(self, events):
        super().__init__(Qt.Orientation.Horizontal)

        self.node_list = QListWidget()

        self.details = NodeDetails(events)

        self.node_list.currentItemChanged.connect(self.details.show_node)

        self.details.editing_changed.connect(
            lambda editing: self.node_list.setEnabled(not editing)
        )

        self.addWidget(self.node_list)
        self.addWidget(self.details)
        self.setSizes([250, 750])

    def show_identity(self, node: Pnn) -> None:
        """Update a PNN identity without changing the selected list item."""
        for index in range(self.node_list.count()):
            item = self.node_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole).node_number == node.node_number:
                item.setData(Qt.ItemDataRole.UserRole, node)
                item.setText(f"{node.node_number} - {node.module_type}")
                if item is self.node_list.currentItem():
                    self.details.show_node(item)
                return

        item = QListWidgetItem(f"{node.node_number} - {node.module_type}")
        item.setData(Qt.ItemDataRole.UserRole, node)
        self.node_list.addItem(item)

    def clear_identities(self) -> None:
        self.node_list.clear()
