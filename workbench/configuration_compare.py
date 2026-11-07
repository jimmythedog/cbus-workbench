"""Compare existing node backup dictionaries without Qt or live service objects."""

import logging
from dataclasses import dataclass
from enum import Enum


class ValueState(Enum):
    CONFIRMED = "confirmed"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    EVENT_ABSENT = "event absent"


@dataclass(frozen=True)
class ComparisonValue:
    state: ValueState
    value: int | str | None = None


ABSENT = ComparisonValue(ValueState.ABSENT)
UNKNOWN = ComparisonValue(ValueState.UNKNOWN)
EVENT_ABSENT = ComparisonValue(ValueState.EVENT_ABSENT)
PRESENT = ComparisonValue(ValueState.CONFIRMED, "Present")


@dataclass
class Confirmation:
    """Transient live evidence that the YAML format cannot preserve."""

    events_complete: bool
    ev_values: dict[tuple[int, int], dict[int, int | None]]


@dataclass(frozen=True)
class ComparisonRow:
    section: str
    label: str
    left: ComparisonValue
    right: ComparisonValue
    event: tuple[int, int] | None = None

    @property
    def outcome(self) -> str:
        if ValueState.UNKNOWN in (self.left.state, self.right.state):
            return "unknown"
        return "equal" if self.left == self.right else "different"


@dataclass
class NodeComparison:
    rows: list[ComparisonRow]
    inconclusive: bool


def _ev_values(dataset, event, identity, confirmation):
    if confirmation is not None:
        confirmed = confirmation.ev_values.get(identity, {})
        # The positional snapshot also carries the extent of unread EVs. Its
        # nulls cannot override the stronger sparse confirmation evidence.
        last = max(len(event["eventVariables"]), max(confirmed, default=0))
        return {
            index: UNKNOWN
            if index not in confirmed
            else (
                ABSENT
                if confirmed[index] is None
                else ComparisonValue(ValueState.CONFIRMED, confirmed[index])
            )
            for index in range(1, last + 1)
        }
    return {
        index: (ABSENT if dataset["complete"] else UNKNOWN)
        if value is None
        else ComparisonValue(ValueState.CONFIRMED, value)
        for index, value in enumerate(event["eventVariables"], 1)
    }


def compare_configurations(
    left: dict,
    right: dict,
    *,
    left_confirmation: Confirmation | None = None,
    right_confirmation: Confirmation | None = None,
) -> NodeComparison:
    """Compare two backup-format dictionaries; omitted partial data stays unknown.

    Complete files trim trailing absent EVs. Live confirmation mappings instead
    distinguish every confirmed absence from unread positions, even on partial nodes.
    Equal and unknown rows are retained for callers to choose their presentation.
    """
    rows = [
        ComparisonRow(
            "Node details",
            "Number",
            ComparisonValue(ValueState.CONFIRMED, left["node"]),
            ComparisonValue(ValueState.CONFIRMED, right["node"]),
        )
    ]
    for index in range(max(len(left["nvs"]), len(right["nvs"]))):
        values = []
        for dataset in (left, right):
            value = dataset["nvs"][index] if index < len(dataset["nvs"]) else None
            values.append(
                UNKNOWN
                if value is None
                else ComparisonValue(ValueState.CONFIRMED, value)
            )
        rows.append(ComparisonRow("Node variables", f"NV {index + 1}", *values))

    events = [
        {(e["nodeNumber"], e["eventNumber"]): e for e in d["events"]}
        for d in (left, right)
    ]
    for identity in sorted(events[0].keys() | events[1].keys()):
        rows.extend(
            _compare_event(
                identity, left, right, events, left_confirmation, right_confirmation
            )
        )
    result = NodeComparison(
        rows,
        not left["complete"]
        or not right["complete"]
        or any(row.outcome == "unknown" for row in rows),
    )
    # Use the project's TRACE level without importing its Qt-backed path setup.
    logging.getLogger("workbench.backups").log(
        5,
        "Configurations compared",
        extra={
            "fields": {
                "left_node": left["node"],
                "right_node": right["node"],
                "rows": len(rows),
                "differences": sum(row.outcome == "different" for row in rows),
                "unknown": sum(row.outcome == "unknown" for row in rows),
                "inconclusive": result.inconclusive,
            }
        },
    )
    return result


def _compare_event(
    identity, left, right, events, left_confirmation, right_confirmation
):
    rows = []
    membership = []
    evs = []
    defaults = []
    for dataset, saved, confirmation in zip(
        (left, right), events, (left_confirmation, right_confirmation)
    ):
        complete = (
            dataset["complete"]
            if confirmation is None
            else confirmation.events_complete
        )
        present = identity in saved
        membership.append(PRESENT if present else EVENT_ABSENT if complete else UNKNOWN)
        evs.append(
            _ev_values(
                dataset,
                saved[identity],
                identity,
                confirmation,
            )
            if present
            else {}
        )
        defaults.append(
            ABSENT if confirmation is None and dataset["complete"] else UNKNOWN
        )
    rows.append(ComparisonRow("Consumed events", "Event", *membership, identity))
    for index in range(1, max(max(evs[0], default=0), max(evs[1], default=0)) + 1):
        values = [
            evs[side].get(index, defaults[side])
            if membership[side] == PRESENT
            else membership[side]
            for side in (0, 1)
        ]
        # For a one-sided event, show numeric EVs actually confirmed there;
        # do not invent a list of absent/unread EVs beneath the membership row.
        if membership[0] != membership[1] and not any(
            value.state == ValueState.CONFIRMED for value in values
        ):
            continue
        rows.append(ComparisonRow("Consumed events", f"EV {index}", *values, identity))
    return rows
