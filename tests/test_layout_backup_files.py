"""Layout saves preserve node records and require acknowledgement of partial data."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox, QTreeWidget

from workbench.backup_compare import BackupCompare
from workbench.backup_view import BackupView
from workbench.cbus_service import DiscoveryProgress, NodeState
from workbench.layout_view import LayoutView
from workbench.node_backup_files import load_node_backup, node_backup, save_backup
from workbench.node_backups import NodeBackups
from workbench.pnn import Pnn
from workbench.ui_errors import ErrorReporter


class LayoutBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        description = patch(
            "workbench.layout_backup_workflow.QInputDialog.getText",
            return_value=("", True),
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
        self.view = LayoutView(empty=True)
        self.view.set_connected(True)
        self.addCleanup(self.view.close)
        self.state = NodeState(Pnn(42, 1, 2, 5))
        self.state.parameters = {5: 4, 6: 1}
        self.state.nv_values = {1: 9}
        self.state.stored_event_count = 1
        self.state.event_identities = {7: (100, 200)}
        self.state.ev_values = {7: {1: 0, 2: None, 3: 8, 4: None}}
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(self.state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        self.view.show_live_layout("Yard", lambda: [self.state])

    def files(self):
        return sorted(self.root.rglob("*.yaml"))

    def answer(self, label):
        def click():
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, QMessageBox)
            self.assertTrue("42" in dialog.text() or "No nodes" in dialog.text())
            for button in dialog.buttons():
                if button.text().replace("&", "") == label:
                    button.click()
                    return
            self.fail(f"Missing {label}")

        QTimer.singleShot(0, click)
        self.view.backup_buttons["New"].click()

    def test_description_yaml_and_list_display(self):
        for kind in ("parameter", "nv", "event", "ev"):
            setattr(self.state, f"{kind}_progress", DiscoveryProgress.COMPLETE)
        self.state.nv_values = {1: 0, 2: 4, 3: 8}
        self.state.ev_values[7] = {1: 0, 2: 5, 3: 9, 4: None}
        for entered, expected in (("  Before changes  ", "Before changes"), ("  ", "")):
            with self.subTest(description=entered):
                self.description.return_value = (entered, True)
                self.view.new_backup()
                row = self.view.layout_backups.topLevelItem(0)
                path = row.data(0, Qt.ItemDataRole.UserRole)
                saved = yaml.safe_load(path.read_text())
                self.assertEqual(saved.get("description", ""), expected)
                if not expected:
                    self.assertNotIn("description", saved)
                self.assertEqual(row.text(0), path.name)
                self.assertEqual(row.text(1), expected)
                self.assertTrue(row.icon(0).isNull())
                self.assertEqual(row.toolTip(0), str(path))
                linked = self.root / "layouts/Yard/nodes/42/backups" / path.name
                self.assertNotIn("description", load_node_backup(linked))

    def test_node_list_inherits_only_its_matching_manifest_description(self):
        tree = NodeBackups()
        self.addCleanup(tree.close)
        expected = {}
        for description in ("First layout", "Second layout", ""):
            self.description.return_value = (description, True)
            self.view.new_backup()
            row = self.view.layout_backups.topLevelItem(0)
            manifest = row.data(0, Qt.ItemDataRole.UserRole)
            expected[manifest.name] = description

        # A retained node file remains listable after its manifest is removed.
        self.description.return_value = ("Removed parent", True)
        self.view.new_backup()
        manifest = self.view.layout_backups.topLevelItem(0).data(
            0, Qt.ItemDataRole.UserRole
        )
        expected[manifest.name] = ""
        manifest.unlink()

        standalone = node_backup(self.state)
        standalone["description"] = "Standalone node"
        path = save_backup("Yard", standalone)
        expected[path.name] = "Standalone node"
        tree.show_live_node("Yard", 42)
        displayed = {
            tree.topLevelItem(index).text(0): tree.topLevelItem(index).text(1)
            for index in range(tree.topLevelItemCount())
        }
        self.assertEqual(displayed, expected)
        for node_path in (self.root / "layouts/Yard/nodes/42/backups").glob("*.yaml"):
            backup = load_node_backup(node_path)
            if backup["partOfLayoutBackup"]:
                self.assertNotIn("description", backup)

    def test_cancel_description_writes_no_files(self):
        self.description.return_value = ("Ignored", False)
        self.view.new_backup()
        self.assertEqual(list((self.root / "layouts/Yard/backups").glob("*.yaml")), [])

    def test_save_repeatedly_and_list_only_selected_layout(self):
        other = NodeState(Pnn(99, 2, 3, 4))
        other.parameters = {6: 0}
        other.parameter_progress = other.nv_progress = DiscoveryProgress.COMPLETE
        other.event_progress = other.ev_progress = DiscoveryProgress.SKIPPED
        self.view.show_live_layout("Yard", lambda: [self.state, other])
        self.view.backup_buttons["New"].click()
        self.view.backup_buttons["New"].click()
        self.assertEqual(len(self.files()), 6)
        manifests = sorted((self.root / "layouts/Yard/backups").glob("*.yaml"))
        for path in manifests:
            self.assertEqual(path.parent, self.root / "layouts/Yard/backups")
            self.assertEqual(
                yaml.safe_load(path.read_text()),
                {
                    "format_version": 1,
                    "complete": True,
                    "nodeNumbers": [42, 99],
                },
            )
            for state in (self.state, other):
                node_path = (
                    self.root
                    / "layouts/Yard/nodes"
                    / str(state.identity.node_number)
                    / "backups"
                    / path.name
                )
                expected = node_backup(state)
                expected["partOfLayoutBackup"] = True
                self.assertEqual(yaml.safe_load(node_path.read_text()), expected)
        self.view.show_live_layout("Other", list)
        self.assertEqual(self.view.layout_backups.topLevelItemCount(), 0)
        self.view.show_live_layout("Yard", lambda: [self.state])
        self.assertEqual(self.view.layout_backups.topLevelItemCount(), 2)
        row = self.view.layout_backups.topLevelItem(0)
        self.assertEqual(row.text(1), "")
        self.view.layout_backups.setCurrentItem(row)
        self.assertTrue(self.view.backup_buttons["View"].isEnabled())
        self.assertTrue(self.view.backup_buttons["Restore"].isEnabled())
        self.assertFalse(self.view.backup_buttons["Delete"].isEnabled())

        def inspect_layout(dialog):
            tree = dialog.findChild(QTreeWidget)
            node = tree.topLevelItem(1)
            self.assertEqual(node.text(0), "Node 42")
            self.assertEqual(tree.topLevelItem(2).text(0), "Node 99")
            variables = node.child(0)
            self.assertEqual(variables.text(0), "Node variables")
            self.assertEqual(variables.childCount(), 1)
            self.assertEqual(variables.child(0).text(0), "NV 1")
            self.assertEqual(variables.child(0).text(1), "9")
            events = node.child(1)
            self.assertEqual(events.text(0), "Consumed events")
            event = events.child(0)
            self.assertEqual(event.text(0), "100:200")
            self.assertEqual(event.childCount(), 3)
            self.assertEqual(
                [(event.child(i).text(0), event.child(i).text(1)) for i in range(3)],
                [("EV 1", "0"), ("EV 2", "Absent"), ("EV 3", "8")],
            )

        with patch("workbench.layout_view.LayoutBackupView.exec", inspect_layout):
            self.view.view_backup()

    def test_node_yaml_requires_explicit_boolean_ownership(self):
        backup = node_backup(self.state)
        del backup["partOfLayoutBackup"]
        path = save_backup("Yard", backup)
        with self.assertRaises(ValueError):
            load_node_backup(path)
        for value in (None, 0, "false"):
            backup["partOfLayoutBackup"] = value
            path.write_text(yaml.safe_dump(backup))
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_node_backup(path)

    def test_associated_node_view_compare_and_standalone_ownership(self):
        self.view.new_backup()
        details = self.view.node_view.details
        details.logical_layout = "Yard"
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, self.state.identity)
        details.show_node(item)
        details.show_live_state(self.state)
        row = details.node_backups.topLevelItem(0)
        self.assertIsNotNone(row)
        details.node_backups.setCurrentItem(row)
        node_path = row.data(0, Qt.ItemDataRole.UserRole)
        self.assertIs(yaml.safe_load(node_path.read_text())["partOfLayoutBackup"], True)
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
            details.view_backup()
            details.compare_backup()
        self.assertIn("Part of layout backup", displayed[0])
        self.assertIn("100:200", displayed[0])
        self.assertIn("No differences found", displayed[1])
        path = save_backup("Yard", node_backup(self.state))
        self.assertIs(yaml.safe_load(path.read_text())["partOfLayoutBackup"], False)

    def test_node_write_failure_does_not_publish_manifest(self):
        other = NodeState(Pnn(99, 2, 3, 4))
        other.parameters = {6: 0}
        other.parameter_progress = other.nv_progress = DiscoveryProgress.COMPLETE
        other.event_progress = other.ev_progress = DiscoveryProgress.SKIPPED
        self.view.show_live_layout("Yard", lambda: [self.state, other])
        blocked = self.root / "layouts/Yard/nodes/99"
        blocked.mkdir(parents=True)
        (blocked / "backups").write_text("not a directory")
        reporter = ErrorReporter(self.view)
        with patch("workbench.ui_errors.QMessageBox.critical") as error:
            reporter.run("Cannot save layout backup", self.view.new_backup)
        self.assertIn("Cannot save layout backup", error.call_args.args[2])
        self.assertEqual(list((self.root / "layouts/Yard/backups").glob("*.yaml")), [])
        self.assertEqual(len(self.files()), 1)  # Earlier node file remains available.
        self.assertEqual(self.view.layout_backups.topLevelItemCount(), 0)

    def test_manifest_write_failure_is_reported_after_node_save(self):
        directory = self.root / "layouts/Yard"
        directory.mkdir(parents=True)
        (directory / "backups").write_text("not a directory")
        reporter = ErrorReporter(self.view)
        with patch("workbench.ui_errors.QMessageBox.critical") as error:
            reporter.run("Cannot save layout backup", self.view.new_backup)
        self.assertIn("Cannot save layout backup", error.call_args.args[2])
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(self.files()[0].parent, directory / "nodes/42/backups")
        self.assertEqual(self.view.layout_backups.topLevelItemCount(), 0)

    def test_missing_associated_node_is_reported_when_viewing_manifest(self):
        self.view.new_backup()
        node_path = next((self.root / "layouts/Yard/nodes/42/backups").glob("*.yaml"))
        node_path.unlink()
        self.view.layout_backups.setCurrentItem(
            self.view.layout_backups.topLevelItem(0)
        )
        reporter = ErrorReporter(self.view)
        with patch("workbench.ui_errors.QMessageBox.critical") as error:
            reporter.run("Cannot view layout backup", self.view.view_backup)
        self.assertIn("Cannot view layout backup", error.call_args.args[2])
        self.assertIn(node_path.name, error.call_args.args[2])

    def test_partial_cancel_and_save(self):
        del self.state.ev_values[7][2]
        self.answer("Cancel")
        self.assertEqual(self.files(), [])
        self.answer("Save Anyway")
        backup = yaml.safe_load(self.files()[0].read_text())
        self.assertFalse(backup["complete"])
        self.assertEqual(backup["nodeNumbers"], [42])
        row = self.view.layout_backups.topLevelItem(0)
        self.assertEqual(self.view.layout_backups.columnCount(), 2)
        self.assertEqual(self.view.layout_backups.headerItem().text(0), "Filename")
        self.assertEqual(self.view.layout_backups.headerItem().text(1), "Description")
        self.assertEqual(row.text(1), "")
        self.assertFalse(row.icon(0).isNull())
        self.assertEqual(
            row.toolTip(0),
            "Configuration discovery was incomplete when this backup was created.",
        )

    def test_empty_discovery_requires_confirmation_and_stays_incomplete(self):
        self.view.show_live_layout("Empty", list)
        self.answer("Cancel")
        self.assertEqual(self.files(), [])
        self.answer("Save Anyway")
        backup = yaml.safe_load(self.files()[0].read_text())
        self.assertFalse(backup["complete"])
        self.assertEqual(backup["nodeNumbers"], [])

    def test_filesystem_error_uses_existing_reporter(self):
        (self.root / "layouts").write_text("not a directory")
        reporter = ErrorReporter(self.view)
        with patch("workbench.ui_errors.QMessageBox.critical") as error:
            reporter.run("Cannot save layout backup", self.view.new_backup)
        self.assertIn("Cannot save layout backup", error.call_args.args[2])
        self.assertEqual(self.files(), [])
