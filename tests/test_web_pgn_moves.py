"""Execute the browser's PGN move detection without loading the UI."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is required for browser JavaScript tests")
class TestWebPgnMoves(unittest.TestCase):
    def test_move_detection_ignores_headers_and_comments(self):
        script = (Path(__file__).parents[1] / "web/picoweb/static/js/app.js").read_text(encoding="utf-8")
        start = script.index("function pgnTextHasMoves(")
        end = script.index("\n}", start) + 2
        root = '[Date "2026.09.05"]\n[SetUp "1"]\n[FEN "8/8/8/8/8/8/4K3/7k w - - 0 1"]\n\n'
        cases = [
            (None, False),
            ("", False),
            (root + "*", False),
            ('[Event "1. e4"]\n\n*', False),
            ('[Event "A \\"quote\\" 1. e4"]\n\n*', False),
            (root + "{Try 1. e4\nthen 1... e5} *", False),
            (root + "; 1. e4\n% 1... e5\n*", False),
            ("1. *", False),
            ("1-0", False),
            ("0-1", False),
            ("1/2-1/2", False),
            (root + "1. Kf3 *", True),
            ("1.e4 e5 2.Nf3 *", True),
            ("23... Nxd4+ *", True),
            ("1. {A comment} e4 *", True),
            ("1. O-O *", True),
            ("1... 0-0-0 *", True),
            ("1. e8=Q+ *", True),
            ("e4 e5 *", True),
        ]
        program = script[start:end] + "\nconsole.log(JSON.stringify(" + json.dumps(
            [pgn for pgn, _ in cases]
        ) + ".map(pgnTextHasMoves)));"
        result = subprocess.run(
            ["node", "-e", program], capture_output=True, text=True, check=True, timeout=10
        )
        for (pgn, expected), actual in zip(cases, json.loads(result.stdout), strict=True):
            with self.subTest(pgn=pgn):
                self.assertEqual(expected, actual)

    def test_export_uses_root_fen_side_and_fullmove_number(self):
        root = Path(__file__).parents[1]
        app = (root / "web/picoweb/static/js/app.js").read_text(encoding="utf-8")
        chess = (root / "web/picoweb/static/js/chess960.min.js").read_text(encoding="utf-8")
        exporter_start = app.index("function PgnExporter(")
        exporter_end = app.index("function cloneMainlineToNode(", exporter_start)
        exporter = app[exporter_start:exporter_end]
        program = chess + "\nvar chessGameType = 0;\n" + exporter + r"""
function exportLine(fen, moves) {
    var root = {fen: fen, previous: null, variations: []};
    var parent = root;
    var board = new Chess(fen, chessGameType);
    moves.forEach(function (uci, index) {
        var move = board.move({from: uci.slice(0, 2), to: uci.slice(2, 4)});
        if (!move) throw new Error('illegal test move: ' + uci);
        var node = {
            move: move,
            previous: parent,
            variations: [],
            nags: [],
            half_move_num: index + 1
        };
        parent.variations = [node];
        parent = node;
    });
    var out = new PgnExporter();
    exportGame(root, out, false, false, undefined, false);
    return out.toString();
}
var cases = [
    exportLine(
        'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
        ['e2e4', 'e7e5', 'g1f3']
    ),
    exportLine(
        'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1',
        ['b8c6', 'g1f3', 'g8f6']
    ),
    exportLine(
        'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 23',
        ['b8c6', 'g1f3']
    )
];
console.log(JSON.stringify(cases));
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True, text=True, check=True, timeout=10
        )
        self.assertEqual(
            ["1. e4 e5 2. Nf3", "1... Nc6 2. Nf3 Nf6", "23... Nc6 24. Nf3"],
            json.loads(result.stdout),
        )
