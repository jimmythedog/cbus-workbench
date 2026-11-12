"""Persist layout menu changes without changing the UI when a save fails."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from layout_fixture import sample_settings
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from workbench.app_settings import SettingsError, load_settings, save_settings
from workbench.layout_settings import LayoutSettingsDialog
from workbench.window import MainWindow


class LayoutPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "settings.yaml"
        path_patch = patch(
            "workbench.app_settings.settings_path", return_value=self.path
        )
        path_patch.start()
        self.addCleanup(path_patch.stop)

    def open_window(self, settings=None):
        if settings is not None:
            save_settings(settings)
        window = MainWindow()
        self.addCleanup(window.close)
        return window

    @staticmethod
    def accept_new(dialog):
        dialog.name_edit.setText("Garden")
        dialog.logical_layout_combo.setCurrentText("garden")
        dialog.connection_type_combo.setCurrentText("Serial")
        dialog.serial_port_edit.setText("/dev/ttyACM2")
        dialog.can_id_spin.setValue(127)
        dialog.auto_connect_check.setChecked(True)
        return QDialog.DialogCode.Accepted

    def test_first_new_layout_is_default_and_settings_survive_restart(self):
        window = self.open_window()
        with patch.object(LayoutSettingsDialog, "exec", self.accept_new):
            window.new_layout()

        saved = load_settings()
        self.assertEqual(saved["default_layout"], "Garden")
        self.assertEqual(saved["layouts"]["Garden"]["logical_layout"], "garden")
        self.assertTrue(saved["layouts"]["Garden"]["auto_connect"])
        self.assertEqual(saved["layouts"]["Garden"]["connection"]["type"], "Serial")
        self.assertEqual(saved["layouts"]["Garden"]["connection"]["can_id"], 127)
        self.assertEqual(
            saved["layouts"]["Garden"]["connection"]["serial_port"],
            "/dev/ttyACM2",
        )
        reopened = MainWindow()
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.default_layout, "Garden")
        self.assertEqual(reopened.layout_settings["Garden"]["can_id"], 127)
        self.assertEqual(reopened.layout_group.checkedAction().data(), "Garden")
        self.assertEqual(reopened.layout_group.checkedAction().text(), "Garden ★")

    def test_rename_default_updates_key_without_changing_logical_layout(self):
        window = self.open_window(sample_settings())
        view = window.layouts["Home"]

        def rename(dialog):
            dialog.name_edit.setText("Main")
            return QDialog.DialogCode.Accepted

        with (
            patch.object(LayoutSettingsDialog, "exec", rename),
            patch.object(QMessageBox, "question") as question,
        ):
            window.edit_layout()

        question.assert_not_called()
        saved = load_settings()
        self.assertEqual(saved["default_layout"], "Main")
        self.assertNotIn("Home", saved["layouts"])
        self.assertEqual(saved["layouts"]["Main"]["logical_layout"], "home")
        self.assertIs(window.layouts["Main"], view)
        self.assertEqual(window.layout_group.checkedAction().data(), "Main")
        self.assertEqual(window.layout_group.checkedAction().text(), "Main ★")

        other = next(
            a for a in window.layout_group.actions() if a.data() == "Test Layout"
        )
        other.setChecked(True)
        window.select_layout(other)
        self.assertEqual(window.default_layout, "Main")
        self.assertEqual(load_settings()["default_layout"], "Main")
        self.assertEqual(other.text(), "Test Layout")

    def test_edit_tcp_can_id_survives_restart(self):
        window = self.open_window(sample_settings())

        def edit_can_id(dialog):
            self.assertEqual(dialog.connection_type_combo.currentText(), "TCP/IP")
            self.assertEqual(dialog.can_id_spin.value(), 126)
            dialog.can_id_spin.setValue(100)
            return QDialog.DialogCode.Accepted

        with patch.object(LayoutSettingsDialog, "exec", edit_can_id):
            window.edit_layout()

        self.assertEqual(window.layout_settings["Home"]["can_id"], 100)
        self.assertEqual(
            load_settings()["layouts"]["Home"]["connection"]["can_id"], 100
        )
        reopened = MainWindow()
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.layout_settings["Home"]["can_id"], 100)

    def test_delete_default_then_last_layout(self):
        window = self.open_window(sample_settings())
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            window.delete_layout()
            self.assertEqual(window.default_layout, "Test Layout")
            self.assertEqual(load_settings()["default_layout"], "Test Layout")
            self.assertEqual(window.layout_group.checkedAction().data(), "Test Layout")
            self.assertEqual(
                window.layout_group.checkedAction().text(), "Test Layout ★"
            )
            window.delete_layout()

        self.assertEqual(load_settings(), {"default_layout": None, "layouts": {}})
        self.assertIsNone(window.default_layout)
        self.assertIsNone(window.layout_group.checkedAction())
        self.assertFalse(window.edit_action.isEnabled())
        self.assertFalse(window.set_default_action.isEnabled())

    def test_set_default_action_saves_without_changing_selection(self):
        window = self.open_window(sample_settings())
        home, other = window.layout_group.actions()
        self.assertEqual(home.text(), "Home ★")
        self.assertTrue(home.isChecked())
        self.assertFalse(window.set_default_action.isEnabled())
        self.assertEqual(
            [action.text() for action in window.layout_menu.actions()[:4]],
            ["&New…", "&Edit…", "&Delete…", "Set as &default"],
        )

        other.trigger()
        self.assertTrue(window.set_default_action.isEnabled())
        self.assertEqual(load_settings()["default_layout"], "Home")
        self.assertEqual(home.text(), "Home ★")
        self.assertTrue(other.isChecked())
        self.assertFalse(home.isChecked())

        window.set_default_action.trigger()
        self.assertEqual(window.default_layout, "Test Layout")
        self.assertEqual(load_settings()["default_layout"], "Test Layout")
        self.assertEqual(home.text(), "Home")
        self.assertEqual(other.text(), "Test Layout ★")
        self.assertTrue(other.isChecked())
        self.assertFalse(window.set_default_action.isEnabled())

        home.trigger()
        self.assertTrue(window.set_default_action.isEnabled())
        self.assertEqual(other.text(), "Test Layout ★")
        self.assertTrue(home.isChecked())
        self.assertEqual(load_settings()["default_layout"], "Test Layout")

        reopened = MainWindow()
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.default_layout, "Test Layout")
        self.assertEqual(reopened.layout_group.checkedAction().text(), "Test Layout ★")
        self.assertFalse(reopened.set_default_action.isEnabled())

    def test_set_default_save_failure_keeps_indicator_and_default(self):
        window = self.open_window(sample_settings())
        home, other = window.layout_group.actions()
        other.trigger()
        original = self.path.read_bytes()

        with (
            patch(
                "workbench.window.save_settings", side_effect=SettingsError("disk full")
            ),
            patch.object(QMessageBox, "critical") as critical,
        ):
            window.set_default_action.trigger()

        self.assertIn("Could not set default layout", critical.call_args.args[2])
        self.assertIn("disk full", critical.call_args.args[2])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(window.default_layout, "Home")
        self.assertEqual(home.text(), "Home ★")
        self.assertEqual(other.text(), "Test Layout")
        self.assertTrue(other.isChecked())
        self.assertTrue(window.set_default_action.isEnabled())

    def test_failed_saves_leave_new_edit_and_delete_unchanged(self):
        window = self.open_window(sample_settings())
        original = self.path.read_bytes()
        original_view = window.layouts["Home"]
        connection = Mock()
        window.connections["Home"] = connection

        def rename(dialog):
            dialog.name_edit.setText("Main")
            return QDialog.DialogCode.Accepted

        def assert_unchanged():
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(list(window.layouts), ["Home", "Test Layout"])
            self.assertEqual(list(window.layout_settings), ["Home", "Test Layout"])
            self.assertEqual(
                [action.data() for action in window.layout_group.actions()],
                ["Home", "Test Layout"],
            )
            self.assertIs(window.layouts["Home"], original_view)
            self.assertIs(window.connections["Home"], connection)
            self.assertEqual(window.layout_group.checkedAction().data(), "Home")
            self.assertEqual(window.default_layout, "Home")

        with patch(
            "workbench.window.save_settings", side_effect=SettingsError("disk full")
        ):
            with (
                patch.object(LayoutSettingsDialog, "exec", self.accept_new),
                patch.object(QMessageBox, "critical") as critical,
            ):
                window.layout_menu.actions()[0].trigger()
                self.assertIn("Could not create layout", critical.call_args.args[2])
                self.assertIn("disk full", critical.call_args.args[2])
                assert_unchanged()
            with (
                patch.object(LayoutSettingsDialog, "exec", rename),
                patch.object(QMessageBox, "critical") as critical,
            ):
                window.edit_action.trigger()
                self.assertIn("Could not update layout", critical.call_args.args[2])
                self.assertIn("disk full", critical.call_args.args[2])
                assert_unchanged()
            with (
                patch.object(
                    QMessageBox,
                    "question",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
                patch.object(QMessageBox, "critical") as critical,
            ):
                window.delete_action.trigger()
                self.assertIn("Could not delete layout", critical.call_args.args[2])
                assert_unchanged()

    def test_active_connections_allow_polling_edits_but_block_connection_changes_and_delete(
        self,
    ):
        window = self.open_window(sample_settings())
        for state in ("Connecting", "Connected"):
            with self.subTest(state=state):
                window.set_connection_state("Home", state)
                self.assertTrue(window.edit_action.isEnabled())
                self.assertFalse(window.delete_action.isEnabled())

                def inspect(dialog):
                    self.assertFalse(dialog.name_edit.isEnabled())
                    self.assertFalse(dialog.can_id_spin.isEnabled())
                    self.assertTrue(dialog.node_poll_spin.isEnabled())
                    return QDialog.DialogCode.Rejected

                with (
                    patch.object(LayoutSettingsDialog, "exec", inspect),
                    patch.object(QMessageBox, "question") as delete_dialog,
                ):
                    window.edit_layout()
                    window.delete_layout()
                delete_dialog.assert_not_called()

        connection = Mock()
        connection.socket.state.return_value = (
            QAbstractSocket.SocketState.ConnectedState
        )
        window.connections["Home"] = connection
        window.set_connection_state("Home", "Error")
        self.assertTrue(window.edit_action.isEnabled())
        self.assertFalse(window.delete_action.isEnabled())
        window.delete_layout()
        self.assertIn("Home", window.layouts)

        connection.socket.state.return_value = (
            QAbstractSocket.SocketState.UnconnectedState
        )
        window.update_layout_actions()
        self.assertTrue(window.edit_action.isEnabled())
        self.assertTrue(window.delete_action.isEnabled())
        with patch.object(
            LayoutSettingsDialog, "exec", return_value=QDialog.DialogCode.Rejected
        ):
            window.edit_layout()

    def test_logical_layout_change_requires_confirmation_and_can_return_to_edit(self):
        window = self.open_window(sample_settings())
        calls = 0

        def edit_then_cancel(dialog):
            nonlocal calls
            calls += 1
            if calls == 1:
                dialog.logical_layout_combo.setCurrentText("different")
                return QDialog.DialogCode.Accepted
            self.assertEqual(dialog.logical_layout_combo.currentText(), "different")
            return QDialog.DialogCode.Rejected

        with (
            patch.object(LayoutSettingsDialog, "exec", edit_then_cancel),
            patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.No
            ) as question,
        ):
            window.edit_layout()

        self.assertEqual(calls, 2)
        self.assertIn("different stored node configuration", question.call_args.args[2])
        self.assertIn("will not be moved or deleted", question.call_args.args[2])
        self.assertEqual(load_settings()["layouts"]["Home"]["logical_layout"], "home")

        def accept_change(dialog):
            dialog.logical_layout_combo.setCurrentText("different")
            return QDialog.DialogCode.Accepted

        with (
            patch.object(LayoutSettingsDialog, "exec", accept_change),
            patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ),
        ):
            window.edit_layout()
        self.assertEqual(
            load_settings()["layouts"]["Home"]["logical_layout"], "different"
        )


if __name__ == "__main__":
    unittest.main()
