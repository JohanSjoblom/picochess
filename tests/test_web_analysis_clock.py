import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

APP_JS = Path(__file__).parents[1] / "web/picoweb/static/js/app.js"


def _functions(app: str, names) -> str:
    parts = []
    for name in names:
        start = app.index("function " + name + "(")
        end = app.index("\n}", start) + 2
        parts.append(app[start:end])
    return "\n".join(parts)


class TestPonderClockAfterGameEnd(unittest.TestCase):
    """In Ponder the clock shows the result of a finished position, not the last analysis (#527)."""

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_finished_position_keeps_result_text_until_another_position(self):
        app = APP_JS.read_text(encoding="utf-8")
        program = _functions(
            app,
            (
                "isAnalysisClockMode",
                "_buildAnalysisClockLine",
                "stopAnalysisClock",
                "isTerminalPosition",
                "markFinishedPosition",
                "updateFinishedPosition",
                "showsFinishedPosition",
                "showBackendClockText",
                "enterAnalysisClockMode",
                "updateAnalysisClock",
            ),
        )
        program += r"""
var assert = require('assert');
var Chess = require(CHESS_JS).Chess;
var window = {_picoSystemInfo: {interaction_mode: 'ponder'}};
var chessGameType = 0;
var clockText = '';
var dgtClockTextEl = {html: function (text) { clockText = text; }};
var analysisClockData = null;
var lastPositionFen = '';
var finishedPositionFen = null;
var finishedPositionClockText = null;
// The Clock handler's condition in ws.onmessage.
function clockMessage(text) {
    showBackendClockText(text);
}
var before = '6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1';
var mate = 'rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3';
var analysis = {fen: before, depth: 40, score: 99998, mate: 1, pv: ['Ra8#']};
assert.strictEqual(isTerminalPosition(before), false);
assert.strictEqual(isTerminalPosition(mate), true);

updateFinishedPosition(before);
updateAnalysisClock(analysis);
var analysisLine = clockText;
assert(analysisLine.indexOf('Ra8') >= 0, analysisLine);
clockMessage('5:00 5:00');
assert.strictEqual(clockText, analysisLine, 'Ponder ignores clock text while analysing');

// The mating move, then GameEnd and the backend's result text.
updateFinishedPosition(mate);
markFinishedPosition();
clockMessage('Checkmate');
assert.strictEqual(clockText, 'Checkmate');
updateAnalysisClock(analysis);
updateAnalysisClock({source: 'engine', clear: true});
assert.strictEqual(clockText, 'Checkmate', 'stale analysis must not replace the result');
window._picoSystemInfo.interaction_mode = 'normal';
clockMessage('Analysis mode');
window._picoSystemInfo.interaction_mode = 'ponder';
enterAnalysisClockMode();
assert.strictEqual(clockText, 'Checkmate', 'entering Ponder restores the result');
clockMessage('Analysis mode');
assert.strictEqual(clockText, 'Checkmate', 'mode text must not replace the result');
updateFinishedPosition(mate);
assert.strictEqual(clockText, 'Checkmate', 'the same position again keeps the result');

// Takeback: analysis takes over again.
updateFinishedPosition(before);
assert.strictEqual(clockText, '');
assert.strictEqual(showsFinishedPosition(), false);
updateAnalysisClock(analysis);
assert.strictEqual(clockText, analysisLine);
"""
        program = program.replace("CHESS_JS", json.dumps(str(APP_JS.parent / "chess960.min.js")))
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
            handle.write(program)
            script = handle.name
        try:
            result = subprocess.run(["node", script], capture_output=True, text=True, timeout=10)
        finally:
            os.unlink(script)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_message_handlers_track_finished_positions(self):
        app = APP_JS.read_text(encoding="utf-8").replace("\r\n", "\n")

        def handler(event):
            start = app.index("case '" + event + "':")
            return app[start:app.index("break;", start)]

        self.assertIn("updateFinishedPosition(data.fen);", handler("Fen"))
        self.assertIn("finishedPositionFen = null;", handler("Game"))
        self.assertIn("markFinishedPosition();", handler("GameEnd"))
        self.assertIn("if (isDefinitiveResult(_res)) {", handler("Header"))
        self.assertIn("if (isTerminalPosition(lastPositionFen)) {", handler("Header"))
        self.assertIn("showBackendClockText(data.msg);", handler("Clock"))
        self.assertIn("enterAnalysisClockMode();", handler("SystemInfo"))

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_final_result_on_playable_position_keeps_analysis(self):
        app = APP_JS.read_text(encoding="utf-8")
        program = _functions(app, ("isTerminalPosition", "isDefinitiveResult"))
        program += "\nvar Chess = require(" + json.dumps(str(APP_JS.parent / "chess960.min.js")) + ").Chess;\n"
        program += """
var assert = require('assert');
var chessGameType = 0;
var playable = '6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1';
var mate = 'rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3';
var stalemate = '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1';
assert.strictEqual(isDefinitiveResult('1-0'), true);
assert.strictEqual(isTerminalPosition(playable), false, 'resignation leaves legal moves');
assert.strictEqual(isTerminalPosition(mate), true, 'checkmate survives reconnect');
assert.strictEqual(isTerminalPosition(stalemate), true, 'stalemate survives reconnect');
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
