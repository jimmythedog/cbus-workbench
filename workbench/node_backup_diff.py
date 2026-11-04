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


def compare_live_node(state, backup):
    """Compare only confirmed values; return differences and an uncertainty flag.

    Missing live keys are unknown, while present EV None values are confirmed
    absent. A partial file cannot distinguish absence from unread positions.
    """
    from .cbus_service import DiscoveryProgress
    from .node_backup_files import node_backup

    differences = []
    inconclusive = not backup["complete"] or not node_backup(state)["complete"]
    unknown = object()

    def compare(section, label, old, new):
        nonlocal inconclusive
        if old is unknown or new is unknown:
            inconclusive = True
        elif old != new:
            differences.append((section, label, old, new))

    compare("Node details", "Number", backup["node"], state.identity.node_number)
    saved_nvs = dict(enumerate(backup["nvs"], 1))
    for index in sorted(saved_nvs.keys() | state.nv_values.keys()):
        old = saved_nvs.get(index)
        compare(
            "Node variables",
            f"NV {index}",
            unknown if old is None else old,
            state.nv_values.get(index, unknown),
        )

    saved_events = {
        (event["nodeNumber"], event["eventNumber"]): event["eventVariables"]
        for event in backup["events"]
    }
    live_events = {
        identity: state.ev_values.get(index, {})
        for index, identity in state.event_identities.items()
    }
    # Event membership needs a completed enumeration, independently of EV reads.
    enumeration_complete = (
        state.event_progress == DiscoveryProgress.COMPLETE
        and state.stored_event_count is not None
        and len(live_events) == state.stored_event_count
    ) or (
        not state.identity.is_consumer
        and state.event_progress == DiscoveryProgress.SKIPPED
        and not live_events
    )
    for identity in sorted(saved_events.keys() | live_events.keys()):
        section = f"Consumed events/{identity[0]}:{identity[1]}"
        if identity not in saved_events:
            compare(
                section, "Event", None if backup["complete"] else unknown, "Present"
            )
            continue
        if identity not in live_events:
            compare(
                section, "Event", "Present", None if enumeration_complete else unknown
            )
            continue
        saved = dict(enumerate(saved_events[identity], 1))
        current = live_events[identity]
        last = max(len(saved), state.parameters.get(5, 0), max(current, default=0))
        for index in range(1, last + 1):
            old = saved.get(index)
            # Complete files trim trailing confirmed absences. Partial files do
            # not carry enough information to interpret any null or omission.
            if old is None and not backup["complete"]:
                old = unknown
            compare(section, f"EV {index}", old, current.get(index, unknown))
    return differences, inconclusive
