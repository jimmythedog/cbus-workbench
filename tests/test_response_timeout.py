"""Configuration contract for the temporary hardware response timeout."""

import os
import unittest
from unittest.mock import patch

from workbench.response_timeout import read_response_timeout_ms


class ResponseTimeoutTests(unittest.TestCase):
    def test_unset_uses_existing_two_second_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(read_response_timeout_ms(), 2000)

    def test_positive_millisecond_override(self):
        with patch.dict(os.environ, CBUS_WORKBENCH_RESPONSE_TIMEOUT_MS="4500"):
            self.assertEqual(read_response_timeout_ms(), 4500)

    def test_invalid_setting_identifies_variable_and_requirement(self):
        for value in ("", "0", "-1", "1.5", "slow", "2147483648"):
            with (
                self.subTest(value=value),
                patch.dict(os.environ, CBUS_WORKBENCH_RESPONSE_TIMEOUT_MS=value),
                self.assertRaisesRegex(
                    ValueError,
                    "CBUS_WORKBENCH_RESPONSE_TIMEOUT_MS must be a positive integer",
                ),
            ):
                read_response_timeout_ms()
