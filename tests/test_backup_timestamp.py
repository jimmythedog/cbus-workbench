"""Local timestamps retain their wall time and sorting ignores localized text."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PySide6.QtCore import QLocale, Qt, QTimeZone
from PySide6.QtWidgets import QApplication

from workbench.layout_backups import LayoutBackups
from workbench.node_backups import NodeBackups


class BackupTimestampTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_localized_dates_dst_and_newest_first_preserve_paths(self):
        previous = QLocale()
        self.addCleanup(QLocale.setDefault, previous)
        zone = QTimeZone(b"Europe/London")
        filenames = [
            "2026-01-31_13-14-15-123456.yaml",
            "2026-07-02_13-14-15-123456.yaml",
            "2026-07-02_13-14-15-654321.yaml",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("backups", "nodes/42/backups"):
                target = root / "layouts/Yard" / folder
                target.mkdir(parents=True)
                for filename in filenames:
                    (target / filename).write_text(yaml.safe_dump({"complete": True}))
            for locale, summer, winter in (
                (
                    "en_GB",
                    "02/07/2026 13:14",
                    "31/01/2026 13:14",
                ),
                (
                    "de_DE",
                    "02.07.26 13:14",
                    "31.01.26 13:14",
                ),
            ):
                QLocale.setDefault(QLocale(locale))
                with (
                    self.subTest(locale=locale),
                    patch(
                        "workbench.node_backup_files.application_directories",
                        return_value={"Data": root},
                    ),
                    patch.object(QTimeZone, "systemTimeZone", return_value=zone),
                ):
                    for table in (NodeBackups(), LayoutBackups(empty=True)):
                        if isinstance(table, NodeBackups):
                            table.show_live_node("Yard", 42)
                        else:
                            table.show_live_layout("Yard")
                        rows = [table.topLevelItem(i) for i in range(3)]
                        self.assertEqual(
                            [row.text(0) for row in rows], [summer, summer, winter]
                        )
                        self.assertEqual(
                            [
                                row.data(0, Qt.ItemDataRole.UserRole).name
                                for row in rows
                            ],
                            list(reversed(filenames)),
                        )
                        table.close()
