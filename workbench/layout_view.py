from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from .node_view import NodeView


class LayoutView(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.node_view = NodeView()
        self.tabs.addTab(self.node_view, "Nodes")
        self.tabs.addTab(QLabel("Events will go here"), "Events")
        self.tabs.addTab(QLabel("Backups will go here"), "Backups")

        layout.addWidget(self.tabs)

        self.node_view.details.editing_changed.connect(self.on_editing_changed)

    def on_editing_changed(self, editing):
        self.tabs.setTabEnabled(1, not editing)  # Events
        self.tabs.setTabEnabled(2, not editing)  # Backups
