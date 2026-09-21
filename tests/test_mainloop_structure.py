import ast
import symtable
import unittest
from pathlib import Path


class MainLoopStructureTest(unittest.TestCase):
    def test_nested_mainloop_has_no_closure_dependencies(self):
        source_path = Path(__file__).parents[1] / "picochess.py"
        source = source_path.read_text(encoding="utf-8")

        tree = ast.parse(source)
        main_function = next(
            node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
        )
        self.assertTrue(
            any(isinstance(node, ast.ClassDef) and node.name == "MainLoop" for node in main_function.body)
        )

        module_table = symtable.symtable(source, str(source_path), "exec")
        main_table = next(child for child in module_table.get_children() if child.get_name() == "main")
        mainloop_table = next(child for child in main_table.get_children() if child.get_name() == "MainLoop")
        free_names = {
            method.get_name(): method.get_frees()
            for method in mainloop_table.get_children()
            if hasattr(method, "get_frees") and method.get_frees()
        }

        self.assertEqual({}, free_names)


if __name__ == "__main__":
    unittest.main()
