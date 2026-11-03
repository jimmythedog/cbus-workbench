"""Saved layouts used by UI tests that exercise Home and Test Layout."""


def sample_settings():
    return {
        "default_layout": "Home",
        "layouts": {
            name: {
                "logical_layout": logical_layout,
                "auto_connect": False,
                "connection": {
                    "type": "TCP/IP",
                    "host": "",
                    "port": 5550,
                    "serial_port": "",
                    "can_id": 126,
                },
            }
            for name, logical_layout in (
                ("Home", "home"),
                ("Test Layout", "test-layout"),
            )
        },
    }
