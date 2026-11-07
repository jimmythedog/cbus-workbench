"""Observable presentation of structured comparison results in the shared tree."""

import os
import unittest
from copy import deepcopy

from PySide6.QtWidgets import QApplication, QTreeWidget

from workbench.backup_diff_tree import add_node_differences
from workbench.configuration_compare import compare_configurations


class BackupDiffTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def render_event(self, result):
        tree = QTreeWidget()
        tree.setColumnCount(3)
        self.addCleanup(tree.close)
        add_node_differences(tree, result)
        event = tree.topLevelItem(0).child(0)
        self.assertTrue(event.isExpanded())
        return [
            [event.child(i).text(c) for c in range(3)]
            for i in range(event.childCount())
        ]

    def test_one_sided_details_hide_membership_without_changing_results(self):
        present = {
            "node": 42,
            "complete": True,
            "nvs": [],
            "events": [
                {"nodeNumber": 258, "eventNumber": 2, "eventVariables": [0, 13]}
            ],
        }
        missing = dict(present, events=[])
        for left, right, expected in (
            (present, missing, [["EV 1", "0", "—"], ["EV 2", "13", "—"]]),
            (missing, present, [["EV 1", "—", "0"], ["EV 2", "—", "13"]]),
        ):
            with self.subTest(left_present=bool(left["events"])):
                result = compare_configurations(left, right)
                before = deepcopy(result)
                self.assertEqual(self.render_event(result), expected)
                self.assertEqual(result, before)
                self.assertTrue(any(row.label == "Event" for row in result.rows))

    def test_one_sided_events_without_confirmed_evs_keep_membership(self):
        for complete, values in ((True, []), (True, [None]), (False, [None])):
            present = {
                "node": 42,
                "complete": complete,
                "nvs": [],
                "events": [
                    {"nodeNumber": 258, "eventNumber": 2, "eventVariables": values}
                ],
            }
            missing = dict(present, complete=True, events=[])
            for left, right, expected in (
                (present, missing, [["Event", "Present", "—"]]),
                (missing, present, [["Event", "—", "Present"]]),
            ):
                with self.subTest(
                    complete=complete, values=values, left_present=bool(left["events"])
                ):
                    self.assertEqual(
                        self.render_event(compare_configurations(left, right)), expected
                    )

    def test_confirmed_absence_and_unknown_have_distinct_labels(self):
        left = {
            "node": 42,
            "complete": True,
            "nvs": [],
            "events": [
                {"nodeNumber": 258, "eventNumber": 2, "eventVariables": [None, 0, 0]}
            ],
        }
        right = deepcopy(left)
        right["events"][0]["eventVariables"] = [0, None, None]
        self.assertEqual(
            self.render_event(compare_configurations(left, right)),
            [["EV 1", "—", "0"], ["EV 2", "0", "—"], ["EV 3", "0", "—"]],
        )
        right["complete"] = False
        result = compare_configurations(left, right)
        self.assertEqual(
            self.render_event(result),
            [["EV 1", "—", "0"], ["EV 2", "0", "Unknown"], ["EV 3", "0", "Unknown"]],
        )
        self.assertTrue(result.inconclusive)
