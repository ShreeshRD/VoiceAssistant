from __future__ import annotations

import unittest
from unittest import mock

from ASR import config as config_module
from ASR import insertion


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

    def test_trailing_space_after_sentence_end(self) -> None:
        config = config_module.Config(insertion="wtype")
        for text in ("Done.", "Really?", "Stop!", "Wait…", "He said “hi.”"):
            with self.subTest(text=text):
                with mock.patch.object(insertion, "type_text") as type_text:
                    result = insertion.deliver(text, config)
                    type_text.assert_called_once_with(text + " ")
                self.assertTrue(result.ok)

    def test_trailing_space_not_added_to_unfinished_text(self) -> None:
        config = config_module.Config(insertion="wtype")
        for text in ("hello", "a comma,", "semi;", "colon:"):
            with self.subTest(text=text):
                with mock.patch.object(insertion, "type_text") as type_text:
                    insertion.deliver(text, config)
                    type_text.assert_called_once_with(text)

    def test_trailing_space_can_be_disabled(self) -> None:
        config = config_module.Config(insertion="wtype", trailing_space=False)
        with mock.patch.object(insertion, "type_text") as type_text:
            insertion.deliver("Done.", config)
            type_text.assert_called_once_with("Done.")

    def test_trailing_space_reaches_clipboard(self) -> None:
        config = config_module.Config(insertion="copy")
        with mock.patch.object(insertion, "write_clipboard") as write:
            insertion.deliver("Done.", config)
            write.assert_called_once_with("Done. ")

    def test_sanitize_keeps_trailing_space(self) -> None:
        self.assertEqual(insertion.sanitize_for_typing("hello "), "hello ")
        self.assertEqual(insertion.sanitize_for_typing("hello"), "hello")

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
