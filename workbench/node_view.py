import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSplitter

from .cbus_service import NodeState
from .logging_config import trace
from .node_backup_files import saved_node_numbers
from .node_details import NodeDetails
from .node_metadata import load_metadata
from .parameter_names import module_name
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
        self.saved_metadata = {}
        self.state_lookup: Callable[[int], NodeState] | None = None
        self.discovering = False
        self.selection_before_discovery: int | None = None

        self.node_list.currentItemChanged.connect(self.show_selected_node)

        self.details.editing_changed.connect(
            lambda editing: self.node_list.setEnabled(not editing)
        )

        self.addWidget(self.node_list)
        self.addWidget(self.details)
        self.setSizes([250, 750])

    def begin_discovery(self) -> None:
        """Leave details empty while full layout discovery updates the node list."""
        current = self.node_list.currentItem()
        self.selection_before_discovery = (
            node_number(current.data(Qt.ItemDataRole.UserRole)) if current else None
        )
        self.discovering = True
        self.node_list.setCurrentItem(None)
        self.node_list.setEnabled(False)
        trace(
            logger,
            "Node selection suspended for layout discovery",
            extra={"fields": {"node_number": self.selection_before_discovery}},
        )

    def finish_discovery(self, status: str) -> None:
        """Restore selection once, including after incomplete discovery."""
        if not self.discovering or status == "Discovering configuration…":
            return
        self.discovering = False
        self.node_list.setEnabled(True)
        selected = None
        if status != "Disconnected":
            for index in range(self.node_list.count()):
                item = self.node_list.item(index)
                node = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(node, Pnn):
                    if selected is None:
                        selected = item
                    if node.node_number == self.selection_before_discovery:
                        selected = item
                        break
        self.selection_before_discovery = None
        self.node_list.setCurrentItem(selected)
        trace(
            logger,
            "Node selection resumed after layout discovery",
            extra={
                "fields": {
                    "status": status,
                    "node_number": (
                        node_number(selected.data(Qt.ItemDataRole.UserRole))
                        if selected
                        else None
                    ),
                }
            },
        )

    def show_selected_node(self, current, _previous=None) -> None:
        self.details.show_node(current)
        if current is not None and self.state_lookup is not None:
            node = current.data(Qt.ItemDataRole.UserRole)
            if isinstance(node, Pnn):
                self.details.show_live_state(self.state_lookup(node.node_number))

    def refresh_state(self, node_number: int) -> None:
        """Refresh the navigator identity and selected details from service state."""
        if self.state_lookup is None:
            return
        state = self.state_lookup(node_number)
        if state is None:
            return
        identity = state.identity
        name = module_name(identity.manufacturer, identity.module_type)
        for index in range(self.node_list.count()):
            item = self.node_list.item(index)
            node = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(node, Pnn) and node.node_number == node_number:
                item.setData(Qt.ItemDataRole.UserRole, identity)
                item.setText(f"{node_number} - {name}")
                if item is self.node_list.currentItem():
                    self.details.show_live_state(state)
                return

    def show_identity(self, node: Pnn) -> None:
        """Update a PNN identity without changing the selected list item."""
        name = module_name(node.manufacturer, node.module_type)
        for index in range(self.node_list.count()):
            item = self.node_list.item(index)
            if node_number(item.data(Qt.ItemDataRole.UserRole)) == node.node_number:
                item.setData(Qt.ItemDataRole.UserRole, node)
                item.setText(f"{node.node_number} - {name}")
                if item is self.node_list.currentItem():
                    self.show_selected_node(item)
                return

        first_node = self.node_list.count() == 0
        item = NodeListItem(f"{node.node_number} - {name}")
        item.setData(Qt.ItemDataRole.UserRole, node)
        self.node_list.addItem(item)
        if first_node and not self.discovering:
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
        """Load saved identification independently of live discovery and backups."""
        self.saved_metadata = {
            number: load_metadata(logical_layout, number)
            for number in saved_node_numbers(logical_layout)
        }
        self.details.saved_metadata = self.saved_metadata
        for number in self.saved_metadata:
            if any(
                node_number(self.node_list.item(i).data(Qt.ItemDataRole.UserRole))
                == number
                for i in range(self.node_list.count())
            ):
                continue
            item = NodeListItem(f"{number} (offline)")
            item.setData(Qt.ItemDataRole.UserRole, number)
            self.node_list.addItem(item)
        if (
            not self.discovering
            and self.node_list.currentItem() is None
            and self.node_list.count()
        ):
            self.node_list.setCurrentRow(0)
