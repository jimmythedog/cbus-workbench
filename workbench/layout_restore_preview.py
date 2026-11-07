"""UI review only: python -m workbench.layout_restore_preview (no hardware access)."""

from PySide6.QtWidgets import QApplication

from .layout_restore_dialog import LayoutRestoreDialog


def main():
    app = QApplication.instance() or QApplication([])
    presence = {
        256: "Online",
        258: "Online",
        259: "Offline",
        261: "Checking",
        262: "Checking…",
    }
    dialog = LayoutRestoreDialog(presence, presence=presence)
    dialog.show_presence(262, "Incompatible", ["NV count mismatch"])
    dialog.exec()
    # Keep QApplication alive until the dialog has closed.
    return app


if __name__ == "__main__":
    main()
