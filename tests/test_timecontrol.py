import unittest
from unittest.mock import Mock, patch

import chess

from timecontrol import TimeControl, TimeMode


class TestTimeControl(unittest.TestCase):

    def test_board_loss_refund_restores_running_time_and_clock_source(self):
        tc = TimeControl(mode=TimeMode.BLITZ, blitz=1)
        tc.active_color = chess.WHITE
        tc.run_color = chess.WHITE
        tc.start_time = 100.0
        tc.timer = Mock()
        tc.clock_time[chess.WHITE] = 55  # stale display reading from before disconnect
        with patch("timecontrol.time.time", return_value=105.0):
            tc.stop_internal(refund_seconds=5.0)

        self.assertEqual(60.0, tc.internal_time[chess.WHITE])
        self.assertEqual(60.0, tc.clock_time[chess.WHITE])
        self.assertEqual(60.0, tc.internal_time[chess.BLACK])
        tc.timer.stop.assert_called_once_with()

    def test_board_loss_refund_never_exceeds_running_interval(self):
        tc = TimeControl(mode=TimeMode.BLITZ, blitz=1)
        tc.active_color = chess.WHITE
        tc.start_time = 100.0
        tc.timer = Mock()
        with patch("timecontrol.time.time", return_value=102.0):
            tc.stop_internal(refund_seconds=5.0)

        self.assertEqual(60.0, tc.internal_time[chess.WHITE])

    def test_ordinary_clock_stop_still_charges_elapsed_time(self):
        tc = TimeControl(mode=TimeMode.BLITZ, blitz=1)
        tc.active_color = chess.WHITE
        tc.start_time = 100.0
        tc.timer = Mock()
        with patch("timecontrol.time.time", return_value=105.0):
            tc.stop_internal()

        self.assertEqual(55.0, tc.internal_time[chess.WHITE])

    def test_uci_returns_int_for_movestogo(self):
        tc = TimeControl(mode=TimeMode.BLITZ, moves_to_go=20)
        tc.set_clock_times(5, 5, 10)
        self.assertEqual(10, tc.uci()["movestogo"])
