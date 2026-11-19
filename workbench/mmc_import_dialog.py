"""Choose MMC layouts and preview their annotation changes before saving."""

import logging
from pathlib import Path

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .app_settings import layout_settings_for_storage, layout_settings_for_ui
from .layout_settings import collect_layout_settings
from .logging_config import trace
from .mmc_import import plan_import, save_import
from .mmc_layouts import find_mmc_layouts, mmc_layouts_directory

logger = logging.getLogger("workbench.mmc_import")


class MmcImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import MMC layouts")
        self.resize(950, 500)
        self.sources = []
        self.result_plan = None
        self.directory = mmc_layouts_directory()
        layout = QVBoxLayout(self)
        introduction = QLabel(
            "Choose an MMC layouts directory, one layout directory, or layoutData.json.\n"
            "A matching CW name uses that layout; a new name creates a layout. No hardware changes."
        )
        introduction.setWordWrap(True)
        layout.addWidget(introduction)
        browse = QHBoxLayout()
        for title, slot in (
            ("Browse directory…", self.browse_directory),
            ("Browse file…", self.browse_file),
        ):
            button = QPushButton(title)
            button.clicked.connect(slot)
            browse.addWidget(button)
        browse.addStretch()
        layout.addLayout(browse)
        self.table = QTableWidget(0, 3)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalHeaderLabels(
            [
                "MMC layout",
                "CW layout name",
                "Annotation changes",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.itemChanged.connect(self.update_preview)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.currentCellChanged.connect(self.update_details)
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel("Selected layout details"))
        # A standard read-only text area wraps at any width and scrolls when
        # skipped categories need more space than this compact preview allows.
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        line_height = self.details.fontMetrics().lineSpacing()
        self.details.setMinimumHeight(line_height * 5 + 12)
        self.details.setMaximumHeight(line_height * 8 + 12)
        layout.addWidget(self.details)
        self.overwrite = QCheckBox("Overwrite existing annotations")
        self.overwrite.toggled.connect(self.update_preview)
        layout.addWidget(self.overwrite)
        self.summary = QLabel("No layouts selected")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.import_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_button.setText("Import")
        self.import_button.setEnabled(False)
        self.buttons.accepted.connect(self.import_layouts)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def browse_directory(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "MMC layouts directory", str(self.directory)
        )
        if chosen:
            self.load_source(Path(chosen))

    def browse_file(self):
        chosen, _ = QFileDialog.getOpenFileName(
            self, "MMC layout file", str(self.directory), "MMC layout (layoutData.json)"
        )
        if chosen:
            self.load_source(Path(chosen))

    def load_source(self, source: Path):
        """Keep the current preview intact if a newly selected source is invalid."""
        try:
            sources = find_mmc_layouts(source)
        except (OSError, ValueError, TypeError) as error:
            logger.exception("Cannot preview MMC source=%s", source)
            QMessageBox.warning(self, "Cannot read MMC layouts", str(error))
            return
        self.sources = sources
        self.directory = source.parent if source.is_file() else source
        self.table.blockSignals(True)
        self.table.setRowCount(len(sources))
        for row, item in enumerate(sources):
            label = QTableWidgetItem(item.title)
            label.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            label.setCheckState(Qt.CheckState.Checked)
            label.setToolTip(str(item.path))
            self.table.setItem(row, 0, label)
            self.table.setItem(row, 1, QTableWidgetItem(item.title))
            cell = QTableWidgetItem()
            cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 2, cell)
        self.table.blockSignals(False)
        self.table.setCurrentCell(0, 0)
        self.update_preview()

    def selections(self):
        return [
            (source, self.table.item(row, 1).text())
            for row, source in enumerate(self.sources)
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]

    def update_preview(self):
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                self.table.item(row, 2).setText("")
            plan = plan_import(self.selections(), self.overwrite.isChecked())
            for target in plan.targets:
                row = self.sources.index(target.source)
                counts = target.counts
                self.table.item(row, 2).setText(
                    f"{counts['added']} added, {counts['replaced']} replaced, {counts['preserved']} preserved"
                )
                self.table.item(row, 2).setToolTip(self.table.item(row, 2).text())
            self.summary.setText(
                "Preview only. Named event identities join the catalogue regardless of overwrite. Blank annotations never erase saved values. Imported nodes remain offline until discovered."
            )
            self.import_button.setEnabled(True)
        except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
            logger.exception("Cannot prepare MMC import preview")
            self.summary.setText(str(error))
            self.import_button.setEnabled(False)
        finally:
            self.table.blockSignals(False)
            self.update_details()

    def update_details(self):
        row = self.table.currentRow()
        if row < 0:
            self.details.clear()
            return
        source = self.sources[row]
        try:
            # Include unchecked rows: selection previews a row, its checkbox
            # independently controls whether it will be imported.
            plan = plan_import(
                [(source, self.table.item(row, 1).text())], self.overwrite.isChecked()
            )
            target = plan.targets[0]
            connection = plan.settings["layouts"][target.name]["connection"]
            if connection["type"] == "Serial":
                endpoint = f"Serial — device: {connection['serial_port']}"
            elif connection["type"] == "Simulator":
                endpoint = "Simulator"
            else:
                endpoint = f"TCP/IP — host: {connection['host'] or '(not set)'}; port: {connection['port']}"
            note = (
                source.connection_note
                if target.new
                else "Existing connection settings retained."
            )
            self.details.setPlainText(
                f"Destination: {'New' if target.new else 'Existing'} CW layout — {target.name}\n"
                f"Imported nodes: {len(source.nodes)}\n"
                f"Connection: {endpoint}; CAN ID: {connection['can_id']}. {note}\n"
                f"Skipped data: {', '.join(source.skipped) or 'None'}"
            )
        except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
            self.details.setPlainText(str(error))

    def import_layouts(self):
        try:
            # Re-read destinations at confirmation; do not overwrite edits made since preview.
            plan = plan_import(self.selections(), self.overwrite.isChecked())
            layouts = layout_settings_for_ui(
                {
                    name: saved
                    for name, saved in plan.settings["layouts"].items()
                    if saved["logical_layout"]
                }
            )
            selections = []
            reviewed = {}
            for target in plan.targets:
                name = target.name
                initial = layout_settings_for_ui(
                    {name: plan.settings["layouts"][name]}
                )[name]
                settings = collect_layout_settings(
                    self,
                    layouts,
                    initial,
                    allow_auto_connect=False,
                    allow_existing=True,
                )
                if settings is None:
                    trace(logger, "MMC import cancelled during layout review")
                    return
                name = settings["name"]
                layouts[name] = settings
                reviewed.update(layout_settings_for_storage({name: settings}))
                selections.append((target.source, name))
            # All reviews finish before any file is saved; cancellation is side-effect free.
            plan = plan_import(selections, self.overwrite.isChecked(), reviewed)
            save_import(plan)
        except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
            logger.exception("Cannot import MMC layouts")
            QMessageBox.warning(self, "MMC import failed", str(error))
            self.update_preview()
            return
        self.result_plan = plan
        self.accept()
