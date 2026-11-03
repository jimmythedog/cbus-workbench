"""Observable YAML settings storage and validation."""

import tempfile
import unittest
from pathlib import Path

import yaml
from PySide6.QtCore import QCoreApplication, QStandardPaths

from workbench.app_settings import (
    SettingsError,
    load_settings,
    save_settings,
    settings_path,
)


class AppSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "data" / "settings.yaml"

    def test_path_uses_qt_application_data_location(self):
        previous_name = QCoreApplication.applicationName()
        self.addCleanup(QCoreApplication.setApplicationName, previous_name)
        QCoreApplication.setApplicationName("Settings Path Test")

        path = settings_path()
        self.assertEqual(QCoreApplication.applicationName(), "Settings Path Test")
        self.assertEqual(
            path,
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppDataLocation
                )
            )
            / "settings.yaml",
        )

    def test_missing_file_loads_empty_configuration(self):
        self.assertEqual(
            load_settings(self.path), {"default_layout": None, "layouts": {}}
        )
        self.assertFalse(self.path.exists())

    def test_tcp_and_serial_settings_round_trip_with_layout_names_as_keys(self):
        settings = {
            "default_layout": "Home",
            "layouts": {
                "Home": {
                    "logical_layout": "track-plan",
                    "auto_connect": True,
                    "connection": {
                        "type": "TCP/IP",
                        "host": "localhost",
                        "port": 5550,
                        "serial_port": "",
                    },
                },
                "Workshop": {
                    "logical_layout": "workshop",
                    "auto_connect": False,
                    "connection": {
                        "type": "Serial",
                        "host": "",
                        "port": 5550,
                        "serial_port": "/dev/ttyACM1",
                    },
                },
            },
        }

        save_settings(settings, self.path)

        self.assertEqual(load_settings(self.path), settings)
        self.assertEqual(yaml.safe_load(self.path.read_text()), settings)
        self.assertEqual(set(load_settings(self.path)["layouts"]), {"Home", "Workshop"})

        settings["layouts"]["Home"]["connection"]["host"] = "new-host"
        save_settings(settings, self.path)
        self.assertEqual(load_settings(self.path), settings)

    def test_empty_layout_collection_saves_with_null_default(self):
        settings = {"default_layout": None, "layouts": {}}

        save_settings(settings, self.path)

        self.assertEqual(load_settings(self.path), settings)
        self.assertIsNone(yaml.safe_load(self.path.read_text())["default_layout"])

    def test_stale_default_recovers_to_first_layout_without_rewriting_file(self):
        self.path.parent.mkdir(parents=True)
        content = (
            "default_layout: Old Name\n"
            "layouts:\n"
            "  Home:\n"
            "    logical_layout: home\n"
            "    connection:\n"
            "      type: TCP/IP\n"
            "      host: ''\n"
            "      port: 5550\n"
            "      serial_port: ''\n"
            "  Workshop:\n"
            "    logical_layout: workshop\n"
            "    connection:\n"
            "      type: Serial\n"
            "      host: ''\n"
            "      port: 5550\n"
            "      serial_port: /dev/ttyACM1\n"
        )
        self.path.write_text(content)

        with self.assertLogs("workbench.settings", level="WARNING") as captured:
            settings = load_settings(self.path)

        self.assertIn("Old Name", captured.output[0])
        self.assertEqual(settings["default_layout"], "Home")
        self.assertFalse(settings["layouts"]["Home"]["auto_connect"])
        self.assertEqual(self.path.read_text(), content)

        save_settings(settings, self.path)
        self.assertEqual(
            yaml.safe_load(self.path.read_text())["default_layout"], "Home"
        )

    def test_stale_default_with_no_layouts_recovers_to_none(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("default_layout: Missing\nlayouts: {}\n")

        with self.assertLogs("workbench.settings", level="WARNING") as captured:
            settings = load_settings(self.path)

        self.assertIn("Missing", captured.output[0])
        self.assertEqual(settings, {"default_layout": None, "layouts": {}})
        self.assertIn("default_layout: Missing", self.path.read_text())

    def test_invalid_yaml_is_reported_and_not_overwritten(self):
        self.path.parent.mkdir(parents=True)
        invalid = "layouts: [unfinished\n"
        self.path.write_text(invalid)

        with self.assertLogs("workbench.settings", level="ERROR"):
            with self.assertRaisesRegex(
                SettingsError, "Invalid settings.*settings.yaml"
            ):
                load_settings(self.path)
            with self.assertRaises(SettingsError):
                save_settings({"default_layout": None, "layouts": {}}, self.path)

        self.assertEqual(self.path.read_text(), invalid)

    def test_invalid_layout_settings_are_reported_and_not_overwritten(self):
        self.path.parent.mkdir(parents=True)
        invalid = "default_layout: Home\nlayouts:\n  Home:\n    auto_connect: yes\n"
        self.path.write_text(invalid)

        with self.assertLogs("workbench.settings", level="ERROR"):
            with self.assertRaisesRegex(SettingsError, "logical_layout"):
                load_settings(self.path)
            with self.assertRaises(SettingsError):
                save_settings({"default_layout": None, "layouts": {}}, self.path)

        self.assertEqual(self.path.read_text(), invalid)

    def test_invalid_settings_cannot_be_saved(self):
        with (
            self.assertLogs("workbench.settings", level="ERROR"),
            self.assertRaisesRegex(SettingsError, "default_layout must name"),
        ):
            save_settings({"default_layout": "Home", "layouts": {}}, self.path)

        self.assertFalse(self.path.exists())

    def test_save_rejects_default_that_is_not_a_layout(self):
        settings = {
            "default_layout": None,
            "layouts": {
                "Home": {
                    "logical_layout": "home",
                    "connection": {
                        "type": "TCP/IP",
                        "host": "",
                        "port": 5550,
                        "serial_port": "",
                    },
                }
            },
        }
        for default in (None, "Missing"):
            with self.subTest(default=default):
                settings["default_layout"] = default
                with (
                    self.assertLogs("workbench.settings", level="ERROR"),
                    self.assertRaisesRegex(SettingsError, "default_layout must name"),
                ):
                    save_settings(settings, self.path)
                self.assertFalse(self.path.exists())

    def test_invalid_logical_layout_directory_names_are_rejected(self):
        settings = {
            "default_layout": "Home",
            "layouts": {
                "Home": {
                    "logical_layout": "home",
                    "connection": {
                        "type": "TCP/IP",
                        "host": "",
                        "port": 5550,
                        "serial_port": "",
                    },
                }
            },
        }
        for name in ("", "  ", ".", "..", "a/b", "a\\b"):
            with self.subTest(name=name):
                settings["layouts"]["Home"]["logical_layout"] = name
                with (
                    self.assertLogs("workbench.settings", level="ERROR"),
                    self.assertRaisesRegex(SettingsError, "logical_layout"),
                ):
                    save_settings(settings, self.path)
                self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
