"""Read-only eligibility checks for the layout restore selection dialog."""

import logging

import yaml
from PySide6.QtCore import QObject

from .layout_restore_dialog import LayoutRestoreDialog
from .logging_config import trace
from .node_backup_files import load_layout_node


def load_manifest(path):
    with path.open(encoding="utf-8") as stream:
        manifest = yaml.safe_load(stream)
    if not (
        isinstance(manifest, dict)
        and manifest.get("format_version") == 1
        and type(manifest.get("complete")) is bool
        and isinstance(manifest.get("nodeNumbers"), list)
        and all(type(n) is int and 1 <= n <= 65535 for n in manifest["nodeNumbers"])
        and len(set(manifest["nodeNumbers"])) == len(manifest["nodeNumbers"])
    ):
        raise ValueError("Invalid layout backup manifest")
    return manifest


class LayoutRestoreSelection(QObject):
    def __init__(self, parent, service, manifest_path):
        super().__init__(parent)
        self.service = service
        manifest = load_manifest(manifest_path)
        self.backups = {
            number: load_layout_node(manifest_path, number)
            for number in manifest["nodeNumbers"]
        }
        self.dialog = LayoutRestoreDialog(
            self.backups, parent, presence=dict.fromkeys(self.backups, "Checking…")
        )
        self.dialog.setWindowTitle("Layout Restore — check node eligibility")
        self.active = True
        service.presence_checked.connect(self.checked)
        service.connection.state_changed.connect(self.connection_changed)
        self.dialog.finished.connect(self.dispose)

    def start(self):
        try:
            self.service.check_presence(sorted(self.backups))
        except ValueError:
            self.dispose()
            raise

    def checked(self, number, online, module_type):
        if not self.active or number not in self.backups:
            return
        reasons = []
        state = self.service.node_states.get(number)
        backup = self.backups[number]
        if online:
            if state is None:
                reasons.append("Target identity not discovered")
            else:
                if not state.identity.is_flim:
                    reasons.append("FLiM node required")
                if module_type != state.identity.module_type:
                    reasons.append("Module type changed since discovery")
                count = state.parameters.get(6)
                if count is None:
                    reasons.append("NV count not confirmed")
                elif len(backup["nvs"]) > count or (
                    backup["complete"] and len(backup["nvs"]) != count
                ):
                    reasons.append("NV count mismatch")
                if backup["events"] and not state.identity.is_consumer:
                    reasons.append("Node does not support consumed events")
                capacity = state.parameters.get(5)
                if backup["events"] and capacity is None:
                    reasons.append("EV capacity not confirmed")
                elif capacity is not None and any(
                    len(event["eventVariables"]) > capacity
                    for event in backup["events"]
                ):
                    reasons.append("EV count exceeds node capacity")
        status = "Online" if online else "Offline"
        self.dialog.show_presence(number, status, reasons)
        trace(
            logging.getLogger("workbench.ui"),
            "Layout restore eligibility checked",
            extra={
                "fields": {
                    "layout": self.service.connection.layout_name,
                    "node_number": number,
                    "online": online,
                    "reasons": reasons,
                }
            },
        )

    def connection_changed(self, state):
        if state != "Connected":
            for number in self.backups:
                self.dialog.show_presence(number, "Offline")
            self.dispose()

    def dispose(self, *_args):
        if not self.active:
            return
        self.active = False
        self.service.cancel_presence_checks()
        self.service.presence_checked.disconnect(self.checked)
        self.service.connection.state_changed.disconnect(self.connection_changed)
