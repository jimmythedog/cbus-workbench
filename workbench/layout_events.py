from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QStackedWidget,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class DescriptionDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        # Qt calls this when editing is requested for a cell (index),
        # typically by double-clicking it.
        #
        # index.column() != 1  - the current column is not Description
        # index.parent().isValid() - if the current index has a parent, it must be a consumer row
        # If either of the above are true, we do not create an editor, as we only allow editing of desc
        if index.column() != 1 or index.parent().isValid():
            return None
        return super().createEditor(parent, option, index)


class LayoutEvents(QWidget):
    editing_changed = Signal(bool)

    def __init__(self, nodes, events):
        super().__init__()

        layout = QVBoxLayout(self)

        self.nodes = nodes
        self.events = events

        self.table = QTreeWidget()
        self.table.setItemDelegate(DescriptionDelegate(self.table))
        self.table.setHeaderLabels(["Event", "Description"])
        self.table.setColumnWidth(0, 250)
        self.table.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(
            self.table, 1
        )  # 1 = the table tree widget should receive the avail. extra space

        self.refresh()
        self.actions = QStackedWidget()

        view_actions = QWidget()
        view_layout = QHBoxLayout(view_actions)
        view_layout.addStretch()

        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self.begin_edit)
        view_layout.addWidget(self.edit_button)

        edit_actions = QWidget()
        edit_layout = QHBoxLayout(edit_actions)
        edit_layout.addStretch()

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_edit)
        edit_layout.addWidget(self.save_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_edit)
        edit_layout.addWidget(self.cancel_button)

        self.actions.addWidget(view_actions)
        self.actions.addWidget(edit_actions)

        layout.addWidget(
            self.actions, 0
        )  # 0 = the actions stacked widget should NOT receive their share of any avail. extra space

    def refresh(self):
        self.table.clear()

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
                event_item.setFlags(event_item.flags() | Qt.ItemFlag.ItemIsEditable)

                consumer_identifier = f"{node_number}:{event_number}"

                for node in self.nodes:
                    if consumer_identifier in node.consumed_events:
                        QTreeWidgetItem(
                            event_item,
                            [f"{node.module_type} ({node.number})"],
                        )

    def set_editing(self, editing):
        self.table.setEditTriggers(
            QTreeWidget.EditTrigger.DoubleClicked
            if editing
            else QTreeWidget.EditTrigger.NoEditTriggers
        )

        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            flags = item.flags()

            if editing:
                item.setFlags(flags | Qt.ItemFlag.ItemIsEditable)
            else:
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsEditable)

    def begin_edit(self):
        self.set_editing(True)
        self.actions.setCurrentIndex(1)  # show Save & Cancel buttons
        self.editing_changed.emit(True)

    def save_edit(self):
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            node_number, event_number = item.data(0, Qt.ItemDataRole.UserRole)
            self.events[node_number][event_number]["description"] = item.text(1)

        self.finish_edit()

    def cancel_edit(self):
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            node_number, event_number = item.data(0, Qt.ItemDataRole.UserRole)
            item.setText(
                1, self.events[node_number][event_number].get("description", "")
            )

        self.finish_edit()

    def finish_edit(self):
        self.set_editing(False)
        self.actions.setCurrentIndex(0)  # show Edit button
        self.editing_changed.emit(False)
