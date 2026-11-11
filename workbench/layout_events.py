from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .event_description_edit import EventDescriptionDialog


class LayoutEvents(QWidget):
    def __init__(self, nodes, events):
        super().__init__()

        layout = QVBoxLayout(self)

        self.nodes = nodes
        self.events = events
        self.annotations = None

        self.table = QTreeWidget()
        self.table.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.edit_description)
        self.table.setHeaderLabels(["Event", "Description"])
        self.table.setColumnWidth(0, 250)
        self.table.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(
            self.table, 1
        )  # 1 = the table tree widget should receive the avail. extra space

        self.refresh()

    def refresh(self):
        self.table.clear()
        observations = getattr(self, "observed_events", None)
        if observations is not None:
            names = (
                self.annotations.load().get("events", {})
                if self.annotations is not None
                else {}
            )
            for identity in sorted(observations.events):
                item = QTreeWidgetItem(
                    self.table, [identity.label(), names.get(identity.label(), "")]
                )
                item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    (identity.node_number, identity.event_number),
                )
            return

        for node_number, node_events in self.events.items():
            for event_number, details in node_events.items():
                identifier = (
                    str(event_number)
                    if node_number == 0
                    else f"{node_number}:{event_number}"
                )

                event_item = QTreeWidgetItem(
                    self.table,
                    [identifier, details.get("description", "")],
                )
                event_item.setData(
                    0, Qt.ItemDataRole.UserRole, (node_number, event_number)
                )

                consumer_identifier = f"{node_number}:{event_number}"

                for node in self.nodes:
                    if consumer_identifier in node.consumed_events:
                        QTreeWidgetItem(
                            event_item,
                            [f"{node.module_type} ({node.number})"],
                        )

    def edit_description(self, item, column):
        if column != 1 or item.parent() is not None or self.annotations is None:
            return
        nn, en = item.data(0, Qt.ItemDataRole.UserRole)
        dialog = EventDescriptionDialog(self, self.annotations, f"{nn}:{en}")
        dialog.exec()
        dialog.deleteLater()
