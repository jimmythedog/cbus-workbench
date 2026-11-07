"""Pure comparison contracts for existing-format node configuration dictionaries."""

import unittest
from copy import deepcopy

from workbench.configuration_compare import (
    ABSENT,
    EVENT_ABSENT,
    UNKNOWN,
    ValueState,
    compare_configurations,
)


def configuration(events, *, complete=True, nvs=None):
    return {
        "format_version": 1,
        "complete": complete,
        "node": 42,
        "partOfLayoutBackup": False,
        "nvs": [0] if nvs is None else nvs,
        "events": [
            {"nodeNumber": node, "eventNumber": event, "eventVariables": values}
            for node, event, values in events
        ],
    }


class ConfigurationCompareTests(unittest.TestCase):
    def test_equal_values_and_event_order_are_preserved(self):
        left = configuration([(100, 2, [0, None, 7]), (0, 12, [8])])
        right = deepcopy(left)
        right["events"].reverse()
        result = compare_configurations(left, right)
        self.assertFalse(result.inconclusive)
        self.assertTrue(all(row.outcome == "equal" for row in result.rows))
        self.assertTrue(
            any(row.label == "EV 1" and row.left.value == 0 for row in result.rows)
        )

    def test_one_sided_events_include_confirmed_evs_in_both_directions(self):
        present = configuration([(258, 2, [0, None, 13])])
        absent = configuration([])
        for left, right in ((absent, present), (present, absent)):
            with self.subTest(left_present=bool(left["events"])):
                result = compare_configurations(left, right)
                rows = [row for row in result.rows if row.event == (258, 2)]
                self.assertEqual([row.label for row in rows], ["Event", "EV 1", "EV 3"])
                for row in rows:
                    missing = row.right if left["events"] else row.left
                    self.assertEqual(missing, EVENT_ABSENT)
                self.assertFalse(result.inconclusive)

    def test_common_event_absence_zero_and_unknown_are_distinct(self):
        left = configuration([(100, 2, [0, None])])
        right = configuration([(100, 2, [None, 0, 8])])
        rows = compare_configurations(left, right).rows
        evs = {row.label: row for row in rows if row.label.startswith("EV ")}
        self.assertEqual(evs["EV 1"].right, ABSENT)
        self.assertEqual(evs["EV 2"].right.value, 0)
        self.assertEqual(evs["EV 3"].left, ABSENT)  # Trimmed complete-file tail.
        left["complete"] = False
        result = compare_configurations(left, right)
        self.assertTrue(result.inconclusive)
        evs = {row.label: row for row in result.rows if row.label.startswith("EV ")}
        self.assertEqual(evs["EV 2"].left, UNKNOWN)
        self.assertEqual(evs["EV 3"].left, UNKNOWN)

    def test_partial_membership_and_sparse_nvs_do_not_assert_absence(self):
        left = configuration([], complete=False, nvs=[None, 0])
        right = configuration([(0, 12, [0])], nvs=[9])
        for a, b in ((left, right), (right, left)):
            result = compare_configurations(a, b)
            self.assertTrue(result.inconclusive)
            event = next(row for row in result.rows if row.label == "Event")
            self.assertEqual(event.outcome, "unknown")
            self.assertIn(ValueState.UNKNOWN, (event.left.state, event.right.state))
            self.assertTrue(
                all(
                    row.outcome == "unknown"
                    for row in result.rows
                    if row.label.startswith("NV ")
                )
            )
