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
        dialog.annotations_checkbox.setChecked(False)
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

    def test_annotations_allow_restore_without_selecting_nodes(self):
        dialog = LayoutRestoreDialog(
            [1, 2],
            presence={1: "Online", 2: "Offline"},
            has_annotations=True,
            annotation_nodes={1},
        )
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.restore_button.text(), "Restore")
        dialog.node_checkboxes[1].setChecked(False)
        self.assertEqual(dialog.selected_nodes(), set())
        self.assertTrue(dialog.restore_button.isEnabled())
        dialog.annotations_checkbox.setChecked(False)
        self.assertFalse(dialog.restore_button.isEnabled())
        dialog.node_checkboxes[1].setChecked(True)
        self.assertTrue(dialog.restore_button.isEnabled())
        dialog.annotations_checkbox.setChecked(True)
        self.assertTrue(dialog.restore_button.isEnabled())
        dialog.show_presence(1, "Offline")
        self.assertEqual(dialog.selected_nodes(), {1})
        self.assertEqual(dialog.selected_configuration_nodes(), set())
        self.assertTrue(dialog.restore_button.isEnabled())
        dialog.annotations_checkbox.setChecked(False)
        self.assertFalse(dialog.restore_button.isEnabled())

    def test_no_online_nodes_cannot_restore(self):
        dialog = LayoutRestoreDialog([1, 2], presence={1: "Offline", 2: "Checking"})
        self.addCleanup(dialog.deleteLater)
        dialog.annotations_checkbox.setChecked(False)
        self.assertEqual(dialog.selected_nodes(), set())
        self.assertFalse(
            dialog.findChild(QDialogButtonBox)
            .button(QDialogButtonBox.StandardButton.Ok)
            .isEnabled()
        )

    def test_operation_choices_allow_offline_node_annotations_and_disable_neither(self):
        dialog = LayoutRestoreDialog(
            [1, 2],
            presence={1: "Offline", 2: "Incompatible"},
            has_annotations=True,
            configuration_available=False,
            annotation_nodes={1},
        )
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.configuration_checkbox.isChecked())
        self.assertTrue(dialog.annotations_checkbox.isChecked())
        self.assertTrue(dialog.restore_button.isEnabled())
        self.assertEqual(dialog.selected_configuration_nodes(), set())
        dialog.configuration_checkbox.setChecked(False)
        self.assertTrue(dialog.restore_button.isEnabled())
        self.assertTrue(dialog.node_checkboxes[1].isEnabled())
        self.assertFalse(dialog.node_checkboxes[2].isEnabled())
        dialog.node_checkboxes[1].setChecked(True)
        dialog.node_checkboxes[2].setChecked(False)
        dialog.show_presence(2, "Offline")
        self.assertEqual(dialog.selected_nodes(), {1})
        dialog.annotations_checkbox.setChecked(False)
        self.assertFalse(dialog.restore_button.isEnabled())

    def test_both_options_select_annotations_but_only_eligible_hardware(self):
        dialog = LayoutRestoreDialog(
            [258, 259, 260],
            presence={258: "Checking…", 259: "Checking…", 260: "Checking…"},
            has_annotations=True,
            annotation_nodes={258, 259, 260},
        )
        self.addCleanup(dialog.deleteLater)
        dialog.node_checkboxes[260].setChecked(False)
        dialog.show_presence(258, "Online")
        dialog.show_presence(259, "Online", ["NV count mismatch"])
        dialog.show_presence(260, "Online")
        self.assertEqual(dialog.node_checkboxes[258].text(), "Node 258 — Online")
        self.assertTrue(dialog.node_checkboxes[258].isEnabled())
        self.assertEqual(dialog.selected_nodes(), {258, 259})
        self.assertEqual(dialog.selected_configuration_nodes(), {258})
        dialog.annotations_checkbox.setChecked(False)
        self.assertFalse(dialog.node_checkboxes[259].isEnabled())
        self.assertEqual(dialog.selected_nodes(), {258})
        dialog.annotations_checkbox.setChecked(True)
        self.assertEqual(dialog.selected_nodes(), {258, 259})
        dialog.configuration_checkbox.setChecked(False)
        self.assertEqual(dialog.selected_configuration_nodes(), set())
        self.assertEqual(dialog.selected_nodes(), {258, 259})

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
