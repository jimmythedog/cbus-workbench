"""Show the directories Qt resolves for this application."""

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .paths import application_directories

logger = logging.getLogger("workbench.paths")


class ApplicationDirectoriesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application Directories")
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        for row, (name, path) in enumerate(application_directories().items()):
            field = QLineEdit(str(path))
            field.setReadOnly(True)
            copy = QPushButton("Copy Path")
            copy.clicked.connect(
                lambda checked=False, p=path: QGuiApplication.clipboard().setText(
                    str(p)
                )
            )
            open_folder = QPushButton("Open Folder")
            open_folder.clicked.connect(
                lambda checked=False, p=path: self.open_folder(p)
            )
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(field, row, 1)
            grid.addWidget(copy, row, 2)
            grid.addWidget(open_folder, row, 3)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(800, self.sizeHint().height())

    def open_folder(self, path):
        if not path.is_dir():
            QMessageBox.information(
                self, "Open Folder", f"The folder does not exist yet:\n{path}"
            )
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            logger.warning("Could not open application directory: %s", path)
            QMessageBox.warning(
                self, "Open Folder", f"Could not open the folder:\n{path}"
            )
