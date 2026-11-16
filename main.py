import logging
import sys

from PySide6.QtWidgets import QApplication

from workbench.app_settings import saved_log_level
from workbench.logging_config import configure_logging, trace
from workbench.paths import APP_NAME, DISPLAY_NAME


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(DISPLAY_NAME)
    # Wayland shells match windows to cbus-workbench.desktop (and its icon) by this name.
    app.setDesktopFileName(APP_NAME)
    # Read before configuring logging so startup records use the saved level.
    log_path = configure_logging(saved_log_level())
    logger = logging.getLogger("workbench.app")
    logger.info("Application starting", extra={"fields": {"log_file": str(log_path)}})
    try:
        from workbench.response_timeout import RESPONSE_TIMEOUT_MS
    except ValueError as error:
        logger.exception("Invalid CBUS response timeout configuration")
        sys.exit(str(error))
    logger.info("CBUS response timeout: %s ms", RESPONSE_TIMEOUT_MS)
    from workbench.window import MainWindow

    trace(logger, "Constructing Qt application and main window")
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
