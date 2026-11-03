"""The auto-connect choice in the layout dialog and in-memory layouts."""

import os
import unittest
from unittest.mock import patch

from layout_fixture import sample_settings
from PySide6.QtWidgets import QApplication, QDialog

from workbench.layout_settings import LayoutSettingsDialog
from workbench.window import MainWindow


class LayoutSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch("workbench.window.load_settings", return_value=sample_settings()):
            self.window = MainWindow()
        self.addCleanup(self.window.close)
        save_patch = patch("workbench.window.save_settings")
        save_patch.start()
        self.addCleanup(save_patch.stop)

    def test_new_layout_defaults_to_auto_connect_off(self):
        def accept_new(dialog):
            self.assertFalse(dialog.auto_connect_check.isChecked())
            dialog.name_edit.setText("Garden")
            dialog.logical_layout_combo.setCurrentText("garden")
            return QDialog.DialogCode.Accepted

        with patch.object(LayoutSettingsDialog, "exec", accept_new):
            self.window.new_layout()

        self.assertFalse(self.window.layout_settings["Garden"]["auto_connect"])

    def test_new_layout_can_enable_auto_connect(self):
        def accept_new(dialog):
            dialog.name_edit.setText("Garden")
            dialog.logical_layout_combo.setCurrentText("garden")
            dialog.auto_connect_check.setChecked(True)
            return QDialog.DialogCode.Accepted

        with patch.object(LayoutSettingsDialog, "exec", accept_new):
            self.window.new_layout()

        self.assertTrue(self.window.layout_settings["Garden"]["auto_connect"])

    def test_edit_initialises_and_updates_auto_connect_without_changing_connection(
        self,
    ):
        current = self.window.layout_settings["Home"]
        current.update(
            auto_connect=True,
            connection_type="Serial",
            serial_port="/dev/ttyACM1",
        )

        def accept_edit(dialog):
            self.assertTrue(dialog.auto_connect_check.isChecked())
            self.assertEqual(dialog.connection_type_combo.currentText(), "Serial")
            self.assertEqual(dialog.serial_port_edit.text(), "/dev/ttyACM1")
            dialog.auto_connect_check.setChecked(False)
            return QDialog.DialogCode.Accepted

        with patch.object(LayoutSettingsDialog, "exec", accept_edit):
            self.window.edit_layout()

        updated = self.window.layout_settings["Home"]
        self.assertFalse(updated["auto_connect"])
        self.assertEqual(updated["connection_type"], "Serial")
        self.assertEqual(updated["serial_port"], "/dev/ttyACM1")

    def test_cancel_leaves_existing_layout_settings_unchanged(self):
        original = self.window.layout_settings["Home"].copy()

        def cancel_edit(dialog):
            dialog.auto_connect_check.setChecked(True)
            dialog.host_edit.setText("changed-host")
            return QDialog.DialogCode.Rejected

        with patch.object(LayoutSettingsDialog, "exec", cancel_edit):
            self.window.edit_layout()

        self.assertEqual(self.window.layout_settings["Home"], original)

    def test_cancel_new_layout_does_not_create_it(self):
        def cancel_new(dialog):
            dialog.name_edit.setText("Garden")
            dialog.logical_layout_combo.setCurrentText("garden")
            dialog.auto_connect_check.setChecked(True)
            return QDialog.DialogCode.Rejected

        with patch.object(LayoutSettingsDialog, "exec", cancel_new):
            self.window.new_layout()

        self.assertNotIn("Garden", self.window.layout_settings)


if __name__ == "__main__":
    unittest.main()
