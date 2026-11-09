"""Application directory resolution and Help dialog behaviour."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from workbench.application_directories_dialog import ApplicationDirectoriesDialog
from workbench.paths import system_mdf_directory


class ApplicationDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux XDG paths")
    def test_xdg_overrides(self):
        env = os.environ.copy()
        for key in ("CONFIG", "DATA", "STATE", "CACHE"):
            env[f"XDG_{key}_HOME"] = str(self.root / key.lower())
        code = (
            "from PySide6.QtCore import QCoreApplication; "
            "from workbench.paths import application_directories, user_mdf_directory; "
            "QCoreApplication.setApplicationName('cbus-workbench'); "
            "print('\\n'.join(map(str, application_directories().values()))); "
            "print(user_mdf_directory())"
        )
        output = subprocess.check_output(
            [sys.executable, "-c", code], env=env, text=True
        )
        self.assertEqual(
            output.splitlines(),
            [
                str(self.root / key / "cbus-workbench")
                for key in ("config", "data", "state", "cache")
            ]
            + [str(self.root / "data" / "cbus-workbench" / "mdfs")],
        )

    def test_system_mdfs_resolve_from_source_and_bundle_root(self):
        self.assertEqual(
            system_mdf_directory(),
            Path(__file__).resolve().parents[1] / "resources" / "mdfs",
        )
        with patch.object(sys, "_MEIPASS", str(self.root), create=True):
            self.assertEqual(system_mdf_directory(), self.root / "resources" / "mdfs")
        self.assertFalse((self.root / "resources").exists())

    def test_dialog_displays_copies_and_opens_resolved_paths(self):
        app = QApplication.instance() or QApplication([])
        paths = {
            name: self.root / name
            for name in ("Configuration", "Data", "State", "Cache")
        }
        paths["Configuration"].mkdir()
        with patch(
            "workbench.application_directories_dialog.application_directories",
            return_value=paths,
        ):
            dialog = ApplicationDirectoriesDialog()
        self.assertEqual(
            [field.text() for field in dialog.findChildren(QLineEdit)],
            list(map(str, paths.values())),
        )
        buttons = dialog.findChildren(QPushButton)
        next(button for button in buttons if button.text() == "Copy Path").click()
        self.assertEqual(app.clipboard().text(), str(paths["Configuration"]))
        with patch(
            "workbench.application_directories_dialog.QDesktopServices.openUrl",
            return_value=True,
        ) as opened:
            next(button for button in buttons if button.text() == "Open Folder").click()
            opened.assert_called_once_with(
                QUrl.fromLocalFile(str(paths["Configuration"]))
            )
        with patch(
            "workbench.application_directories_dialog.QMessageBox.information"
        ) as info:
            dialog.open_folder(paths["Data"])
            info.assert_called_once()
        dialog.close()
