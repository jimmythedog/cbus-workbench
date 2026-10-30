from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from .layout_events import LayoutEvents
from .node_view import NodeView


class LayoutView(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.events = {
            0: {
                30001: {},
                30002: {},
            },
            256: {
                1: {},
                2: {},
                302: {"description": "turnout1 reached mid point"},
            },
            259: {
                1: {},
            },
        }

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.node_view = NodeView(self.events)
        self.tabs.addTab(self.node_view, "Nodes")

        nodes = [
            self.node_view.node_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.node_view.node_list.count())
        ]

        self.layout_events = LayoutEvents(nodes, self.events)

        self.tabs.addTab(self.layout_events, "Events")

        self.tabs.addTab(QLabel("Backups will go here"), "Backups")

        layout.addWidget(self.tabs)

        self.node_view.details.editing_changed.connect(self.on_editing_changed)
        self.layout_events.editing_changed.connect(self.on_layout_events_editing)

    def on_tab_changed(self, index):
        if index == 0:  # Nodes tab
            node_events = self.node_view.details.node_events
            node_events.show_node(node_events.node)

    def on_editing_changed(self, editing):
        self.tabs.setTabEnabled(1, not editing)  # Events
        self.tabs.setTabEnabled(2, not editing)  # Backups

    def on_layout_events_editing(self, editing):
        self.tabs.setTabEnabled(0, not editing)  # Nodes
        self.tabs.setTabEnabled(2, not editing)  # Backups
