from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from ASR import ipc, paths


class FakeEngine:
    def handle(self, command: str) -> dict:
        return {
            "ok": True,
            "state": "idle",
            "message": f"handled {command}",
            "data": {"running": True},
        }


class IPCTests(unittest.TestCase):
    def test_roundtrip_and_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "dictate.sock"
            ready = threading.Event()
            thread = threading.Thread(
                target=ipc.serve,
                args=(FakeEngine(),),
                kwargs={"on_ready": ready.set},
                daemon=True,
            )
            with mock.patch.object(paths, "socket_path", return_value=socket_path):
                thread.start()
                self.assertTrue(ready.wait(2))
                response = ipc.request("status", timeout=2, autostart=False)
                self.assertTrue(response["ok"])
                self.assertEqual(response["message"], "handled status")
                ipc.shutdown_server()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
                self.assertFalse(socket_path.exists())

    def test_missing_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "absent.sock"
            with mock.patch.object(paths, "socket_path", return_value=socket_path):
                with self.assertRaises(ipc.IPCError):
                    ipc.request("status", timeout=0.5, autostart=False)


if __name__ == "__main__":
    unittest.main()
