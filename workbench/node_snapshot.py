from copy import deepcopy


def restore_node_snapshot(node, contents):
    """Apply saved configuration values from normalized backup contents."""

    node.nv_values = deepcopy(contents["nv_values"])
    node.consumed_events = deepcopy(contents["consumed_events"])
    node.ev_values = deepcopy(contents["ev_values"])


def create_node_snapshot(node):
    """Capture the current node configuration in CW-OLD backup format."""

    events = []

    for event_id, values in node.ev_values.items():
        node_number, event_number = map(int, event_id.split(":"))

        events.append(
            {
                "nodeNumber": node_number,
                "eventNumber": event_number,
                "eventVariables": [values[index] for index in sorted(values)],
            }
        )

    annotations = deepcopy(node.annotations)

    # Include descriptions already held by the current Node model.
    if node.consumed_events:
        annotations.setdefault("events", {})["consumed"] = deepcopy(
            node.consumed_events
        )

    return {
        "nodeNumber": node.number,
        "manufacturerId": node.manufacturer_id,
        "moduleId": node.module_id,
        "nodeVariables": [node.nv_values[index] for index in sorted(node.nv_values)],
        "events": events,
        "annotations": annotations,
        "metadata": {
            "parameters": deepcopy(node.parameters),
            "canId": node.can_id,
        },
        "partOfLayoutBackup": False,
    }
