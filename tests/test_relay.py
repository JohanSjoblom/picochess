import asyncio
import unittest

import chess

from relay.relay import Relay, RelayError, _endpoint_urls


START_FEN = chess.Board().fen(en_passant="fen")


def position_event(event="Game", play="newgame", fen=START_FEN, move="0000"):
    return {
        "event": event,
        "play": play,
        "fen": fen,
        "move": move,
        "variant": "chess",
    }


class FakeEndpoint:
    def __init__(self, name, initial_fen=START_FEN, acknowledge=True):
        self.name = name
        self.board = None
        self.connected = False
        self.closed = False
        self.acknowledge = acknowledge
        self.sent = []
        self.messages = asyncio.Queue()
        self.messages.put_nowait(position_event(fen=initial_fen))

    async def connect(self):
        self.connected = True

    async def receive(self):
        return await self.messages.get()

    async def send_move(self, move, resulting_fen):
        self.sent.append((move, resulting_fen))
        if self.acknowledge:
            self.messages.put_nowait(
                position_event(event="Fen", play="user", fen=resulting_fen, move=move.uci())
            )

    async def close(self):
        self.closed = True


class TestRelay(unittest.IsolatedAsyncioTestCase):
    async def test_arm_accepts_identical_positions_and_ignores_snapshot_play_value(self):
        first = FakeEndpoint("A")
        second = FakeEndpoint("B")
        first.messages = asyncio.Queue()
        first.messages.put_nowait(position_event(event="Fen", play="computer", move="e2e4"))
        relay = Relay(first, second)

        fen = await relay.arm()

        self.assertEqual(START_FEN, fen)
        self.assertTrue(relay.armed)
        self.assertEqual([], second.sent)

    async def test_arm_rejects_different_positions(self):
        moved = chess.Board()
        moved.push_uci("e2e4")
        first = FakeEndpoint("A")
        second = FakeEndpoint("B", moved.fen(en_passant="fen"))
        relay = Relay(first, second)

        with self.assertRaisesRegex(RelayError, "positions differ"):
            await relay.arm()

    async def test_engine_move_is_forwarded_and_user_event_is_only_acknowledged(self):
        first = FakeEndpoint("A")
        second = FakeEndpoint("B")
        relay = Relay(first, second)
        await relay.arm()
        expected = chess.Board()
        expected.push_uci("e2e4")
        expected_fen = expected.fen(en_passant="fen")

        await relay.process_event(
            first,
            position_event(event="Fen", play="computer", fen=expected_fen, move="e2e4"),
        )
        acknowledgement = await second.receive()
        await relay.process_event(second, acknowledgement)

        self.assertEqual([(chess.Move.from_uci("e2e4"), expected_fen)], second.sent)
        self.assertEqual(expected_fen, first.board.fen(en_passant="fen"))
        self.assertEqual(expected_fen, second.board.fen(en_passant="fen"))
        self.assertIsNone(relay.pending_move)
        self.assertEqual([], first.sent)

    async def test_unexpected_user_move_stops_as_desynchronization(self):
        first = FakeEndpoint("A")
        second = FakeEndpoint("B")
        relay = Relay(first, second)
        await relay.arm()

        with self.assertRaisesRegex(RelayError, "unexpected user move"):
            await relay.process_event(
                first,
                position_event(event="Fen", play="user", fen=START_FEN, move="e2e4"),
            )

    async def test_same_position_reload_allows_switch_sides_after_arming(self):
        first = FakeEndpoint("A")
        second = FakeEndpoint("B")
        relay = Relay(first, second)
        await relay.arm()

        result = await relay.process_event(
            first,
            position_event(event="Fen", play="reload", fen=START_FEN, move="0000"),
        )

        self.assertIsNone(result)
        self.assertIsNone(relay.pending_move)

    async def test_position_changing_reload_stops_as_desynchronization(self):
        first = FakeEndpoint("A")
        second = FakeEndpoint("B")
        relay = Relay(first, second)
        await relay.arm()
        moved = chess.Board()
        moved.push_uci("e2e4")

        with self.assertRaisesRegex(RelayError, "reload changed"):
            await relay.process_event(
                first,
                position_event(
                    event="Fen",
                    play="reload",
                    fen=moved.fen(en_passant="fen"),
                    move="e2e4",
                ),
            )

    async def test_terminal_source_reload_is_accepted_before_destination_ack(self):
        before_mate = chess.Board()
        for move in ("f2f3", "e7e5", "g2g4"):
            before_mate.push_uci(move)
        initial_fen = before_mate.fen(en_passant="fen")
        first = FakeEndpoint("A", initial_fen)
        second = FakeEndpoint("B", initial_fen, acknowledge=False)
        relay = Relay(first, second)
        await relay.arm()
        after_mate = before_mate.copy()
        after_mate.push_uci("d8h4")
        mate_fen = after_mate.fen(en_passant="fen")

        await relay.process_event(
            first,
            position_event(event="Fen", play="computer", fen=mate_fen, move="d8h4"),
        )
        result = await relay.process_event(
            first,
            position_event(event="Fen", play="reload", fen=mate_fen, move="d8h4"),
        )

        self.assertIsNone(result)
        self.assertIsNotNone(relay.pending_move)
        self.assertTrue(first.board.is_checkmate())

    async def test_nonterminal_source_reload_is_rejected_while_ack_is_pending(self):
        first = FakeEndpoint("A")
        second = FakeEndpoint("B", acknowledge=False)
        relay = Relay(first, second)
        await relay.arm()
        moved = chess.Board()
        moved.push_uci("e2e4")
        moved_fen = moved.fen(en_passant="fen")
        await relay.process_event(
            first,
            position_event(event="Fen", play="computer", fen=moved_fen, move="e2e4"),
        )

        with self.assertRaisesRegex(RelayError, "unexpected reload while a move is pending"):
            await relay.process_event(
                first,
                position_event(event="Fen", play="reload", fen=moved_fen, move="e2e4"),
            )

    async def test_new_game_and_game_end_return_normal_stop_reasons(self):
        first = FakeEndpoint("A")
        second = FakeEndpoint("B")
        relay = Relay(first, second)
        await relay.arm()

        self.assertIn("new game", await relay.process_event(first, position_event()))
        self.assertIn(
            "game ended",
            await relay.process_event(first, {"event": "GameEnd", "result": "1-0"}),
        )

    async def test_run_closes_both_connections_after_game_end(self):
        first = FakeEndpoint("A")
        second = FakeEndpoint("B")
        first.messages.put_nowait({"event": "GameEnd", "result": "1/2-1/2"})
        relay = Relay(first, second)

        reason = await relay.run()

        self.assertIn("game ended", reason)
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)

    async def test_run_times_out_when_destination_does_not_acknowledge(self):
        first = FakeEndpoint("A")
        second = FakeEndpoint("B", acknowledge=False)
        moved = chess.Board()
        moved.push_uci("e2e4")
        first.messages.put_nowait(
            position_event(
                event="Fen",
                play="computer",
                fen=moved.fen(en_passant="fen"),
                move="e2e4",
            )
        )
        relay = Relay(first, second, timeout=0.01)

        with self.assertRaisesRegex(RelayError, "timed out waiting"):
            await relay.run()

        self.assertTrue(first.closed)
        self.assertTrue(second.closed)

    async def test_nonstandard_variant_is_rejected_while_arming(self):
        first = FakeEndpoint("A")
        second = FakeEndpoint("B")
        first.messages = asyncio.Queue()
        event = position_event()
        event["variant"] = "atomic"
        first.messages.put_nowait(event)

        with self.assertRaisesRegex(RelayError, "standard chess only"):
            await Relay(first, second).arm()


class TestRelayUrls(unittest.TestCase):
    def test_http_base_url(self):
        self.assertEqual(
            ("ws://pico.local:8080/event", "http://pico.local:8080/channel"),
            _endpoint_urls("http://pico.local:8080/"),
        )

    def test_https_and_base_path(self):
        self.assertEqual(
            ("wss://host/pico/event", "https://host/pico/channel"),
            _endpoint_urls("https://host/pico"),
        )

    def test_scheme_is_optional(self):
        self.assertEqual(
            ("ws://pico-a:8080/event", "http://pico-a:8080/channel"),
            _endpoint_urls("pico-a:8080"),
        )
