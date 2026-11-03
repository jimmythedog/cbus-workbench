"""Names for confirmed standard CBUS parameter codes."""

import unittest

from workbench.parameter_names import cpu_name, transport_name


class ParameterNameTests(unittest.TestCase):
    def test_defined_and_unknown_transport_codes(self):
        self.assertEqual(transport_name(1), "CAN")
        self.assertEqual(transport_name(2), "Ethernet")
        self.assertEqual(transport_name(3), "MiWi")
        self.assertEqual(transport_name(4), "USB")
        self.assertIsNone(transport_name(0))
        self.assertIsNone(transport_name(5))
        self.assertIsNone(transport_name(None))

    def test_cpu_requires_matching_manufacturer_and_type(self):
        self.assertEqual(cpu_name(1, 13), "P18F25K80")
        self.assertEqual(cpu_name(3, 1), "ARM1176JZF_S")
        self.assertIsNone(cpu_name(None, 13))
        self.assertIsNone(cpu_name(1, None))
        self.assertIsNone(cpu_name(2, 13))
        self.assertIsNone(cpu_name(3, 13))
        self.assertIsNone(cpu_name(1, 24))
        self.assertIsNone(cpu_name(0, 0))


if __name__ == "__main__":
    unittest.main()
