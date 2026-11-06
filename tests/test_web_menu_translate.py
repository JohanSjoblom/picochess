"""Exercise live translation changes in the browser overlay menu."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is required for browser JavaScript tests")
class TestWebMenuTranslate(unittest.TestCase):
    def test_static_menu_label_returns_to_english_after_language_switch(self):
        template = (Path(__file__).parents[1] / "web/picoweb/templates/clock.html").read_text(
            encoding="utf-8"
        )
        menu_text_start = template.index("            function menuText(")
        menu_text_end = template.index("            function menuPath(", menu_text_start)
        translate_start = template.index("            function translateStaticMenu(")
        translate_end = template.index("            function applyMenuText(", translate_start)
        functions = template[menu_text_start:menu_text_end] + template[translate_start:translate_end]
        program = """
var menuTextMap = {Mode: 'Modus'};
var textNode = {nodeValue: 'Mode'};
var overlay = {querySelectorAll: function() { return []; }};
var document = {createTreeWalker: function() {
    var returned = false;
    return {nextNode: function() {
        if (returned) return null;
        returned = true;
        return textNode;
    }};
}};
var NodeFilter = {SHOW_TEXT: 4};
""" + functions + """
translateStaticMenu();
var dutch = textNode.nodeValue;
menuTextMap = {Mode: 'Mode'};
translateStaticMenu();
console.log(JSON.stringify({dutch: dutch, english: textNode.nodeValue}));
"""

        result = subprocess.run(
            ["node", "-e", program], capture_output=True, text=True, check=True, timeout=10
        )

        self.assertEqual({"dutch": "Modus", "english": "Mode"}, json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
