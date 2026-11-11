"""MDF text substitution follows issue 0.15 §§12–13, including legacy MDFs."""

import unittest

from workbench.mdf_tokens import (
    normalise_overrides,
    normalise_token,
    substitute_tokens,
    token_defaults,
)


class MdfTokenTests(unittest.TestCase):
    def test_identifiers_and_user_values_share_normalisation(self):
        self.assertEqual(normalise_token("palette 1"), normalise_token("palette1"))
        self.assertEqual(normalise_token("CHANNEL 2"), ("channel", "2"))
        self.assertNotEqual(normalise_token("Palette1"), normalise_token("palette1"))
        self.assertEqual(
            normalise_overrides(
                {"CHANNEL ": {"02": " Turnout "}, "palette": {"1": ""}}
            ),
            {"channel": {"2": "Turnout"}},
        )

    def test_new_defaults_legacy_defaults_and_literal_user_replacements(self):
        # Representative defaults and spaced/unspaced references from CANARGB,
        # CAN4IN4OUT and MMCTEST. Definitions remain owned by the descriptor.
        data = {
            "tokens": {
                "palette": {"defaultNames": {"1": "0 : Black / off"}},
                "channel": {"defaultNames": {"1": "New default"}},
            },
            "channelNames": {"1": "Switch 1", "2": "LED 1"},
            "numberOfChannels": 2,
            "nodeVariables": [{"displayTitle": "Palette entry ${palette 1}"}],
            "eventVariables": [
                {
                    "options": [
                        {"label": "${palette1}"},
                        {"label": "${CHANNEL 2}"},
                        {"label": "${wormholes7}"},
                    ]
                }
            ],
        }
        defaults = token_defaults(data)
        self.assertEqual(defaults[("channel", "1")], "New default")
        resolved = substitute_tokens(data, {"palette": {"1": "Signal ${channel2}"}})
        self.assertEqual(
            resolved["nodeVariables"][0]["displayTitle"],
            "Palette entry Signal ${channel2}",
        )
        self.assertEqual(
            [o["label"] for o in resolved["eventVariables"][0]["options"]],
            ["Signal ${channel2}", "LED 1", "wormholes7"],
        )
        self.assertEqual(
            substitute_tokens(data, {})["eventVariables"][0]["options"][0]["label"],
            "0 : Black / off",
        )
        self.assertEqual(
            data["nodeVariables"][0]["displayTitle"], "Palette entry ${palette 1}"
        )

    def test_legacy_count_and_highest_channel_default_are_editable(self):
        self.assertEqual(
            list(
                token_defaults({"numberOfChannels": 2, "channelNames": {"3": "Output"}})
            ),
            [("channel", "1"), ("channel", "2"), ("channel", "3")],
        )
