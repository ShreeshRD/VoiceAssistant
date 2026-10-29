"""Wayland text delivery.

The macOS app verifies insertion through the Accessibility API. Wayland does
not expose an equivalent, so this port prefers wtype (a virtual keyboard) and
offers an explicit clipboard mode. It never sends Enter, and it never retries a
write that may already have been delivered.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

from . import config as config_module


class InsertionError(RuntimeError):
    pass


@dataclass
class DeliveryResult:
    ok: bool
    method: str
    message: str


def have(command: str) -> bool:
    return shutil.which(command) is not None


def sanitize_for_typing(text: str) -> str:
    # wtype maps newlines to Return; that can submit a chat composer. Dictation
    # is single-line text, so flatten line breaks rather than sending Enter.
    payload = re.sub(r"\s+", " ", text.replace("\x00", "")).strip()
    # Keep a deliberately added trailing space (see with_trailing_space) so
    # back-to-back dictations do not run together in the focused field.
    if payload and text[-1:].isspace():
        payload += " "
    return payload


_SENTENCE_END = re.compile(r"[.!?…](?:[\"'”’\)\]]*)$")


def with_trailing_space(text: str) -> str:
    """Append one space when text ends with sentence-ending punctuation."""
    if text and _SENTENCE_END.search(text):
        return text + " "
    return text


def _run(command: list[str], *, input_text: str | None = None, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=os.environ.copy(),
        )
    except FileNotFoundError as exc:
        raise InsertionError(f"{command[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise InsertionError(f"{command[0]} timed out") from exc


def type_text(text: str) -> None:
    if not have("wtype"):
        raise InsertionError("wtype is not installed. Install wtype or use insertion=copy.")
    if not os.environ.get("WAYLAND_DISPLAY"):
        raise InsertionError("WAYLAND_DISPLAY is not set; wtype needs a Wayland session.")
    payload = sanitize_for_typing(text)
    if not payload:
        raise InsertionError("there is no text to insert")
    result = _run(["wtype", "--", payload], timeout=30)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise InsertionError(detail or f"wtype exited with {result.returncode}")
    # Never send Return. This is intentional and mirrors the macOS app.


def read_clipboard() -> str | None:
    if not have("wl-paste"):
        return None
    try:
        result = _run(
            ["wl-paste", "--no-newline", "--type", "text/plain"],
            timeout=1.5,
        )
    except InsertionError:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout
    return value if len(value) <= 1_000_000 else None


def write_clipboard(text: str) -> None:
    if not have("wl-copy"):
        raise InsertionError("wl-copy is not installed. Install wl-clipboard or use insertion=wtype.")
    if not os.environ.get("WAYLAND_DISPLAY"):
        raise InsertionError("WAYLAND_DISPLAY is not set; wl-copy needs a Wayland session.")
    result = _run(["wl-copy", "--type", "text/plain"], input_text=text, timeout=5)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise InsertionError(detail or f"wl-copy exited with {result.returncode}")


def clear_clipboard() -> None:
    if not have("wl-copy"):
        return
    _run(["wl-copy", "--clear"], timeout=5)


def _paste_shortcut() -> None:
    if not have("wtype"):
        raise InsertionError("wtype is not installed, so Ctrl+V cannot be sent")
    result = _run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], timeout=5)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise InsertionError(detail or f"wtype exited with {result.returncode}")


def _deliver_clipboard(text: str, restore: bool) -> DeliveryResult:
    previous = read_clipboard() if restore else None
    write_clipboard(text)
    if not have("wtype"):
        return DeliveryResult(
            True,
            "copy",
            "Text copied to the clipboard. Press Ctrl+V to insert it.",
        )
    try:
        _paste_shortcut()
    except InsertionError as exc:
        return DeliveryResult(
            True,
            "copy",
            f"Text copied to the clipboard; Ctrl+V could not be sent ({exc}).",
        )
    # Give the focused client a moment to read the selection, then restore only
    # if the clipboard still contains exactly what we put there.
    time.sleep(0.6)
    if restore:
        try:
            if read_clipboard() == text:
                if previous is None or previous == "":
                    clear_clipboard()
                else:
                    write_clipboard(previous)
        except InsertionError:
            pass
    return DeliveryResult(True, "clipboard", "Pasted. Check the field before retrying.")


def deliver(text: str, config: config_module.Config) -> DeliveryResult:
    text = text.strip("\n")
    if not text.strip():
        return DeliveryResult(False, "none", "There is no text to insert.")
    if config.trailing_space:
        text = with_trailing_space(text)
    mode = config.insertion
    if mode == "none":
        return DeliveryResult(True, "none", "Transcript ready; insertion is disabled.")
    if mode == "wtype":
        try:
            type_text(text)
            return DeliveryResult(True, "wtype", "Typed into the focused window.")
        except InsertionError as exc:
            if have("wl-copy"):
                try:
                    write_clipboard(text)
                    return DeliveryResult(
                        True,
                        "copy",
                        f"Typing failed ({exc}). Text copied to the clipboard; press Ctrl+V.",
                    )
                except InsertionError:
                    pass
            return DeliveryResult(False, "wtype", f"Could not insert text: {exc}")
    if mode == "clipboard":
        try:
            return _deliver_clipboard(text, config.restore_clipboard)
        except InsertionError as exc:
            return DeliveryResult(False, "clipboard", f"Could not paste text: {exc}")
    if mode == "copy":
        try:
            write_clipboard(text)
            return DeliveryResult(True, "copy", "Text copied to the clipboard. Press Ctrl+V.")
        except InsertionError as exc:
            return DeliveryResult(False, "copy", f"Could not copy text: {exc}")
    # auto: prefer direct typing, which never touches the clipboard.
    if have("wtype"):
        try:
            type_text(text)
            return DeliveryResult(True, "wtype", "Typed into the focused window.")
        except InsertionError as exc:
            if have("wl-copy"):
                try:
                    write_clipboard(text)
                    return DeliveryResult(
                        True,
                        "copy",
                        f"Typing failed ({exc}). Text copied to the clipboard; press Ctrl+V.",
                    )
                except InsertionError:
                    pass
            return DeliveryResult(False, "wtype", f"Could not insert text: {exc}")
    if have("wl-copy"):
        try:
            write_clipboard(text)
            return DeliveryResult(True, "copy", "Text copied to the clipboard. Press Ctrl+V.")
        except InsertionError as exc:
            return DeliveryResult(False, "copy", f"Could not copy text: {exc}")
    return DeliveryResult(
        False,
        "none",
        "Neither wtype nor wl-copy is installed. Install wtype and wl-clipboard.",
    )
