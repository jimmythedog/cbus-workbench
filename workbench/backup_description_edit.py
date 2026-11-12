"""Edit backup descriptions locally without involving the CBUS service."""

import logging
from pathlib import Path

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from .description_dialog import DescriptionDialog
from .logging_config import trace

logger = logging.getLogger("workbench.backups")


def edit_backup_description(table, item, column):
    path = item.data(0, Qt.ItemDataRole.UserRole)
    if column != 1 or not isinstance(path, Path):
        return
    try:
        with path.open(encoding="utf-8") as stream:
            backup = yaml.safe_load(stream)
        # Layout members display the owning manifest's description.
        if backup.get("partOfLayoutBackup"):
            path = path.parents[3] / "backups" / path.name
            with path.open(encoding="utf-8") as stream:
                backup = yaml.safe_load(stream)
        trace(logger, "Edit backup description path=%s", path)

        def save(text):
            # Reload so this edit owns only the description, never configuration.
            with path.open(encoding="utf-8") as stream:
                current = yaml.safe_load(stream)
            current["description"] = text
            temporary = path.with_suffix(".yaml.tmp")
            temporary.write_text(
                yaml.safe_dump(current, sort_keys=False), encoding="utf-8"
            )
            temporary.replace(path)
            item.setText(1, text)
            logger.info("Backup description saved path=%s", path)

        dialog = DescriptionDialog(
            table, "backup", path.name, backup.get("description", ""), save
        )
        result = dialog.exec()
        trace(
            logger, "Backup description editor closed path=%s result=%s", path, result
        )
        dialog.deleteLater()
    except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
        logger.exception("Cannot edit backup description path=%s", path)
        QMessageBox.warning(table, "Description not opened", str(error))
