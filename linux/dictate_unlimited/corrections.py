"""Explicit local word/phrase corrections.

Ported from Sources/DictateCore/LocalCorrections.swift. Matching is literal,
case-insensitive, longest-first, non-overlapping and non-cascading. Replacement
text is never interpreted as a regular expression or processed a second time.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

MAXIMUM_TERM_LENGTH = 120

# Swift uses [\p{L}\p{N}\p{M}_]. Python's \w covers Unicode letters, digits and
# underscore; add the common combining-mark ranges so accented text is treated
# as part of the surrounding word.
_WORD = r"(?:[\w\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f])"


class CorrectionError(ValueError):
    pass


@dataclass
class Correction:
    id: str
    heard: str
    replacement: str

    @classmethod
    def new(cls, heard: str, replacement: str) -> "Correction":
        return cls(uuid.uuid4().hex, heard, replacement)


def _is_control(character: str) -> bool:
    return character in "\r\n\t" or unicodedata.category(character) == "Cc"


def validate(
    heard: str,
    replacement: str,
    existing: Iterable[Correction],
    excluding_id: str | None = None,
) -> str | None:
    for value in (heard, replacement):
        if any(_is_control(character) for character in value):
            return "Corrections must be a single line without control characters."
    source = heard.strip()
    destination = replacement.strip()
    if not source or not destination:
        return "Enter both what was heard and its replacement."
    if len(source) > MAXIMUM_TERM_LENGTH or len(destination) > MAXIMUM_TERM_LENGTH:
        return f"Each correction field must contain at most {MAXIMUM_TERM_LENGTH} characters."
    source_key = _key(source)
    for entry in existing:
        if entry.id == excluding_id:
            continue
        if _key(entry.heard.strip()) == source_key:
            return "A correction for that phrase already exists."
    return None


def _key(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def apply(text: str, entries: Iterable[Correction]) -> str:
    if not text:
        return text
    accepted: list[Correction] = []
    for entry in entries:
        entry = Correction(entry.id, entry.heard.strip(), entry.replacement.strip())
        if validate(entry.heard, entry.replacement, accepted) is None:
            accepted.append(entry)
    if not accepted:
        return text

    ordered = sorted(
        enumerate(accepted),
        key=lambda pair: (-len(pair[1].heard), pair[0]),
    )
    alternatives: list[str] = []
    for _, entry in ordered:
        composed = unicodedata.normalize("NFC", entry.heard)
        decomposed = unicodedata.normalize("NFD", entry.heard)
        values = [composed]
        if decomposed != composed:
            values.append(decomposed)
        alternatives.extend(re.escape(value) for value in values)

    replacements = {_key(entry.heard): entry.replacement for entry in accepted}
    pattern = rf"(?<!{_WORD})(?:{'|'.join(alternatives)})(?!{_WORD})"
    try:
        expression = re.compile(pattern, re.IGNORECASE | re.UNICODE)
    except re.error:
        return text

    output: list[str] = []
    cursor = 0
    for match in expression.finditer(text):
        replacement = replacements.get(_key(match.group(0)))
        if replacement is None:
            continue
        output.append(text[cursor : match.start()])
        output.append(replacement)
        cursor = match.end()
    if cursor == 0:
        return text
    output.append(text[cursor:])
    return "".join(output)


class CorrectionStore:
    """JSON-backed corrections with corrupt-file preservation."""

    def __init__(self, path: Path):
        self.path = path
        self.entries: list[Correction] = []
        self.load_error: str | None = None
        self.load()

    def load(self) -> None:
        self.load_error = None
        self.entries = []
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            items = raw.get("entries", []) if isinstance(raw, dict) else raw
            if not isinstance(items, list):
                raise ValueError("entries must be a list")
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("entry must be an object")
                entry = Correction(
                    id=str(item["id"]),
                    heard=str(item["heard"]).strip(),
                    replacement=str(item["replacement"]).strip(),
                )
                if validate(entry.heard, entry.replacement, self.entries) is not None:
                    raise ValueError(f"invalid correction: {entry.heard!r}")
                self.entries.append(entry)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.load_error = f"{self.path}: {exc}"
            self.entries = []

    def _guard(self) -> None:
        if self.load_error:
            raise CorrectionError(
                "The corrections file is unreadable; it has been left in place. "
                f"Fix {self.path} or run `dictate dictionary clear --force`."
            )

    def _save(self) -> None:
        self._guard()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "version": 1,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "entries": [asdict(entry) for entry in self.entries],
                    },
                    handle,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def add(self, heard: str, replacement: str) -> Correction:
        self._guard()
        source = heard.strip()
        destination = replacement.strip()
        error = validate(source, destination, self.entries)
        if error:
            raise CorrectionError(error)
        entry = Correction.new(source, destination)
        self.entries.append(entry)
        self._save()
        return entry

    def remove(self, entry_id: str) -> bool:
        self._guard()
        for index, entry in enumerate(self.entries):
            if entry.id == entry_id:
                del self.entries[index]
                self._save()
                return True
        return False

    def clear(self, force: bool = False) -> None:
        if self.load_error and not force:
            self._guard()
        self.entries = []
        self.load_error = None
        self._save()

    def find(self, entry_id: str) -> Correction | None:
        return next((entry for entry in self.entries if entry.id == entry_id), None)

    def apply(self, text: str) -> str:
        return apply(text, self.entries)
