import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .backup_diff_tree import add_node_differences, set_comparison_headings
from .configuration_compare import ValueState, compare_configurations
from .logging_config import trace
from .node_backup_diff import compare_live_configuration, compare_node
from .node_backup_files import load_layout_node


class LayoutBackupCompare(QDialog):
    def __init__(
        self,
        backup,
        nodes,
        events,
        node_backups,
        parent=None,
        *,
        manifest_path=None,
        headings=("Backup", "Current"),
        snapshots=None,
        offline=(),
        message="",
        connection=None,
        retry_available=None,
        retry_signals=(),
    ):
        super().__init__(parent)
        self.retry_available = retry_available
        self.retry_button = None

        self.setWindowTitle("Layout backup — Compare with current")
        self.resize(750, 500)

        layout = QVBoxLayout(self)

        if message:
            label = QLabel(message)
            label.setWordWrap(True)
            layout.addWidget(label)

        tree = QTreeWidget()
        set_comparison_headings(tree, headings)
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tree.setColumnWidth(0, 250)
        layout.addWidget(tree)

        if snapshots is not None:
            self._compare_selected(tree, snapshots, nodes, offline)
            self.selected_snapshots = snapshots
            self.tree = tree
            if connection is not None:
                connection.state_changed.connect(self.connection_changed)
        elif manifest_path is not None:
            self._compare_live(tree, backup, nodes, manifest_path)
        else:
            self._compare_prototype(tree, backup, nodes, events, node_backups)

        if tree.topLevelItemCount() == 0:
            QTreeWidgetItem(tree, ["No differences found"])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        if snapshots is not None and retry_available is not None:
            self.retry_button = buttons.addButton(
                "Retry", QDialogButtonBox.ButtonRole.ActionRole
            )
            self.retry_button.clicked.connect(self.accept)
            for signal in retry_signals:
                signal.connect(self.update_retry)
            self.update_retry()
        layout.addWidget(buttons)

    def update_retry(self, *_args):
        if self.retry_button is not None:
            self.retry_button.setVisible(self.needs_retry)
            self.retry_button.setEnabled(self.needs_retry and self.retry_available())

    def connection_changed(self, state):
        if state != "Connected":
            self.tree.clear()
            self._compare_selected(
                self.tree, self.selected_snapshots, [], self.selected_snapshots
            )
        self.update_retry()

    def _compare_selected(self, tree, snapshots, states, offline):
        """Use the same comparison engine; unread targets have unknown actual data."""
        self.needs_retry = False
        current = {state.identity.node_number: state for state in states}
        for number, snapshot in snapshots.items():
            item = QTreeWidgetItem(tree, [f"Node {number}"])
            if number in offline:
                QTreeWidgetItem(item, ["Offline"])
            if number in current:
                comparison = compare_live_configuration(current[number], snapshot)
            else:
                unknown = {"node": number, "complete": False, "nvs": [], "events": []}
                comparison = compare_configurations(snapshot, unknown)
            self.needs_retry |= any(
                row.outcome == "different"
                or (
                    row.left.state != ValueState.UNKNOWN
                    and row.right.state == ValueState.UNKNOWN
                )
                for row in comparison.rows
            )
            add_node_differences(item, comparison)
            if comparison.inconclusive:
                if number not in offline and not any(
                    row.outcome == "unknown" for row in comparison.rows
                ):
                    QTreeWidgetItem(item, ["Unknown"])
            elif not any(row.outcome != "equal" for row in comparison.rows):
                QTreeWidgetItem(item, ["No differences found"])
            item.setExpanded(True)

    def _compare_live(self, tree, backup, states, manifest_path):
        current = {state.identity.node_number: state for state in states}
        saved = set(backup["nodeNumbers"])
        inconclusive = not backup["complete"] or not saved
        configurations = QTreeWidgetItem(["Node configurations"])
        for number in sorted(saved | current.keys()):
            # Load every manifest member, including nodes not currently discovered,
            # so missing or invalid associated files use the usual error reporter.
            snapshot = (
                load_layout_node(manifest_path, number) if number in saved else None
            )
            node_item = QTreeWidgetItem([f"Node {number}"])
            if snapshot is None or number not in current:
                inconclusive = True
                # Neither discovery pass proves the absence of undiscovered hardware.
                QTreeWidgetItem(
                    node_item,
                    [
                        "Node membership inconclusive",
                        "Included"
                        if snapshot is not None
                        else "Not included in manifest",
                        "Discovered" if number in current else "Not discovered",
                    ],
                )
            else:
                differences = compare_live_configuration(current[number], snapshot)
                partial = differences.inconclusive
                add_node_differences(node_item, differences)
                inconclusive = inconclusive or partial
                if partial:
                    QTreeWidgetItem(
                        node_item, ["Comparison inconclusive: some values are unknown"]
                    )
            if node_item.childCount():
                configurations.addChild(node_item)
                node_item.setExpanded(True)
        if configurations.childCount():
            tree.addTopLevelItem(configurations)
            configurations.setExpanded(True)
        if inconclusive:
            QTreeWidgetItem(tree, ["Layout comparison inconclusive"])
        trace(
            logging.getLogger("workbench.backups"),
            "Layout backup compared",
            extra={
                "fields": {
                    "path": str(manifest_path),
                    "saved_nodes": sorted(saved),
                    "current_nodes": sorted(current),
                    "inconclusive": inconclusive,
                }
            },
        )

    def _compare_prototype(self, tree, backup, nodes, events, node_backups):
        # Compare node membership.
        saved_nodes = set(backup["nodeNumbers"])
        current_nodes = {node.number for node in nodes}

        node_section = QTreeWidgetItem(["Nodes"])

        for number in sorted(saved_nodes | current_nodes):
            if (number in saved_nodes) != (number in current_nodes):
                QTreeWidgetItem(
                    node_section,
                    [
                        f"Node {number}",
                        "Not found" if number not in saved_nodes else "",
                        "Not found" if number not in current_nodes else "",
                    ],
                )

        if node_section.childCount():
            tree.addTopLevelItem(node_section)
            node_section.setExpanded(True)

        # Compare configurations in the associated node snapshots.
        configuration_section = QTreeWidgetItem(["Node configurations"])
        timestamp = backup.get("timestamp")

        if timestamp is not None:
            for node in nodes:
                if node.number not in saved_nodes:
                    continue

                snapshot = node_backups.layout_snapshot(node.number, timestamp)

                if snapshot is None:
                    continue

                differences = compare_node(node, snapshot)

                if not differences:
                    continue

                node_item = QTreeWidgetItem([f"Node {node.number}"])
                configuration_section.addChild(node_item)
                node_item.setExpanded(True)

                add_node_differences(node_item, differences)

        if configuration_section.childCount():
            tree.addTopLevelItem(configuration_section)
            configuration_section.setExpanded(True)
        # Compare produced event descriptions.
        event_section = QTreeWidgetItem(["Produced events"])

        saved_events = backup["eventCatalogue"]

        for node_number in sorted(saved_events.keys() | events.keys()):
            saved = saved_events.get(node_number, {})
            current = events.get(node_number, {})

            node_item = QTreeWidgetItem([f"Node {node_number}"])

            for event_number in sorted(saved.keys() | current.keys()):
                old = saved.get(event_number)
                new = current.get(event_number)

                # Current events store their descriptions in dictionaries.
                if isinstance(new, dict):
                    new = new.get("description", "")

                if old != new:
                    QTreeWidgetItem(
                        node_item,
                        [
                            f"Event {event_number}",
                            str(old) if old is not None else "—",
                            str(new) if new is not None else "—",
                        ],
                    )

            if node_item.childCount():
                event_section.addChild(node_item)
                node_item.setExpanded(True)

        if event_section.childCount():
            tree.addTopLevelItem(event_section)
            event_section.setExpanded(True)
