import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
APP_JS = ROOT / "web/picoweb/static/js/app.js"
CHESS_JS = ROOT / "web/picoweb/static/js/chess960.min.js"


def _functions(app: str, names) -> str:
    parts = []
    for name in names:
        start = app.index("function " + name + "(")
        end = app.index("\n}", start) + 2
        parts.append(app[start:end])
    return "\n".join(parts)


class TestWebMoveNumbers(unittest.TestCase):
    """The first move of a game that starts with Black keeps its "1..." number (#526)."""

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_first_black_move_number_is_not_hidden_with_sidelines(self):
        app = APP_JS.read_text(encoding="utf-8")
        program = CHESS_JS.read_text(encoding="utf-8") + "\n"
        program += _functions(app, ("WebExporter", "PgnExporter", "exportGame", "stripFen"))
        program += r"""
var assert = require('assert');
var chessGameType = 0;
var simpleNags = {};
function formatPgnWindowMove(move) { return move.san; }
function figurinizeMove(move) { return move; }

// 1... Rxc3 2. bxc3 (2. Kd1) 2... Kd7, starting from a position with Black to move.
function node(fen, previous) { return {fen: fen, previous: previous, variations: [], nags: [], comment: ''}; }
function play(parent, san) {
    var board = new Chess(parent.fen, chessGameType);
    var move = board.move(san);
    var child = node(board.fen(), parent);
    child.move = move;
    parent.variations.push(child);
    return child;
}
var root = node('2r1k3/8/8/8/8/2N5/1P6/4K3 b - - 0 1', null);
var first = play(root, 'Rxc3');
var second = play(first, 'bxc3');
play(first, 'Kd1');
play(second, 'Kd7');

var web = new WebExporter();
exportGame(root, web, true, true, undefined, false);
var html = web.toString();
var firstMove = html.indexOf('gameMove');
assert(firstMove > 0, html);
var beforeFirstMove = html.slice(0, firstMove);
assert(/1\.\.\. /.test(beforeFirstMove), 'first move has its number: ' + html);
assert(beforeFirstMove.indexOf('variationResumeMoveNumber') < 0, 'first move number is not hideable: ' + html);
assert(html.indexOf('<span class="variationResumeMoveNumber">2... </span>') >= 0,
       'the resume after a sideline stays hideable: ' + html);

var pgn = new PgnExporter();
exportGame(root, pgn, true, true, undefined, false);
assert.strictEqual(pgn.toString(), '1... Rxc3 2. bxc3 ( 2. Kd1 ) 2... Kd7');
"""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
            handle.write(program)
            script = handle.name
        try:
            result = subprocess.run(["node", script], capture_output=True, text=True, timeout=10)
        finally:
            os.unlink(script)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
