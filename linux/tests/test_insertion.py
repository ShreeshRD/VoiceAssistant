from __future__ import annotations

import unittest
from unittest import mock

from dictate_unlimited import config as config_module
from dictate_unlimited import insertion


class DeliveryTests(unittest.TestCase):
    def test_empty_text_is_rejected(self) -> None:
        result = insertion.deliver("   ", config_module.Config())
        self.assertFalse(result.ok)

    def test_wtype_success(self) -> None:
        config = config_module.Config(insertion="wtype")
        with mock.patch.object(insertion, "type_text") as type_text:
            result = insertion.deliver("hello", config)
            type_text.assert_called_once_with("hello")
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "wtype")

    def test_no_tools(self) -> None:
        config = config_module.Config(insertion="auto")
        with mock.patch.object(insertion, "have", return_value=False):
            result = insertion.deliver("hello", config)
        self.assertFalse(result.ok)

    def test_clipboard_copy_only(self) -> None:
        config = config_module.Config(insertion="copy")
        with mock.patch.object(insertion, "write_clipboard") as write:
            result = insertion.deliver("hello", config)
            write.assert_called_once_with("hello")
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "copy")


if __name__ == "__main__":
    unittest.main()
