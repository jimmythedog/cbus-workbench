from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSplitter

from .node import Node
from .node_details import NodeDetails


class NodeView(QSplitter):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)

        node_list = QListWidget()

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

            item = QListWidgetItem(f"{node.number} - {node.module_type}")
            item.setData(Qt.ItemDataRole.UserRole, node)
            node_list.addItem(item)

        details = NodeDetails()

        node_list.currentItemChanged.connect(details.show_node)

        self.addWidget(node_list)
        self.addWidget(details)
        self.setSizes([250, 750])
