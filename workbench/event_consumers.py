"""Which nodes on one connection are configured to consume an event (#87).

Evidence is the connection's live consumed-event discovery only. Observed
traffic, backups and saved offline metadata never establish a consumer. A node
whose consumed events are not confirmed is reported as undetermined, so an
empty consumer list is never presented as complete when it is not.
Matching uses event identities `(NN, EN)`; table slots only locate EVs. Short
events are already `(0, EN)` in both the catalogue and discovery.
"""

import logging
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QTreeWidgetItem

from .cbus_service import DiscoveryProgress
from .logging_config import trace
from .parameter_names import module_name

logger = logging.getLogger("workbench.events")

# Column 0 role for rows this module adds; the views keep using UserRole.
KEY_ROLE = Qt.ItemDataRole.UserRole + 1

NOT_LOADED = "not loaded"
UNDETERMINED_REASONS = {
    DiscoveryProgress.NOT_STARTED: NOT_LOADED,
    DiscoveryProgress.IN_PROGRESS: "loading",
    DiscoveryProgress.INCOMPLETE: "discovery incomplete",
}


@dataclass
class Consumer:
    number: int
    label: str
    ev_count: int | None
    # Integer: confirmed value; None: confirmed absent; missing key: unknown.
    ev_values: dict[int, int | None]


@dataclass
class Consumers:
    confirmed: list[Consumer] = field(default_factory=list)
    # Node number -> why its consumed events are not confirmed.
    undetermined: dict[int, str] = field(default_factory=dict)


def non_consumer(state) -> bool:
    """The PNN consumer flag is what discovery itself uses to skip a node."""
    return state.event_progress == DiscoveryProgress.SKIPPED or (
        state.event_progress == DiscoveryProgress.NOT_STARTED
        and state.identity_confirmed
        and not state.identity.is_consumer
    )


def unread_nodes(service) -> list[int]:
    """Online possible consumers whose events were never read on this connection.

    These are the "not loaded" nodes of find_consumers(); they do not depend on
    the event. Failed reads are excluded: load_events() never retries them.
    """
    if service is None or service.connection.state != "Connected":
        return []
    return [
        number
        for number, state in sorted(service.node_states.items())
        if service.presence.get(number, False)
        and state.event_progress == DiscoveryProgress.NOT_STARTED
        and not non_consumer(state)
    ]


def find_consumers(identity, service, known_numbers) -> Consumers:
    """Confirmed consumers of identity, plus nodes that might still consume it."""
    identity = tuple(identity)
    connected = service is not None and service.connection.state == "Connected"
    states = service.node_states if connected else {}
    presence = service.presence if connected else {}
    result = Consumers()
    for number in sorted(set(known_numbers) | set(states)):
        state = states.get(number)
        if not connected:
            result.undetermined[number] = "disconnected"
            continue
        if state is None or not presence.get(number, False):
            # Saved-only and Offline nodes: their last configuration is unconfirmed.
            result.undetermined[number] = "Offline"
            continue
        progress = state.event_progress
        if non_consumer(state):
            continue
        if progress != DiscoveryProgress.COMPLETE:
            result.undetermined[number] = UNDETERMINED_REASONS[progress]
            continue
        slot = next(
            (s for s, event in state.event_identities.items() if event == identity),
            None,
        )
        if slot is None:
            continue
        # Module type only: refreshes run on every discovery step, so avoid
        # rereading each node's annotation file here.
        result.confirmed.append(
            Consumer(
                number,
                module_name(state.identity.manufacturer, state.identity.module_type),
                state.parameters.get(5),
                dict(state.ev_values.get(slot, {})),
            )
        )
    trace(
        logger,
        "Event consumers resolved",
        extra={
            "fields": {
                "identity": identity,
                "consumers": [consumer.number for consumer in result.confirmed],
                "undetermined": result.undetermined,
            }
        },
    )
    return result


def add_consumer_rows(parent: QTreeWidgetItem, identity, consumers: Consumers) -> None:
    for consumer in consumers.confirmed:
        row = QTreeWidgetItem(parent, [f"Node {consumer.number} - {consumer.label}"])
        row.setData(0, KEY_ROLE, (identity, consumer.number))
        row.setToolTip(0, "Double-click to open this node's consumed events")
        values = consumer.ev_values
        indices = (
            range(1, consumer.ev_count + 1)
            if consumer.ev_count is not None
            else sorted(values)
        )
        for index in indices:
            if index in values and values[index] is None:
                continue  # Confirmed absent, as in the node's consumed events.
            value = values.get(index)
            QTreeWidgetItem(
                row, [f"EV {index}", "Unknown" if value is None else str(value)]
            )
    if consumers.undetermined:
        # Per-node reasons are traced by find_consumers(); listing them here
        # would make one unreadably long row on a large layout.
        hint = (
            "Right-click to load unread nodes"
            if NOT_LOADED in consumers.undetermined.values()
            else "Use Layouts → Refresh"
        )
        QTreeWidgetItem(parent, ["Not determined", hint])
    elif not consumers.confirmed:
        QTreeWidgetItem(parent, ["No configured consumers"])


class ConsumerTree:
    """Adds expandable consumers below the top-level event rows of a tree.

    The owning view's rows keep their own (NN, EN) in column 0 UserRole.
    Children are built from already discovered state on expansion only.
    """

    def __init__(self, tree):
        self.tree = tree
        # Set by LayoutView: identity -> Consumers, and (node, identity) -> None.
        self.lookup = None
        self.open_node = None
        # Double-click stays for description editing and navigation, as in
        # Consumed Events; the arrow expands.
        tree.setExpandsOnDoubleClick(False)
        tree.itemExpanded.connect(self.fill)
        tree.itemDoubleClicked.connect(self.open)

    def save(self):
        """Expanded and current rows, by identity and node, not by tree position."""
        expanded = set()
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item.isExpanded():
                expanded.add(item.data(0, Qt.ItemDataRole.UserRole))
                for index in range(item.childCount()):
                    child = item.child(index)
                    if child.isExpanded():
                        expanded.add(child.data(0, KEY_ROLE))
        current = self.tree.currentItem()
        return expanded, self.key(current) if current is not None else None

    def restore(self, state):
        """Make the view's freshly added event rows expandable; reapply state."""
        if self.lookup is None:
            return
        expanded, current_key = state
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            item.setData(0, KEY_ROLE, True)
            item.setChildIndicatorPolicy(
                QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
            )
            identity = item.data(0, Qt.ItemDataRole.UserRole)
            item.setExpanded(identity in expanded)  # Expanding fills the rows.
            rows = [item]
            for index in range(item.childCount()):
                child = item.child(index)
                child.setExpanded(child.data(0, KEY_ROLE) in expanded)
                rows.append(child)
                rows.extend(child.child(i) for i in range(child.childCount()))
            if current_key is None:
                continue
            for candidate in rows:
                if self.key(candidate) == current_key:
                    self.tree.setCurrentItem(candidate)

    def key(self, item):
        """Event rows: identity; consumer rows: (identity, node); EVs add the label."""
        parent = item.parent()
        if parent is None:
            return (item.data(0, Qt.ItemDataRole.UserRole), None)
        if parent.parent() is None:
            key = item.data(0, KEY_ROLE)  # None for status rows.
            return None if key is None else (key, None)
        return (parent.data(0, KEY_ROLE), item.text(0))

    def refresh(self) -> None:
        """Rebuild consumers after configuration changes, keeping expansion."""
        if self.lookup is None:
            return
        state = self.save()
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item.data(0, KEY_ROLE):
                item.setExpanded(False)
                item.takeChildren()
        self.restore(state)

    def fill(self, item) -> None:
        if (
            self.lookup is None
            or item.parent() is not None
            or not item.data(0, KEY_ROLE)
            or item.childCount()
        ):
            return
        identity = item.data(0, Qt.ItemDataRole.UserRole)
        add_consumer_rows(item, identity, self.lookup(identity))

    def open(self, item, _column) -> None:
        key = item.data(0, KEY_ROLE)
        if self.open_node is None or item.parent() is None or key is None:
            return
        identity, number = key
        trace(
            logger,
            "Open consuming node requested",
            extra={"fields": {"node_number": number, "identity": identity}},
        )
        # Navigation can rebuild this tree; let other double-click slots finish
        # with the clicked item first.
        QTimer.singleShot(0, self.tree, lambda: self.open_node(number, identity))

    def load_action(self, service) -> QAction:
        """Read unread nodes' events and EVs (no NVs); expansion never reads."""
        action = QAction("Load Unread Nodes", self.tree)
        action.setEnabled(bool(unread_nodes(service)) and not service.writes_busy())
        action.triggered.connect(lambda: load_unread_nodes(service))
        return action


def load_unread_nodes(service) -> None:
    """Queue existing on-demand event reads; views refresh as replies arrive."""
    numbers = unread_nodes(service)
    started = [number for number in numbers if service.load_events(number)]
    trace(
        logger,
        "Load unread nodes requested",
        extra={
            "fields": {
                "layout": service.connection.layout_name,
                "unread": numbers,
                "started": started,
            }
        },
    )
