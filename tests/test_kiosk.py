import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


class TestKioskSupervisor(unittest.TestCase):
    def wait_for_lines(self, path: Path, expected: int, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists() and len(path.read_text(encoding="utf-8").splitlines()) >= expected:
                return
            time.sleep(0.05)
        self.fail(f"Timed out waiting for {expected} lines in {path}")

    def test_browser_follows_picochess_service_lifecycle(self):
        repo = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            service_state = temp / "service-state"
            browser_started = temp / "browser-started"
            browser_stopped = temp / "browser-stopped"
            service_state.write_text("active", encoding="utf-8")

            systemctl = bin_dir / "systemctl"
            systemctl.write_text(
                "#!/bin/sh\n"
                "if [ \"$3\" = \"picochess-update.service\" ]; then exit 1; fi\n"
                f"[ \"$(cat '{service_state}')\" = \"active\" ]\n",
                encoding="utf-8",
            )
            systemctl.chmod(0o755)

            chromium = bin_dir / "chromium"
            chromium.write_text(
                "#!/bin/sh\n"
                f"echo started >> '{browser_started}'\n"
                f"trap \"echo stopped >> '{browser_stopped}'; exit 0\" HUP INT TERM\n"
                "while true; do sleep 0.05; done\n",
                encoding="utf-8",
            )
            chromium.chmod(0o755)

            pkill = bin_dir / "pkill"
            pkill.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            pkill.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(temp),
                    "USER": "test-user",
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "XDG_SESSION_TYPE": "wayland",
                    "PICOCHESS_KIOSK_CHROMIUM": str(chromium),
                    "PICOCHESS_KIOSK_URL": "http://127.0.0.1:8080",
                    "PICOCHESS_KIOSK_POLL_INTERVAL": "0.05",
                    "PICOCHESS_KIOSK_STARTUP_POLL_INTERVAL": "0.05",
                }
            )

            kiosk = subprocess.Popen(
                ["bash", str(repo / "kiosk.sh")],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.wait_for_lines(browser_started, 1)

                service_state.write_text("inactive", encoding="utf-8")
                self.wait_for_lines(browser_stopped, 1)
                self.assertIsNone(kiosk.poll())

                service_state.write_text("active", encoding="utf-8")
                self.wait_for_lines(browser_started, 2)
            finally:
                kiosk.terminate()
                kiosk.communicate(timeout=5)

            self.wait_for_lines(browser_stopped, 2)
            self.assertEqual(0, kiosk.returncode)


if __name__ == "__main__":
    unittest.main()
