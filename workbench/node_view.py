import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSplitter

from .cbus_service import NodeState
from .logging_config import trace
from .node_backup_files import saved_node_numbers
from .node_details import NodeDetails
from .pnn import Pnn


def node_number(node):
    return node if isinstance(node, int) else node.node_number


logger = logging.getLogger("workbench.ui")


class NodeListItem(QListWidgetItem):
    def __lt__(self, other):
        return node_number(self.data(Qt.ItemDataRole.UserRole)) < node_number(
            other.data(Qt.ItemDataRole.UserRole)
        )


class NodeView(QSplitter):
    def __init__(self, events):
        super().__init__(Qt.Orientation.Horizontal)

        self.node_list = QListWidget()
        self.node_list.setSortingEnabled(True)

        self.details = NodeDetails(events)
        self.state_lookup: Callable[[int], NodeState] | None = None

        self.node_list.currentItemChanged.connect(self.show_selected_node)

        self.details.editing_changed.connect(
            lambda editing: self.node_list.setEnabled(not editing)
        )

        self.addWidget(self.node_list)
        self.addWidget(self.details)
        self.setSizes([250, 750])

    def show_selected_node(self, current, _previous=None) -> None:
        self.details.show_node(current)
        if current is not None and self.state_lookup is not None:
            node = current.data(Qt.ItemDataRole.UserRole)
            if isinstance(node, Pnn):
                self.details.show_live_state(self.state_lookup(node.node_number))

    def refresh_state(self, node_number: int) -> None:
        """Read current service state for the selected node after a change."""
        current = self.node_list.currentItem()
        if current is None or self.state_lookup is None:
            return
        node = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(node, Pnn) and node.node_number == node_number:
            self.details.show_live_state(self.state_lookup(node_number))

    def show_identity(self, node: Pnn) -> None:
        """Update a PNN identity without changing the selected list item."""
        for index in range(self.node_list.count()):
            item = self.node_list.item(index)
            if node_number(item.data(Qt.ItemDataRole.UserRole)) == node.node_number:
                item.setData(Qt.ItemDataRole.UserRole, node)
                item.setText(f"{node.node_number} - {node.module_type}")
                if item is self.node_list.currentItem():
                    self.show_selected_node(item)
                return

        first_node = self.node_list.count() == 0
        item = NodeListItem(f"{node.node_number} - {node.module_type}")
        item.setData(Qt.ItemDataRole.UserRole, node)
        self.node_list.addItem(item)
        if first_node:
            self.node_list.setCurrentItem(item)
            trace(
                logger,
                "First discovered node selected",
                extra={"fields": {"node_number": node.node_number}},
            )

    def clear_identities(self) -> None:
        self.state_lookup = None
        self.node_list.clear()

    def show_saved_nodes(self, logical_layout):
        """Reuse the navigator without retaining identities or discovery values."""
        for number in saved_node_numbers(logical_layout):
            if any(
                node_number(self.node_list.item(i).data(Qt.ItemDataRole.UserRole))
                == number
                for i in range(self.node_list.count())
            ):
                continue
            item = NodeListItem(f"{number} (offline)")
            item.setData(Qt.ItemDataRole.UserRole, number)
            self.node_list.addItem(item)
        if self.node_list.currentItem() is None and self.node_list.count():
            self.node_list.setCurrentRow(0)
