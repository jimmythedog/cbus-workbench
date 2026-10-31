from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSplitter

from .node import Node
from .node_details import NodeDetails


class NodeView(QSplitter):
    def __init__(self, events):
        super().__init__(Qt.Orientation.Horizontal)

        self.node_list = QListWidget()

        for number in range(256, 356):
            node = Node(
                number=number,
                module_type="CANMIO",
                can_id=126,
                firmware="3d",
                has_mdf=number % 2 == 0,
                nv_values={
                    1: 0,
                    2: number % 256,
                    3: 128,
                    4: 10,
                    5: 1,
                },
            )

            node.consumed_events = (
                {
                    "256:1": "Main line signal",
                    "256:302": "Turnout reached midpoint",
                    "0:30001": "Yard lighting",
                }
                if number in (256, 261)
                else {}
            )

            node.ev_values = {
                event: {1: 0, 2: 1, 3: 0} for event in node.consumed_events
            }

            item = QListWidgetItem(f"{node.number} - {node.module_type}")
            item.setData(Qt.ItemDataRole.UserRole, node)
            self.node_list.addItem(item)

        self.details = NodeDetails(events)

        self.node_list.currentItemChanged.connect(self.details.show_node)

        self.details.editing_changed.connect(
            lambda editing: self.node_list.setEnabled(not editing)
        )

        self.addWidget(self.node_list)
        self.addWidget(self.details)
        self.setSizes([250, 750])
