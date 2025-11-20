#!/usr/bin/env python3

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import asyncio
import unittest
from unittest.mock import patch

from uci.engine import UciEngine, UciShell
from uci.rating import Rating, Result

UCI_ELO = "UCI_Elo"
UCI_ELO_NON_STANDARD = "UCI Elo"


class MockEngine(object):
    def __init__(self, *args, **kwargs):
        self.options = {UCI_ELO: None}

    async def configure(self, options):
        pass

    async def ping(self):
        pass

    def uci(self):
        pass


@patch("chess.engine.UciProtocol", new=MockEngine)
class TestEngine(unittest.IsolatedAsyncioTestCase):
    def __init__(self, tests=()):
        super().__init__(tests)
        self.loop = asyncio.get_event_loop()

    async def test_engine_uses_elo(self):
        eng = UciEngine("some_test_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "1400"})
        self.assertEqual(1400, eng.engine_rating)

    async def test_engine_uses_elo_non_standard_option(self):
        eng = UciEngine("some_test_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO_NON_STANDARD: "1400"})
        self.assertEqual(1400, eng.engine_rating)

    async def test_engine_uses_rating(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "aUtO"}, Rating(1345.5, 123.0))
        self.assertEqual(1350, eng.engine_rating)  # rounded to next 50

    async def test_engine_uses_rating_non_standard_option(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO_NON_STANDARD: "aUtO"}, Rating(1345.5, 123.0))
        self.assertEqual(1350, eng.engine_rating)  # rounded to next 50

    async def test_engine_adaptive_when_using_auto(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto"}, Rating(1345.5, 123.0))
        self.assertTrue(eng.is_adaptive)
        self.assertEqual(1350, eng.engine_rating)  # rounded to next 50

    async def test_engine_adaptive_when_using_auto_non_standard_option(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO_NON_STANDARD: "auto"}, Rating(1345.5, 123.0))
        self.assertTrue(eng.is_adaptive)
        self.assertEqual(1350, eng.engine_rating)  # rounded to next 50

    async def test_engine_not_adaptive_when_using_auto_and_no_rating(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto"}, None)
        self.assertFalse(eng.is_adaptive)
        self.assertEqual(-1, eng.engine_rating)

    async def test_engine_not_adaptive_when_not_using_auto(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "1234"}, Rating(1345.5, 123.0))
        self.assertFalse(eng.is_adaptive)
        self.assertEqual(1234, eng.engine_rating)

    async def test_engine_has_rating_as_information_when_not_adaptive(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "1234"}, None)
        self.assertFalse(eng.is_adaptive)
        self.assertEqual(1234, eng.engine_rating)

    async def test_engine_has_rating_as_information_when_not_adaptive_non_standard_option(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO_NON_STANDARD: "1234"}, None)
        self.assertFalse(eng.is_adaptive)
        self.assertEqual(1234, eng.engine_rating)

    async def test_invalid_value_for_uci_elo(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "XXX"}, Rating(450.5, 123.0))
        self.assertEqual(-1, eng.engine_rating)

    async def test_engine_does_not_eval_for_no_rating(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "max(auto, 800)"}, None)
        self.assertEqual(-1, eng.engine_rating)

    async def test_engine_uses_eval_for_rating(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "max(auto, 800)"}, Rating(450.5, 123.0))
        self.assertEqual(800, eng.engine_rating)

    async def test_engine_uses_eval_for_rating_non_standard_option(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO_NON_STANDARD: "max(auto, 800)"}, Rating(450.5, 123.0))
        self.assertEqual(800, eng.engine_rating)

    async def test_simple_eval(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto + 100"}, Rating(850.5, 123.0))
        self.assertEqual(950, eng.engine_rating)

    async def test_fancy_eval(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup(
            {UCI_ELO: 'exec("import random; random.seed();") or max(800, (auto + random.randint(10,80)))'},
            Rating(850.5, 123.0),
        )
        self.assertGreater(eng.engine_rating, 859)
        self.assertLess(eng.engine_rating, 931)

    async def test_eval_syntax_error(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "max(auto,"}, Rating(450.5, 123.0))
        self.assertEqual(-1, eng.engine_rating)

    async def test_eval_error(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: 'max(auto, "abc")'}, Rating(450.5, 123.0))
        self.assertEqual(-1, eng.engine_rating)

    @patch("uci.engine.write_picochess_ini")
    async def test_update_rating(self, _):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto"}, Rating(849.5, 123.0))
        self.assertEqual(850, eng.engine_rating)
        await eng.update_rating(Rating(850.5, 123.0), Result.WIN)
        self.assertEqual(900, eng.engine_rating)

    @patch("uci.engine.write_picochess_ini")
    async def test_update_rating_with_eval(self, _):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto + 11"}, Rating(850.5, 123.0))
        self.assertEqual(861, eng.engine_rating)
        new_rating = await eng.update_rating(Rating(850.5, 123.0), Result.WIN)
        self.assertEqual(890, int(new_rating.rating))
        self.assertEqual(901, eng.engine_rating)
