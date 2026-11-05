"""Layout connection choices in the dialog and in-memory layouts."""

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

    def test_summary_tracks_layout_selection_and_settings_edits(self):
        home = self.window.layouts["Home"]
        self.assertEqual(
            home.layout_summary.text(), "Home — Host:   Port: 5550  CAN ID: 126"
        )
        other = self.window.layout_settings["Test Layout"]
        other.update(connection_type="Serial", serial_port="/dev/ttyACM0", can_id=125)
        action = next(
            action
            for action in self.window.layout_group.actions()
            if action.data() == "Test Layout"
        )
        action.trigger()
        view = self.window.layouts["Test Layout"]
        self.assertEqual(
            view.layout_summary.text(),
            "Test Layout — Device: /dev/ttyACM0  CAN ID: 125",
        )
        view.tabs.setCurrentIndex(1)

        def accept_edit(dialog):
            dialog.name_edit.setText("Test Rig")
            dialog.connection_type_combo.setCurrentText("TCP/IP")
            dialog.host_edit.setText("railway")
            dialog.port_spin.setValue(5551)
            dialog.can_id_spin.setValue(127)
            return QDialog.DialogCode.Accepted

        with patch.object(LayoutSettingsDialog, "exec", accept_edit):
            self.window.edit_layout()
        self.assertEqual(
            view.layout_summary.text(),
            "Test Rig — Host: railway  Port: 5551  CAN ID: 127",
        )
        self.assertEqual(view.tabs.currentIndex(), 1)
        self.assertEqual(
            [view.tabs.tabText(i) for i in range(view.tabs.count())],
            ["Nodes", "Events", "Backups"],
        )

    def test_summary_stays_beside_tabs_at_narrow_width(self):
        view = self.window.layouts["Home"]
        self.window.show()
        self.window.resize(800, 600)
        self.app.processEvents()
        narrow_width = self.window.width()
        settings = self.window.layout_settings["Home"]
        settings["host"] = "a-long-railway-hostname-" * 5
        view.show_summary("Home", settings)
        self.window.show()
        self.window.resize(800, 600)
        self.app.processEvents()
        self.assertLessEqual(self.window.width(), narrow_width)
        summary = view.layout_summary
        tabs = view.tabs.tabBar()
        self.assertGreaterEqual(summary.x(), tabs.geometry().right())
        self.assertLessEqual(summary.geometry().right(), view.tabs.width())
        self.assertLessEqual(summary.y(), tabs.geometry().bottom())
        self.assertGreaterEqual(summary.geometry().bottom(), tabs.y())
        self.assertEqual(summary.toolTip(), summary.text())

    def test_new_layout_defaults_to_auto_connect_off(self):
        def accept_new(dialog):
            self.assertFalse(dialog.auto_connect_check.isChecked())
            self.assertEqual(dialog.can_id_spin.value(), 126)
            self.assertEqual(dialog.can_id_spin.minimum(), 100)
            self.assertEqual(dialog.can_id_spin.maximum(), 127)
            dialog.name_edit.setText("Garden")
            dialog.logical_layout_combo.setCurrentText("garden")
            return QDialog.DialogCode.Accepted

        with patch.object(LayoutSettingsDialog, "exec", accept_new):
            self.window.new_layout()

        self.assertFalse(self.window.layout_settings["Garden"]["auto_connect"])
        self.assertEqual(self.window.layout_settings["Garden"]["can_id"], 126)

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
            can_id=125,
        )

        def accept_edit(dialog):
            self.assertTrue(dialog.auto_connect_check.isChecked())
            self.assertEqual(dialog.connection_type_combo.currentText(), "Serial")
            self.assertEqual(dialog.serial_port_edit.text(), "/dev/ttyACM1")
            self.assertEqual(dialog.can_id_spin.value(), 125)
            self.assertTrue(dialog.can_id_spin.isVisibleTo(dialog))
            dialog.auto_connect_check.setChecked(False)
            dialog.can_id_spin.setValue(127)
            return QDialog.DialogCode.Accepted

        with patch.object(LayoutSettingsDialog, "exec", accept_edit):
            self.window.edit_layout()

        updated = self.window.layout_settings["Home"]
        self.assertFalse(updated["auto_connect"])
        self.assertEqual(updated["connection_type"], "Serial")
        self.assertEqual(updated["serial_port"], "/dev/ttyACM1")
        self.assertEqual(updated["can_id"], 127)

    def test_can_id_is_available_for_tcp_and_serial(self):
        dialog = LayoutSettingsDialog()
        self.addCleanup(dialog.close)
        for connection_type in ("TCP/IP", "Serial"):
            with self.subTest(connection_type=connection_type):
                dialog.connection_type_combo.setCurrentText(connection_type)
                self.assertTrue(dialog.can_id_spin.isVisibleTo(dialog))
                self.assertEqual(dialog.settings()["can_id"], 126)

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
