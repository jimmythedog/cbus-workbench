"""Contextual editing of layout and node-owned event descriptions."""

import logging

from PySide6.QtCore import QObject

from .description_dialog import DescriptionDialog
from .logging_config import trace

logger = logging.getLogger("workbench.annotations")


class EventDescriptionDialog(DescriptionDialog):
    """A missing node number selects layout names; a number selects that node."""

    def __init__(self, parent, annotations, identity, number=None):
        data = annotations.load(number)
        self.key = "events" if number is None else "consumedEvents"

        def save(text):
            current = annotations.load(number)
            current.setdefault(self.key, {})[identity] = text
            annotations.save(current, number)

        fallback = (
            annotations.load().get("events", {}).get(identity, "")
            if number is not None
            else ""
        )
        super().__init__(
            parent,
            "event",
            identity,
            data.get(self.key, {}).get(identity, fallback),
            save,
        )
        trace(
            logger,
            "Edit event description layout=%s node=%s event=%s",
            annotations.logical_layout,
            number,
            identity,
        )


class NodeEventNameEditor(QObject):
    def __init__(self, details):
        super().__init__(details)
        self.details = details
        self.dialog = None
        details.node_events.consumed_table.itemDoubleClicked.connect(self.edit_consumed)
        details.node_events.produced_table.itemDoubleClicked.connect(self.edit_produced)

    def cancel(self):
        if self.dialog is not None:
            self.dialog.reject()

    def edit_consumed(self, item, column):
        if column == 1 and item.parent() is None and self.details.node is not None:
            self.edit(item.text(0), self.details.annotation_number())

    def edit_produced(self, item, column):
        if column == 1 and item.parent() is None:
            self.edit(item.text(0))

    def edit(self, identity, number=None):
        details = self.details
        if not details.annotations or not details.can_edit_annotations():
            return
        dialog = self.dialog = EventDescriptionDialog(
            details, details.annotations, identity, number
        )
        details.annotation_editing = True
        try:
            dialog.exec()
        finally:
            details.annotation_editing = False
            self.dialog = None
            details.refresh_annotations()
            if details.live_state is not None:
                details.show_live_state(details.live_state, details.live_mdf)
            dialog.deleteLater()
