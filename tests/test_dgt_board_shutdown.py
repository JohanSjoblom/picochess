import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from dgt.api import Event
from dgt.board import DgtBoard
from dgt.util import DgtClk, DgtCmd, DgtMsg


class TestDgtBoardShutdown(unittest.IsolatedAsyncioTestCase):
    async def test_stop_ends_reader_and_closes_serial_connection(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        serial = Mock()
        board.serial = serial
        board._read_serial = Mock(return_value=b"")

        board.run()
        await asyncio.sleep(0)
        await board.stop()

        self.assertTrue(board.stop_requested.is_set())
        self.assertTrue(board.incoming_board_task.done())
        self.assertIsNone(board.serial)
        serial.close.assert_called_once_with()

    async def test_run_clears_previous_stop_request(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.stop_requested.set()
        board._process_incoming_board_forever = Mock()

        board.run()
        await board.incoming_board_task

        self.assertFalse(board.stop_requested.is_set())
        board._process_incoming_board_forever.assert_called_once_with()

    async def test_stop_tolerates_serial_connection_already_being_closed(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        serial = Mock()
        serial.close.side_effect = TypeError("descriptor already closed")
        board.serial = serial

        await board.stop()

        self.assertIsNone(board.serial)
        serial.close.assert_called_once_with()

    async def test_read_tolerates_descriptor_closed_by_shutdown(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.serial = Mock()
        board.serial.read.side_effect = TypeError("descriptor already closed")
        board.stop_requested.set()

        self.assertEqual(board._read_serial(), b"")

    async def test_read_tolerates_transient_type_error_during_reconnect(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.serial = Mock()
        board.serial.read.side_effect = TypeError("descriptor changed during reconnect")

        self.assertEqual(board._read_serial(), b"")

    async def test_stop_tolerates_reader_failing_during_serial_close(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)

        async def reader_failed():
            raise TypeError("descriptor already closed")

        board.incoming_board_task = asyncio.create_task(reader_failed())

        await board.stop()

        self.assertTrue(board.incoming_board_task.done())

    async def test_setup_does_not_open_connection_during_shutdown(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board._open_serial = Mock(return_value=True)
        board.stop_requested.set()

        self.assertFalse(board._setup_serial_port())
        board._open_serial.assert_not_called()

    @patch("dgt.board.Observable.fire", new_callable=AsyncMock)
    async def test_board_connection_events_fire_once_per_transition(self, observable_fire):
        board = DgtBoard("/dev/test", False, False, False, asyncio.get_running_loop())
        board.connected = True
        board.device = "/dev/rfcomm123"
        board._queue_display = Mock()
        board.write_command = Mock(return_value=True)
        board.ask_battery_status = Mock()
        board.startup_serial_clock = Mock()
        board.version_timer.start = Mock()
        board.version_timer.stop = Mock()
        board.watchdog_timer.start = Mock()

        board._on_disconnect()
        board._on_disconnect()
        await asyncio.sleep(0.01)
        self.assertEqual(1, observable_fire.await_count)
        self.assertIsInstance(observable_fire.await_args.args[0], Event.BOARD_CONNECTION_LOST)

        board._process_board_message(DgtMsg.DGT_MSG_VERSION, (3, 10), 2)
        await asyncio.sleep(0.01)
        self.assertEqual(2, observable_fire.await_count)
        self.assertIsInstance(observable_fire.await_args.args[0], Event.BOARD_CONNECTION_RESTORED)

    async def test_concurrent_setup_opens_serial_only_once(self):
        board = DgtBoard("/dev/test", False, False, False, asyncio.get_running_loop())
        first_opening = threading.Event()
        finish_first = threading.Event()
        second_waiting = threading.Event()

        class ObservedLock:
            def __init__(self):
                self.lock = threading.Lock()
                self.entries = 0

            def __enter__(self):
                self.entries += 1
                if self.entries == 2:
                    second_waiting.set()
                self.lock.acquire()
                return self

            def __exit__(self, *_):
                self.lock.release()

        board.lock = ObservedLock()

        def open_serial(_device):
            first_opening.set()
            if not finish_first.wait(5):
                raise TimeoutError("first reconnect remained blocked")
            board.serial = Mock()
            return True

        board._open_serial = Mock(side_effect=open_serial)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(board._setup_serial_port)
            self.assertTrue(await asyncio.to_thread(first_opening.wait, 5))
            second = executor.submit(board._setup_serial_port)
            try:
                self.assertTrue(await asyncio.to_thread(second_waiting.wait, 5))
            finally:
                finish_first.set()
            self.assertTrue(first.result(timeout=5))
            self.assertTrue(second.result(timeout=5))

        board._open_serial.assert_called_once_with("/dev/test")

    async def test_stop_closes_connection_reopened_by_reader(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        original_serial = Mock()
        reopened_serial = Mock()
        board.serial = original_serial

        async def reader_reopened_connection():
            board.serial = reopened_serial

        board.incoming_board_task = asyncio.create_task(reader_reopened_connection())

        await board.stop()

        original_serial.close.assert_called_once_with()
        reopened_serial.close.assert_called_once_with()
        self.assertIsNone(board.serial)

    async def test_handshake_retry_runs_blocking_work_off_event_loop(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board._retry_handshake_blocking = Mock()

        with patch("dgt.board.asyncio.to_thread") as to_thread:
            await board._retry_handshake()

        to_thread.assert_awaited_once_with(board._retry_handshake_blocking)

    async def test_watchdog_runs_blocking_work_off_event_loop(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board._watchdog_blocking = Mock()

        with patch("dgt.board.asyncio.to_thread") as to_thread:
            await board._watchdog()

        to_thread.assert_awaited_once_with(board._watchdog_blocking)

    async def test_watchdog_does_not_write_during_shutdown(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.write_command = Mock()
        board.stop_requested.set()

        board._watchdog_blocking()

        board.write_command.assert_not_called()

    async def test_watchdog_gives_up_after_three_clock_resends(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.serial = Mock()
        clock_command = [
            DgtCmd.DGT_CLOCK_MESSAGE,
            0x03,
            DgtClk.DGT_CMD_CLOCK_START_MESSAGE,
            DgtClk.DGT_CMD_CLOCK_VERSION,
            DgtClk.DGT_CMD_CLOCK_END_MESSAGE,
        ]

        with patch("dgt.board.time.time", return_value=100.0):
            board.write_command(clock_command)
        clock_times = [103.0, 103.0, 106.0, 106.0, 109.0, 109.0, 112.0]
        with (
            patch("dgt.board.time.time", side_effect=clock_times),
            patch("dgt.board.logger.warning") as log_warning,
        ):
            board._watchdog_blocking()
            board._watchdog_blocking()
            board._watchdog_blocking()
            board._watchdog_blocking()

        self.assertEqual(0.0, board.clock_lock)
        self.assertEqual([], board.last_clock_command)
        self.assertEqual(0, board.clock_resend_attempts)
        self.assertEqual(8, board.serial.write.call_count)
        log_warning.assert_called_once()

        writes_after_giveup = board.serial.write.call_count
        with patch("dgt.board.time.time", return_value=115.0):
            board._watchdog_blocking()
        self.assertEqual(writes_after_giveup + 1, board.serial.write.call_count)

    async def test_new_clock_command_gets_fresh_resend_budget(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.serial = Mock()
        board.clock_resend_attempts = 3
        clock_command = [
            DgtCmd.DGT_CLOCK_MESSAGE,
            0x03,
            DgtClk.DGT_CMD_CLOCK_START_MESSAGE,
            DgtClk.DGT_CMD_CLOCK_VERSION,
            DgtClk.DGT_CMD_CLOCK_END_MESSAGE,
        ]

        with patch("dgt.board.time.time", return_value=200.0):
            board.write_command(clock_command)

        self.assertEqual(0, board.clock_resend_attempts)
        self.assertEqual(200.0, board.clock_lock)
        self.assertEqual(clock_command, board.last_clock_command)

    async def test_clock_response_clears_resend_budget(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.clock_lock = 100.0
        board.clock_resend_attempts = 2
        board._queue_display = Mock()

        with patch("dgt.board.time.time", return_value=101.0):
            board._process_board_message(DgtMsg.DGT_MSG_BWTIME, (0, 0, 0, 0, 0, 0, 0), 7)

        self.assertEqual(0.0, board.clock_lock)
        self.assertEqual(0, board.clock_resend_attempts)

    def _silent_link_board(self, loop):
        """A connected board whose disconnect side effects stay inside the test."""
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.connected = True
        board.handshake_pending = False
        board.serial = Mock()
        board.last_board_message = 100.0
        board.write_command = Mock(return_value=True)
        board.version_timer = Mock()
        board.version_timer.is_running.return_value = True
        return board

    async def test_watchdog_drops_link_when_board_stops_answering(self):
        board = self._silent_link_board(asyncio.get_running_loop())
        serial = board.serial

        with patch("dgt.board.Observable.fire", new_callable=AsyncMock) as fire:
            with patch("dgt.board.time.monotonic", return_value=106.0):
                board._watchdog_blocking()
            await asyncio.sleep(0.01)

        self.assertFalse(board.connected)
        self.assertTrue(board.handshake_pending)
        self.assertIsNone(board.serial)
        serial.close.assert_called_once_with()
        self.assertEqual(1, fire.await_count)
        self.assertIsInstance(fire.await_args.args[0], Event.BOARD_CONNECTION_LOST)

    async def test_watchdog_keeps_link_while_board_answers(self):
        board = self._silent_link_board(asyncio.get_running_loop())

        with patch("dgt.board.time.monotonic", return_value=104.0):
            board._watchdog_blocking()

        self.assertTrue(board.connected)
        self.assertIsNotNone(board.serial)

    async def test_watchdog_ignores_silence_during_handshake(self):
        board = self._silent_link_board(asyncio.get_running_loop())
        board.handshake_pending = True

        with patch("dgt.board.time.monotonic", return_value=200.0):
            board._watchdog_blocking()

        self.assertTrue(board.connected)
        self.assertIsNotNone(board.serial)

    async def test_watchdog_drops_silent_link_only_once(self):
        board = self._silent_link_board(asyncio.get_running_loop())

        with patch("dgt.board.Observable.fire", new_callable=AsyncMock) as fire:
            with patch("dgt.board.time.monotonic", return_value=106.0):
                board._watchdog_blocking()
                board._watchdog_blocking()
            await asyncio.sleep(0.01)

        self.assertEqual(1, fire.await_count)

    async def test_board_message_refreshes_silence_stamp(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board._read_serial = Mock(side_effect=[bytes([0, 4]), bytes([3])])
        board._process_board_message = Mock()

        with patch("dgt.board.time.monotonic", return_value=250.0):
            board._read_board_message(bytes([DgtMsg.DGT_MSG_VERSION.value]))

        self.assertEqual(250.0, board.last_board_message)

    async def test_watchdog_requests_bluetooth_battery_every_minute(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.connected = True
        board.channel = "BT"
        board.last_battery_request = 100.0
        board.write_command = Mock(return_value=True)

        with patch("dgt.board.time.monotonic", return_value=160.0):
            board._watchdog_blocking()

        self.assertEqual(
            [
                call([DgtCmd.DGT_RETURN_SERIALNR]),
                call([DgtCmd.DGT_SEND_BATTERY_STATUS]),
            ],
            board.write_command.call_args_list,
        )
        self.assertEqual(160.0, board.last_battery_request)

    async def test_watchdog_does_not_request_battery_for_usb_board(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.connected = True
        board.channel = "USB"
        board.last_battery_request = 100.0
        board.write_command = Mock(return_value=True)

        with patch("dgt.board.time.monotonic", return_value=400.0):
            board._watchdog_blocking()

        board.write_command.assert_called_once_with([DgtCmd.DGT_RETURN_SERIALNR])

    async def test_battery_request_is_marked_before_serial_write(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.connected = True
        board.channel = "BT"
        commands = []

        def write_command(command):
            commands.append(command)
            if command == [DgtCmd.DGT_SEND_BATTERY_STATUS]:
                board._watchdog_blocking()
            return True

        board.write_command = write_command
        with patch("dgt.board.time.monotonic", return_value=400.0):
            board.ask_battery_status()

        self.assertEqual(1, commands.count([DgtCmd.DGT_SEND_BATTERY_STATUS]))
        self.assertEqual(400.0, board.last_battery_request)

    async def test_write_tolerates_serial_closed_during_lock_acquisition(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.serial = Mock()

        class DisconnectingLock:
            def __enter__(self):
                board.serial = None

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        board.lock = DisconnectingLock()

        self.assertTrue(board.write_command([DgtCmd.DGT_RETURN_SERIALNR]))

    async def test_incomplete_board_message_is_discarded_after_one_timeout(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board._read_serial = Mock(side_effect=[bytes([0, 5]), b""])
        board._process_board_message = Mock()

        message = board._read_board_message(bytes([DgtMsg.DGT_MSG_VERSION.value]))

        self.assertEqual(message, ())
        self.assertEqual(board._read_serial.call_count, 2)
        board._process_board_message.assert_not_called()

    async def test_overlapping_serial_startup_is_skipped(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.write_command = Mock()
        board.startup_lock.acquire()

        try:
            self.assertFalse(board._startup_serial_board())
        finally:
            board.startup_lock.release()

        board.write_command.assert_not_called()

    async def test_serial_startup_sends_one_complete_handshake(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.write_command = Mock()

        self.assertTrue(board._startup_serial_board())

        self.assertEqual(board.write_command.call_count, 2)
        self.assertTrue(board.handshake_pending)

    async def test_rfcomm_failure_preserves_pairing_before_retry(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("", False, True, False, loop)
        board.btctl = Mock()
        board.bt_state = 7
        board.bt_current_device = 0
        board.bt_mac_list = ["00:06:66:64:C4:07"]
        board.bt_name_list = ["DGT_BT_21704"]
        board.bt_line = "stale output"
        board.bt_rfcomm = Mock()

        with patch("dgt.board.time.monotonic", return_value=100):
            board._defer_bluetooth_after_rfcomm_failure()

        board.btctl.stdin.write.assert_not_called()
        self.assertEqual(board.bt_state, 8)
        self.assertEqual(board.bt_retry_after, 102)
        self.assertEqual(board.bt_current_device, 0)
        self.assertEqual(board.bt_mac_list, ["00:06:66:64:C4:07"])
        self.assertEqual(board.bt_name_list, ["DGT_BT_21704"])
        self.assertEqual(board.bt_line, "stale output")
        self.assertIsNone(board.bt_rfcomm)

    async def test_rfcomm_retry_waits_then_tries_next_candidate(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("", False, True, False, loop)
        board.btctl = Mock()
        board.btctl.stdout.fileno.return_value = 42
        board.bt_state = 8
        board.bt_retry_after = 100
        board.bt_current_device = 0
        board.bt_mac_list = ["00:06:66:64:C4:07", "00:06:66:64:C4:08"]
        board.bt_name_list = ["DGT_BT_21704", "DGT_BT_21705"]

        with patch("dgt.board.time.monotonic", return_value=99):
            self.assertFalse(board._open_bluetooth())
        board.btctl.stdin.write.assert_not_called()

        with (
            patch("dgt.board.time.monotonic", return_value=101),
            patch("dgt.board.read", return_value=b""),
        ):
            self.assertFalse(board._open_bluetooth())

        board.btctl.stdin.write.assert_called_once_with("pair 00:06:66:64:C4:08\n")
        board.btctl.stdin.flush.assert_called_once_with()
        self.assertEqual(board.bt_current_device, 1)
        self.assertEqual(board.bt_state, 5)

    async def test_paired_board_is_trusted_before_rfcomm_connect(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("", False, True, False, loop)
        board.btctl = Mock()
        board.btctl.stdout.fileno.return_value = 42
        board.bt_state = 6
        board.bt_current_device = 0
        board.bt_mac_list = ["00:06:66:64:C4:07"]
        board.bt_name_list = ["DGT_BT_21704"]
        rfcomm = Mock()
        rfcomm.poll.return_value = None

        with (
            patch("dgt.board.read", return_value=b""),
            patch("dgt.board.path.exists", return_value=False),
            patch("dgt.board.subprocess.Popen", return_value=rfcomm) as popen,
        ):
            self.assertFalse(board._open_bluetooth())

        board.btctl.stdin.write.assert_called_once_with("trust 00:06:66:64:C4:07\n")
        board.btctl.stdin.flush.assert_called_once_with()
        popen.assert_called_once()
        self.assertIn("rfcomm connect 123 00:06:66:64:C4:07", popen.call_args.args[0])
        self.assertEqual(board.bt_state, 7)
