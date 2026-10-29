"""Desktop notifications with a Hyprland fallback."""

from __future__ import annotations

import logging
import shutil
import subprocess

from . import config as config_module

LOG = logging.getLogger(__name__)
APP = "Speech Flow"


def notify(
    config: config_module.Config,
    message: str,
    urgency: str = "normal",
    timeout_ms: int = 2500,
    *,
    title: str = APP,
    replace_id: int | None = None,
    group: str = "speech-flow",
    icon: str | None = None,
) -> None:
    """Show a notification.

    ``replace_id`` and ``group`` let the assistant update one bubble in place
    while a reply streams instead of stacking dozens of notifications.
    """
    if not config.notifications:
        LOG.info("%s", message)
        return
    if shutil.which("notify-send"):
        command = [
            "notify-send",
            "--app-name",
            APP,
            "--urgency",
            urgency,
            "--expire-time",
            str(timeout_ms),
            f"--hint=string:x-canonical-private-synchronous:{group}",
        ]
        if replace_id is not None:
            command.append(f"--replace-id={int(replace_id)}")
        if icon:
            command.append(f"--icon={icon}")
        command.extend([title, message])
        try:
            subprocess.run(
                command,
                capture_output=True,
                timeout=3,
                check=False,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    if shutil.which("hyprctl"):
        text = message if title == APP else f"{title}: {message}"
        try:
            subprocess.run(
                ["hyprctl", "notify", "1", str(timeout_ms), "0xff89b4fa", text],
                capture_output=True,
                timeout=3,
                check=False,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    LOG.info("%s", message)
