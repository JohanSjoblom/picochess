import asyncio
import unittest
from unittest.mock import Mock, patch

from dgt.board import DgtBoard
from dgt.util import DgtCmd, DgtMsg


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

        with patch("dgt.board.asyncio.to_thread", return_value=asyncio.sleep(0)) as to_thread:
            await board._retry_handshake()

        to_thread.assert_called_once_with(board._retry_handshake_blocking)

    async def test_watchdog_runs_blocking_work_off_event_loop(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board._watchdog_blocking = Mock()

        with patch("dgt.board.asyncio.to_thread", return_value=asyncio.sleep(0)) as to_thread:
            await board._watchdog()

        to_thread.assert_called_once_with(board._watchdog_blocking)

    async def test_watchdog_does_not_write_during_shutdown(self):
        loop = asyncio.get_running_loop()
        board = DgtBoard("/dev/test", False, False, False, loop)
        board.write_command = Mock()
        board.stop_requested.set()

        board._watchdog_blocking()

        board.write_command.assert_not_called()

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
