"""Exercise browser projection against real PGN trees and raw transport caches."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

import chess
import chess.pgn

from server import EventHandler, DGTHandler
from web_history import history_scope, preserve, project_message, read_game, reset_history


class TestWebHistory(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.shared = {"system_info": {"is_mame": True, "mame_capabilities": {"position": True, "edit": False}}}
        self.board = chess.Board()
        for move in ("e4", "e5", "Nf3", "Nc6"):
            self.board.push_san(move)
        preserve(self.shared, str(chess.pgn.Game.from_board(self.board)), self.board.fen(), "set_position")
        self.live = self.board.copy(stack=False)

    def message(self, board=None, **extra):
        board = board if board is not None else self.live
        return dict(event="Fen", pgn=str(chess.pgn.Game.from_board(board)), fen=board.fen(),
                    history_scope=dict(history_scope(self.shared)), **extra)

    def moves(self, message):
        return [m.uci() for m in read_game(message["pgn"]).mainline_moves()]

    def test_initial_root_and_continuation_are_composed_without_mutation(self):
        self.assertEqual(4, len(self.moves(project_message(self.shared, self.message()))))
        self.live.push_san("Bc4")
        raw = self.message()
        before = copy.deepcopy(self.shared)
        combined = project_message(self.shared, raw)
        self.assertEqual(5, len(self.moves(combined)))
        self.assertEqual(1, len(self.moves(raw)))
        self.assertEqual(before, self.shared)
        self.assertEqual(self.live.fen(), read_game(combined["pgn"]).end().board().fen())
        self.assertNotIn("FEN", read_game(combined["pgn"]).headers)

    def test_takeback_and_alternative_replace_continuation(self):
        self.live.push_san("Bc4")
        self.live.push_san("Nf6")
        self.assertEqual(6, len(self.moves(project_message(self.shared, self.message()))))
        self.live.pop()
        self.live.pop()
        self.assertEqual(4, len(self.moves(project_message(self.shared, self.message()))))
        self.live.push_san("Bb5")
        moves = self.moves(project_message(self.shared, self.message()))
        self.assertEqual("f1b5", moves[-1])
        self.assertNotIn("f1c4", moves)

    def test_repeated_set_position_truncates_combined_line(self):
        self.live.push_san("Bc4")
        combined = read_game(project_message(self.shared, self.message())["pgn"])
        earlier = combined.next().next().board()
        old_scope = dict(history_scope(self.shared))
        preserve(self.shared, str(combined), earlier.fen(), "set_position")
        result = project_message(self.shared, self.message(earlier.copy(stack=False)))
        self.assertEqual(["e2e4", "e7e5"], self.moves(result))
        self.assertEqual(old_scope["gameid"], history_scope(self.shared)["gameid"])
        self.assertGreater(history_scope(self.shared)["revision"], old_scope["revision"])

    def test_repeated_set_position_preserves_selection_after_previous_midpoint(self):
        # The first Set Pos snapshot ends after 2...Nc6. Play beyond that root,
        # then select 3...Nf6 from the composed browser line for another Set Pos.
        for move in ("Bc4", "Nf6", "d3", "Be7"):
            self.live.push_san(move)
        first_projection = project_message(self.shared, self.message())
        combined = read_game(first_projection["pgn"])
        selected = list(combined.mainline())[5]
        selected_board = selected.board()
        selected.variations = []
        old_scope = dict(history_scope(self.shared))

        # This is the complete original-to-selected prefix posted by the web
        # client. The backend and engine are then rebased at 3...Nf6.
        preserve(self.shared, str(combined), selected_board.fen(), "set_position")
        second_live = selected_board.copy(stack=False)
        second_live.push_san("d4")
        second_live.push_san("exd4")

        raw = self.message(second_live)
        result = project_message(self.shared, raw)
        self.assertEqual(["d2d4", "e5d4"], self.moves(raw))
        self.assertEqual(
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "d2d4", "e5d4"],
            self.moves(result),
        )
        self.assertNotIn("d2d3", self.moves(result))
        self.assertNotIn("f8e7", self.moves(result))
        self.assertEqual(old_scope["gameid"], history_scope(self.shared)["gameid"])
        self.assertGreater(history_scope(self.shared)["revision"], old_scope["revision"])

    def test_recovery_keeps_previous_prefix(self):
        self.live.push_san("Bc4")
        preserve(self.shared, self.message()["pgn"], self.live.fen(), "engine_recovery")
        self.live = self.live.copy(stack=False)
        self.live.push_san("Nf6")
        self.assertEqual(6, len(self.moves(project_message(self.shared, self.message()))))

    def test_wrong_root_scope_engine_and_reset_do_not_merge(self):
        raw = self.message(chess.Board())
        self.assertIs(raw, project_message(self.shared, raw))
        raw = self.message()
        raw["history_scope"]["revision"] += 1
        self.assertIs(raw, project_message(self.shared, raw))
        raw = self.message()
        self.shared["system_info"]["mame_capabilities"]["edit"] = True
        self.assertIs(raw, project_message(self.shared, raw))
        self.shared["system_info"]["mame_capabilities"]["edit"] = False
        self.shared["system_info"]["is_mame"] = False
        self.assertIs(raw, project_message(self.shared, raw))
        self.shared["system_info"]["is_mame"] = True
        reset_history(self.shared)
        self.assertIs(raw, project_message(self.shared, raw))

    def test_read_game_truncation_and_custom_root_review_points(self):
        board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 23")
        board.push_san("Nc6")
        selected = board.fen()
        board.push_san("Nf3")
        board.push_san("Nf6")
        reset_history(self.shared)
        preserve(self.shared, str(chess.pgn.Game.from_board(board)), selected, "read_game")
        points = [{"halfmove": 1, "target_halfmove": 1, "reason": "variation"},
                  {"halfmove": 3, "target_halfmove": 2, "reason": "variation"}]
        result = project_message(self.shared, self.message(chess.Board(selected), mistakes=points))
        self.assertEqual(["b8c6"], self.moves(result))
        self.assertEqual([points[0]], result["mistakes"])

    def test_malformed_or_mismatching_transport_falls_back(self):
        raw = self.message()
        raw["fen"] = chess.STARTING_FEN
        self.assertIs(raw, project_message(self.shared, raw))
        raw = self.message()
        raw["pgn"] = '[FEN "invalid"]'
        with patch("chess.pgn.LOGGER.error"):
            self.assertIs(raw, project_message(self.shared, raw))

    def test_custom_black_root_numbering_and_watcher_target(self):
        root = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 23")
        root.push_san("Nc6")
        root.push_san("Nf3")
        preserve(self.shared, str(chess.pgn.Game.from_board(root)), root.fen(), "set_position")
        live = root.copy(stack=False)
        live.push_san("Nf6")
        result = project_message(self.shared, self.message(live, mistakes=[{"halfmove": live.ply()}]))
        self.assertIn("23... Nc6 24. Nf3 Nf6", result["pgn"])
        self.assertEqual(2, result["mistakes"][0]["target_halfmove"])

    async def test_broadcast_reconnect_and_sync_share_projection(self):
        self.live.push_san("Bc4")
        raw = self.message()
        self.shared["last_dgt_move_msg"] = raw
        client = Mock(shared=self.shared)
        client.real_ip.return_value = "127.0.0.1"
        expected = project_message(self.shared, raw)
        with patch.object(EventHandler, "clients", {client}), patch("server.client_ips", []):
            EventHandler.write_to_clients(raw)
            client.write_message.assert_called_with(expected)
            client.reset_mock()
            EventHandler.open(client)
            client.write_message.assert_any_call(expected)
        handler = Mock(shared=self.shared)
        handler.get_argument.return_value = "get_last_move"
        await DGTHandler.get(handler)
        handler.write.assert_called_once_with(expected)
        self.assertEqual(1, len(self.moves(self.shared["last_dgt_move_msg"])))

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_browser_renders_navigates_and_syncs_combined_initial_game(self):
        root = Path(__file__).parents[1]
        app = (root / "web/picoweb/static/js/app.js").read_text()
        functions = []
        for name in ("loadGame", "addNewMove", "setHeaders", "WebExporter", "exportGame",
                     "getWebGameHeader", "writeVariationTree", "stripFen", "isDefinitiveResult",
                     "goToStart", "goToPosition", "findPositionByFen", "fenWithoutEnPassant",
                     "goToDGTFen", "updateDGTPosition", "pgnTextHasMoves"):
            start = app.index("function " + name + "(")
            end = app.index("\n}", start) + 2
            functions.append(app[start:end])
        raw = self.message(play="newgame")
        raw["event"] = "Game"
        payload = project_message(self.shared, raw)
        program = (root / "web/picoweb/static/js/chess960.min.js").read_text() + "\n"
        program += "\n".join(functions) + "\nvar payload = " + json.dumps(payload) + ";\n"
        program += r"""
var assert = require('assert');
var START_FEN = new Chess().fen(), setupBoardFen = START_FEN, chessGameType = 0;
var currentPosition = {fen: payload.fen}, gameHistory = {}, fenHash = {};
var webHistoryMerged = false, webExploreMode = false, computerside = 'w';
var simpleNags = {}, pgnEl = '#pgn', rendered = '', window = {};
function $(el) { return {html: function (text) {rendered = text;}}; }
$.isEmptyObject = function (obj) {return Object.keys(obj).length === 0;};
$.get = function (url, params, callback) { callback(payload); return {fail: function () {}}; };
function setLivePgnTreeActive() {}
function bindPgnFenLinks() {}
function applyPgnVariationVisibility() {}
function syncWebExploreFromCurrentPosition() {}
function shouldAutoExploreLoadedFinishedPgn() {return false;}
function formatPgnWindowMove(move) {return move.san;}
function figurinizeMove(move) {return move;}
function saymove() {}
function stopAnalysis() {}
function removeHighlights() {}
function removeArrow() {}
function updateChessGround() {}
function updateStatus() {}
function stopWebExploreMode() {}
function highlightBoard() {}
function addArrow() {}
function updateTutorMistakes() {}
function isSameGameAsPgn() {return false;}
function newBoard() {throw new Error('Sync must not clear a combined initial game');}
function forcePosition() {throw new Error('Live FEN must exist in combined tree');}
goToDGTFen();
assert.equal((rendered.match(/data-fen=/g) || []).length, 4);
assert.equal(fenWithoutEnPassant(currentPosition.fen), fenWithoutEnPassant(payload.fen));
goToStart();
assert.equal(currentPosition.fen, START_FEN);
assert.equal((rendered.match(/data-fen=/g) || []).length, 4);
var mid = gameHistory.variations[0].variations[0];
assert(goToPosition(mid.fen));
assert.strictEqual(currentPosition, mid);
// Reconnecting delivers backend headers after the composed PGN.
setHeaders({FEN: payload.fen, SetUp: '1', Result: '*'});
assert(!gameHistory.originalHeader.FEN);
goToDGTFen();
assert.equal((rendered.match(/data-fen=/g) || []).length, 4);
assert.equal(fenWithoutEnPassant(currentPosition.fen), fenWithoutEnPassant(payload.fen));
"""
        subprocess.run(["node", "-e", program], capture_output=True, text=True, check=True, timeout=10)
