from __future__ import annotations

import unittest

from ASR.cli import hyprland_block, replace_hyprland_block


class HyprlandBlockTests(unittest.TestCase):
    def test_tap_mode(self) -> None:
        block = hyprland_block(False)
        self.assertIn("exec-once", block)
        self.assertIn("dictate toggle", block)
        self.assertIn("dictate paste-last", block)
        self.assertIn("dictate cancel", block)
        self.assertNotIn("bindr", block)
        self.assertIn("# >>> speech-flow >>>", block)
        self.assertIn("# <<< speech-flow <<<", block)

    def test_hold_mode(self) -> None:
        block = hyprland_block(True)
        self.assertIn("dictate start", block)
        self.assertIn("dictate stop", block)
        self.assertIn("bindr", block)

    def test_no_enter_key(self) -> None:
        self.assertNotIn("Return", hyprland_block(False))
        self.assertNotIn("Enter", hyprland_block(False))

    def test_replaces_existing_block(self) -> None:
        block = hyprland_block(False)
        current = f"monitor=,preferred,auto,1\n\n{block}\n"
        updated = replace_hyprland_block(current, block)
        self.assertEqual(updated.count("exec-once"), 1)
        self.assertIn("monitor=,preferred,auto,1", updated)

    def test_migrates_legacy_block(self) -> None:
        block = hyprland_block(False, assistant=True)
        current = (
            "monitor=,preferred,auto,1\n\n"
            "# >>> dictate-unlimited >>>\n"
            "exec-once = old dictate\n"
            "# <<< dictate-unlimited <<<\n"
        )
        updated = replace_hyprland_block(current, block)
        self.assertNotIn("dictate-unlimited", updated)
        self.assertNotIn("old dictate", updated)
        self.assertEqual(updated.count("exec-once"), 1)
        self.assertIn("assistant toggle", updated)


if __name__ == "__main__":
    unittest.main()
