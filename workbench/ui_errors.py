"""Report UI operation failures and uncaught Qt callback exceptions."""

import logging
from collections.abc import Callable
from types import TracebackType

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMessageBox, QWidget

logger = logging.getLogger("workbench.errors")


class ErrorReporter(QObject):
    show_requested = Signal(str)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._parent = parent
        # A signal from another thread is queued to this GUI-thread object.
        self.show_requested.connect(self._show_dialog)

    def run(self, description: str, operation: Callable[[], None]) -> None:
        """Run a top-level UI action; report failures instead of re-raising them."""
        try:
            operation()
        except Exception as error:
            logger.exception(description)
            self.show_requested.emit(
                f"{description}\n\n{type(error).__name__}: {error}"
            )

    def handle_unexpected(
        self,
        error_type: type[BaseException],
        error: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        """Handle exceptions PySide6 passes to sys.excepthook from callbacks."""
        logger.error(
            "Unexpected Qt callback failure",
            exc_info=(error_type, error, traceback),
        )
        self.show_requested.emit(
            f"An unexpected error occurred.\n\n{error_type.__name__}: {error}"
        )

    @Slot(str)
    def _show_dialog(self, message: str) -> None:
        QMessageBox.critical(self._parent, "CBUS Workbench error", message)
