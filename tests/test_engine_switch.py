from types import SimpleNamespace
import unittest

import chess
import chess.variant

from engine_switch import (
    confirmation_matches,
    game_context_fingerprint,
    has_protected_game_context,
    variant_switch_forbidden,
    variant_switch_requires_confirmation,
    variant_from_level_name,
    variant_level_elo,
)


def _state(game=None, variant="chess", **overrides):
    values = {
        "game": game or chess.Board(),
        "variant": variant,
        "done_computer_fen": None,
        "loaded_pgn_filename": "",
        "game_started": False,
        "game_generation": 7,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestEngineSwitchPolicy(unittest.TestCase):
    def test_variant_level_aliases_share_one_mapping(self):
        self.assertEqual("kingofthehill", variant_from_level_name("KotH@1500"))
        self.assertEqual("racingkings", variant_from_level_name("RK@2000"))
        self.assertEqual("antichess", variant_from_level_name("Anti@1000"))
        self.assertEqual(1500, variant_level_elo("KotH@1500"))
        self.assertIsNone(variant_level_elo("Elo@1500"))
        self.assertIsNone(variant_level_elo("KotH@custom"))

    def test_untouched_variant_start_does_not_require_confirmation(self):
        state = _state(chess.variant.RacingKingsBoard(), "racingkings")

        self.assertFalse(has_protected_game_context(state))
        self.assertFalse(variant_switch_requires_confirmation(state, "chess"))

        state = _state(chess.Board(), "3check")
        self.assertFalse(has_protected_game_context(state))
        self.assertFalse(variant_switch_requires_confirmation(state, "chess"))

    def test_game_started_counts_even_without_moves(self):
        state = _state(game_started=True)

        self.assertTrue(variant_switch_requires_confirmation(state, "atomic"))

    def test_custom_root_position_counts_without_moves(self):
        state = _state(chess.Board("8/8/8/8/8/8/4K3/7k w - - 0 1"))

        self.assertTrue(has_protected_game_context(state))

    def test_pending_engine_move_and_loaded_pgn_count(self):
        self.assertTrue(has_protected_game_context(_state(done_computer_fen="pending")))
        self.assertTrue(has_protected_game_context(_state(loaded_pgn_filename="game.pgn")))

    def test_fingerprint_changes_after_move_but_not_for_clock_or_evaluation(self):
        state = _state()
        fingerprint = game_context_fingerprint(state)
        state.clock_time = 123
        state.evaluation = 0.42
        self.assertEqual(fingerprint, game_context_fingerprint(state))

        state.game.push_uci("e2e4")
        self.assertNotEqual(fingerprint, game_context_fingerprint(state))

    def test_confirmation_requires_generation_and_fingerprint(self):
        state = _state()
        fingerprint = game_context_fingerprint(state)

        self.assertTrue(confirmation_matches(state, 7, fingerprint))
        self.assertFalse(confirmation_matches(state, 8, fingerprint))
        self.assertFalse(confirmation_matches(state, 7, "stale"))

    def test_externally_authoritative_modes_refuse_variant_switch(self):
        for mode in ("observe", "remote", "engine_match"):
            with self.subTest(mode=mode):
                state = _state(interaction_mode=mode)
                self.assertTrue(variant_switch_forbidden(state, "atomic"))

        self.assertFalse(variant_switch_forbidden(_state(interaction_mode="analysis"), "atomic"))


if __name__ == "__main__":
    unittest.main()
