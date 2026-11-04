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

    if "format_version" in backup:
        return {
            "complete": backup["complete"],
            "partOfLayoutBackup": backup["partOfLayoutBackup"],
            "node_details": {"number": backup["node"]},
            "nv_values": dict(enumerate(backup["nvs"], 1)),
            "consumed_events": {
                f"{event['nodeNumber']}:{event['eventNumber']}": ""
                for event in backup["events"]
            },
            "ev_values": {
                f"{event['nodeNumber']}:{event['eventNumber']}": dict(
                    enumerate(event["eventVariables"], 1)
                )
                for event in backup["events"]
            },
        }

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


def display_value(value):
    return "Absent / unknown" if value is None else str(value)


def add_configuration_items(parent, contents):
    """Show NVs and consumed events consistently in node and layout backups."""
    # Saved node variables
    variables = QTreeWidgetItem(parent, ["Node variables"])
    for number, value in sorted(contents["nv_values"].items()):
        QTreeWidgetItem(variables, [f"NV {number}", display_value(value)])

    # Saved consumed events and their event variables
    events = QTreeWidgetItem(parent, ["Consumed events"])
    for event_id, description in contents["consumed_events"].items():
        event = QTreeWidgetItem(events, [event_id, description])

        for number, value in contents["ev_values"].get(event_id, {}).items():
            text = (
                "Absent"
                if value is None and contents.get("complete") is True
                else display_value(value)
            )
            QTreeWidgetItem(event, [f"EV {number}", text])


class BackupView(QDialog):
    def __init__(self, node, backup, parent=None):
        super().__init__(parent)

        contents = backup_contents(backup)

        self.setWindowTitle(
            f"Node {contents['node_details']['number']} — Backup contents"
        )
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
        if "complete" in contents:
            QTreeWidgetItem(
                snapshot,
                ["Discovery", "Complete" if contents["complete"] else "Incomplete"],
            )
        for key in ("created", "description"):
            if key in contents:
                QTreeWidgetItem(snapshot, [key.capitalize(), contents[key]])
        if contents.get("partOfLayoutBackup"):
            QTreeWidgetItem(snapshot, ["Ownership", "Part of layout backup"])
        snapshot.setExpanded(True)

        # Saved node details
        details = QTreeWidgetItem(tree, ["Node details"])
        for name, value in contents["node_details"].items():
            QTreeWidgetItem(
                details, [name.replace("_", " ").capitalize(), display_value(value)]
            )

        add_configuration_items(tree, contents)

        # Saved NV descriptions
        descriptions = (
            QTreeWidgetItem(tree, ["NV descriptions"])
            if "nv_descriptions" in contents
            else None
        )
        for number, description in contents.get("nv_descriptions", {}).items():
            QTreeWidgetItem(descriptions, [f"NV {number}", description])

        # Other saved annotations
        annotations = (
            QTreeWidgetItem(tree, ["Annotations"])
            if "annotations" in contents
            else None
        )
        for name, value in contents.get("annotations", {}).items():
            QTreeWidgetItem(annotations, [str(name), display_value(value)])

        details.setExpanded(True)
