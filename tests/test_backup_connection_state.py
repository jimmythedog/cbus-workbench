"""Backups stay readable offline without keeping discovery state alive."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QTreeWidget

from workbench.cbus_service import NodeState
from workbench.layout_view import LayoutView
from workbench.node_backup_files import node_backup, save_backup
from workbench.pnn import Pnn


class BackupConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        paths = patch(
            "workbench.node_backup_files.application_directories",
            return_value={"Data": Path(temp.name)},
        )
        paths.start()
        self.addCleanup(paths.stop)
        self.state = NodeState(Pnn(42, 1, 2, 5))
        self.state.nv_values = {1: 73}
        backup = node_backup(self.state)
        backup["partOfLayoutBackup"] = True
        save_backup("yard", backup, "layout.yaml")
        save_backup(
            "yard",
            {"format_version": 1, "complete": False, "nodeNumbers": [42]},
            "layout.yaml",
        )
        self.view = LayoutView(empty=True)
        self.addCleanup(self.view.close)
        self.states = []
        self.view.show_live_layout("yard", lambda: self.states)
        self.details = self.view.node_view.details

    def select_backups(self):
        for tree in (self.view.layout_backups, self.details.node_backups):
            tree.setCurrentItem(tree.topLevelItem(0))

    def assert_buttons(self, connected, live_node):
        for owner in (self.view, self.details):
            buttons = owner.backup_buttons
            self.assertEqual(
                buttons["New"].isEnabled(),
                connected and (owner is self.view or live_node),
            )
            self.assertTrue(buttons["View"].isEnabled())
            self.assertEqual(buttons["Compare"].isEnabled(), connected)
            self.assertFalse(buttons["Restore"].isEnabled())
            self.assertFalse(buttons["Delete"].isEnabled())

    def test_offline_view_and_reconnection(self):
        self.select_backups()
        self.assert_buttons(False, False)
        self.assertEqual(
            self.view.node_view.node_list.currentItem().text(), "42 (offline)"
        )
        self.assertEqual(self.details.summary.title(), "Node 42 (offline)")
        titles = []

        def inspect(dialog):
            titles.append(dialog.windowTitle())
            self.assertIsNotNone(dialog.findChild(QTreeWidget))
            return 0

        with (
            patch("workbench.backup_view.BackupView.exec", inspect),
            patch("workbench.layout_backup_view.LayoutBackupView.exec", inspect),
        ):
            self.details.view_backup()
            self.view.view_backup()
        self.assertEqual(len(titles), 2)
        with (
            patch(
                "workbench.node_backup_workflow.BackupCompare.exec",
                side_effect=AssertionError("Offline comparison"),
            ),
            patch(
                "workbench.layout_view.LayoutBackupCompare.exec",
                side_effect=AssertionError("Offline comparison"),
            ),
        ):
            self.details.compare_backup()
            self.view.compare_backup()
        self.states.append(self.state)
        self.view.node_view.state_lookup = lambda number: self.state
        self.view.set_connected(True)
        self.view.node_view.show_identity(self.state.identity)
        self.select_backups()
        self.assert_buttons(True, True)
        self.assertEqual(
            self.view.node_view.node_list.currentItem().text(),
            f"42 - {self.state.identity.module_type}",
        )
        self.assertEqual(
            self.details.summary.title(),
            f"Node 42 — {self.state.identity.module_type}",
        )
        self.view.set_connected(False)
        self.states.clear()
        self.view.node_view.clear_identities()
        self.view.node_view.show_saved_nodes("yard")
        self.select_backups()
        self.assertIsNone(self.details.live_state)
        self.assert_buttons(False, False)
        self.assertEqual(
            self.view.node_view.node_list.currentItem().text(), "42 (offline)"
        )
        self.assertEqual(self.details.summary.title(), "Node 42 (offline)")
        self.view.node_view.state_lookup = lambda number: self.state
        self.states.append(self.state)
        self.view.set_connected(True)
        self.view.node_view.show_identity(self.state.identity)
        self.select_backups()
        self.assert_buttons(True, True)
        self.assertEqual(
            self.view.node_view.node_list.currentItem().text(),
            f"42 - {self.state.identity.module_type}",
        )
        self.assertEqual(
            self.details.summary.title(),
            f"Node 42 — {self.state.identity.module_type}",
        )
        with (
            patch("workbench.backup_compare.BackupCompare.exec", inspect),
            patch("workbench.layout_backup_compare.LayoutBackupCompare.exec", inspect),
        ):
            self.details.compare_backup()
            self.view.compare_backup()
        self.assertEqual(len(titles), 4)

    def test_node_connection_details_follow_discovery_and_disconnect(self):
        def assert_details(can_id, status):
            self.assertEqual(self.details.can_id.text(), can_id)
            self.assertEqual(self.details.summary_can_id.text(), f"CAN ID: {can_id}")
            self.assertEqual(self.details.status.text(), status)
            self.assertEqual(self.details.summary_status.text(), f"Status: {status}")

        assert_details("-", "Offline")
        self.view.set_connected(True)
        assert_details("-", "-")
        self.view.node_view.show_identity(self.state.identity)
        assert_details("-", "-")
        self.view.node_view.state_lookup = lambda number: self.state
        self.view.node_view.refresh_state(42)
        assert_details("-", "Online")
        self.state.can_id = 7
        self.view.node_view.refresh_state(42)
        assert_details("7", "Online")
        self.view.set_connected(False)
        assert_details("7", "Offline")
        self.view.node_view.clear_identities()
        self.view.node_view.show_saved_nodes("yard")
        assert_details("-", "Offline")

    def test_selection_and_layout_changes(self):
        for connected in (False, True):
            self.view.set_connected(connected)
            for owner, tree in (
                (self.view, self.view.layout_backups),
                (self.details, self.details.node_backups),
            ):
                tree.clearSelection()
                for action in ("View", "Compare", "Restore", "Delete"):
                    self.assertFalse(owner.backup_buttons[action].isEnabled())
        self.select_backups()
        self.assert_buttons(True, False)
        self.view.show_live_layout("empty-layout", list)
        self.assertEqual(self.view.node_view.node_list.count(), 0)
        self.assertFalse(self.details.backup_buttons["New"].isEnabled())
        self.assertFalse(self.details.backup_buttons["View"].isEnabled())
        self.assertFalse(self.view.backup_buttons["View"].isEnabled())
