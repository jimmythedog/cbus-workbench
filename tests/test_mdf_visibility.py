"""Visibility contracts from the MMC MDF inventory, without Qt or MDF loading."""

import unittest

from workbench.mdf_visibility import MdfVisibilityError, evaluate_visibility


class MdfVisibilityTests(unittest.TestCase):
    def test_simple_byte_and_bit_conditions(self):
        cases = [
            ({"nv": 16, "equals": 2}, {16: 2}, {}, True),
            ({"nv": 16, "equals": 2}, {16: 3}, {}, False),
            ({"nv": 16, "equals": 0}, {}, {}, None),
            ({"nv": 16, "equals": 0}, {16: None}, {}, None),
            ({"ev": 1, "equals": 1}, {1: 1}, {1: 0}, False),
            ({"ev": 1, "equals": 1}, {}, {1: 1}, True),
            ({"ev": 1, "equals": 0}, {1: 0}, {}, None),
            ({"nvBit": {"index": 2, "bit": 7}, "equals": 1}, {2: 128}, {}, True),
            ({"nvBit": {"index": 2, "bit": 7}, "equals": 1}, {2: 1}, {}, False),
            ({"evBit": {"index": 3, "bit": 7}, "equals": 0}, {}, {3: 0}, True),
            ({"evBit": {"index": 3, "bit": 7}, "equals": 0}, {3: 0}, {}, None),
        ]
        for condition, nvs, evs, expected in cases:
            with self.subTest(condition=condition, nvs=nvs, evs=evs):
                self.assertIs(evaluate_visibility(condition, nvs, evs), expected)

    def test_inventory_jll_expressions(self):
        # CANLEVER-A550-1a: mode selection and membership in channel actions.
        lever = {
            "and": [
                {"!=": [{"NV": 19}, 2]},
                {"in": [{"NV": 72}, [2, 18, 34, 50, 66, 82, 98, 114]]},
            ]
        }
        # CANACC5-A502-2V: group visibility from the current event's bits.
        accessory = {
            "or": [
                {"==": [{"EVbit": [3, 0]}, False]},
                {"==": [{"EVbit": [3, 1]}, False]},
            ]
        }
        # CANPAN-A51D-5a: EV2 must lie in 1..32.
        panel = {"and": [{">": [{"EV": 2}, 0]}, {"<=": [{"EV": 2}, 32]}]}
        cases = [
            (lever, {19: 1, 72: 18}, {}, True),
            (lever, {19: 2, 72: 18}, {}, False),
            (lever, {19: 1, 72: 3}, {}, False),
            (lever, {19: 1}, {}, None),
            (accessory, {}, {3: 1}, True),
            (accessory, {}, {3: 3}, False),
            (accessory, {3: 0}, {}, None),
            (panel, {}, {2: 1}, True),
            (panel, {}, {2: 32}, True),
            (panel, {}, {2: 0}, False),
            (panel, {}, {2: 33}, False),
            (panel, {}, {}, None),
            ({"==": [{"NVbit": [17, 0]}, True]}, {17: 1}, {}, True),
            ({"==": [{"NV": 19}, 2]}, {19: 2}, {}, True),
            ({"!=": [{"EV": 1}, 0]}, {}, {}, None),
        ]
        for expression, nvs, evs, expected in cases:
            with self.subTest(expression=expression, nvs=nvs, evs=evs):
                self.assertIs(
                    evaluate_visibility({"JLL": expression}, nvs, evs), expected
                )

    def test_three_valued_nested_combinations(self):
        for operator in ("and", "or"):
            for left in (True, False, None):
                for right in (True, False, None):
                    values = {
                        index: int(value)
                        for index, value in ((1, left), (2, right))
                        if value is not None
                    }
                    children = [{"==": [{"NV": index}, 1]} for index in (1, 2)]
                    # Nest a conjunction to verify propagation through multiple levels.
                    expression = {
                        operator: [children[0], {"and": [children[1], {"==": [1, 1]}]}]
                    }
                    if operator == "and":
                        expected = (
                            False
                            if left is False or right is False
                            else None
                            if left is None or right is None
                            else True
                        )
                    else:
                        expected = (
                            True
                            if left is True or right is True
                            else None
                            if left is None or right is None
                            else False
                        )
                    with self.subTest(operator=operator, left=left, right=right):
                        self.assertIs(
                            evaluate_visibility({"JLL": expression}, values, {}),
                            expected,
                        )

    def test_redundant_or_is_evaluated_as_written(self):
        # CANPAN-A51D-1y uses OR here, not the range AND used by 5a.
        expression = {"JLL": {"or": [{">": [{"EV": 2}, 0]}, {"<=": [{"EV": 2}, 32]}]}}
        for value, expected in ((0, True), (33, True), (255, True), (None, None)):
            with self.subTest(value=value):
                self.assertIs(evaluate_visibility(expression, {}, {2: value}), expected)

    def test_invalid_syntax_is_an_error_even_with_unread_or_decisive_values(self):
        conditions = [
            None,
            {},
            {"slot": True, "lessThan": 4},
            {"nv": 0, "equals": 1},
            {"ev": True, "equals": 1},
            {"nv": 1, "equals": True},
            {"nv": 1, "equals": 256},
            {"nv": 1, "equals": 0, "extra": 1},
            {"nvBit": {"index": 1, "bit": 8}, "equals": 0},
            {"evBit": {"index": 1}, "equals": 0},
            {"evBit": {"index": 1, "bit": 0}, "equals": 2},
        ]
        invalid_jll = [
            {},
            {"not": [True]},
            {"and": []},
            {"or": {}},
            {"==": [{"NV": 1}]},
            {"==": [{"NV": 1}, 0], "!=": [1, 2]},
            {"==": [{"NVbit": [1, -1]}, False]},
            {"==": [{"EVbit": [1]}, False]},
            {"==": [{"EV": 256}, 0]},
            {"==": [{"var": "NV1"}, 0]},
            {"in": [{"NV": 1}, "not a list"]},
            {"in": [{"NV": 1}, [{"NV": 2}]]},
            {"<=": [{"NV": 1}, "32"]},
            {"and": [{"==": [0, 1]}, {"unsupported": []}]},
            {"or": [{"==": [1, 1]}, {"unsupported": []}]},
        ]
        conditions.extend({"JLL": expression} for expression in invalid_jll)
        for condition in conditions:
            with (
                self.subTest(condition=condition),
                self.assertRaises(MdfVisibilityError),
            ):
                evaluate_visibility(condition, {}, {})
        for value in (-1, 256, "1", True):
            with (
                self.subTest(invalid_byte=value),
                self.assertRaises(MdfVisibilityError),
            ):
                evaluate_visibility({"nv": 1, "equals": 1}, {1: value}, {})


if __name__ == "__main__":
    unittest.main()
