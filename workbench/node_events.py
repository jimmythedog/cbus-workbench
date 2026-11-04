from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .cbus_service import NodeState
from .pnn import Pnn


class NoHoverDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if index.parent().isValid() and not index.siblingAtColumn(0).data():
            option.state &= ~QStyle.StateFlag.State_MouseOver

        super().paint(painter, option, index)

    def createEditor(self, parent, option, index):
        if index.column() == 0:
            return None

        return super().createEditor(parent, option, index)


class RawEvDelegate(NoHoverDelegate):
    def createEditor(self, parent, option, index):
        if index.column() == 0:
            return None

        if index.parent().isValid():
            editor = QSpinBox(parent)
            editor.setRange(0, 255)
            return editor

        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QSpinBox):
            editor.setValue(int(index.data()))
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QSpinBox):
            model.setData(index, editor.value())
        else:
            super().setModelData(editor, model, index)


class NodeEvents(QSplitter):
    def __init__(self, events=None):
        super().__init__(Qt.Orientation.Horizontal)

        self.events = events if events is not None else {}
        self.node = None
        self.editing_descriptions = None
        self.editing_values = None

        produced = QGroupBox("Known produced events")
        produced_layout = QVBoxLayout(produced)

        self.produced_table = QTableWidget(0, 2)
        self.produced_table.setHorizontalHeaderLabels(["Event", "Description"])
        self.produced_table.horizontalHeader().setStretchLastSection(True)
        self.produced_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        produced_layout.addWidget(self.produced_table)

        consumed = QGroupBox("Consumed events")
        consumed_layout = QVBoxLayout(consumed)

        self.consumed_table = QTreeWidget()
        self.consumed_table.setExpandsOnDoubleClick(False)
        self.consumed_table.setItemDelegate(RawEvDelegate(self.consumed_table))
        self.consumed_table.header().setStretchLastSection(True)
        self.consumed_table.setHeaderLabels(["Event", "Description"])
        consumed_layout.addWidget(self.consumed_table)

        self.addWidget(produced)
        self.addWidget(consumed)
        self.setSizes([400, 600])

    def show_node(self, node):
        self.produced_table.setRowCount(0)
        expanded_events = set()

        if node is self.node:
            for index in range(self.consumed_table.topLevelItemCount()):
                item = self.consumed_table.topLevelItem(index)
                if item.isExpanded():
                    expanded_events.add(item.text(0))

        self.node = node
        self.consumed_table.clear()

        if node is None:
            return

        self.show_produced_events(node.number)

        for event, description in node.consumed_events.items():
            parent = QTreeWidgetItem(self.consumed_table, [event, description])
            parent.setExpanded(event in expanded_events)
            parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsEditable)

            if not node.has_mdf:
                for number, value in node.ev_values.get(event, {}).items():
                    ev_item = QTreeWidgetItem(parent, [f"EV {number}", str(value)])
                    ev_item.setFlags(ev_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    ev_item.setData(0, Qt.ItemDataRole.UserRole, number)
                continue

            details = QTreeWidgetItem(parent)
            details.setFlags(details.flags() & ~Qt.ItemFlag.ItemIsSelectable)

            form = QWidget()
            layout = QFormLayout(form)

            action = QComboBox()
            action.setObjectName("action")

            action.addItems(["No action", "Set output", "Pulse output"])
            action.setCurrentIndex(node.ev_values.get(event, {}).get(1, 0))
            action.setMaximumWidth(200)
            layout.addRow("Action:", action)

            output = QSpinBox()
            output.setObjectName("output")
            output.setRange(0, 255)
            output.setValue(node.ev_values.get(event, {}).get(2, 0))
            output.setMaximumWidth(100)
            layout.addRow("Output:", output)

            invert = QCheckBox()
            invert.setObjectName("invert")
            invert.setChecked(bool(node.ev_values.get(event, {}).get(3, 0)))
            layout.addRow("Invert:", invert)

            # The tree takes ownership of form and its child controls.
            self.consumed_table.setItemWidget(details, 1, form)
            details.setSizeHint(1, form.sizeHint())

        self.set_editing(False)

    def show_produced_events(self, node_number: int) -> None:
        produced = [
            (f"{node_number}:{number}", details.get("description", ""))
            for number, details in self.events.get(node_number, {}).items()
        ]
        self.produced_table.setRowCount(len(produced))
        for row, (event, description) in enumerate(produced):
            event_item = QTableWidgetItem(event)
            event_item.setFlags(event_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.produced_table.setItem(row, 0, event_item)
            self.produced_table.setItem(row, 1, QTableWidgetItem(description))

    def show_live_state(self, state: NodeState) -> None:
        """Show discovered consumed events using their internal table indices."""
        same_node = (
            isinstance(self.node, Pnn)
            and self.node.node_number == state.identity.node_number
        )
        expanded = set()
        if same_node:
            for row in range(self.consumed_table.topLevelItemCount()):
                item = self.consumed_table.topLevelItem(row)
                if item.isExpanded():
                    expanded.add(item.data(0, Qt.ItemDataRole.UserRole))

        self.node = state.identity
        self.consumed_table.clear()
        self.show_produced_events(state.identity.node_number)
        ev_count = state.parameters.get(5)
        for index, (event_node, event_number) in sorted(state.event_identities.items()):
            description = (
                self.events.get(event_node, {})
                .get(event_number, {})
                .get("description", "")
            )
            event = f"{event_node}:{event_number}"
            parent = QTreeWidgetItem(self.consumed_table, [event, description])
            parent.setData(0, Qt.ItemDataRole.UserRole, index)
            values = state.ev_values.get(index, {})
            indices = range(1, ev_count + 1) if ev_count is not None else sorted(values)
            for ev_index in indices:
                value = values.get(ev_index)
                QTreeWidgetItem(
                    parent, [f"EV {ev_index}", "-" if value is None else str(value)]
                )
            parent.setExpanded(index in expanded)
        self.set_editing(False)

    def set_editing(self, editing):
        self.produced_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.consumed_table.setEditTriggers(
            QTreeWidget.EditTrigger.DoubleClicked
            if editing
            else QTreeWidget.EditTrigger.NoEditTriggers
        )

        for event_index in range(self.consumed_table.topLevelItemCount()):
            event = self.consumed_table.topLevelItem(event_index)

            for child_index in range(event.childCount()):
                child = event.child(child_index)
                form = self.consumed_table.itemWidget(child, 1)

                if form is not None:
                    for control in form.findChildren(QWidget):
                        if isinstance(control, (QComboBox, QSpinBox, QCheckBox)):
                            control.setEnabled(editing)

    def begin_edit(self):
        self.editing_descriptions = self.node.consumed_events.copy()
        self.editing_values = deepcopy(self.node.ev_values)
        self.set_editing(True)

    def save_edit(self):
        for index in range(self.consumed_table.topLevelItemCount()):
            item = self.consumed_table.topLevelItem(index)
            event = item.text(0)

            self.editing_descriptions[event] = item.text(1)

            if not self.node.has_mdf:
                for child_index in range(item.childCount()):
                    child = item.child(child_index)

                    number = child.data(0, Qt.ItemDataRole.UserRole)
                    value = int(child.text(1))

                    self.editing_values[event][number] = value
            else:
                details = item.child(0)
                form = self.consumed_table.itemWidget(details, 1)

                action = form.findChild(QComboBox, "action")
                output = form.findChild(QSpinBox, "output")
                invert = form.findChild(QCheckBox, "invert")

                if action.currentIndex() >= 0:
                    self.editing_values[event][1] = action.currentIndex()
                self.editing_values[event][2] = output.value()
                self.editing_values[event][3] = int(invert.isChecked())

        self.node.consumed_events = self.editing_descriptions
        self.node.ev_values = self.editing_values

        self.editing_descriptions = None
        self.editing_values = None

        self.show_node(self.node)

    def cancel_edit(self):
        self.editing_descriptions = None
        self.show_node(self.node)
