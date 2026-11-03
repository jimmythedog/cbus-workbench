import logging
import sys

from PySide6.QtWidgets import QApplication

from workbench.app_settings import APP_NAME
from workbench.logging_config import configure_logging, trace
from workbench.window import MainWindow


def main():
    log_path = configure_logging()
    logger = logging.getLogger("workbench.app")
    logger.info("Application starting", extra={"fields": {"log_file": str(log_path)}})
    trace(logger, "Constructing Qt application and main window")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    window = MainWindow()
    previous_excepthook = sys.excepthook
    sys.excepthook = window.error_reporter.handle_unexpected

    try:
        window.show()
        logger.debug("Main window shown")
        exit_code = app.exec()
    finally:
        sys.excepthook = previous_excepthook
    logger.info("Application shut down", extra={"fields": {"exit_code": exit_code}})
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
