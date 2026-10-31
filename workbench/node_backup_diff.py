from .backup_view import backup_contents


def compare_node(node, backup):
    """Return differences between a node backup and the current node."""

    contents = backup_contents(backup)
    differences = []

    def compare_section(title, saved, current, label):
        for key in sorted(saved.keys() | current.keys()):
            old = saved.get(key)
            new = current.get(key)

            if old != new:
                differences.append((title, label(key), old, new))

    saved_details = contents["node_details"]
    current_details = {
        "number": node.number,
        "can_id": node.can_id,
    }

    if "module_type" in saved_details:
        current_details["module_type"] = node.module_type

    if "firmware" in saved_details:
        current_details["firmware"] = node.firmware

    compare_section(
        "Node details",
        {key: value for key, value in saved_details.items() if key in current_details},
        current_details,
        lambda key: key.replace("_", " ").capitalize(),
    )

    compare_section(
        "Node variables",
        contents["nv_values"],
        node.nv_values,
        lambda key: f"NV {key}",
    )

    compare_section(
        "NV descriptions",
        contents["nv_descriptions"],
        node.nv_descriptions,
        lambda key: f"NV {key}",
    )

    event_ids = (
        contents["consumed_events"].keys()
        | node.consumed_events.keys()
        | contents["ev_values"].keys()
        | node.ev_values.keys()
    )

    for event_id in sorted(event_ids):
        old = contents["consumed_events"].get(event_id)
        new = node.consumed_events.get(event_id)

        if old != new:
            differences.append((f"Consumed events/{event_id}", "Description", old, new))

        saved_evs = contents["ev_values"].get(event_id, {})
        current_evs = node.ev_values.get(event_id, {})

        compare_section(
            f"Consumed events/{event_id}",
            saved_evs,
            current_evs,
            lambda key: f"EV {key}",
        )

    return differences
