"""Selection checks use the real request/response path without discovering nodes."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from workbench import response_timeout
from workbench.cbus_service import CbusService, NodeState
from workbench.layout_restore_selection import LayoutRestoreSelection
from workbench.pnn import Pnn


class Connection(QObject):
    frame_received = Signal(bytes)
    state_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.layout_name = "Yard"
        self.state = "Connected"
        self.sent = []

    def send(self, frame):
        self.sent.append(frame)


class LayoutRestoreSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.manifest = manifest = root / "backups" / "saved.yaml"
        manifest.parent.mkdir()
        manifest.write_text(
            yaml.safe_dump(
                {"format_version": 1, "complete": True, "nodeNumbers": [1, 2, 3]}
            )
        )
        for number in (1, 2, 3):
            path = root / "nodes" / str(number) / "backups" / manifest.name
            path.parent.mkdir(parents=True)
            path.write_text(
                yaml.safe_dump(
                    {
                        "format_version": 1,
                        "complete": True,
                        "partOfLayoutBackup": True,
                        "node": number,
                        "nvs": [4],
                        "events": [],
                    }
                )
            )
        self.parent = QWidget()
        self.connection = Connection()
        self.service = CbusService(self.connection, 126)
        for number, count in ((1, 1), (2, 1), (3, 2)):
            identity = Pnn(number, 1, 2, 4)
            self.service.nodes[number] = identity
            self.service.node_states[number] = NodeState(
                identity, parameters={6: count}
            )
        self.selection = LayoutRestoreSelection(self.parent, self.service, manifest)

    def tearDown(self):
        self.selection.dialog.close()
        self.service.close()
        self.parent.deleteLater()
        self.connection.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def reply(self, number):
        self.connection.frame_received.emit(f":SB040N9B{number:04X}0302;".encode())

    def test_mixed_presence_and_compatibility_only_send_sequential_parameter_three(
        self,
    ):
        rows = self.selection.dialog.node_checkboxes
        self.assertTrue(
            all(
                "Checking" in row.text() and not row.isEnabled()
                for row in rows.values()
            )
        )
        with patch.object(response_timeout, "RESPONSE_TIMEOUT_MS", 100):
            self.assertEqual(self.connection.sent, [])
            self.selection.start()
            self.assertEqual(len(self.connection.sent), 1)
            self.reply(1)
            self.assertEqual(self.selection.dialog.selected_nodes(), {1})
            for _ in range(100):
                if len(self.connection.sent) == 3:
                    break
                QTest.qWait(10)
            self.assertEqual(len(self.connection.sent), 3)
            self.reply(3)
        self.assertEqual(
            [row.text() for row in rows.values()],
            ["Node 1 — Online", "Node 2 — Offline", "Node 3 — NV count mismatch"],
        )
        self.assertEqual(self.selection.dialog.selected_nodes(), {1})
        self.assertEqual(
            self.connection.sent,
            [f":SBFC0N73000{number}03;".encode() for number in (1, 2, 3)],
        )

    def test_configuration_toggle_stops_unsent_checks_and_restarts_eligibility(self):
        path = (
            self.manifest.parent.parent / "nodes" / "2" / "backups" / self.manifest.name
        )
        backup = yaml.safe_load(path.read_text())
        path.write_text(
            yaml.safe_dump({**backup, "annotations": {"name": "Offline name"}})
        )
        self.selection.dialog.close()
        self.selection.deleteLater()
        self.selection = LayoutRestoreSelection(
            self.parent, self.service, self.manifest
        )
        self.selection.start()
        self.assertEqual(self.connection.sent, [b":SBFC0N73000103;"])
        self.selection.dialog.configuration_checkbox.setChecked(False)
        self.assertTrue(self.selection.dialog.node_checkboxes[2].isEnabled())
        self.assertFalse(self.selection.dialog.node_checkboxes[1].isEnabled())
        self.selection.dialog.node_checkboxes[2].setChecked(True)
        self.reply(1)  # Drain the already transmitted read; no further checks follow.
        self.assertEqual(self.connection.sent, [b":SBFC0N73000103;"])
        self.assertEqual(self.selection.dialog.selected_nodes(), {2})
        self.assertEqual(self.selection.dialog.selected_configuration_nodes(), set())
        self.selection.dialog.configuration_checkbox.setChecked(True)
        self.assertEqual(self.connection.sent[-1], b":SBFC0N73000103;")
        self.reply(1)
        self.assertIn("Online", self.selection.dialog.node_checkboxes[1].text())
        self.assertEqual(self.selection.dialog.selected_configuration_nodes(), {1})

    def assert_stopped(self, number=1):
        sent = list(self.connection.sent)
        self.reply(number)
        self.assertEqual(self.connection.sent, sent)
        self.assertEqual(self.selection.dialog.selected_nodes(), set())

    def test_close_stops_remaining_checks_and_ignores_late_reply(self):
        self.selection.start()
        self.selection.dialog.reject()
        self.assert_stopped()

    def test_disconnect_disables_selected_nodes_and_stops_remaining_checks(self):
        self.selection.start()
        self.reply(1)
        self.assertEqual(self.selection.dialog.selected_nodes(), {1})
        self.connection.state = "Disconnected"
        self.connection.state_changed.emit("Disconnected")
        self.assert_stopped(2)
