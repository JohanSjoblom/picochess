"""Execute the browser's PGN move detection without loading the UI."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is required for browser JavaScript tests")
class TestWebPgnMoves(unittest.TestCase):
    def test_dgt_battery_footer_uses_live_system_info_and_connection_status(self):
        root = Path(__file__).parents[1]
        script = (root / "web/picoweb/static/js/app.js").read_text(encoding="utf-8")
        template = (root / "web/picoweb/templates/clock.html").read_text(encoding="utf-8")
        css = (root / "web/picoweb/static/css/base.css").read_text(encoding="utf-8")

        self.assertIn('id="picoFooterBattery"', template)
        self.assertIn("function updateDgtBatteryStatus()", script)
        self.assertIn("dgtBoardConnected = true", script)
        self.assertIn("dgtBoardConnected = false", script)
        self.assertIn(
            "Object.assign(window._picoSystemInfo, data.msg);\n"
            "                        updateDgtBatteryStatus();",
            script,
        )
        self.assertIn(".footer-battery-low .footer-battery-body", css)
        self.assertIn("--battery-level", css)

        start = script.index("function dgtBatteryPresentation(")
        end = script.index("\n}\n\nfunction updateDgtBatteryStatus", start) + 2
        program = script[start:end] + (
            "\nconsole.log(JSON.stringify(["
            "dgtBatteryPresentation('42%', true),"
            "dgtBatteryPresentation('15%', true),"
            "dgtBatteryPresentation('9%', true),"
            "dgtBatteryPresentation('N/A', true),"
            "dgtBatteryPresentation('42%', false)"
            "]));"
        )
        result = subprocess.run(
            ["node", "-e", program], capture_output=True, text=True, check=True, timeout=10
        )
        states = json.loads(result.stdout)
        self.assertEqual("footer-battery-good", states[0]["className"])
        self.assertEqual("footer-battery-medium", states[1]["className"])
        self.assertEqual("footer-battery-low", states[2]["className"])
        self.assertEqual("—", states[3]["text"])
        self.assertEqual("—", states[4]["text"])

    def test_terminal_variant_display_uses_authoritative_server_fen(self):
        script = (Path(__file__).parents[1] / "web/picoweb/static/js/app.js").read_text(encoding="utf-8")
        start = script.index("function authoritativeDisplayFen(")
        end = script.index("\n}", start) + 2
        atomic_terminal_fen = "r1bq3r/p1ppp1pp/1pn5/8/8/8/PPPPPPPP/RNBQKB1R b KQ - 0 3"
        program = script[start:end] + "\n" + (
            f"console.log(authoritativeDisplayFen({{fen: {json.dumps(atomic_terminal_fen)}}}, "
            "{fen: () => 'startpos'}));"
        )
        result = subprocess.run(
            ["node", "-e", program], capture_output=True, text=True, check=True, timeout=10
        )

        self.assertEqual(atomic_terminal_fen, result.stdout.strip())

    def test_web_exporter_marks_black_move_number_after_variation(self):
        script = (Path(__file__).parents[1] / "web/picoweb/static/js/app.js").read_text(encoding="utf-8")
        start = script.index("function WebExporter(")
        end = script.index("\nfunction PgnExporter(", start)
        program = script[start:end] + "\nconst exporter = new WebExporter();\n" + (
            "exporter.put_fullmove_number('b', 47, true);\n"
            "console.log(exporter.toString());"
        )
        result = subprocess.run(
            ["node", "-e", program], capture_output=True, text=True, check=True, timeout=10
        )

        self.assertEqual(
            '<span class="variationResumeMoveNumber">47... </span>',
            result.stdout.strip(),
        )

        css = (Path(__file__).parents[1] / "web/picoweb/static/css/base.css").read_text(encoding="utf-8")
        self.assertIn(
            "#pgn.pgn-variations-hidden .variationResumeMoveNumber",
            css,
        )

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

    def test_set_position_prefix_stops_at_selected_node(self):
        root = Path(__file__).parents[1]
        app = (root / "web/picoweb/static/js/app.js").read_text(encoding="utf-8")
        chess = (root / "web/picoweb/static/js/chess960.min.js").read_text(encoding="utf-8")
        exporter_start = app.index("function PgnExporter(")
        exporter_end = app.index("function writeVariationTree(", exporter_start)
        prefix_code = app[exporter_start:exporter_end]
        program = chess + "\n" + prefix_code + r"""
var chessGameType = 0;
var START_FEN = new Chess().fen();
var setupBoardFen = START_FEN;
var gameHistory = {
    fen: START_FEN,
    previous: null,
    variations: [],
    originalHeader: {Result: '*'}
};
function getPgnGameHeader(headers) {
    var result = '';
    Object.keys(headers).forEach(function (key) {
        result += '[' + key + ' "' + headers[key] + '"]\n';
    });
    return result + '\n';
}
var board = new Chess();
var parent = gameHistory;
var nodes = [];
['e2e4', 'e7e5', 'g1f3', 'b8c6'].forEach(function (uci, index) {
    var move = board.move({from: uci.slice(0, 2), to: uci.slice(2, 4)});
    var node = {
        move: move,
        previous: parent,
        variations: [],
        nags: [],
        half_move_num: index + 1,
        fen: board.fen()
    };
    parent.variations = [node];
    parent = node;
    nodes.push(node);
});
console.log(JSON.stringify(buildPgnPrefixForNode(nodes[1])));
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True, text=True, check=True, timeout=10
        )
        prefix = json.loads(result.stdout)
        self.assertIn("1. e4 e5", prefix)
        self.assertNotIn("Nf3", prefix)
        self.assertNotIn("Nc6", prefix)
        self.assertTrue(prefix.endswith("*"))
