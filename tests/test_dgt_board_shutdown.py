import asyncio
import unittest
from unittest.mock import Mock, patch

from dgt.api import DgtCmd
from dgt.board import DgtBoard


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
