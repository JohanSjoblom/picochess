"""Exercise browser analysis-clock formatting and game-result display."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

APP_JS = Path(__file__).parents[1] / "web/picoweb/static/js/app.js"


def _functions(app: str, names) -> str:
    parts = []
    for name in names:
        start = app.index("function " + name + "(")
        end = app.index("\n}", start) + 2
        parts.append(app[start:end])
    return "\n".join(parts)


@unittest.skipUnless(shutil.which("node"), "Node.js is required for browser JavaScript tests")
class TestWebAnalysisClock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = (Path(__file__).parents[1] / "web/picoweb/static/js/app.js").read_text(
            encoding="utf-8"
        )
        start = script.index("function analysisClockModeChanged(")
        end = script.index("\nfunction stopAnalysisClock(", start)
        cls.analysis_clock_functions = script[start:end]

    def run_node(self, body):
        program = "var window = {};\n" + self.analysis_clock_functions + "\n" + body
        result = subprocess.run(
            ["node", "-e", program], capture_output=True, text=True, check=True, timeout=10
        )
        return json.loads(result.stdout)

    def test_localizes_san_piece_letters_for_supported_languages(self):
        result = self.run_node(
            "console.log(JSON.stringify(["
            "localizeSanPieceLetters('Qxe5+', 'nl'),"
            "localizeSanPieceLetters('R1e2', 'nl'),"
            "localizeSanPieceLetters('Nf3', 'de'),"
            "localizeSanPieceLetters('Bxc6', 'fr'),"
            "localizeSanPieceLetters('Kf2', 'es'),"
            "localizeSanPieceLetters('e8=Q+', 'it'),"
            "localizeSanPieceLetters('Qxe5+', 'en')"
            "]));"
        )

        self.assertEqual(["Dxe5+", "T1e2", "Sf3", "Fxc6", "Rf2", "e8=D+", "Qxe5+"], result)

    def test_analysis_clock_uses_the_configured_language(self):
        result = self.run_node(
            "window._picoCurrentSettings = {language: 'nl'};"
            "console.log(JSON.stringify(_buildAnalysisClockLine({"
            "fen: '8/8/8/8/8/8/8/K6k w - - 0 24',"
            "pv: ['Qxe5+'], depth: 27, score: 234"
            "})));"
        )

        self.assertEqual("24. Dxe5+ d27 +2.34", result)

    def test_analysis_clock_falls_back_to_live_system_language(self):
        result = self.run_node(
            "window._picoSystemInfo = {language: 'nl'};"
            "console.log(JSON.stringify(_buildAnalysisClockLine({"
            "fen: '8/8/8/8/8/8/8/K6k b - - 0 24',"
            "pv: ['Nf3'], depth: 10, mate: -3"
            "})));"
        )

        self.assertEqual("24...Pf3 d10 #-3", result)

    def test_partial_system_info_update_keeps_ponder_mode(self):
        result = self.run_node(
            "window._picoSystemInfo = {interaction_mode: 'ponder', language: 'en'};"
            "console.log(JSON.stringify({"
            "changed: updateAnalysisClockSystemInfo({battery: 67}),"
            "mode: window._picoSystemInfo.interaction_mode"
            "}));"
        )

        self.assertEqual({"changed": False, "mode": "ponder"}, result)

    def test_live_language_update_replaces_stale_settings_cache(self):
        result = self.run_node(
            "window._picoCurrentSettings = {language: 'en'};"
            "window._picoSystemInfo = {interaction_mode: 'ponder', language: 'en'};"
            "updateAnalysisClockSystemInfo({language: 'nl'});"
            "console.log(JSON.stringify({"
            "language: window._picoCurrentSettings.language,"
            "line: _buildAnalysisClockLine({"
            "fen: '8/8/8/8/8/8/8/K6k w - - 0 24',"
            "pv: ['Nf3'], depth: 10, score: 0"
            "})"
            "}));"
        )

        self.assertEqual({"language": "nl", "line": "24. Pf3 d10 0.00"}, result)

    def test_mode_transition_clears_analysis_clock_on_entry_and_exit(self):
        script = (Path(__file__).parents[1] / "web/picoweb/static/js/app.js").read_text(
            encoding="utf-8"
        )
        result = self.run_node(
            "console.log(JSON.stringify(["
            "analysisClockModeChanged('normal', 'ponder'),"
            "analysisClockModeChanged('ponder', 'normal'),"
            "analysisClockModeChanged('ponder', 'ponder'),"
            "analysisClockModeChanged('normal', 'normal')"
            "]));"
        )

        self.assertEqual([True, True, False, False], result)
        self.assertIn("updateAnalysisClockSystemInfo(data.msg)", script)


class TestPonderClockAfterGameEnd(unittest.TestCase):
    """In Ponder the clock shows the result of a finished position, not the last analysis (#527)."""

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_finished_position_keeps_result_text_until_another_position(self):
        app = APP_JS.read_text(encoding="utf-8")
        program = _functions(
            app,
            (
                "isAnalysisClockMode",
                "analysisClockLanguage",
                "localizeSanPieceLetters",
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
