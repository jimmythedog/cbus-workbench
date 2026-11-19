"""Which nodes on one connection are configured to consume an event (#87).

Evidence is the connection's live consumed-event discovery only. Observed
traffic, backups and saved offline metadata never establish a consumer. A node
whose consumed events are not confirmed is reported as undetermined, so an
empty consumer list is never presented as complete when it is not.
Matching uses event identities `(NN, EN)`; table slots only locate EVs. Short
events are already `(0, EN)` in both the catalogue and discovery.

A consumer's EVs are interpreted by the same MDF presentation as its Consumed
Events (event_mdf.py), read-only, using only the NVs discovery has read.
"""

import logging
from dataclasses import dataclass, field, replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QTreeWidgetItem

from .cbus_service import DiscoveryProgress
from .event_mdf import EvContainer, NoHoverDelegate, add_ev_controls, ev_definitions
from .logging_config import trace
from .parameter_names import module_name

logger = logging.getLogger("workbench.events")

# Column 0 role for rows this module adds; the views keep using UserRole.
KEY_ROLE = Qt.ItemDataRole.UserRole + 1
# Consumer rows hold their Consumer until expansion builds its MDF controls.
PENDING_ROLE = Qt.ItemDataRole.UserRole + 2

NOT_LOADED = "not loaded"
DISCONNECTED = "disconnected"
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
    # Read NVs only: MDF visibility and labels treat the rest as unknown.
    nv_values: dict[int, int | None] = field(default_factory=dict)


@dataclass
class Consumers:
    confirmed: list[Consumer] = field(default_factory=list)
    # Node number -> why its consumed events are not confirmed.
    undetermined: dict[int, str] = field(default_factory=dict)


def without_nvs(consumers: Consumers) -> Consumers:
    """Consumers as they would be built, ignoring NVs, which update in place."""
    return replace(
        consumers,
        confirmed=[replace(consumer, nv_values={}) for consumer in consumers.confirmed],
    )


def non_consumer(state) -> bool:
    """The PNN consumer flag is what discovery itself uses to skip a node."""
    return state.event_progress == DiscoveryProgress.SKIPPED or (
        state.event_progress == DiscoveryProgress.NOT_STARTED
        and state.identity_confirmed
        and not state.identity.is_consumer
    )


def unread_nodes(service) -> list[int]:
    """Online possible consumers whose events or NVs were never read here.

    Unread events are the "not loaded" nodes of find_consumers(). Unread NVs
    leave MDF labels and visibility of confirmed consumers unknown. Neither
    depends on the event. Failed reads are excluded: load_events() and
    load_nvs() never retry them, and load_nvs() needs the NV count.
    """
    if service is None or service.connection.state != "Connected":
        return []
    return [
        number
        for number, state in sorted(service.node_states.items())
        if service.presence.get(number, False)
        and not non_consumer(state)
        and (
            state.event_progress == DiscoveryProgress.NOT_STARTED
            or (
                state.nv_progress == DiscoveryProgress.NOT_STARTED
                and 6 in state.parameters
            )
        )
    ]


def find_consumers(identity, service, known_names: dict[int, str]) -> Consumers:
    """Confirmed consumers of identity, plus nodes that might still consume it.

    known_names maps navigator nodes to the label it shows (user-defined name,
    else module type); consumers missing from it (or with an empty label) fall
    back to module type.
    """
    identity = tuple(identity)
    connected = service is not None and service.connection.state == "Connected"
    states = service.node_states if connected else {}
    presence = service.presence if connected else {}
    result = Consumers()
    for number in sorted(set(known_names) | set(states)):
        state = states.get(number)
        if not connected:
            result.undetermined[number] = DISCONNECTED
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
        # The navigator's cached label: refreshes run on every discovery step,
        # so avoid rereading each node's annotation file here.
        result.confirmed.append(
            Consumer(
                number,
                known_names.get(number)
                or module_name(state.identity.manufacturer, state.identity.module_type),
                state.parameters.get(5),
                dict(state.ev_values.get(slot, {})),
                dict(state.nv_values),
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
            ev = QTreeWidgetItem(
                row, [f"EV {index}", "Unknown" if value is None else str(value)]
            )
            ev.setData(0, Qt.ItemDataRole.UserRole, index)
        row.setData(0, PENDING_ROLE, consumer)
    if consumers.undetermined:
        reasons = set(consumers.undetermined.values())
        # Refresh needs a connection, so a disconnected layout must connect first.
        if DISCONNECTED in reasons:
            hint = "Use Layouts → Connect"
        elif NOT_LOADED in reasons:
            hint = "Right-click to load unread nodes"
        else:
            hint = "Use Layouts → Refresh"
        # Collapsed by default: a large layout can have many such nodes.
        status = QTreeWidgetItem(parent, ["Not determined", hint])
        status.setData(0, KEY_ROLE, (identity, None))
        for number, reason in sorted(consumers.undetermined.items()):
            QTreeWidgetItem(status, [f"Node {number}", reason])
    elif not consumers.confirmed:
        QTreeWidgetItem(parent, ["No configured consumers"])


class ConsumerTree:
    """Adds expandable consumers below the top-level event rows of a tree.

    The owning view's rows keep their own (NN, EN) in column 0 UserRole.
    Children are built from already discovered state on expansion only.
    """

    def __init__(self, tree):
        self.tree = tree
        # Set by LayoutView: identity -> Consumers, (node, identity) -> None,
        # and node -> token-substituted MDF data or None.
        self.lookup = None
        self.open_node = None
        self.mdf_lookup = None
        # Identity -> the Consumers its current rows were built from.
        self.shown = {}
        # Double-click stays for description editing and navigation, as in
        # Consumed Events; the arrow expands.
        tree.setExpandsOnDoubleClick(False)
        # As Consumed Events: no expand animation flicker and no hover on
        # MDF control rows.
        tree.setAnimated(False)
        tree.setItemDelegate(NoHoverDelegate(tree))
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
        """Event rows: identity; consumer rows: (identity, node); EVs add the label.

        An MDF control row keys as its EV row, as in Consumed Events.
        """
        parent = item.parent()
        grandparent = parent.parent() if parent is not None else None
        if grandparent is not None and grandparent.parent() is not None:
            item, parent = parent, grandparent
        if parent is None:
            return (item.data(0, Qt.ItemDataRole.UserRole), None)
        if parent.parent() is None:
            key = item.data(0, KEY_ROLE)  # None for status rows.
            return None if key is None else (key, None)
        return (parent.data(0, KEY_ROLE), item.text(0))

    def refresh(self, *, rebuild=False) -> None:
        """Rebuild changed consumers after configuration changes, keeping expansion.

        Discovery updates arrive for every reply, so expanded events whose
        consumers are unchanged keep their rows and any MDF controls already
        built; NV-only changes refresh those controls in place (as #151 does in
        Consumed Events). Collapsed events are emptied and rebuild on expansion.
        rebuild=True rebuilds them all, e.g. for renamed MDF tokens.
        """
        if self.lookup is None:
            return
        state = self.save()
        rebuilt = []
        updated = []
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if not item.data(0, KEY_ROLE) or not item.childCount():
                continue
            identity = item.data(0, Qt.ItemDataRole.UserRole)
            if not rebuild and item.isExpanded():
                consumers = self.lookup(identity)
                shown = self.shown.get(identity)
                if consumers == shown:
                    continue
                if shown is not None and without_nvs(consumers) == without_nvs(shown):
                    self.update_nvs(item, consumers)
                    self.shown[identity] = consumers
                    updated.append(identity)
                    continue
            item.setExpanded(False)
            item.takeChildren()
            rebuilt.append(identity)
        if rebuilt or updated:
            trace(
                logger,
                "Event consumers refreshed",
                extra={"fields": {"rebuilt": rebuilt, "nvs_updated": updated}},
            )
        self.restore(state)

    def update_nvs(self, event, consumers: Consumers) -> None:
        """Give built MDF controls (and unbuilt consumers) the latest NVs."""
        rows = [
            child
            for child in (event.child(i) for i in range(event.childCount()))
            if (child.data(0, KEY_ROLE) or (None, None))[1] is not None
        ]
        # Consumer rows come first, in find_consumers() order.
        for row, consumer in zip(rows, consumers.confirmed):
            if row.data(0, PENDING_ROLE) is not None:
                row.setData(0, PENDING_ROLE, consumer)
                continue
            for ev in (row.child(i) for i in range(row.childCount())):
                form = self.tree.itemWidget(ev, 1)
                if isinstance(form, EvContainer):
                    for settings in form.settings:
                        settings.show_values(
                            consumer.ev_values,
                            nv_values=consumer.nv_values,
                            ev_values=consumer.ev_values,
                        )
                    form.show_rows()

    def fill(self, item) -> None:
        if self.lookup is None:
            return
        if item.parent() is not None:
            self.add_controls(item)
            return
        if not item.data(0, KEY_ROLE) or item.childCount():
            return
        identity = item.data(0, Qt.ItemDataRole.UserRole)
        consumers = self.lookup(identity)
        self.shown[identity] = consumers
        add_consumer_rows(item, identity, consumers)

    def add_controls(self, row) -> None:
        """Build a consumer's MDF controls once, on its first expansion."""
        consumer = row.data(0, PENDING_ROLE)
        if consumer is None or self.mdf_lookup is None:
            return
        row.setData(0, PENDING_ROLE, None)
        event = row.parent()
        data = self.mdf_lookup(consumer.number)
        trace(
            logger,
            "Build consumer EV controls",
            extra={
                "fields": {
                    "node_number": consumer.number,
                    "identity": event.data(0, Qt.ItemDataRole.UserRole),
                    "mdf": data is not None,
                }
            },
        )
        if data is None:
            return  # Raw EVs only, as Consumed Events shows without an MDF.
        ev_rows = {
            child.data(0, Qt.ItemDataRole.UserRole): child
            for child in (row.child(i) for i in range(row.childCount()))
        }
        # No token editor: these controls are read-only, unlike Consumed Events.
        add_ev_controls(
            self.tree,
            event,
            ev_rows,
            list(ev_definitions(data.get("eventVariables", []))),
            consumer.nv_values,
            consumer.ev_values,
            consumer.number,
        )

    def open(self, item, _column) -> None:
        key = item.data(0, KEY_ROLE)
        if self.open_node is None or item.parent() is None or key is None:
            return
        identity, number = key
        if number is None:
            return  # The Not determined row.
        trace(
            logger,
            "Open consuming node requested",
            extra={"fields": {"node_number": number, "identity": identity}},
        )
        # Navigation can rebuild this tree; let other double-click slots finish
        # with the clicked item first.
        QTimer.singleShot(0, self.tree, lambda: self.open_node(number, identity))

    def load_action(self, service) -> QAction:
        """Read unread nodes' events, EVs and NVs; expansion never reads."""
        action = QAction("Load Unread Nodes", self.tree)
        action.setEnabled(bool(unread_nodes(service)) and not service.writes_busy())
        action.triggered.connect(lambda: load_unread_nodes(service))
        return action


def load_unread_nodes(service) -> None:
    """Queue existing on-demand NV and event reads; views refresh on replies."""
    numbers = unread_nodes(service)
    started = []
    for number in numbers:
        # Both reads are requested; each skips a section already read.
        nvs = service.load_nvs(number)
        if service.load_events(number) or nvs:
            started.append(number)
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
