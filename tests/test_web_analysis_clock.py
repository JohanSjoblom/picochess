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
                "markFinishedPosition",
                "updateFinishedPosition",
                "showsFinishedPosition",
                "updateAnalysisClock",
            ),
        )
        program += r"""
var assert = require('assert');
var window = {_picoSystemInfo: {interaction_mode: 'ponder'}};
var chessGameType = 0;
var clockText = '';
var dgtClockTextEl = {html: function (text) { clockText = text; }};
var analysisClockData = null;
var lastPositionFen = '';
var finishedPositionFen = null;
// The Clock handler's condition in ws.onmessage.
function clockMessage(text) {
    if (!isAnalysisClockMode() || showsFinishedPosition()) { dgtClockTextEl.html(text); }
}
var before = '6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1';
var mate = 'R5k1/5ppp/8/8/8/8/8/1R4K1 b - - 1 1';
var analysis = {fen: before, depth: 40, score: 99998, mate: 1, pv: ['Ra8#']};

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
updateFinishedPosition(mate);
assert.strictEqual(clockText, 'Checkmate', 'the same position again keeps the result');

// Takeback: analysis takes over again.
updateFinishedPosition(before);
assert.strictEqual(clockText, '');
assert.strictEqual(showsFinishedPosition(), false);
updateAnalysisClock(analysis);
assert.strictEqual(clockText, analysisLine);
"""
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
        self.assertIn("markFinishedPosition();", handler("Header"))
        self.assertIn("if (!isAnalysisClockMode() || showsFinishedPosition()) {", handler("Clock"))


if __name__ == "__main__":
    unittest.main()
