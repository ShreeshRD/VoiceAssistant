from __future__ import annotations

import unittest

from dictate_unlimited.cli import hyprland_block


class HyprlandBlockTests(unittest.TestCase):
    def test_tap_mode(self) -> None:
        block = hyprland_block(False)
        self.assertIn("exec-once", block)
        self.assertIn("dictate toggle", block)
        self.assertIn("dictate paste-last", block)
        self.assertIn("dictate cancel", block)
        self.assertNotIn("bindr", block)

    def test_hold_mode(self) -> None:
        block = hyprland_block(True)
        self.assertIn("dictate start", block)
        self.assertIn("dictate stop", block)
        self.assertIn("bindr", block)

    def test_no_enter_key(self) -> None:
        self.assertNotIn("Return", hyprland_block(False))
        self.assertNotIn("Enter", hyprland_block(False))


if __name__ == "__main__":
    unittest.main()
