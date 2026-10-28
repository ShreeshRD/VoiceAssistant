"""Desktop notifications with a Hyprland fallback."""

from __future__ import annotations

import logging
import shutil
import subprocess

from . import config as config_module

LOG = logging.getLogger(__name__)
APP = "Dictate Unlimited"


def notify(
    config: config_module.Config,
    message: str,
    urgency: str = "normal",
    timeout_ms: int = 2500,
) -> None:
    if not config.notifications:
        LOG.info("%s", message)
        return
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                [
                    "notify-send",
                    "--app-name",
                    APP,
                    "--urgency",
                    urgency,
                    "--expire-time",
                    str(timeout_ms),
                    "--hint=string:x-canonical-private-synchronous:dictate-unlimited",
                    APP,
                    message,
                ],
                capture_output=True,
                timeout=3,
                check=False,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    if shutil.which("hyprctl"):
        try:
            subprocess.run(
                ["hyprctl", "notify", "1", str(timeout_ms), "0xff89b4fa", f"{APP}: {message}"],
                capture_output=True,
                timeout=3,
                check=False,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    LOG.info("%s", message)
