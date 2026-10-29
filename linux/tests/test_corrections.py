from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ASR.corrections import (
    Correction,
    CorrectionError,
    CorrectionStore,
    apply,
    run_chat,
    validate,
)


class CorrectionApplyTests(unittest.TestCase):
    def test_literal_case_insensitive_replacement(self) -> None:
        entries = [Correction("1", "map", "Mac")]
        self.assertEqual(apply("I use a Map.", entries), "I use a Mac.")

    def test_word_boundaries(self) -> None:
        entries = [Correction("1", "cat", "dog")]
        self.assertEqual(apply("concatenate cat catalog", entries), "concatenate dog catalog")

    def test_underscore_is_a_word_character(self) -> None:
        entries = [Correction("1", "foo", "bar")]
        self.assertEqual(apply("foo_bar foo", entries), "foo_bar bar")

    def test_longest_phrase_wins(self) -> None:
        entries = [
            Correction("1", "York", "Y"),
            Correction("2", "New York", "NYC"),
        ]
        self.assertEqual(apply("New York and York", entries), "NYC and Y")

    def test_replacements_are_not_cascaded(self) -> None:
        entries = [
            Correction("1", "cat", "dog"),
            Correction("2", "dog", "pet"),
        ]
        self.assertEqual(apply("cat", entries), "dog")

    def test_unicode_composed_and_decomposed(self) -> None:
        entries = [Correction("1", "café", "coffee")]
        self.assertEqual(apply("café", entries), "coffee")
        self.assertEqual(apply("cafe\u0301", entries), "coffee")

    def test_replacement_is_literal(self) -> None:
        entries = [Correction("1", "cat", r"C:\path$1\\")]
        self.assertEqual(apply("cat", entries), r"C:\path$1\\")

    def test_empty_text(self) -> None:
        self.assertEqual(apply("", [Correction("1", "a", "b")]), "")

    def test_invalid_entries_are_skipped(self) -> None:
        entries = [
            Correction("1", "cat", ""),
            Correction("2", "dog", "pet"),
        ]
        self.assertEqual(apply("cat dog", entries), "cat pet")


class CorrectionValidationTests(unittest.TestCase):
    def test_duplicate_is_case_insensitive(self) -> None:
        existing = [Correction("1", "New York", "NYC")]
        self.assertIsNotNone(validate("new york", "NY", existing))

    def test_control_characters_rejected(self) -> None:
        self.assertIsNotNone(validate("a\nb", "c", []))
        self.assertIsNotNone(validate("a", "c\td", []))

    def test_length_limit(self) -> None:
        self.assertIsNotNone(validate("x" * 121, "y", []))
        self.assertIsNone(validate("x" * 120, "y", []))

    def test_excluding_own_id(self) -> None:
        existing = [Correction("1", "cat", "dog")]
        self.assertIsNone(validate("cat", "cat", existing, excluding_id="1"))


class CorrectionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "corrections.json"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_add_persist_and_reload(self) -> None:
        store = CorrectionStore(self.path)
        entry = store.add("map", "Mac")
        self.assertTrue(self.path.exists())
        reloaded = CorrectionStore(self.path)
        self.assertEqual(len(reloaded.entries), 1)
        self.assertEqual(reloaded.entries[0].id, entry.id)
        self.assertEqual(reloaded.apply("map"), "Mac")

    def test_remove(self) -> None:
        store = CorrectionStore(self.path)
        entry = store.add("map", "Mac")
        self.assertTrue(store.remove(entry.id))
        self.assertFalse(store.remove(entry.id))
        self.assertEqual(store.entries, [])

    def test_corrupt_file_is_preserved_and_blocks_writes(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        store = CorrectionStore(self.path)
        self.assertIsNotNone(store.load_error)
        with self.assertRaises(CorrectionError):
            store.add("a", "b")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{not json")
        store.clear(force=True)
        self.assertEqual(store.entries, [])
        json.loads(self.path.read_text(encoding="utf-8"))

class CorrectionChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "corrections.json"
        self.store = CorrectionStore(self.path)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def chat(self, lines: list[str], reload_fn=None) -> tuple[int, list[str]]:
        queue = list(lines)
        output: list[str] = []

        def fake_input(prompt: str = "") -> str:
            if not queue:
                raise EOFError
            return queue.pop(0)

        code = run_chat(
            self.store,
            input_fn=fake_input,
            output_fn=output.append,
            reload_fn=reload_fn,
        )
        return code, output

    def test_add_through_chat_and_reload(self) -> None:
        reloads: list[str] = []
        code, output = self.chat(["m. d. => MD", "quit"], reload_fn=lambda: reloads.append("ok") or "reloaded")
        self.assertEqual(code, 0)
        self.assertEqual([entry.heard for entry in self.store.entries], ["m. d."])
        self.assertEqual(self.store.apply("open the m. d. file"), "open the MD file")
        self.assertTrue(any("added" in line for line in output))
        self.assertEqual(reloads, ["ok"])

    def test_alternate_separator_and_quotes(self) -> None:
        code, _ = self.chat(['add "m. d." -> "MD"', "exit"])
        self.assertEqual(code, 0)
        self.assertEqual(self.store.entries[0].heard, "m. d.")
        self.assertEqual(self.store.entries[0].replacement, "MD")

    def test_list_remove_and_undo(self) -> None:
        code, output = self.chat(
            ["map => Mac", "cat => dog", "list", "remove 1", "undo", "list", "q"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.store.entries, [])
        self.assertTrue(any(line.strip().startswith("1.") for line in output))

    def test_apply_is_a_preview_only(self) -> None:
        self.store.add("map", "Mac")
        code, output = self.chat(["apply use a map", "quit"])
        self.assertEqual(code, 0)
        self.assertIn("use a Mac", output)
        self.assertEqual(len(self.store.entries), 1)

    def test_invalid_line_keeps_chat_open(self) -> None:
        code, output = self.chat(["nonsense", "map => Mac", "quit"])
        self.assertEqual(code, 0)
        self.assertTrue(any("heard => replacement" in line for line in output))
        self.assertEqual(len(self.store.entries), 1)

    def test_eof_exits_cleanly(self) -> None:
        code, output = self.chat([])
        self.assertEqual(code, 0)
        self.assertIn("", output)


if __name__ == "__main__":
    unittest.main()
