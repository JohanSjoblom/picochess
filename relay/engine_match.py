"""One-peer transport for the experimental physical-board engine match mode."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import chess

from .relay import PicoEndpoint, RelayEndpoint, RelayError, _canonical_fen


LOGGER = logging.getLogger(__name__)
INITIAL_POSITION_GRACE_SECONDS = 2.0

RemoteMoveCallback = Callable[[chess.Move, str], Awaitable[None]]
StopCallback = Callable[[str], Awaitable[None]]


class EngineMatchClient:
    """Synchronize a local physical-board game with one NOEBOARD Picochess.

    The local caller decides when a move has really been executed on the
    physical board.  Only then is a local engine move posted to the peer or a
    remote engine move acknowledged locally.
    """

    def __init__(
        self,
        remote_url: str,
        on_remote_move: RemoteMoveCallback,
        on_stop: StopCallback,
        timeout: float = 10.0,
        endpoint: RelayEndpoint | None = None,
    ) -> None:
        self.endpoint = endpoint or PicoEndpoint("remote", remote_url, timeout)
        self.on_remote_move = on_remote_move
        self.on_stop = on_stop
        self.timeout = timeout
        self.pending_local_move: tuple[chess.Move, str] | None = None
        self.pending_remote_move: tuple[chess.Move, str] | None = None
        self._pending_remote_since: float | None = None
        self.armed = False
        self._closing = False

    async def arm(self, local_fen: str) -> str:
        """Connect and require the peer to have exactly the local position."""

        if self.armed:
            raise RelayError("engine match is already armed")
        local_board, canonical_local_fen = _canonical_fen(local_fen)
        await self.endpoint.connect()
        try:
            async with asyncio.timeout(min(self.timeout, INITIAL_POSITION_GRACE_SECONDS)):
                while True:
                    message = await self.endpoint.receive()
                    if message is None:
                        raise RelayError("remote: connection closed while arming")
                    event = message.get("event")
                    if event == "GameEnd":
                        raise RelayError("remote: game has already ended")
                    if event not in ("Game", "Fen"):
                        continue
                    remote_board, remote_fen = self._event_position(message)
                    if remote_fen != canonical_local_fen:
                        raise RelayError(
                            "positions differ while arming: "
                            f"local={canonical_local_fen}, remote={remote_fen}"
                        )
                    self.endpoint.board = remote_board
                    self.armed = True
                    LOGGER.info("REMOTE match ready")
                    LOGGER.debug("REMOTE matched initial position fen=%s", canonical_local_fen)
                    return canonical_local_fen
        except TimeoutError as exc:
            if canonical_local_fen != chess.STARTING_FEN:
                raise RelayError("remote: timed out waiting for an initial position") from exc
            # Temporary compatibility for a cold-started Picochess web server:
            # it currently has no cached board event until the first game event.
            self.endpoint.board = local_board
            self.armed = True
            LOGGER.info("REMOTE peer has no published position; assuming standard starting position")
            LOGGER.debug("REMOTE inferred initial position fen=%s", canonical_local_fen)
            return canonical_local_fen
        except Exception:
            await self.endpoint.close()
            raise

    @staticmethod
    def _event_position(message: dict[str, Any]) -> tuple[chess.Board, str]:
        variant = str(message.get("variant", "chess")).lower()
        if variant != "chess":
            raise RelayError(
                f"remote: unsupported variant {variant!r}; engine match MVP supports standard chess only"
            )
        return _canonical_fen(message.get("fen", ""))

    async def send_local_move(self, move: chess.Move, resulting_fen: str) -> None:
        """Post a physically confirmed local-engine move to the remote peer."""

        if not self.armed or self.endpoint.board is None:
            raise RelayError("engine match is not armed")
        if self.pending_local_move or self.pending_remote_move:
            raise RelayError("cannot send a local move while another move is pending")
        if move not in self.endpoint.board.legal_moves:
            raise RelayError(f"local move {move.uci()} is not legal in the synchronized position")
        expected = self.endpoint.board.copy(stack=True)
        expected.push(move)
        _, canonical_result = _canonical_fen(resulting_fen)
        expected_fen = expected.fen(en_passant="fen")
        if canonical_result != expected_fen:
            raise RelayError(
                f"local move {move.uci()} produced unexpected FEN: "
                f"expected {expected_fen}, got {canonical_result}"
            )
        self.pending_local_move = (move, expected_fen)
        try:
            await self.endpoint.send_move(move, expected_fen)
        except Exception:
            self.pending_local_move = None
            raise
        LOGGER.debug(
            "REMOTE forwarded local move %s expected_fen=%s",
            move.uci(),
            expected_fen,
        )

    def confirm_remote_move(self, move: chess.Move, resulting_fen: str) -> None:
        """Confirm that the announced remote move was executed on the eboard."""

        pending = self.pending_remote_move
        if pending is None:
            raise RelayError("no remote move is waiting for physical confirmation")
        _, canonical_result = _canonical_fen(resulting_fen)
        if pending != (move, canonical_result):
            raise RelayError(
                f"physical confirmation does not match remote move {pending[0].uci()}"
            )
        self.pending_remote_move = None
        wait_seconds = (
            time.monotonic() - self._pending_remote_since
            if self._pending_remote_since is not None
            else 0.0
        )
        self._pending_remote_since = None
        LOGGER.debug(
            "REMOTE confirmed peer move %s on eboard after %.1fs fen=%s",
            move.uci(),
            wait_seconds,
            canonical_result,
        )

    async def _process_message(self, message: dict[str, Any]) -> str | None:
        event = message.get("event")
        if event == "Game":
            return "remote started a new game"
        if event == "GameEnd":
            if self.endpoint.board and self.endpoint.board.is_game_over():
                LOGGER.info("remote game ended in the synchronized terminal position")
                return None
            return f"remote game ended: {message.get('result') or 'unknown result'}"
        if event != "Fen":
            return None

        if self.endpoint.board is None:
            raise RelayError("remote position is unknown")
        play = message.get("play")
        _, reported_fen = self._event_position(message)

        if play == "user":
            pending = self.pending_local_move
            if pending is None:
                raise RelayError("remote: unexpected user move acknowledgement")
            move = self._message_move(message, "acknowledged")
            if pending != (move, reported_fen):
                raise RelayError(
                    f"remote acknowledgement does not match local move {pending[0].uci()}"
                )
            updated = self.endpoint.board.copy(stack=True)
            if move not in updated.legal_moves:
                raise RelayError(f"remote acknowledged illegal move {move.uci()}")
            updated.push(move)
            if updated.fen(en_passant="fen") != reported_fen:
                raise RelayError("remote acknowledgement produced a different position")
            self.endpoint.board = updated
            self.pending_local_move = None
            LOGGER.debug(
                "REMOTE received acknowledgement for local move %s fen=%s",
                move.uci(),
                reported_fen,
            )
            return None

        if play == "computer":
            if self.pending_local_move is not None:
                raise RelayError("remote engine moved before acknowledging the local move")
            if self.pending_remote_move is not None:
                raise RelayError("remote engine moved while its previous move is still on the eboard")
            move = self._message_move(message, "engine")
            if move not in self.endpoint.board.legal_moves:
                raise RelayError(f"remote engine sent illegal move {move.uci()}")
            updated = self.endpoint.board.copy(stack=True)
            updated.push(move)
            expected_fen = updated.fen(en_passant="fen")
            if reported_fen != expected_fen:
                raise RelayError(
                    f"remote engine move {move.uci()} reported unexpected FEN: "
                    f"expected {expected_fen}, got {reported_fen}"
                )
            self.endpoint.board = updated
            self.pending_remote_move = (move, expected_fen)
            self._pending_remote_since = time.monotonic()
            LOGGER.debug(
                "REMOTE received peer move %s; waiting for eboard expected_fen=%s",
                move.uci(),
                expected_fen,
            )
            await self.on_remote_move(move, expected_fen)
            return None

        if play == "reload":
            current_fen = self.endpoint.board.fen(en_passant="fen")
            if reported_fen != current_fen:
                raise RelayError(
                    f"remote reload changed position: current={current_fen}, reported={reported_fen}"
                )
            if (self.pending_local_move or self.pending_remote_move) and not self.endpoint.board.is_game_over():
                raise RelayError("remote: unexpected reload while a move is pending")
            LOGGER.debug("REMOTE accepted same-position reload from peer fen=%s", reported_fen)
            return None

        if play in ("review", "newgame"):
            return f"remote changed position ({play})"
        raise RelayError(f"remote: unrecognized Fen event play={play!r}")

    @staticmethod
    def _message_move(message: dict[str, Any], description: str) -> chess.Move:
        try:
            return chess.Move.from_uci(str(message.get("move", "")))
        except ValueError as exc:
            raise RelayError(f"remote: invalid {description} move {message.get('move')!r}") from exc

    async def run(self) -> None:
        """Read peer events until shutdown, disconnect, or unsafe state."""

        if not self.armed:
            raise RelayError("engine match must be armed before run")
        reason: str | None = None
        try:
            while True:
                message = await self.endpoint.receive()
                if message is None:
                    raise RelayError("remote connection closed")
                reason = await self._process_message(message)
                if reason:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = str(exc)
        finally:
            self.armed = False
            self._pending_remote_since = None
            await self.endpoint.close()
        if reason and not self._closing:
            await self.on_stop(reason)

    async def close(self) -> None:
        self._closing = True
        self.armed = False
        self._pending_remote_since = None
        await self.endpoint.close()
