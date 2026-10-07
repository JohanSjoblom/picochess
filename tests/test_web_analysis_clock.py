"""Exercise the browser-side analysis-clock formatting without loading the UI."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


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
        self.assertIn("analysisClockModeChanged(_prevMode, data.msg.interaction_mode)", script)
