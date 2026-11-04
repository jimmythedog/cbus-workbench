from PySide6.QtWidgets import QTreeWidgetItem


def add_node_differences(parent, differences):
    """Add compare_node() differences beneath a tree or node item."""
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

        absent = (
            "Absent"
            if section_name.startswith("Consumed events/")
            and item_name.startswith("EV ")
            else "—"
        )
        QTreeWidgetItem(
            section,
            [
                item_name,
                str(old) if old is not None else absent,
                str(new) if new is not None else absent,
            ],
        )
