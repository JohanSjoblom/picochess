import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from uci.write import write_engine_ini


class TestManagedVariantSidecars(unittest.TestCase):
    def _run_build(self, include_fairy_uci: bool):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "fairy"
            binary.write_text("engine", encoding="utf-8")
            binary.chmod(0o755)
            variants = root / "variants.ini"
            variants.write_bytes(b"[fairy-atomic]\nfile = fairy\nuci = fairy-atomic.uci\n")
            atomic = root / "fairy-atomic.uci"
            atomic.write_bytes(b"[Atomic@1000]\nVariant = atomic\nUCI_Elo = 1000\n")
            if include_fairy_uci:
                (root / "fairy.uci").write_bytes(b"[Legacy]\nSkill Level = 1\n")

            managed_before = {path.name: path.read_bytes() for path in (variants, atomic)}
            engine = Mock()
            engine.has_levels.return_value = True
            engine.has_limit_strength.return_value = False
            engine.has_skill_level.return_value = False
            engine.has_handicap_level.return_value = False
            engine.has_strength.return_value = False
            engine.get_name.return_value = "Fairy-Stockfish"
            engine.get_options.return_value = {}

            with patch("uci.write.UciEngine", return_value=engine), patch(
                "uci.write.asyncio.get_event_loop", return_value=Mock()
            ):
                write_engine_ini(str(root))

            self.assertEqual(managed_before, {path.name: path.read_bytes() for path in (variants, atomic)})
            self.assertTrue((root / "fairy.uci").is_file())

    def test_existing_legacy_sidecar_does_not_change_managed_profiles(self):
        self._run_build(include_fairy_uci=True)

    def test_fresh_package_generates_only_legacy_sidecar(self):
        self._run_build(include_fairy_uci=False)


if __name__ == "__main__":
    unittest.main()
