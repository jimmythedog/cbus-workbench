from PySide6.QtWidgets import QTreeWidgetItem

from .configuration_compare import NodeComparison, ValueState


def set_comparison_headings(tree, headings=("Backup", "Current")):
    tree.setHeaderLabels(["Item", *headings])


def _comparison_rows(comparison):
    events_with_details = {
        row.event
        for row in comparison.rows
        if row.label.startswith("EV ")
        and ValueState.EVENT_ABSENT in (row.left.state, row.right.state)
        and ValueState.CONFIRMED in (row.left.state, row.right.state)
    }
    for row in comparison.rows:
        if row.outcome == "equal":
            continue
        # EV details already show which side lacks the event. Keep membership
        # alone when there are no confirmed values to inspect beneath it.
        if row.label == "Event" and row.event in events_with_details:
            continue
        section = row.section
        if row.event is not None:
            section += f"/{row.event[0]}:{row.event[1]}"
        values = []
        for value in (row.left, row.right):
            values.append(
                {
                    ValueState.ABSENT: "—",
                    ValueState.EVENT_ABSENT: "—",
                    ValueState.UNKNOWN: (
                        f"Unknown (last confirmed: {value.value})"
                        if value.value is not None
                        else "Unknown"
                    ),
                }.get(value.state, str(value.value))
            )
        yield section, row.label, *values


def add_node_differences(parent, differences):
    """Render structured results, or the unchanged prototype difference tuples.

    Equal rows stay in the dataset. Unverified values display as Unknown;
    the caller also shows the comparison's uncertainty summary.
    """
    if isinstance(differences, NodeComparison):
        differences = _comparison_rows(differences)
    sections = {}

    for section_name, item_name, old, new in differences:
        if section_name.startswith("Consumed events/"):
            event_id = section_name.split("/", 1)[1]
            consumed = sections.get("Consumed events")
            if consumed is None:
                consumed = QTreeWidgetItem(parent, ["Consumed events"])
                consumed.setExpanded(True)
                sections["Consumed events"] = consumed

            event_key = f"event:{event_id}"
            section = sections.get(event_key)
            if section is None:
                section = QTreeWidgetItem(consumed, [event_id])
                section.setExpanded(True)
                sections[event_key] = section
        else:
            section = sections.get(section_name)
            if section is None:
                section = QTreeWidgetItem(parent, [section_name])
                section.setExpanded(True)
                sections[section_name] = section

        QTreeWidgetItem(
            section,
            [
                item_name,
                str(old) if old is not None else "—",
                str(new) if new is not None else "—",
            ],
        )
