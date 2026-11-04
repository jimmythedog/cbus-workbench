"""Saved layout comparison uses confirmed configuration and reports uncertainty."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PySide6.QtWidgets import QApplication, QTreeWidget

from workbench.cbus_service import DiscoveryProgress, NodeState
from workbench.layout_backup_compare import LayoutBackupCompare
from workbench.layout_view import LayoutView
from workbench.node_backup_files import node_backup
from workbench.pnn import Pnn
from workbench.ui_errors import ErrorReporter


class LayoutBackupCompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        description = patch(
            "workbench.layout_backup_workflow.QInputDialog.getText",
            return_value=("Before layout changes", True),
        )
        self.description = description.start()
        self.addCleanup(description.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        paths = patch(
            "workbench.node_backup_files.application_directories",
            return_value={"Data": self.root},
        )
        paths.start()
        self.addCleanup(paths.stop)
        self.state = NodeState(Pnn(42, 1, 2, 5))
        self.state.parameters = {5: 3, 6: 1}
        self.state.nv_values = {1: 0}
        self.state.stored_event_count = 2
        self.state.event_identities = {7: (100, 200), 2: (0, 12)}
        self.state.ev_values = {7: {1: 0, 2: None, 3: None}, 2: {1: 5, 2: 6, 3: 7}}
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(self.state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        self.view = LayoutView(empty=True)
        self.view.set_connected(True)
        self.addCleanup(self.view.close)
        self.states = [self.state]
        self.view.show_live_layout("Yard", lambda: self.states)
        self.view.new_backup()
        self.manifest = next((self.root / "layouts/Yard/backups").glob("*.yaml"))
        self.node_path = (
            self.root / "layouts/Yard/nodes/42/backups" / self.manifest.name
        )
        self.view.layout_backups.setCurrentItem(
            self.view.layout_backups.topLevelItem(0)
        )

    def rows(self):
        rows = []

        def inspect(dialog):
            tree = dialog.findChild(QTreeWidget)
            self.assertEqual(
                [tree.headerItem().text(i) for i in range(3)],
                ["Item", "Backup", "Current"],
            )

            def walk(item, parents):
                for index in range(item.childCount()):
                    child = item.child(index)
                    path = parents + (child.text(0),)
                    rows.append((path, child.text(1), child.text(2)))
                    walk(child, path)

            walk(tree.invisibleRootItem(), ())

        with patch.object(LayoutBackupCompare, "exec", inspect):
            self.view.backup_buttons["Compare"].click()
        return rows

    def test_equal_configuration_matches_event_identities_after_slot_changes(self):
        self.assertTrue(self.view.backup_buttons["Compare"].isEnabled())
        self.state.event_identities = {1: (0, 12), 9: (100, 200)}
        self.state.ev_values = {1: self.state.ev_values[2], 9: self.state.ev_values[7]}
        self.assertEqual(self.rows(), [(("No differences found",), "", "")])

    def test_differences_and_unknowns_share_existing_hierarchy(self):
        self.state.nv_values[1] = 8
        self.state.ev_values[7] = {1: None, 2: 0}  # EV3 is unread, not absent.
        rows = self.rows()
        prefix = ("Node configurations", "Node 42")
        self.assertIn((prefix + ("Node variables", "NV 1"), "0", "8"), rows)
        event = prefix + ("Consumed events", "100:200")
        self.assertIn((event + ("EV 1",), "0", "Absent"), rows)
        self.assertIn((event + ("EV 2",), "Absent", "0"), rows)
        self.assertFalse(any(path[-1] == "EV 3" for path, _, _ in rows))
        self.assertTrue(any("inconclusive" in path[-1] for path, _, _ in rows))
        self.assertFalse(any(path[-1] == "No differences found" for path, _, _ in rows))

    def test_partial_saved_node_does_not_turn_nulls_into_differences(self):
        backup = node_backup(self.state)
        backup.update(complete=False, partOfLayoutBackup=True)
        backup["nvs"] = [None]
        backup["events"][0]["eventVariables"] = [None]
        self.node_path.write_text(yaml.safe_dump(backup))
        self.state.nv_values[1] = 99
        self.state.ev_values[7] = {1: 99, 2: 99, 3: 99}
        rows = self.rows()
        self.assertFalse(
            any(path[-1].startswith(("NV ", "EV ")) for path, _, _ in rows)
        )
        self.assertTrue(any("inconclusive" in path[-1] for path, _, _ in rows))

    def test_incomplete_live_node_and_empty_manifest_are_inconclusive(self):
        self.state.nv_values.clear()
        self.state.nv_progress = DiscoveryProgress.INCOMPLETE
        rows = self.rows()
        self.assertFalse(any(path[-1] == "NV 1" for path, _, _ in rows))
        self.assertTrue(any("inconclusive" in path[-1] for path, _, _ in rows))
        self.manifest.write_text(
            yaml.safe_dump(
                {
                    "format_version": 1,
                    "complete": False,
                    "nodeNumbers": [],
                }
            )
        )
        self.states = []
        self.assertEqual(self.rows(), [(("Layout comparison inconclusive",), "", "")])

    def test_missing_and_additional_nodes_are_uncertain(self):
        self.states = [NodeState(Pnn(99, 2, 3, 4))]
        rows = self.rows()
        prefix = ("Node configurations",)
        self.assertIn(
            (
                prefix + ("Node 42", "Node membership inconclusive"),
                "Included",
                "Not discovered",
            ),
            rows,
        )
        self.assertIn(
            (
                prefix + ("Node 99", "Node membership inconclusive"),
                "Not included in manifest",
                "Discovered",
            ),
            rows,
        )
        self.assertFalse(any(path[-1] == "No differences found" for path, _, _ in rows))

    def test_missing_or_invalid_associated_files_use_existing_reporter(self):
        reporter = ErrorReporter(self.view)
        for content in (None, "node: 42", "[invalid YAML"):
            if content is None:
                self.node_path.unlink()
            else:
                self.node_path.write_text(content)
            with patch("workbench.ui_errors.QMessageBox.critical") as error:
                reporter.run("Cannot compare layout backup", self.view.compare_backup)
            self.assertIn("Cannot compare layout backup", error.call_args.args[2])

    def test_prototype_still_compares_membership_and_event_descriptions(self):
        backup = {"nodeNumbers": [256], "eventCatalogue": {0: {12: "Old"}}}
        dialog = LayoutBackupCompare(
            backup, [], {0: {12: {"description": "New"}}}, None
        )
        self.addCleanup(dialog.close)
        tree = dialog.findChild(QTreeWidget)
        self.assertEqual(tree.topLevelItem(0).child(0).text(0), "Node 256")
        event = tree.topLevelItem(1).child(0).child(0)
        self.assertEqual([event.text(i) for i in range(3)], ["Event 12", "Old", "New"])
