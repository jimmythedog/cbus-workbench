from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from .node_view import NodeView


class LayoutView(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(NodeView(), "Nodes")
        tabs.addTab(QLabel("Events will go here"), "Events")
        tabs.addTab(QLabel("Backups will go here"), "Backups")

        layout.addWidget(tabs)
