"""Wait for on-demand configuration reads before a layout-wide operation."""

import logging

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import QApplication

from .cbus_service import CbusService, DiscoveryStatus
from .logging_config import trace

logger = logging.getLogger("workbench.ui")


def load_online_configuration(
    parent, service: CbusService, *, consumers_only: bool = False
) -> bool:
    """Read online nodes never loaded, then return; False if the connection ended.

    Connecting reads only parameters, but layout backups, comparisons and Teach
    need whole nodes. A local event loop keeps replies flowing while the window
    is disabled, as Layout Restore does. Failed reads are left to the caller's
    existing incomplete handling.
    """
    started = service.load_online_configuration(consumers_only=consumers_only)
    if not started:
        return True
    fields = {"layout": service.connection.layout_name, "nodes": started}
    trace(logger, "Waiting for node configuration", extra={"fields": fields})
    loop = QEventLoop()

    def settled(status):
        if status != DiscoveryStatus.DISCOVERING:
            loop.quit()

    window = parent.window()
    was_enabled = window.isEnabled()
    service.discovery_status_changed.connect(settled)
    window.setEnabled(False)
    # Qt shows no widget cursor over a disabled window.
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        if service.discovery_status == DiscoveryStatus.DISCOVERING:
            loop.exec()
    finally:
        QApplication.restoreOverrideCursor()
        window.setEnabled(was_enabled)
        service.discovery_status_changed.disconnect(settled)
    connected = not service._closed and service.connection.state == "Connected"
    trace(
        logger,
        "Node configuration wait finished",
        extra={
            "fields": {
                **fields,
                "status": service.discovery_status,
                "connected": connected,
            }
        },
    )
    return connected
