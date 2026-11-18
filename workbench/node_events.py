import logging
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QMessageBox,
    QSpinBox,
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
from .event_mdf import EvContainer, EvValueValidator, add_ev_controls, ev_definitions
from .logging_config import trace
from .observed_events import EventIdentity
from .pnn import Pnn
from .send_event_dialog import event_menu

logger = logging.getLogger(__name__)


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
        if index.column() == 0 or not index.parent().isValid():
            return None

        if index.parent().isValid():
            if index.parent().parent().isValid():
                return None
            tree = self.parent()
            if isinstance(tree.itemWidget(tree.itemFromIndex(index), 1), EvContainer):
                return None
            editor = QLineEdit(parent)
            editor.setValidator(EvValueValidator(0, 255, editor))
            return editor

        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QLineEdit):
            editor.setText(str(index.data()))
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QLineEdit):
            # Preserve blank input: the shared configuration interprets it as
            # absence, while an explicitly entered zero remains numeric.
            if not editor.text() or editor.hasAcceptableInput():
                model.setData(index, editor.text())
        else:
            super().setModelData(editor, model, index)


class NodeEvents(QWidget):
    def __init__(self, events=None):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.events = events if events is not None else {}
        self.annotations = None
        self.node = None
        self.live_state = None
        self.live_mdf = None
        self.source_mdf = None
        self.token_editor = None
        self.editing_descriptions = None
        self.editing_values = None
        self.desired_configuration = None
        self.ev_presentation = None
        self.ev_definitions = []
        self.pending_ev_controls = {}

        self.produced_page = QGroupBox("Known produced events", self)
        # NodeDetails reparents this existing widget into its own tab.
        self.produced_page.hide()
        produced = self.produced_page
        produced_layout = QVBoxLayout(produced)

        self.produced_table = QTableWidget(0, 2)
        self.produced_table.verticalHeader().hide()
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
        # Expand animation draws a snapshot, then swaps in the real EV control
        # row widgets (#168), which shows as a flicker.
        self.consumed_table.setAnimated(False)
        self.consumed_table.itemChanged.connect(self.update_configuration_value)
        self.consumed_table.itemExpanded.connect(self.show_event_controls)
        self.consumed_table.setItemDelegate(RawEvDelegate(self.consumed_table))
        self.consumed_table.header().setStretchLastSection(True)
        self.consumed_table.setHeaderLabels(["Event", "Description"])
        consumed_layout.addWidget(self.consumed_table)

        layout.addWidget(consumed)
        self.cbus_service = None
        self.consumed_actions = ()
        for table in (self.produced_table, self.consumed_table):
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            table.customContextMenuRequested.connect(
                lambda position, table=table: self.show_event_menu(table, position)
            )

    def show_event_menu(self, table, position):
        item = table.itemAt(position)
        if table is self.consumed_table:
            # New/Delete Event actions are owned by NodeDetails, beside its buttons.
            if item is not None and item.parent() is not None:
                return
            # Delete Event acts on the current item: make it the clicked row.
            self.consumed_table.setCurrentItem(item)
            identity = item.data(0, Qt.ItemDataRole.UserRole) if item else None
            event_menu(
                table, position, self.cbus_service, identity, self.consumed_actions
            )
            return
        if item is None:
            return
        identity = tuple(map(int, table.item(item.row(), 0).text().split(":")))
        actions = []
        # Only observed rows can be forgotten; Forget All stays in Layout → Events.
        observations = getattr(self, "observed_events", None)
        if observations is not None:
            forget = QAction("Forget Event", table)
            forget.triggered.connect(
                lambda: self.forget_event(observations, EventIdentity(*identity))
            )
            actions.append(forget)
        event_menu(table, position, self.cbus_service, identity, actions)

    def forget_event(self, observations, identity):
        """Remove from the layout catalogue; both event views refresh on changed."""
        try:
            observations.forget({identity})
        except OSError as error:
            QMessageBox.warning(self, "Event not forgotten", str(error))

    def selected_identity(self):
        """The selected consumed event's identity, or None for EV/detail rows."""
        item = self.consumed_table.currentItem()
        if item is None or item.parent() is not None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def show_node(self, node):
        self.ev_presentation = None
        self.pending_ev_controls.clear()
        self.offline_identities = set()
        self.live_state = None
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

        for event, description in sorted(
            node.consumed_events.items(),
            key=lambda entry: tuple(map(int, entry[0].split(":"))),
        ):
            parent = QTreeWidgetItem(self.consumed_table, [event, description])
            parent.setExpanded(event in expanded_events)

            if not node.has_mdf:
                for number, value in node.ev_values.get(event, {}).items():
                    ev_item = QTreeWidgetItem(parent, [f"EV {number}", str(value)])
                    ev_item.setFlags(ev_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    ev_item.setData(0, Qt.ItemDataRole.UserRole, number)
                continue

            details = QTreeWidgetItem(parent)
            details.setData(0, Qt.ItemDataRole.UserRole, True)
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
        # Network observations belong to the layout, not node configuration.
        names = self.annotations.load().get("events", {}) if self.annotations else {}
        observations = getattr(self, "observed_events", None)
        if observations is not None:
            produced = [
                (identity.label(), names.get(identity.label(), ""))
                for identity in sorted(observations.events)
                if identity.node_number == node_number and node_number != 0
            ]
        else:
            produced = [
                (
                    f"{node_number}:{number}",
                    names.get(
                        f"{node_number}:{number}", details.get("description", "")
                    ),
                )
                for number, details in self.events.get(node_number, {}).items()
                if node_number != 0
            ]
        self.produced_table.setRowCount(len(produced))
        for row, (event, description) in enumerate(produced):
            event_item = QTableWidgetItem(event)
            event_item.setFlags(event_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.produced_table.setItem(row, 0, event_item)
            self.produced_table.setItem(row, 1, QTableWidgetItem(description))

    def show_live_state(self, state: NodeState, mdf=None) -> None:
        """Use stable event identities in the UI; indices belong to discovery only."""
        self.live_state = state
        if self.editing_values is not None or self.desired_configuration is not None:
            return
        self.live_mdf = mdf
        same_node = (
            isinstance(self.node, Pnn)
            and self.node.node_number == state.identity.node_number
        )
        # NodeState is mutated in place by discovery. Keep a value snapshot so
        # unchanged refreshes retain both the tree and its existing controls.
        presentation = deepcopy(
            {
                "node_number": state.identity.node_number,
                "ev_count": state.parameters.get(5),
                "identities": state.event_identities,
                "ev_values": state.ev_values,
                "nv_values": state.nv_values,
                "mdf": mdf,
                "catalogue": self.events,
            }
        )
        if same_node and presentation == self.ev_presentation:
            trace(
                logger,
                "Retain unchanged EV presentation node=%s",
                state.identity.node_number,
            )
            return
        previous = self.ev_presentation
        self.ev_presentation = presentation
        if (
            same_node
            and previous is not None
            and {**previous, "nv_values": None} == {**presentation, "nv_values": None}
        ):
            # NV replies change only the context of EV forms (visibility, labels),
            # so refresh the expanded forms in place rather than rebuilding (#151).
            # Collapsed events read the new NVs from ev_presentation on expansion.
            trace(
                logger,
                "NV-only change; refresh expanded EV forms node=%s",
                state.identity.node_number,
            )
            self.refresh_ev_controls(self.live_context)
            return
        expanded = set()
        selected = None
        if same_node:
            current = self.consumed_table.currentItem()
            if current is not None and current.parent() is not None:
                # A selected MDF control row (#168) restores as its EV row.
                while current.parent().parent() is not None:
                    current = current.parent()
            for row in range(self.consumed_table.topLevelItemCount()):
                item = self.consumed_table.topLevelItem(row)
                identity = item.data(0, Qt.ItemDataRole.UserRole)
                if item.isExpanded():
                    expanded.add(identity)
                if current is item:
                    selected = (identity, None)
                elif current is not None and current.parent() is item:
                    selected = (identity, current.text(0))

        self.node = state.identity
        self.pending_ev_controls.clear()
        self.consumed_table.clear()
        self.show_produced_events(state.identity.node_number)
        self.ev_definitions = (
            list(ev_definitions(presentation["mdf"].get("eventVariables", [])))
            if mdf
            else []
        )
        ev_count = state.parameters.get(5)
        # Order displayed identities, retaining each discovery slot's EV values.
        for index, (event_node, event_number) in sorted(
            state.event_identities.items(), key=lambda entry: entry[1]
        ):
            description = (
                self.events.get(event_node, {})
                .get(event_number, {})
                .get("description", "")
            )
            event = f"{event_node}:{event_number}"
            parent = QTreeWidgetItem(self.consumed_table, [event, description])
            parent.setData(0, Qt.ItemDataRole.UserRole, (event_node, event_number))
            values = state.ev_values.get(index, {})
            indices = range(1, ev_count + 1) if ev_count is not None else sorted(values)
            ev_rows = {}
            for ev_index in indices:
                value = values.get(ev_index)
                item = QTreeWidgetItem(
                    parent,
                    [
                        f"EV {ev_index}",
                        "" if value is None else str(value),
                    ],
                )
                ev_rows[ev_index] = item
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                item.setData(0, Qt.ItemDataRole.UserRole, value is not None)
                item.setHidden(value is None)
            identity = (event_node, event_number)
            # Expansion consumes this entry once. Copy values to preserve the
            # confirmed interpretation if raw editing starts before expansion.
            self.pending_ev_controls[identity] = (ev_rows, dict(values))
            parent.setExpanded(identity in expanded)
            if selected is not None and selected[0] == identity:
                ev = selected[1]
                current = (
                    parent
                    if ev is None
                    else next(
                        (row for row in ev_rows.values() if row.text(0) == ev), None
                    )
                )
                if current is not None:
                    self.consumed_table.setCurrentItem(current)
        self.set_editing(False)
        self.refresh_annotations(state.identity.node_number)

    def refresh_annotations(self, number):
        if not self.annotations:
            return
        names = self.annotations.load(number).get("consumedEvents", {})
        # Layout names are display defaults only; they never create consumed rows.
        descriptions = self.annotations.load().get("events", {}) | names
        # Saved names are useful offline even without a current hardware table.
        if self.live_state is None:
            self.consumed_table.clear()
            for identity in sorted(
                set(names) | getattr(self, "offline_identities", set()),
                key=lambda identity: tuple(map(int, identity.split(":"))),
            ):
                item = QTreeWidgetItem(
                    self.consumed_table, [identity, descriptions.get(identity, "")]
                )
                item.setData(
                    0, Qt.ItemDataRole.UserRole, tuple(map(int, identity.split(":")))
                )
        else:
            for row in range(self.consumed_table.topLevelItemCount()):
                item = self.consumed_table.topLevelItem(row)
                item.setText(1, descriptions.get(item.text(0), ""))

        for row in range(self.consumed_table.topLevelItemCount()):
            self.consumed_table.topLevelItem(row).setToolTip(
                1, "Double-click to edit this node's event description"
            )

    def show_event_controls(self, event):
        """Construct the existing MDF layout once, on an event's first expansion."""
        if event.parent() is not None:
            return  # EV rows expand only to show their existing control rows.
        identity = event.data(0, Qt.ItemDataRole.UserRole)
        pending = self.pending_ev_controls.pop(identity, None)
        if pending is None or self.ev_presentation is None:
            return
        rows, values = pending
        trace(
            logger,
            "Build expanded EV controls node=%s event=%s",
            self.node.node_number,
            identity,
        )
        nv_values = self.ev_presentation["nv_values"]
        if self.desired_configuration is not None:
            nv_values, values = self.configuration_context(identity)
        add_ev_controls(
            self.consumed_table,
            event,
            rows,
            self.ev_definitions,
            nv_values,
            values,
            self.node.node_number,
            source_definitions=list(
                ev_definitions(self.source_mdf.get("eventVariables", []))
            )
            if self.source_mdf
            else None,
            token_editor=self.token_editor,
        )
        # Expansion may happen after Edit exposes unread raw EV rows.
        for row in rows.values():
            form = self.consumed_table.itemWidget(row, 1)
            if isinstance(form, EvContainer):
                form.set_editing(self.desired_configuration is not None)

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

                # Show all supported EVs while editing.
                # Otherwise, show only EVs with confirmed values.
                confirmed = child.data(0, Qt.ItemDataRole.UserRole)
                child.setHidden(not editing and not confirmed)

                form = self.consumed_table.itemWidget(child, 1)

                if isinstance(form, EvContainer):
                    form.set_editing(editing)
                elif form is not None:
                    for control in form.findChildren(QWidget):
                        if isinstance(control, (QComboBox, QSpinBox, QCheckBox)):
                            control.setEnabled(editing)

    def begin_configuration_edit(self, desired: dict) -> None:
        """Edit the shared backup dictionary using event identities, never slots."""
        self.desired_configuration = desired
        self.set_editing(True)
        self.refresh_configuration_controls()

    def add_pending_event(self, identity):
        """Add a new identity to the Events draft; Save teaches, Cancel discards.

        EV1 starts at 0; later EVs stay undefined until edited. Save still
        requires a nonzero EV. Its rows and expanded MDF controls are the
        ordinary ones and edit the same desired configuration as existing events.
        """
        nn, en = identity
        self.desired_configuration["events"].append(
            {"nodeNumber": nn, "eventNumber": en, "eventVariables": [0]}
        )
        parent = QTreeWidgetItem(self.consumed_table, [f"{nn}:{en}", "New event"])
        parent.setData(0, Qt.ItemDataRole.UserRole, identity)
        rows = {}
        for ev_index in range(1, self.live_state.parameters[5] + 1):
            text = "0" if ev_index == 1 else ""
            item = QTreeWidgetItem(parent, [f"EV {ev_index}", text])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(0, Qt.ItemDataRole.UserRole, ev_index == 1)
            rows[ev_index] = item
        self.pending_ev_controls[identity] = (rows, {1: 0})
        self.consumed_table.setCurrentItem(parent)
        # Expansion builds the MDF controls from the desired configuration.
        parent.setExpanded(True)
        trace(
            logger,
            "Pending new event added node=%s event=%s",
            self.node.node_number,
            identity,
        )

    def configuration_context(self, identity):
        desired = self.desired_configuration
        event = next(
            event
            for event in desired["events"]
            if (event["nodeNumber"], event["eventNumber"]) == identity
        )
        nvs = desired["nvs"]
        if isinstance(nvs, list):
            nvs = dict(enumerate(nvs, 1))
        return nvs, dict(enumerate(event["eventVariables"], 1))

    def live_context(self, identity):
        """NV and EV values for one consumed event in the live presentation."""
        presentation = self.ev_presentation
        index = next(
            index
            for index, event in presentation["identities"].items()
            if event == identity
        )
        return presentation["nv_values"], presentation["ev_values"].get(index, {})

    def refresh_configuration_controls(self):
        if self.desired_configuration is None:
            return
        self.refresh_ev_controls(self.configuration_context)

    def refresh_ev_controls(self, context_for):
        """Refresh existing forms only; collapsed events keep deferred construction."""
        tree = self.consumed_table
        for row in range(tree.topLevelItemCount()):
            event = tree.topLevelItem(row)
            identity = event.data(0, Qt.ItemDataRole.UserRole)
            context = None
            for child_index in range(event.childCount()):
                item = event.child(child_index)
                form = tree.itemWidget(item, 1)
                if isinstance(form, EvContainer):
                    if context is None:
                        context = context_for(identity)
                    nvs, evs = context
                    for settings in form.settings:
                        settings.show_values(evs, nv_values=nvs, ev_values=evs)
                    form.show_rows()
        trace(logger, "Refreshed EV controls node=%s", self.node.node_number)

    def update_configuration_value(self, item, column):
        if column != 1:
            return
        parent = item.parent()
        if parent is None or parent.parent() is not None:
            return
        form = self.consumed_table.itemWidget(item, 1)
        if isinstance(form, EvContainer) and form.raw_value.text() != item.text(1):
            form.raw_value.setText(item.text(1))
        if self.desired_configuration is None:
            return
        identity = parent.data(0, Qt.ItemDataRole.UserRole)
        event = next(
            event
            for event in self.desired_configuration["events"]
            if (event["nodeNumber"], event["eventNumber"]) == identity
        )
        text = item.text(1)
        if text and (not text.isdecimal() or not 0 <= int(text) <= 255):
            return
        index = parent.indexOfChild(item)
        values = event["eventVariables"]
        values.extend([None] * (index + 1 - len(values)))
        values[index] = int(text) if text else None
        # Match node_backup(): trailing confirmed absences are omitted.
        while values and values[-1] is None:
            values.pop()
        trace(
            logger,
            "Raw EV edit node=%s event=%s ev=%s value=%s",
            self.node.node_number,
            identity,
            index + 1,
            values[index] if index < len(values) else None,
        )
        self.refresh_configuration_controls()

    def begin_edit(self):
        """Retain the prototype editor for configured, offline nodes."""
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
                    if not child.text(1):
                        continue
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
        self.ev_presentation = None
        self.desired_configuration = None
        self.editing_descriptions = None
        self.editing_values = None
        if self.live_state is not None:
            self.show_live_state(self.live_state, self.live_mdf)
        else:
            self.show_node(self.node)
