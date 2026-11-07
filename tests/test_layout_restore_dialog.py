"""Layout restore selection includes unavailable nodes without permitting writes."""

import os
import unittest

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QPushButton

from workbench.layout_restore_dialog import LayoutRestoreDialog


class LayoutRestoreDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        self.doCleanups()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_selection_only_includes_online_nodes(self):
        presence = {1: "Online", 2: "Offline", 3: "Checking", 4: "Incompatible"}
        dialog = LayoutRestoreDialog(presence, presence=presence)
        self.addCleanup(dialog.deleteLater)
        for number, status in presence.items():
            row = dialog.node_checkboxes[number]
            self.assertIn(status, row.text())
            self.assertEqual(row.isEnabled(), status == "Online")
        self.assertEqual(dialog.selected_nodes(), {1})
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        restore = dialog.findChild(QDialogButtonBox).button(
            QDialogButtonBox.StandardButton.Ok
        )
        buttons["Select None"].click()
        self.assertEqual(dialog.selected_nodes(), set())
        self.assertFalse(restore.isEnabled())
        buttons["Select All"].click()
        self.assertEqual(dialog.selected_nodes(), {1})
        self.assertTrue(restore.isEnabled())

    def test_no_online_nodes_cannot_restore(self):
        dialog = LayoutRestoreDialog([1, 2], presence={1: "Offline", 2: "Checking"})
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.selected_nodes(), set())
        self.assertFalse(
            dialog.findChild(QDialogButtonBox)
            .button(QDialogButtonBox.StandardButton.Ok)
            .isEnabled()
        )

    def test_multiple_compatibility_reasons_are_available_without_horizontal_scrolling(
        self,
    ):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QScrollArea

        dialog = LayoutRestoreDialog([262], presence={262: "Checking…"})
        self.addCleanup(dialog.deleteLater)
        reasons = ["NV count mismatch", "EV count exceeds node capacity"]
        dialog.show_presence(262, "Incompatible", reasons)
        row = dialog.node_checkboxes[262]
        self.assertEqual(row.text(), "Node 262 — Incompatible (2 issues)")
        self.assertEqual(row.toolTip().splitlines(), reasons)
        self.assertFalse(row.isEnabled())
        self.assertEqual(
            dialog.findChild(QScrollArea).horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
