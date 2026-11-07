from .configuration_compare import Confirmation, ValueState, compare_configurations


def compare_node(node, backup):
    """Return differences between a node backup and the current node."""

    from .backup_view import backup_contents

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


def compare_live_configuration(state, backup):
    """Adapt live confirmation evidence without changing the persisted format."""
    from .cbus_service import DiscoveryProgress
    from .node_backup_files import node_backup, positional_values

    events = {
        identity: state.ev_values.get(index, {})
        for index, identity in state.event_identities.items()
    }
    enumeration_complete = (
        state.event_progress == DiscoveryProgress.COMPLETE
        and state.stored_event_count is not None
        and len(events) == state.stored_event_count
    ) or (
        not state.identity.is_consumer
        and state.event_progress == DiscoveryProgress.SKIPPED
        and not events
    )
    current = node_backup(state)
    current["nvs"] = positional_values(
        state.nv_values,
        max(state.parameters.get(6, 0), max(state.nv_values, default=0)),
    )
    return compare_configurations(
        backup,
        current,
        right_confirmation=Confirmation(enumeration_complete, events),
    )


def compare_live_node(state, backup):
    """Keep the legacy confirmed-difference tuples and uncertainty flag for Restore."""
    result = compare_live_configuration(state, backup)
    differences = []

    for row in result.rows:
        if row.outcome != "different":
            continue
        # One-sided EV rows add inspection detail, not additional restore failures.
        if row.label.startswith("EV ") and ValueState.EVENT_ABSENT in (
            row.left.state,
            row.right.state,
        ):
            continue
        section = row.section
        if row.event is not None:
            section += f"/{row.event[0]}:{row.event[1]}"
        differences.append((section, row.label, row.left.value, row.right.value))
    return differences, result.inconclusive
