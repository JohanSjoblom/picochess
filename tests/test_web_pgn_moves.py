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
