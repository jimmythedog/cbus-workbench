"""Saved/live comparison contracts, especially uncertainty and event identity."""

import os
import unittest

from PySide6.QtWidgets import QApplication, QTreeWidget

from workbench.backup_compare import BackupCompare
from workbench.backup_view import BackupView
from workbench.cbus_service import DiscoveryProgress, NodeState
from workbench.node_backup_diff import compare_live_configuration, compare_live_node
from workbench.node_backup_files import node_backup
from workbench.pnn import Pnn


class LiveBackupCompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_view_null_ev_label_depends_on_backup_completeness(self):
        self.backup["events"][0]["eventVariables"] = [0, None, 7]
        for complete, label in ((True, "Absent"), (False, "Absent / unknown")):
            self.backup["complete"] = complete
            dialog = BackupView(self.state.identity, self.backup)
            self.addCleanup(dialog.close)
            tree = dialog.findChild(QTreeWidget)
            events = tree.topLevelItem(3)
            event = events.child(0)
            self.assertEqual(event.child(0).text(1), "0")
            self.assertEqual(event.child(1).text(1), label)
            self.assertEqual(event.child(2).text(1), "7")

    def test_compare_labels_confirmed_absent_evs_on_both_sides(self):
        self.state.ev_values[7] = {1: None, 2: 0}  # EV3 remains unknown.
        dialog = BackupCompare(self.state, self.backup)
        self.addCleanup(dialog.close)
        self.assertIsNone(dialog.retry_button)
        tree = dialog.findChild(QTreeWidget)
        self.assertEqual(tree.headerItem().text(1), "Backup")
        event = tree.topLevelItem(0).child(0)
        self.assertEqual(
            [event.child(0).text(column) for column in range(3)],
            ["EV 1", "0", "—"],
        )
        self.assertEqual(
            [event.child(1).text(column) for column in range(3)],
            ["EV 2", "—", "0"],
        )
        self.assertIn("inconclusive", tree.topLevelItem(1).text(0))

    def setUp(self):
        self.state = NodeState(Pnn(42, 1, 2, 5))
        self.state.parameters = {5: 3, 6: 1}
        self.state.nv_values = {1: 0}
        self.state.stored_event_count = 2
        self.state.event_identities = {7: (256, 101), 2: (0, 12)}
        self.state.ev_values = {7: {1: 0, 2: None, 3: None}, 2: {1: 5, 2: 6, 3: 7}}
        self.state.parameter_progress = DiscoveryProgress.COMPLETE
        self.state.nv_progress = DiscoveryProgress.COMPLETE
        self.state.event_progress = DiscoveryProgress.COMPLETE
        self.state.ev_progress = DiscoveryProgress.COMPLETE
        self.backup = node_backup(self.state)
        self.assertTrue(self.backup["complete"])

    def test_equal_configuration_ignores_event_order_and_table_slots(self):
        self.backup["events"].reverse()
        self.state.event_identities = {1: (0, 12), 9: (256, 101)}
        self.state.ev_values = {1: self.state.ev_values[2], 9: self.state.ev_values[7]}
        self.assertEqual(compare_live_node(self.state, self.backup), ([], False))

    def test_zero_and_confirmed_absence_are_values_but_unknown_is_not(self):
        self.state.nv_values[1] = 8
        self.state.ev_values[7] = {1: None, 2: 0}  # EV3 unread.
        differences, partial = compare_live_node(self.state, self.backup)
        self.assertTrue(partial)
        self.assertEqual(
            differences,
            [
                ("Node variables", "NV 1", 0, 8),
                ("Consumed events/256:101", "EV 1", 0, None),
                ("Consumed events/256:101", "EV 2", None, 0),
            ],
        )

    def test_partial_file_null_and_omissions_remain_uncertain(self):
        self.backup["complete"] = False
        self.backup["events"][0]["eventVariables"] = [None]
        self.state.ev_values[7] = {1: 99, 2: 99, 3: 99}
        self.assertEqual(compare_live_node(self.state, self.backup), ([], True))

    def test_missing_events_require_confirmed_enumeration(self):
        del self.state.event_identities[7]
        self.state.event_progress = DiscoveryProgress.INCOMPLETE
        self.assertEqual(compare_live_node(self.state, self.backup), ([], True))
        self.state.event_progress = DiscoveryProgress.COMPLETE
        self.state.stored_event_count = 1
        differences, _ = compare_live_node(self.state, self.backup)
        self.assertEqual(
            differences, [("Consumed events/256:101", "Event", "Present", None)]
        )
        self.backup["events"] = []
        self.backup["complete"] = False
        self.assertEqual(compare_live_node(self.state, self.backup), ([], True))

    def test_one_sided_event_details_and_supplied_results_headings(self):
        from copy import deepcopy

        from workbench.configuration_compare import compare_configurations

        present = deepcopy(self.backup)
        present["events"] = [
            {"nodeNumber": 258, "eventNumber": 2, "eventVariables": [0, None, 13]}
        ]
        absent = deepcopy(present)
        absent["events"] = []
        for left, right, expected in (
            (
                absent,
                present,
                [["EV 1", "—", "0"], ["EV 3", "—", "13"]],
            ),
            (
                present,
                absent,
                [["EV 1", "0", "—"], ["EV 3", "13", "—"]],
            ),
        ):
            result = compare_configurations(left, right)
            dialog = BackupCompare(
                None, left, comparison=result, headings=("Requested", "Actual")
            )
            self.addCleanup(dialog.close)
            tree = dialog.findChild(QTreeWidget)
            self.assertEqual(
                [tree.headerItem().text(i) for i in range(3)],
                ["Item", "Requested", "Actual"],
            )
            event = tree.topLevelItem(0).child(0)
            self.assertTrue(event.isExpanded())
            self.assertEqual(event.text(0), "258:2")
            self.assertEqual(
                [
                    [event.child(i).text(c) for c in range(3)]
                    for i in range(event.childCount())
                ],
                expected,
            )

    def test_live_confirmation_survives_partial_snapshot(self):
        from workbench.configuration_compare import ABSENT, EVENT_ABSENT, UNKNOWN

        # Enumeration is complete, but an unrelated NV and EV remain unread.
        self.state.nv_values.clear()
        self.state.ev_values[7] = {1: None, 2: 0}
        del self.state.event_identities[2]
        self.state.stored_event_count = 1
        self.assertFalse(node_backup(self.state)["complete"])
        result = compare_live_configuration(self.state, self.backup)
        rows = {(row.event, row.label): row for row in result.rows}
        self.assertEqual(rows[((256, 101), "EV 1")].right, ABSENT)
        self.assertEqual(rows[((256, 101), "EV 3")].right, UNKNOWN)
        self.assertEqual(rows[((0, 12), "Event")].right, EVENT_ABSENT)
        differences, inconclusive = compare_live_node(self.state, self.backup)
        self.assertTrue(inconclusive)
        self.assertEqual(
            differences,
            [
                ("Consumed events/0:12", "Event", "Present", None),
                ("Consumed events/256:101", "EV 1", 0, None),
                ("Consumed events/256:101", "EV 2", None, 0),
            ],
        )
