import asyncio
import unittest

import chess

from dgt.util import Mode, ModeLoop
from mainloop import configured_interaction_mode
from move_policy import should_auto_takeback_mame_blunder
from relay.engine_match import EngineMatchClient
from relay.relay import RelayError
from tests.test_relay import FakeEndpoint, START_FEN, position_event


class TestEngineMatchClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.moves = []
        self.stops = []

    async def on_move(self, move, fen):
        self.moves.append((move, fen))

    async def on_stop(self, reason):
        self.stops.append(reason)

    def client(self, endpoint):
        return EngineMatchClient(
            "http://unused",
            self.on_move,
            self.on_stop,
            endpoint=endpoint,
        )

    async def test_arm_requires_identical_standard_position(self):
        endpoint = FakeEndpoint("remote")
        client = self.client(endpoint)

        armed_fen = await client.arm(START_FEN)

        self.assertEqual(START_FEN, armed_fen)
        self.assertTrue(client.armed)

    async def test_arm_assumes_start_position_for_silent_connected_peer(self):
        endpoint = FakeEndpoint("remote")
        endpoint.messages = asyncio.Queue()
        endpoint.messages.put_nowait({"event": "SystemInfo", "msg": {}})
        client = EngineMatchClient(
            "http://unused",
            self.on_move,
            self.on_stop,
            timeout=0.01,
            endpoint=endpoint,
        )

        with self.assertLogs("relay.engine_match", level="INFO") as captured:
            armed_fen = await client.arm(START_FEN)

        self.assertEqual(START_FEN, armed_fen)
        self.assertEqual(START_FEN, endpoint.board.fen(en_passant="fen"))
        self.assertTrue(client.armed)
        self.assertIn("assuming standard starting position", captured.output[0])

    async def test_silent_peer_is_not_assumed_for_nonstarting_position(self):
        endpoint = FakeEndpoint("remote")
        endpoint.messages = asyncio.Queue()
        client = EngineMatchClient(
            "http://unused",
            self.on_move,
            self.on_stop,
            timeout=0.01,
            endpoint=endpoint,
        )
        moved = chess.Board()
        moved.push_uci("e2e4")

        with self.assertRaisesRegex(RelayError, "timed out waiting for an initial position"):
            await client.arm(moved.fen(en_passant="fen"))

    async def test_local_move_waits_for_remote_acknowledgement(self):
        endpoint = FakeEndpoint("remote", acknowledge=False)
        client = self.client(endpoint)
        await client.arm(START_FEN)
        after = chess.Board()
        move = chess.Move.from_uci("e2e4")
        after.push(move)
        resulting_fen = after.fen(en_passant="fen")

        with self.assertLogs("relay.engine_match", level="DEBUG") as captured:
            await client.send_local_move(move, resulting_fen)
            self.assertEqual((move, resulting_fen), client.pending_local_move)
            await client._process_message(
                position_event(event="Fen", play="user", fen=resulting_fen, move="e2e4")
            )

        self.assertIsNone(client.pending_local_move)
        self.assertEqual(resulting_fen, endpoint.board.fen(en_passant="fen"))
        self.assertTrue(all(record.levelno < 20 for record in captured.records))

    async def test_remote_move_is_announced_then_waits_for_physical_confirmation(self):
        endpoint = FakeEndpoint("remote")
        client = self.client(endpoint)
        await client.arm(START_FEN)
        after = chess.Board()
        move = chess.Move.from_uci("e2e4")
        after.push(move)
        resulting_fen = after.fen(en_passant="fen")

        with self.assertLogs("relay.engine_match", level="DEBUG") as captured:
            await client._process_message(
                position_event(event="Fen", play="computer", fen=resulting_fen, move="e2e4")
            )
            self.assertEqual((move, resulting_fen), client.pending_remote_move)
            client.confirm_remote_move(move, resulting_fen)

        self.assertEqual([(move, resulting_fen)], self.moves)
        self.assertIsNone(client.pending_remote_move)
        self.assertTrue(all(record.levelno < 20 for record in captured.records))
        self.assertIn("waiting for eboard", captured.output[0])
        self.assertIn("confirmed peer move e2e4", captured.output[1])

    async def test_second_remote_move_is_rejected_before_eboard_confirmation(self):
        endpoint = FakeEndpoint("remote")
        client = self.client(endpoint)
        await client.arm(START_FEN)
        after = chess.Board()
        after.push_uci("e2e4")
        first_fen = after.fen(en_passant="fen")
        await client._process_message(
            position_event(event="Fen", play="computer", fen=first_fen, move="e2e4")
        )

        with self.assertRaisesRegex(RelayError, "previous move is still on the eboard"):
            await client._process_message(
                position_event(event="Fen", play="computer", fen=first_fen, move="e7e5")
            )

    async def test_new_game_request_waits_for_peer_confirmation(self):
        endpoint = FakeEndpoint("remote")
        client = self.client(endpoint)
        await client.arm(START_FEN)
        run_task = asyncio.create_task(client.run())

        confirmed_fen = await client.request_new_game()

        self.assertEqual(START_FEN, confirmed_fen)
        self.assertEqual(1, endpoint.new_games)
        self.assertTrue(client.armed)
        self.assertEqual([], self.stops)
        await client.close()
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)

    async def test_game_end_completes_pending_local_mating_move(self):
        before_mate = chess.Board()
        for move in ("f2f3", "e7e5", "g2g4"):
            before_mate.push_uci(move)
        endpoint = FakeEndpoint("remote", before_mate.fen(en_passant="fen"), acknowledge=False)
        client = self.client(endpoint)
        await client.arm(before_mate.fen(en_passant="fen"))
        mate = chess.Move.from_uci("d8h4")
        after_mate = before_mate.copy()
        after_mate.push(mate)

        await client.send_local_move(mate, after_mate.fen(en_passant="fen"))
        result = await client._process_message({"event": "GameEnd", "result": "0-1"})

        self.assertIsNone(result)
        self.assertIsNone(client.pending_local_move)
        self.assertTrue(endpoint.board.is_checkmate())

    async def test_run_reports_connection_loss(self):
        endpoint = FakeEndpoint("remote")
        client = self.client(endpoint)
        await client.arm(START_FEN)
        endpoint.messages.put_nowait(None)

        await client.run()

        self.assertEqual(["remote connection closed"], self.stops)
        self.assertTrue(endpoint.closed)


class TestEngineMatchModeSelection(unittest.TestCase):
    def test_remote_without_peer_url_keeps_legacy_mode(self):
        self.assertEqual(Mode.REMOTE, configured_interaction_mode(Mode.REMOTE, ""))

    def test_remote_with_peer_url_selects_internal_engine_match(self):
        self.assertEqual(
            Mode.ENGINE_MATCH,
            configured_interaction_mode(Mode.REMOTE, " http://pico-remote:8080 "),
        )

    def test_engine_match_is_not_in_user_mode_cycle(self):
        self.assertNotIn(Mode.ENGINE_MATCH, Mode.menu_items())
        self.assertEqual(Mode.PONDER, ModeLoop.next(Mode.REMOTE))
        self.assertEqual(Mode.REMOTE, ModeLoop.prev(Mode.PONDER))

    def test_engine_match_does_not_auto_takeback_mame_blunder(self):
        self.assertFalse(
            should_auto_takeback_mame_blunder(
                Mode.ENGINE_MATCH,
                emulation_mode=True,
                evaluation="??",
                repeated_move=False,
            )
        )

    def test_normal_mode_keeps_mame_blunder_auto_takeback(self):
        self.assertTrue(
            should_auto_takeback_mame_blunder(
                Mode.NORMAL,
                emulation_mode=True,
                evaluation="??",
                repeated_move=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
