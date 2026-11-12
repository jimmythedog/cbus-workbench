"""Editing descriptions preserves saved configuration and supports cancellation."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit, QMessageBox

from workbench.layout_backups import LayoutBackups
from workbench.node_backups import NodeBackups


class BackupDescriptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_save_and_cancel_node_layout_and_linked_node(self):
        for kind in ("node", "layout", "linked"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = root / "layouts/Yard/backups/saved.yaml"
                node = root / "layouts/Yard/nodes/42/backups/saved.yaml"
                original = {
                    "description": "Original",
                    "created": "unchanged timestamp",
                    "complete": True,
                    "partOfLayoutBackup": kind == "linked",
                    "node": 42,
                    "nvs": [1, None, 3],
                    "events": [],
                    "annotations": {"name": "Yard"},
                }
                for path in (manifest, node):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(yaml.safe_dump(original))
                table = LayoutBackups(empty=True) if kind == "layout" else NodeBackups()
                with patch(
                    "workbench.node_backup_files.application_directories",
                    return_value={"Data": root},
                ):
                    if kind == "layout":
                        table.show_live_layout("Yard")
                    else:
                        table.show_live_node("Yard", 42)
                item = table.topLevelItem(0)
                target = manifest if kind in ("layout", "linked") else node
                other = node if target == manifest else manifest
                other_bytes = other.read_bytes()

                def edit(text, button, table=table, item=item):
                    def interact():
                        dialog = QApplication.activeModalWidget()
                        editor = dialog.findChild(QLineEdit)
                        self.assertEqual(editor.text(), item.text(1))
                        editor.setText(text)
                        dialog.findChild(QDialogButtonBox).button(button).click()

                    QTimer.singleShot(0, interact)
                    table.itemDoubleClicked.emit(item, 1)

                edit("Revised", QDialogButtonBox.StandardButton.Save)
                self.assertEqual(
                    yaml.safe_load(target.read_text()),
                    {**original, "description": "Revised"},
                )
                self.assertEqual(item.text(1), "Revised")
                saved_bytes = target.read_bytes()
                edit("Discarded", QDialogButtonBox.StandardButton.Cancel)
                self.assertEqual(target.read_bytes(), saved_bytes)
                self.assertEqual(item.text(1), "Revised")

                # Failed persistence keeps the saved text and permits Cancel.
                def fail_save():
                    dialog = QApplication.activeModalWidget()
                    dialog.findChild(QLineEdit).setText("Failed")
                    with (
                        patch.object(Path, "replace", side_effect=OSError("Read only")),
                        patch.object(QMessageBox, "warning"),
                    ):
                        dialog.findChild(QDialogButtonBox).button(
                            QDialogButtonBox.StandardButton.Save
                        ).click()
                    self.assertTrue(dialog.isVisible())
                    dialog.reject()

                QTimer.singleShot(0, fail_save)
                table.itemDoubleClicked.emit(item, 1)
                self.assertEqual(target.read_bytes(), saved_bytes)
                self.assertEqual(item.text(1), "Revised")
                self.assertEqual(other.read_bytes(), other_bytes)
                self.assertEqual(sorted(target.parent.glob("*.yaml")), [target])
                table.close()
