"""Initial sizing shared by the small contextual annotation dialogs."""

from PySide6.QtWidgets import QDialog, QLayout


def size_annotation_dialog(dialog: QDialog) -> None:
    """Open at least 450 pixels wide, with normal user resizing retained."""
    # SetMinimumSize would overwrite the explicit width when the dialog opens.
    dialog.layout().setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
    dialog.ensurePolished()
    dialog.layout().activate()
    dialog.adjustSize()
    dialog.setMinimumWidth(max(450, dialog.minimumWidth()))
    dialog.resize(max(dialog.width(), dialog.minimumWidth()), dialog.height())
