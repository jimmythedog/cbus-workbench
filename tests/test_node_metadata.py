"""Saved inventory is independent of backups and fresh discovery evidence."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PySide6.QtWidgets import QApplication

from workbench.cbus_service import NodeState
from workbench.layout_view import LayoutView
from workbench.node_backup_files import (
    backup_directory,
    save_backup,
    saved_node_numbers,
)
from workbench.node_metadata import load_metadata, save_metadata
from workbench.pnn import Pnn


class NodeMetadataTests(unittest.TestCase):
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
        self.state.parameters = {0: 10, 1: 165, 3: 32, 10: 1}
        self.state.can_id = 5
        self.path = backup_directory("yard", 42).parent / "metadata.yaml"

    def test_reload_without_connection_or_backup(self):
        save_metadata("yard", self.state)
        self.assertFalse(backup_directory("yard", 42).exists())
        self.assertEqual(saved_node_numbers("yard"), [42])
        metadata = yaml.safe_load(self.path.read_text())
        self.assertEqual(set(metadata), {"parameters", "canId"})
        self.assertEqual(metadata["parameters"], [10, 165, None, 32] + [None] * 6 + [1])
        self.assertEqual(metadata["canId"], 5)
        view = LayoutView(empty=True)
        self.addCleanup(view.close)
        view.show_live_layout("yard", list)
        self.assertEqual(view.node_view.saved_metadata[42], metadata)
        self.assertIsNone(view.node_view.details.live_state)
        self.assertEqual(view.node_view.details.can_id.text(), "5")
        details = view.node_view.details
        self.assertEqual(details.manufacturer.text(), "MERG")
        self.assertEqual(details.module_type.text(), "CANMIO")
        self.assertEqual(details.details_page.module_identifier.text(), "A520")
        self.assertEqual(details.node_mode.text(), "-")
        self.assertEqual(details.consumer.text(), "-")
        # Cached identity must not fill gaps in a fresh live view or enable editing.
        live = NodeState(Pnn(42, 13, 34, 5))
        view.node_view.state_lookup = lambda number: live
        view.set_connected(True)
        view.node_view.show_identity(live.identity)
        self.assertEqual(live.parameters, {})
        self.assertEqual(details.manufacturer.text(), "-")
        self.assertEqual(details.module_type.text(), "-")
        self.assertEqual(details.details_page.module_identifier.text(), "-")
        self.assertFalse(details.edit_button.isEnabled())
        live.parameters = {1: 165}
        view.node_view.refresh_state(42)
        self.assertEqual(details.manufacturer.text(), "MERG")
        self.assertEqual(details.module_type.text(), "-")
        self.assertEqual(details.details_page.module_identifier.text(), "-")
        live.parameters = {3: 32}
        view.node_view.refresh_state(42)
        self.assertEqual(details.manufacturer.text(), "-")
        self.assertEqual(details.module_type.text(), "32")
        self.assertEqual(details.details_page.module_identifier.text(), "-")

    def test_partial_saved_identity_keeps_unknown_fields_unknown(self):
        self.state.parameters = {1: 165}
        save_metadata("yard", self.state)
        view = LayoutView(empty=True)
        self.addCleanup(view.close)
        view.show_live_layout("yard", list)
        details = view.node_view.details
        self.assertEqual(details.manufacturer.text(), "MERG")
        self.assertEqual(details.module_type.text(), "-")
        self.assertEqual(details.details_page.module_identifier.text(), "-")
        self.assertEqual(details.producer.text(), "-")
        self.assertEqual(details.supports_bootloading.text(), "-")

    def test_partial_merge_and_unchanged_file(self):
        save_metadata("yard", self.state)
        partial = NodeState(self.state.identity)
        partial.parameters = {1: 0, 3: 99}
        save_metadata("yard", partial)
        metadata = load_metadata("yard", 42)
        self.assertEqual(metadata["parameters"][0:4], [10, 0, None, 99])
        self.assertEqual(metadata["parameters"][10], 1)
        self.assertEqual(metadata["canId"], 5)
        # Give the file a distinct timestamp so an unnecessary rewrite is visible.
        os.utime(self.path, ns=(1_000_000_000, 1_000_000_000))
        save_metadata("yard", partial)
        self.assertEqual(self.path.stat().st_mtime_ns, 1_000_000_000)
        partial.can_id = 7
        save_metadata("yard", partial)
        self.assertEqual(load_metadata("yard", 42)["canId"], 7)

    def test_retention_and_existing_backups(self):
        backup = save_backup("yard", {"node": 99, "complete": False})
        contents = backup.read_bytes()
        save_metadata("yard", self.state)
        # A later pass sees only another node, with no confirmed parameters or CAN ID.
        save_metadata("yard", NodeState(Pnn(43, 2, 3, 0)))
        self.assertEqual(saved_node_numbers("yard"), [42, 43, 99])
        self.assertEqual(load_metadata("yard", 43), {})
        self.assertEqual(load_metadata("yard", 42)["canId"], 5)
        self.assertEqual(backup.read_bytes(), contents)
        self.assertEqual(saved_node_numbers("other-layout"), [])
