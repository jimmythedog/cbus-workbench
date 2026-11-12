"""Forgetting removes local inventory without touching hardware or layout history."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from test_cbus_service import ConnectionStub

from workbench.cbus_service import CbusService, NodeState
from workbench.layout_view import LayoutView
from workbench.node_backup_files import (
    backup_directory,
    load_layout_node,
    save_backup,
    saved_node_numbers,
)
from workbench.node_metadata import save_metadata
from workbench.pnn import Pnn


class ForgetNodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for module in ("node_backup_files", "annotations"):
            paths = patch(
                f"workbench.{module}.application_directories",
                return_value={"Data": Path(temporary.name)},
            )
            paths.start()
            self.addCleanup(paths.stop)
        self.identity = Pnn(42, 1, 2, 0)
        save_metadata("yard", NodeState(self.identity))
        self.view = LayoutView(empty=True)
        self.addCleanup(self.view.close)
        self.view.show_live_layout("yard", list)
        self.nodes = self.view.node_view
        self.connection = ConnectionStub("yard")
        self.connection.state = "Connected"
        self.service = CbusService(self.connection, can_id=126)
        self.addCleanup(self.service.close)
        self.nodes.details.cbus_service = self.service
        self.view.set_connected(True)
        self.item = self.nodes.node_list.item(0)
        self.directory = backup_directory("yard", 42).parent
        self.view.annotations.save({"name": "Yard lights"}, 42)

    def test_forget_preserves_history_and_allows_rediscovery(self):
        snapshot = {
            "format_version": 1,
            "node": 42,
            "complete": True,
            "partOfLayoutBackup": True,
            "nvs": [],
            "events": [],
        }
        member = save_backup("yard", snapshot, "historical.yaml")
        manifest = save_backup("yard", {"nodeNumbers": [42]}, member.name)
        original_manifest = manifest.read_bytes()
        original_member = member.read_bytes()
        other = save_backup("yard", {"node": 43, "complete": False})
        with patch(
            "workbench.node_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.nodes.forget_saved_node(self.item)
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.nodes.node_list.count(), 0)
        self.assertEqual(self.connection.sent, [])
        self.assertIsNone(self.nodes.details.node)
        self.assertEqual(saved_node_numbers("yard"), [43])
        self.assertEqual(self.view.annotations.load(42), {})
        self.assertEqual(manifest.read_bytes(), original_manifest)
        self.assertEqual(load_layout_node(manifest, 42), snapshot)
        archived = manifest.parent / "nodes" / "42" / member.name
        self.assertEqual(archived.read_bytes(), original_member)
        self.assertTrue(other.exists())
        # Rediscovery uses the ordinary identity path without a remembered name.
        self.nodes.show_identity(self.identity)
        self.assertEqual(self.nodes.node_list.count(), 1)
        self.assertEqual(
            self.nodes.node_list.item(0).data(Qt.ItemDataRole.UserRole), self.identity
        )
        self.assertNotIn("Yard lights", self.nodes.node_list.item(0).text())

    def test_cancel_and_storage_failure_keep_node_visible(self):
        with patch(
            "workbench.node_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            self.nodes.forget_saved_node(self.item)
        self.assertTrue(self.directory.exists())
        self.assertEqual(self.nodes.node_list.count(), 1)
        with (
            patch(
                "workbench.node_view.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch(
                "workbench.node_backup_files.shutil.rmtree",
                side_effect=PermissionError("Access denied"),
            ),
            patch("workbench.node_view.QMessageBox.warning") as warning,
        ):
            self.nodes.forget_saved_node(self.item)
        self.assertTrue(self.directory.exists())
        self.assertEqual(self.nodes.node_list.count(), 1)
        self.assertEqual(self.nodes.details.node, 42)
        self.assertIn("Access denied", warning.call_args.args[2])

    def test_menu_offers_refresh_for_live_and_offline_nodes(self):
        self.view.show()
        self.app.processEvents()
        position = self.nodes.node_list.visualItemRect(self.item).center()
        offered = []
        timer = QTimer()
        timer.setSingleShot(True)

        def dismiss_menu():
            menu = self.app.activePopupWidget()
            offered.extend(action.text() for action in menu.actions())
            menu.close()

        timer.timeout.connect(dismiss_menu)
        timer.start(0)
        self.nodes.show_node_menu(position)
        timer.stop()
        self.assertEqual(offered, ["Refresh Node", "Forget Node"])
        offered.clear()
        self.nodes.show_identity(self.identity)
        timer.start(0)
        self.nodes.show_node_menu(position)
        self.nodes.show_node_menu(QPoint(-1, -1))
        timer.stop()
        self.assertEqual(offered, ["Refresh Node"])
