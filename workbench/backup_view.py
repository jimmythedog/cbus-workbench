from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


def backup_contents(backup):
    """Return the saved configuration in the format used by the View dialog."""

    if "node_details" in backup:
        return backup

    annotations = backup.get("annotations", {})
    descriptions = annotations.get("events", {}).get("consumed", {})

    events = {}
    ev_values = {}

    for saved_event in backup.get("events", []):
        event_id = f"{saved_event['nodeNumber']}:{saved_event['eventNumber']}"
        events[event_id] = descriptions.get(event_id, "")
        ev_values[event_id] = {
            index: value
            for index, value in enumerate(saved_event["eventVariables"], start=1)
        }

    return {
        "created": backup.get("created", ""),
        "description": backup.get("description", ""),
        "node_details": {
            "number": backup["nodeNumber"],
            "manufacturer_id": backup.get("manufacturerId"),
            "module_id": backup.get("moduleId"),
            "can_id": backup.get("metadata", {}).get("canId"),
        },
        "nv_values": {
            index: value
            for index, value in enumerate(backup.get("nodeVariables", []), start=1)
        },
        "consumed_events": events,
        "ev_values": ev_values,
        "nv_descriptions": annotations.get("nvDescriptions", {}),
        "annotations": annotations,
    }


class BackupView(QDialog):
    def __init__(self, node, backup, parent=None):
        super().__init__(parent)

        contents = backup_contents(backup)

        self.setWindowTitle(f"Node {node.number} — Backup contents")
        self.resize(650, 450)

        layout = QVBoxLayout(self)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Item", "Value"])
        tree.setColumnWidth(0, 250)
        layout.addWidget(tree)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        snapshot = QTreeWidgetItem(tree, ["Backup"])
        QTreeWidgetItem(snapshot, ["Created", contents["created"]])
        QTreeWidgetItem(snapshot, ["Description", contents["description"]])
        snapshot.setExpanded(True)

        # Saved node details
        details = QTreeWidgetItem(tree, ["Node details"])
        for name, value in contents["node_details"].items():
            QTreeWidgetItem(details, [name.replace("_", " ").capitalize(), str(value)])

        # Saved node variables
        variables = QTreeWidgetItem(tree, ["Node variables"])
        for number, value in sorted(contents["nv_values"].items()):
            QTreeWidgetItem(variables, [f"NV {number}", str(value)])

        # Saved consumed events and their event variables
        events = QTreeWidgetItem(tree, ["Consumed events"])
        for event_id, description in contents["consumed_events"].items():
            event = QTreeWidgetItem(events, [event_id, description])

            for number, value in contents["ev_values"].get(event_id, {}).items():
                QTreeWidgetItem(event, [f"EV {number}", str(value)])

        # Saved NV descriptions
        descriptions = QTreeWidgetItem(tree, ["NV descriptions"])
        for number, description in contents["nv_descriptions"].items():
            QTreeWidgetItem(descriptions, [f"NV {number}", description])

        # Other saved annotations
        annotations = QTreeWidgetItem(tree, ["Annotations"])
        for name, value in contents["annotations"].items():
            QTreeWidgetItem(annotations, [str(name), str(value)])

        details.setExpanded(True)
