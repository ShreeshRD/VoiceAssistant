from __future__ import annotations

import unittest

from dictate_unlimited.asr import parse_transcript


class ParseTranscriptTests(unittest.TestCase):
    def test_plain_text(self) -> None:
        self.assertEqual(parse_transcript(" hello world\n"), "hello world")

    def test_blank_marker_is_dropped(self) -> None:
        self.assertEqual(parse_transcript("[BLANK_AUDIO]\nhello\nworld\n"), "hello world")
        self.assertEqual(parse_transcript("[BLANK]\nhello\n"), "hello")

    def test_timestamps_are_removed(self) -> None:
        output = "[00:00:00.000 --> 00:00:02.000]   Hello there.\n[00:00:02.000 --> 00:00:04.000]   General Kenobi.\n"
        self.assertEqual(parse_transcript(output), "Hello there. General Kenobi.")

    def test_ansi_and_non_speech(self) -> None:
        output = "\x1b[32m[MUSIC]\x1b[0m\n(silence)\n[NO SPEECH]\nactual words\n"
        self.assertEqual(parse_transcript(output), "actual words")

    def test_parakeet_log_prefix_is_ignored(self) -> None:
        output = "parakeet_init: loading model\nparakeet_model_load: ok\nhello\n"
        self.assertEqual(parse_transcript(output), "hello")

    def test_special_tokens_are_stripped(self) -> None:
        output = "<|startoftranscript|> hello <|endoftext|> world\n"
        self.assertEqual(parse_transcript(output), "hello world")

    def test_whitespace_collapsed(self) -> None:
        self.assertEqual(parse_transcript("a   b\n\nc"), "a b c")

    def test_empty(self) -> None:
        self.assertEqual(parse_transcript("\n[BLANK_AUDIO]\n"), "")


if __name__ == "__main__":
    unittest.main()
