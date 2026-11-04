"""One replacement pass over event identities, preserving sparse backup values."""

from dataclasses import dataclass


@dataclass
class EventRestoreStep:
    identity: tuple[int, int]
    values: dict[int, int]
    unlearn: bool
    # None means removal of an extra event; a list is its saved EV configuration.
    saved_values: list[int | None] | None


def plan_event_restore(state, backup: dict) -> list[EventRestoreStep]:
    """Compare before writing; reconstruct only on confirmed saved absence."""
    live = {
        identity: state.ev_values.get(slot, {})
        for slot, identity in state.event_identities.items()
    }
    steps = []
    for event in backup["events"]:
        identity = (event["nodeNumber"], event["eventNumber"])
        saved = event["eventVariables"]
        numeric = {i: v for i, v in enumerate(saved, 1) if v is not None}
        current = live.get(identity)
        reconstruct = False
        changed = {}
        if current is not None:
            for index in range(1, state.parameters.get(5, 0) + 1):
                value = saved[index - 1] if index <= len(saved) else None
                if value is None:
                    if backup["complete"] and current.get(index) is not None:
                        # Stop comparing: partial edits would be lost by unlearn.
                        reconstruct = True
                        break
                elif current.get(index) != value:
                    changed[index] = value
        if current is None or reconstruct:
            if not numeric:
                # EVLRN teaches an identity together with an EV (index 1..n).
                # EV0 is invalid: do not invent a zero merely to create an event.
                raise ValueError(
                    f"Event {identity[0]}:{identity[1]} needs teaching but has no numeric saved EV. "
                    "CBUS has no standalone empty-event teach operation; event not removed."
                )
            if not any(numeric.values()):
                # Some nodes acknowledge a zero EVLRN without creating an event.
                # Do not unlearn an existing event that we cannot reconstruct.
                raise ValueError(
                    f"Event {identity[0]}:{identity[1]} cannot be reconstructed: "
                    "no nonzero saved EV is available to create it; event not removed."
                )
            steps.append(EventRestoreStep(identity, numeric, reconstruct, saved))
        elif changed:
            steps.append(EventRestoreStep(identity, changed, False, saved))
    return steps


def extra_event_steps(state, backup: dict) -> list[EventRestoreStep]:
    """Find extra identities in post-NV discovery to free capacity before teaching."""
    saved = {(e["nodeNumber"], e["eventNumber"]) for e in backup["events"]}
    return [
        EventRestoreStep(identity, {}, True, None)
        for identity in sorted(set(state.event_identities.values()) - saved)
    ]


def event_step_matches(state, step: EventRestoreStep, complete: bool) -> bool:
    """Verify the identity and its known EVs after the writer's rediscovery."""
    slot = next(
        (
            s
            for s, identity in state.event_identities.items()
            if identity == step.identity
        ),
        None,
    )
    if step.saved_values is None:
        return slot is None
    if slot is None:
        return False
    values = state.ev_values.get(slot, {})
    for index in range(1, max(len(step.saved_values), state.parameters.get(5, 0)) + 1):
        expected = (
            step.saved_values[index - 1] if index <= len(step.saved_values) else None
        )
        if (expected is not None or complete) and (
            index not in values or values[index] != expected
        ):
            return False
    return True


def known_backup_verified(state, backup: dict) -> bool:
    """Incomplete files can establish known values and membership, not equivalence."""
    if any(
        v is not None and state.nv_values.get(i) != v
        for i, v in enumerate(backup["nvs"], 1)
    ):
        return False
    saved = {(e["nodeNumber"], e["eventNumber"]) for e in backup["events"]}
    if set(state.event_identities.values()) != saved:
        return False
    return all(
        event_step_matches(
            state,
            EventRestoreStep(
                (e["nodeNumber"], e["eventNumber"]), {}, False, e["eventVariables"]
            ),
            backup["complete"],
        )
        for e in backup["events"]
    )
