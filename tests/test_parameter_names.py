"""Names for confirmed standard CBUS parameter codes."""

import unittest

from workbench.parameter_names import cpu_name, module_name, transport_name


class ParameterNameTests(unittest.TestCase):
    def test_static_module_names_override_descriptor_names(self):
        for module_type, expected in (
            (1, "CANACC4"),
            (8, "CANSOL"),
            (34, "CANSOL"),
            (36, "CANCDU"),
            (75, "CANGATE"),
            (90, "CANGATEXL"),
            (252, "CANDEV"),
            (254, "EMPTY"),
        ):
            with self.subTest(module_type=module_type):
                self.assertEqual(module_name(165, module_type), expected)
                self.assertEqual(
                    module_name(165, module_type, "Different MDF name"), expected
                )

    def test_unknown_module_names_use_descriptor_or_numeric_fallback(self):
        self.assertEqual(module_name(165, 251, "New module"), "New module")
        self.assertEqual(module_name(250, 36, "VLCB module"), "VLCB module")
        for descriptor in (None, "", "   "):
            with self.subTest(descriptor=descriptor):
                self.assertEqual(module_name(165, 251, descriptor), "251")
                self.assertEqual(module_name(250, 36, descriptor), "36")
        self.assertEqual(module_name(None, 36), "36")
        self.assertEqual(module_name(165, None), "-")

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
