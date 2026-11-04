"""Observable node backup actions and their confirmation boundaries."""

import os
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox

from workbench.node import Node
from workbench.node_details import NodeDetails


class NodeBackupWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.node = Node(
            number=42,
            module_type="Test module",
            can_id=12,
            firmware="1a",
            has_mdf=False,
            nv_values={1: 7},
            nv_descriptions={1: "Speed"},
            consumed_events={"42:3": "Active"},
            ev_values={"42:3": {1: 5}},
        )
        self.details = NodeDetails({})
        self.details.connected = True
        self.addCleanup(self.details.close)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, self.node)
        self.details.show_node(item)

    def select(self, index=0):
        self.details.node_backups.setCurrentItem(
            self.details.node_backups.topLevelItem(index)
        )

    def test_create_cancel_and_view_compare(self):
        backups = self.details.node_backups
        original_count = len(backups.backups_by_node[self.node.number])
        with patch(
            "workbench.node_backup_workflow.QInputDialog.getText",
            return_value=("Ignored", False),
        ):
            self.details.new_backup()
        self.assertEqual(len(backups.backups_by_node[self.node.number]), original_count)

        with patch(
            "workbench.node_backup_workflow.QInputDialog.getText",
            return_value=("  My backup  ", True),
        ):
            self.details.new_backup()
        saved = backups.backups_by_node[self.node.number][0]
        self.assertEqual(saved["description"], "My backup")
        self.assertEqual(saved["nodeVariables"], [7])
        self.assertEqual(
            len(backups.backups_by_node[self.node.number]), original_count + 1
        )

        backups.show_node(self.node)
        self.select()
        with (
            patch("workbench.node_backup_workflow.BackupView.exec") as view,
            patch("workbench.node_backup_workflow.BackupCompare.exec") as compare,
        ):
            self.details.view_backup()
            self.details.compare_backup()
        view.assert_called_once()
        compare.assert_called_once()
        self.assertTrue(self.details.backup_buttons["View"].isEnabled())

    def test_restore_refreshes_variables_and_events_after_confirmation(self):
        self.select(0)
        self.node.nv_values = {1: 99}
        self.node.consumed_events = {}
        self.node.ev_values = {}
        with patch(
            "workbench.node_backup_workflow.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as question:
            self.details.restore_backup()
        self.assertEqual(question.call_args.args[1], "Restore node backup")
        self.assertEqual(self.node.nv_values[1], 0)
        self.assertEqual(self.details.raw_values.item(0, 1).text(), "0")
        self.assertEqual(self.details.node_events.consumed_table.topLevelItemCount(), 1)

    def test_restore_cancel_preserves_node_and_display(self):
        self.select(0)
        original = self.node.nv_values.copy()
        with patch(
            "workbench.node_backup_workflow.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            self.details.restore_backup()
        self.assertEqual(self.node.nv_values, original)
        self.assertEqual(self.details.raw_values.item(0, 1).text(), "7")

    def test_layout_backup_warns_on_restore_and_cannot_be_deleted(self):
        self.select(2)  # The seeded layout backup uses its legacy description.
        with patch(
            "workbench.node_backup_workflow.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ) as question:
            self.details.restore_backup()
        self.assertIn("part of a layout backup", question.call_args.args[2])

        with patch("workbench.node_backup_workflow.QMessageBox.information") as info:
            self.details.delete_backup()
        info.assert_called_once()

        with patch(
            "workbench.node_backup_workflow.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as question:
            self.details.restore_backup()
        self.assertIn("part of a layout backup", question.call_args.args[2])
        self.assertEqual(self.node.nv_values[1], 0)
        self.assertEqual(
            len(self.details.node_backups.backups_by_node[self.node.number]), 3
        )

        item = self.details.node_backups.topLevelItem(0)
        flagged = item.data(0, Qt.ItemDataRole.UserRole)
        flagged["partOfLayoutBackup"] = True
        item.setData(0, Qt.ItemDataRole.UserRole, flagged)
        self.select(0)
        with patch("workbench.node_backup_workflow.QMessageBox.information") as info:
            self.details.delete_backup()
        info.assert_called_once()

    def test_delete_requires_confirmation(self):
        self.select(0)
        with patch(
            "workbench.node_backup_workflow.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            self.details.delete_backup()
        self.assertEqual(
            len(self.details.node_backups.backups_by_node[self.node.number]), 3
        )
        with patch(
            "workbench.node_backup_workflow.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.details.delete_backup()
        self.assertEqual(
            len(self.details.node_backups.backups_by_node[self.node.number]), 2
        )

    def test_no_node_or_backup_selection_is_inert(self):
        with patch("workbench.node_backup_workflow.QMessageBox.question") as question:
            self.details.restore_backup()
            self.details.delete_backup()
        question.assert_not_called()

        self.details.show_node(None)
        self.assertFalse(self.details.backup_buttons["New"].isEnabled())
        self.assertFalse(self.details.backup_buttons["View"].isEnabled())
        with (
            patch("workbench.node_backup_workflow.QInputDialog.getText") as prompt,
            patch("workbench.node_backup_workflow.QMessageBox.question") as question,
        ):
            for action in (
                self.details.new_backup,
                self.details.view_backup,
                self.details.compare_backup,
                self.details.restore_backup,
                self.details.delete_backup,
            ):
                action()
        prompt.assert_not_called()
        question.assert_not_called()


if __name__ == "__main__":
    unittest.main()
