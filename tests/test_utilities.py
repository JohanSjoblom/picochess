import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from utilities import (
    AsyncRepeatingTimer,
    _choose_wayland_backend,
    exit_pico,
    get_engine_mame_par,
    get_window_command,
    reboot,
    shutdown,
    update_pico_engines,
    update_pico_v4,
    update_picochess_now,
)


class TestUtilities(unittest.TestCase):

    @patch("utilities.os.system")
    @patch("utilities.platform.system", return_value="Darwin")
    def test_macos_host_power_commands_are_noops(self, _, os_system):
        shutdown(False, "web")
        reboot(False, "web")
        exit_pico(False, "web")

        os_system.assert_not_called()

    @patch("utilities.subprocess.Popen")
    @patch("utilities.subprocess.run")
    @patch("utilities.platform.system", return_value="Darwin")
    def test_macos_host_updates_are_noops(self, _, run, popen):
        update_pico_engines()
        update_pico_v4()
        update_picochess_now()

        run.assert_not_called()
        popen.assert_not_called()

    def test_engine_mame_par(self):
        self.assertEqual("-speed 1.0 -sound none", get_engine_mame_par(1.0))
        self.assertEqual("-speed 2.01", get_engine_mame_par(2.01, True))
        self.assertEqual("-nothrottle -sound none", get_engine_mame_par(0.009))
        self.assertEqual("-nothrottle", get_engine_mame_par(0.009, True))
        self.assertEqual("-speed 1.0 -sound none -window", get_engine_mame_par(1.0, False, True))
        self.assertEqual("-speed 1.0 -sound none -nowindow", get_engine_mame_par(1.0, False, False))

    @patch("utilities.is_wayland_session", return_value=False)
    def test_get_window_command_x11(self, _):
        self.assertEqual(
            "xdotool keydown alt key Tab; sleep 0.2; xdotool keyup alt",
            get_window_command("switch_window"),
        )

    @patch("utilities._choose_wayland_backend", return_value="ydotool")
    @patch("utilities.is_wayland_session", return_value=True)
    def test_get_window_command_wayland_ydotool(self, _, __):
        self.assertEqual(
            "ydotool key 56:1 15:1 15:0; sleep 0.2; ydotool key 56:0",
            get_window_command("switch_window"),
        )

    @patch("utilities._choose_wayland_backend", return_value="ydotool")
    @patch("utilities.is_wayland_session", return_value=True)
    @patch.dict("utilities.os.environ", {"YDOTOOL_SOCKET": "/home/pi/.ydotool_socket"}, clear=False)
    def test_get_window_command_wayland_ydotool_with_socket(self, _, __):
        self.assertEqual(
            "YDOTOOL_SOCKET=/home/pi/.ydotool_socket ydotool key 56:1 15:1 15:0; "
            "sleep 0.2; YDOTOOL_SOCKET=/home/pi/.ydotool_socket ydotool key 56:0",
            get_window_command("switch_window"),
        )

    @patch("utilities._choose_wayland_backend", return_value=None)
    @patch("utilities.is_wayland_session", return_value=True)
    def test_get_window_command_wayland_no_backend(self, _, __):
        self.assertIsNone(get_window_command("switch_window"))

    @patch("utilities.shutil.which", return_value="/usr/bin/swaymsg")
    @patch.dict("utilities.os.environ", {"PICOCHESS_WAYLAND_WINDOW_BACKEND": "swaymsg"}, clear=False)
    def test_choose_wayland_backend_override_sway(self, _):
        self.assertEqual("swaymsg", _choose_wayland_backend())

    @patch("utilities.shutil.which", return_value=None)
    @patch.dict("utilities.os.environ", {"PICOCHESS_WAYLAND_WINDOW_BACKEND": "ydotool"}, clear=False)
    def test_choose_wayland_backend_override_missing_tool(self, _):
        self.assertIsNone(_choose_wayland_backend())

    @patch("utilities.os.system")
    @patch("utilities.platform.system", return_value="Linux")
    def test_exit_pico_does_not_stop_chromium_outside_kiosk(self, _, os_system):
        exit_pico(dgtpi=False, dev="web")

        os_system.assert_not_called()

    @patch("utilities.subprocess.Popen")
    def test_update_restart_does_not_kill_unowned_chromium(self, popen):
        update_picochess_now(web_port=8080)

        command = popen.call_args.args[0][-1]
        self.assertIn("systemctl restart picochess", command)
        self.assertNotIn("chromium", command)
        self.assertIn('--web-port 8080', command)


class TestAsyncRepeatingTimer(unittest.IsolatedAsyncioTestCase):

    async def test_diagnostics_include_start_and_stop_queue_delay(self):
        loop = asyncio.get_running_loop()
        timer = AsyncRepeatingTimer(10, lambda: None, loop)
        with patch.object(AsyncRepeatingTimer, "lag_warning_seconds", 0.02):
            with self.assertLogs(level="WARNING") as logs:
                for operation in (timer.start, timer.stop):
                    worker = threading.Thread(target=operation)
                    worker.start()
                    worker.join(timeout=1)
                    self.assertFalse(worker.is_alive())
                    time.sleep(0.03)  # Hold the loop after the worker submitted its request.
                    await asyncio.sleep(0)
        messages = "\n".join(logs.output)
        self.assertIn("stage=start-dispatch", messages)
        self.assertIn("stage=stop-dispatch", messages)

    async def test_stop_suppresses_callback_before_queued_cancellation_runs(self):
        loop = asyncio.get_running_loop()
        calls = []
        timer = AsyncRepeatingTimer(0, lambda: calls.append("fired"), loop, repeating=False)
        timer.start()
        await asyncio.sleep(0)  # The timer's sleep(0) wakeup is now ahead of cancellation.
        worker = threading.Thread(target=timer.stop)
        worker.start()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        await asyncio.sleep(0)
        self.assertEqual(calls, [])

    async def test_diagnostics_include_task_dispatch_and_total_first_expiry_delay(self):
        loop = asyncio.get_running_loop()
        fired = asyncio.Event()
        timer = AsyncRepeatingTimer(0, fired.set, loop, repeating=False)
        with patch.object(AsyncRepeatingTimer, "lag_warning_seconds", 0.02):
            with self.assertLogs(level="WARNING") as logs:
                loop.call_soon(time.sleep, 0.03)
                timer.start()  # Task creation happens now; execution waits behind the blocker.
                await asyncio.wait_for(fired.wait(), timeout=1)
        messages = "\n".join(logs.output)
        self.assertIn("stage=task-start", messages)
        self.assertIn("stage=first-expiry", messages)

    async def test_restart_does_not_revive_old_generation(self):
        loop = asyncio.get_running_loop()
        calls = []
        fired = asyncio.Event()

        def callback():
            calls.append("fired")
            fired.set()

        timer = AsyncRepeatingTimer(0, callback, loop, repeating=False)
        timer.start()
        await asyncio.sleep(0)

        def restart():
            timer.stop()
            timer.start()

        worker = threading.Thread(target=restart)
        worker.start()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        await asyncio.wait_for(fired.wait(), timeout=1)
        await asyncio.sleep(0)
        self.assertEqual(calls, ["fired"])
        self.assertFalse(timer.is_running())

    async def test_delayed_stop_does_not_cancel_new_generation(self):
        loop = asyncio.get_running_loop()
        fired = asyncio.Event()
        timer = AsyncRepeatingTimer(0, fired.set, loop, repeating=False)
        with patch.object(timer, "_running_in_target_loop", return_value=False):
            with patch.object(loop, "call_soon_threadsafe") as queued:
                timer.start()
                timer.stop()
                timer.start()
        first_start, old_stop, new_start = queued.call_args_list
        for request in (new_start, first_start, old_stop):
            callback, *args = request.args
            callback(*args)
        await asyncio.wait_for(fired.wait(), timeout=1)

    async def test_diagnostics_report_late_wakeup_and_slow_sync_callback(self):
        loop = asyncio.get_running_loop()
        fired = asyncio.Event()

        def callback():
            time.sleep(0.03)
            fired.set()

        timer = AsyncRepeatingTimer(0.01, callback, loop, repeating=False)
        with patch.object(AsyncRepeatingTimer, "lag_warning_seconds", 0.02):
            with self.assertLogs(level="WARNING") as logs:
                timer.start()
                await asyncio.sleep(0)  # Let the timer schedule its first wakeup.
                loop.call_soon(time.sleep, 0.06)
                await asyncio.wait_for(fired.wait(), timeout=1)

        messages = "\n".join(logs.output)
        self.assertIn("event-loop timer late callback=callback", messages)
        self.assertIn("event-loop timer callback slow callback=callback", messages)

    async def test_start_from_worker_thread_wakes_event_loop(self):
        loop = asyncio.get_running_loop()
        fired = asyncio.Event()
        timer = AsyncRepeatingTimer(0.01, fired.set, loop, repeating=False)

        worker = threading.Thread(target=timer.start)
        worker.start()
        worker.join(timeout=1)

        await asyncio.wait_for(fired.wait(), timeout=1)
        await asyncio.sleep(0)
        self.assertFalse(timer.is_running())

    async def test_repeating_timer_survives_callback_exception(self):
        loop = asyncio.get_running_loop()
        succeeded = asyncio.Event()
        call_count = 0

        def callback():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient callback failure")
            succeeded.set()

        timer = AsyncRepeatingTimer(0.01, callback, loop)
        timer.start()
        try:
            await asyncio.wait_for(succeeded.wait(), timeout=1)
        finally:
            timer.stop()

        self.assertGreaterEqual(call_count, 2)


if __name__ == "__main__":
    unittest.main()
