import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .configuration_load import load_online_configuration
from .event_description_edit import EventDescriptionDialog
from .event_teach import TeachEventDialog, teach_targets
from .logging_config import trace
from .observed_events import EventIdentity
from .send_event_dialog import event_menu

logger = logging.getLogger("workbench.events")


class LayoutEvents(QWidget):
    # Node number and event identity; the layout opens that node's editor.
    teach_requested = Signal(int, object)

    def __init__(self, nodes, events):
        super().__init__()

        layout = QVBoxLayout(self)

        self.nodes = nodes
        self.events = events
        self.annotations = None
        self.cbus_service = None

        self.table = QTreeWidget()
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_event_menu)
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
                identifier = f"{node_number}:{event_number}"

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

    def show_event_menu(self, position):
        item = self.table.itemAt(position)
        identity = (
            item.data(0, Qt.ItemDataRole.UserRole)
            if item and item.parent() is None
            else None
        )
        actions = []
        service = self.cbus_service
        if identity is not None:
            teach = QAction("Teach to Node…", self.table)
            teach.setEnabled(
                service is not None
                and service.connection.state == "Connected"
                and not service.writes_busy()
            )
            teach.triggered.connect(lambda: self.teach_to_node(identity))
            actions.append(teach)
        # Forgetting applies only to the observed catalogue, not imported events.
        observations = getattr(self, "observed_events", None)
        if observations is not None:
            if identity is not None:
                forget = QAction("Forget Event", self.table)
                forget.triggered.connect(
                    lambda: self.forget_events({EventIdentity(*identity)})
                )
                actions.append(forget)
            forget_all = QAction("Forget All Observed Events…", self.table)
            forget_all.setEnabled(bool(observations.events))
            forget_all.triggered.connect(self.forget_all_events)
            actions.append(forget_all)
        # With no identity, event_menu() omits Send and shows only these actions.
        event_menu(self.table, position, service, identity, actions)

    def forget_all_events(self):
        observations = self.observed_events
        answer = QMessageBox.question(
            self,
            "Forget All Observed Events",
            f"Forget all {len(observations.events)} observed events for layout "
            f"'{observations.logical_layout}'?\n\n"
            "Event names, node configuration and backups are kept. "
            "Events seen again are rediscovered automatically.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        confirmed = answer == QMessageBox.StandardButton.Yes
        trace(
            logger,
            "Forget all observed events answered",
            extra={
                "fields": {
                    "layout": observations.logical_layout,
                    "confirmed": confirmed,
                }
            },
        )
        if confirmed:
            self.forget_events(set(observations.events))

    def forget_events(self, identities):
        """Remove identities from the layout catalogue; views refresh on changed."""
        try:
            self.observed_events.forget(identities)
        except OSError as error:
            QMessageBox.warning(self, "Events not forgotten", str(error))

    def teach_to_node(self, identity):
        """Choose a target node, then hand over to its Events Edit workflow."""
        service = self.cbus_service
        if service is None:
            return
        # Targets must be whole, loaded consumer nodes; connecting reads only
        # parameters, so read the rest before listing them.
        if not load_online_configuration(self, service, consumers_only=True):
            return
        dialog = TeachEventDialog(
            self,
            "Teach to Node",
            identity,
            targets=teach_targets(service, self.annotations),
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        identity, number = dialog.identity(), dialog.target_number()
        dialog.deleteLater()
        if accepted and number is not None:
            self.teach_requested.emit(number, identity)
