"""Save the selected layout's discovered configuration without hardware access."""

import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget

from .cbus_service import NodeState
from .logging_config import trace
from .node_backup_files import node_backup, save_backup

logger = logging.getLogger("workbench.backups")


def create_layout_backup(
    parent: QWidget, logical_layout: str, states: Iterable[NodeState]
) -> Path | None:
    """Capture before confirmation so the saved data matches the warning."""
    nodes = [node_backup(state) for state in states]
    incomplete = [str(node["node"]) for node in nodes if not node["complete"]]
    complete = bool(nodes) and not incomplete
    trace(
        logger,
        "Layout backup captured",
        extra={
            "fields": {
                "layout": logical_layout,
                "node_count": len(nodes),
                "complete": complete,
            }
        },
    )
    if not complete:
        dialog = QMessageBox(parent)
        dialog.setWindowTitle("Incomplete layout discovery")
        dialog.setText(
            "Incomplete nodes: " + ", ".join(incomplete)
            if nodes
            else "No nodes have been discovered."
        )
        dialog.setDetailedText(
            "\n".join(
                f"Node {node['node']}: {'Complete' if node['complete'] else 'Incomplete'}"
                for node in nodes
            )
        )
        dialog.setInformativeText("Save the confirmed configuration anyway?")
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        save = dialog.addButton("Save Anyway", QMessageBox.ButtonRole.AcceptRole)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        if dialog.clickedButton() is not save:
            trace(
                logger,
                "Incomplete layout backup cancelled",
                extra={"fields": {"layout": logical_layout}},
            )
            return None
    description, accepted = QInputDialog.getText(
        parent, "New layout backup", "Description (optional):"
    )
    if not accepted:
        trace(
            logger,
            "Layout backup creation cancelled",
            extra={"fields": {"layout": logical_layout}},
        )
        return None
    manifest = {
        "format_version": 1,
        "complete": complete,
        "nodeNumbers": [node["node"] for node in nodes],
    }
    if description.strip():
        manifest["description"] = description.strip()
    filename = f"{datetime.now():%Y-%m-%d_%H-%M-%S-%f}.yaml"
    # Publish the manifest only after all associated node files have been written.
    # Failed writes propagate to the existing reporter; earlier files are retained.
    for node in nodes:
        node["partOfLayoutBackup"] = True
        save_backup(logical_layout, node, filename)
    return save_backup(
        logical_layout,
        manifest,
        filename,
    )
