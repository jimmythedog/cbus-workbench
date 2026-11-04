"""The persisted schema and the live UI's partial-backup acknowledgement."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox

from workbench.cbus_service import DiscoveryProgress, NodeState
from workbench.node_backup_files import node_backup
from workbench.node_details import NodeDetails
from workbench.pnn import Pnn


class NodeBackupFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        paths = patch(
            "workbench.node_backup_files.application_directories",
            return_value={"Data": Path(self.temp.name)},
        )
        paths.start()
        self.addCleanup(paths.stop)
        self.state = NodeState(Pnn(42, 1, 2, 5))
        self.state.parameters = {5: 3, 6: 3}
        self.state.nv_values = {1: 0, 3: 8}
        self.state.stored_event_count = 1
        self.state.event_identities = {7: (256, 101)}
        self.state.ev_values = {7: {1: 0, 3: 9}}
        self.details = NodeDetails({})
        self.details.connected = True
        self.addCleanup(self.details.close)
        self.details.logical_layout = "Yard"
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, self.state.identity)
        self.details.show_node(item)
        self.details.show_live_state(self.state)

    def test_live_backup_view_compare_and_disabled_destructive_actions(self):
        from PySide6.QtWidgets import QTreeWidget

        from workbench.backup_compare import BackupCompare
        from workbench.backup_view import BackupView
        from workbench.node_backup_files import save_backup

        path = save_backup("Yard", node_backup(self.state))
        self.details.node_backups.show_live_node("Yard", 42)
        row = self.details.node_backups.topLevelItem(0)
        self.assertEqual(row.data(0, Qt.ItemDataRole.UserRole), path)
        self.details.node_backups.setCurrentItem(row)
        for name in ("View", "Compare"):
            self.assertTrue(self.details.backup_buttons[name].isEnabled())
        for name in ("Restore", "Delete"):
            self.assertFalse(self.details.backup_buttons[name].isEnabled())

        displayed = []

        def inspect(dialog):
            tree = dialog.findChild(QTreeWidget)

            def texts(item):
                result = [item.text(column) for column in range(tree.columnCount())]
                for index in range(item.childCount()):
                    result.extend(texts(item.child(index)))
                return result

            displayed.append(texts(tree.invisibleRootItem()))

        with (
            patch.object(BackupView, "exec", inspect),
            patch.object(BackupCompare, "exec", inspect),
        ):
            self.details.view_backup()
            self.details.compare_backup()
        self.assertIn("42", displayed[0])
        self.assertIn("256:101", displayed[0])
        self.assertIn("Absent / unknown", displayed[0])
        self.assertNotIn("None", displayed[0])
        self.assertNotIn("Annotations", displayed[0])
        self.assertNotIn("No differences found", displayed[1])
        self.assertTrue(any("inconclusive" in text for text in displayed[1]))

    def test_invalid_or_unreadable_selected_yaml_uses_existing_error_reporter(self):
        from workbench.node_backup_files import save_backup
        from workbench.ui_errors import ErrorReporter

        path = save_backup("Yard", node_backup(self.state))
        self.details.node_backups.show_live_node("Yard", 42)
        self.details.node_backups.setCurrentItem(
            self.details.node_backups.topLevelItem(0)
        )
        reporter = ErrorReporter(self.details)
        for content in ("[broken YAML", "node: 42", None):
            if content is None:
                path.unlink()
            else:
                path.write_text(content)
            with patch("workbench.ui_errors.QMessageBox.critical") as error:
                reporter.run("Cannot view backup", self.details.view_backup)
            self.assertIn("Cannot view backup", error.call_args.args[2])

    def files(self):
        return sorted(Path(self.temp.name).rglob("*.yaml"))

    def answer_partial(self, label):
        def click():
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, QMessageBox)
            for button in dialog.buttons():
                if button.text().replace("&", "") == label:
                    button.click()
                    return
            self.fail(f"Missing {label} button")

        QTimer.singleShot(0, click)
        self.details.backup_buttons["New"].click()

    def test_partial_cancel_then_save_preserves_schema_and_positions(self):
        self.answer_partial("Cancel")
        self.assertEqual(self.files(), [])
        self.answer_partial("Save Anyway")
        (path,) = self.files()
        self.assertEqual(
            path.parent.relative_to(self.temp.name),
            Path("layouts/Yard/nodes/42/backups"),
        )
        self.assertEqual(
            yaml.safe_load(path.read_text()),
            {
                "format_version": 1,
                "complete": False,
                "partOfLayoutBackup": False,
                "node": 42,
                "nvs": [0, None, 8],
                "events": [
                    {
                        "nodeNumber": 256,
                        "eventNumber": 101,
                        "eventVariables": [0, None, 9],
                    }
                ],
            },
        )
        self.details.node_backups.clear()
        self.details.show_node(self.details.node_list_item)
        self.assertEqual(self.details.node_backups.topLevelItem(0).text(0), path.name)
        self.assertEqual(
            self.details.node_backups.topLevelItem(0).text(1), "Incomplete"
        )
        self.assertFalse(self.details.backup_buttons["Restore"].isEnabled())

    def test_complete_save_and_nonconsumer_with_no_events(self):
        self.state.nv_values[2] = 4
        self.state.ev_values[7][2] = 5
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(self.state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        self.details.backup_buttons["New"].click()
        self.details.backup_buttons["New"].click()
        self.assertEqual(len(self.files()), 2)
        self.assertTrue(yaml.safe_load(self.files()[0].read_text())["complete"])
        del self.state.nv_values[2]
        self.assertFalse(node_backup(self.state)["complete"])
        self.state.nv_values[2] = 4
        self.state.event_identities.clear()
        self.state.identity = Pnn(42, 1, 2, 4)
        self.state.event_progress = self.state.ev_progress = DiscoveryProgress.SKIPPED
        self.assertTrue(node_backup(self.state)["complete"])

    def test_unknown_counts_do_not_invent_values(self):
        self.state.parameters.clear()
        self.assertEqual(node_backup(self.state)["nvs"], [0, None, 8])
        self.state.nv_values.clear()
        self.state.ev_values.clear()
        backup = node_backup(self.state)
        self.assertEqual(backup["nvs"], [])
        self.assertEqual(backup["events"][0]["eventVariables"], [])

    def test_completeness_requires_known_counts_and_all_confirmed_values(self):
        self.state.nv_values[2] = 4
        self.state.ev_values[7][2] = 5
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(self.state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        self.assertTrue(node_backup(self.state)["complete"])
        for index in (5, 6):
            with self.subTest(unknown_parameter=index):
                count = self.state.parameters.pop(index)
                self.assertFalse(node_backup(self.state)["complete"])
                self.state.parameters[index] = count
        for count in (None, 2):
            with self.subTest(event_count=count):
                self.state.stored_event_count = count
                self.assertFalse(node_backup(self.state)["complete"])
        self.state.stored_event_count = 1
        del self.state.ev_values[7][2]
        self.assertFalse(node_backup(self.state)["complete"])

    def test_empty_lists_require_confirmed_zero_counts_or_valid_skip(self):
        self.state.nv_values.clear()
        self.state.event_identities.clear()
        self.state.ev_values.clear()
        self.state.parameters = {6: 0}
        self.state.stored_event_count = 0
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(self.state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        self.assertTrue(node_backup(self.state)["complete"])
        self.state.parameters.clear()
        self.assertFalse(node_backup(self.state)["complete"])
        self.state.parameters[6] = 0
        self.state.stored_event_count = None
        self.assertFalse(node_backup(self.state)["complete"])
        self.state.event_progress = self.state.ev_progress = DiscoveryProgress.SKIPPED
        self.assertFalse(node_backup(self.state)["complete"])
        self.state.identity = Pnn(42, 1, 2, 4)
        self.assertTrue(node_backup(self.state)["complete"])
        self.state.event_identities[7] = (256, 101)
        self.assertFalse(node_backup(self.state)["complete"])

    def test_absent_and_unknown_share_yaml_null_but_differ_in_completeness(self):
        self.state.nv_values[2] = 4
        self.state.ev_values[7][2] = None
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(self.state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        absent = node_backup(self.state)
        self.assertTrue(absent["complete"])
        del self.state.ev_values[7][2]
        unknown = node_backup(self.state)
        self.assertFalse(unknown["complete"])
        self.assertEqual(absent["events"], unknown["events"])
        self.assertEqual(absent["events"][0]["eventVariables"], [0, None, 9])

    def test_only_trailing_confirmed_absent_evs_are_trimmed(self):
        self.state.nv_values[2] = 4
        self.state.parameters[5] = 5
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(self.state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        cases = (
            ({1: 0, 2: 12, 3: 0, 4: None, 5: None}, [0, 12, 0], True),
            ({1: 0, 2: None, 3: 12, 4: None, 5: None}, [0, None, 12], True),
            ({1: None, 2: None, 3: None, 4: None, 5: None}, [], True),
            ({1: 0, 2: 12, 3: 0}, [0, 12, 0, None, None], False),
            ({1: 0, 2: 12, 3: 0, 5: None}, [0, 12, 0, None], False),
            ({}, [None, None, None, None, None], False),
        )
        for values, expected, complete in cases:
            with self.subTest(values=values):
                self.state.ev_values[7] = values
                backup = node_backup(self.state)
                self.assertEqual(backup["events"][0]["eventVariables"], expected)
                self.assertEqual(backup["complete"], complete)
                self.assertEqual(backup["nvs"], [0, 4, 8])

    def test_ev_trimming_with_unknown_count_preserves_known_positions(self):
        del self.state.parameters[5]
        self.state.ev_values[7] = {1: 0, 3: 12, 4: None}
        self.state.nv_values = {1: 0}
        backup = node_backup(self.state)
        self.assertEqual(backup["events"][0]["eventVariables"], [0, None, 12])
        self.assertFalse(backup["complete"])
        self.assertEqual(backup["nvs"], [0, None, None])

    def test_filesystem_failure_is_reported_by_existing_exception_boundary(self):
        self.state.nv_values[2] = 4
        self.state.ev_values[7][2] = 5
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(self.state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        with (
            patch(
                "workbench.node_backup_files.Path.mkdir", side_effect=OSError("disk")
            ),
            self.assertRaises(OSError),
        ):
            self.details.new_backup()
        self.assertEqual(self.files(), [])
