"""Relay engine moves between two NOEBOARD Picochess instances.

The relay deliberately uses only Picochess's existing web API.  It does not
manage clocks, colours, modes, engines, or game setup.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

import chess
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from tornado.websocket import WebSocketClientConnection, websocket_connect


LOGGER = logging.getLogger(__name__)


class RelayError(RuntimeError):
    """Raised when the relay cannot safely continue."""


class RelayEndpoint(Protocol):
    """Transport used by the relay state machine."""

    name: str
    board: chess.Board | None

    async def connect(self) -> None:
        ...

    async def receive(self) -> dict[str, Any] | None:
        ...

    async def send_move(self, move: chess.Move, resulting_fen: str) -> None:
        ...

    async def send_new_game(self) -> None:
        ...

    async def close(self) -> None:
        ...


def _canonical_fen(fen: str) -> tuple[chess.Board, str]:
    """Validate and normalize a complete standard-chess FEN."""

    fields = str(fen or "").split()
    if len(fields) != 6:
        raise RelayError(f"expected a complete six-field FEN, got {fen!r}")
    try:
        board = chess.Board(" ".join(fields), chess960=False)
    except ValueError as exc:
        raise RelayError(f"invalid standard-chess FEN {fen!r}: {exc}") from exc
    return board, board.fen(en_passant="fen")


def _endpoint_urls(base_url: str) -> tuple[str, str]:
    """Return websocket and move-channel URLs for a Picochess base URL."""

    candidate = base_url.strip()
    if "://" not in candidate:
        candidate = "http://" + candidate
    parsed = urlsplit(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RelayError(f"invalid Picochess URL: {base_url!r}")
    if parsed.query or parsed.fragment:
        raise RelayError(f"Picochess URL must not contain a query or fragment: {base_url!r}")

    base_path = parsed.path.rstrip("/")
    http_url = urlunsplit((parsed.scheme, parsed.netloc, base_path + "/channel", "", ""))
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url = urlunsplit((ws_scheme, parsed.netloc, base_path + "/event", "", ""))
    return ws_url, http_url


class PicoEndpoint:
    """A Picochess websocket plus its HTTP move endpoint."""

    def __init__(self, name: str, base_url: str, timeout: float = 10.0) -> None:
        self.name = name
        self.base_url = base_url
        self.timeout = timeout
        self.websocket_url, self.channel_url = _endpoint_urls(base_url)
        self.board: chess.Board | None = None
        self._websocket: WebSocketClientConnection | None = None
        self._http = AsyncHTTPClient()

    async def connect(self) -> None:
        request = HTTPRequest(self.websocket_url, connect_timeout=self.timeout)
        try:
            self._websocket = await websocket_connect(
                request,
                ping_interval=20,
                ping_timeout=30,
            )
        except Exception as exc:
            raise RelayError(f"{self.name}: cannot connect to {self.websocket_url}: {exc}") from exc
        LOGGER.info("%s connected to %s", self.name, self.base_url)

    async def receive(self) -> dict[str, Any] | None:
        if self._websocket is None:
            raise RelayError(f"{self.name}: websocket is not connected")
        try:
            raw = await self._websocket.read_message()
        except Exception as exc:
            raise RelayError(f"{self.name}: websocket read failed: {exc}") from exc
        if raw is None:
            return None
        try:
            message = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RelayError(f"{self.name}: invalid websocket JSON: {exc}") from exc
        if not isinstance(message, dict):
            raise RelayError(f"{self.name}: websocket message is not an object")
        return message

    async def send_move(self, move: chess.Move, resulting_fen: str) -> None:
        uci = move.uci()
        await self._post_action(
            {
                "action": "move",
                "fen": resulting_fen,
                "source": uci[:2],
                "target": uci[2:4],
                "promotion": uci[4:],
            },
            "move",
        )

    async def send_new_game(self) -> None:
        """Request a standard new game through Picochess's existing web action."""
        await self._post_action({"action": "new_game", "pos960": "518"}, "new game")

    async def _post_action(self, fields: dict[str, str], description: str) -> None:
        body = urlencode(fields)
        request = HTTPRequest(
            self.channel_url,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body,
            connect_timeout=self.timeout,
            request_timeout=self.timeout,
        )
        try:
            response = await self._http.fetch(request, raise_error=False)
        except Exception as exc:
            raise RelayError(f"{self.name}: {description} POST failed: {exc}") from exc
        if response.code < 200 or response.code >= 300:
            detail = response.body.decode("utf-8", errors="replace").strip()
            raise RelayError(
                f"{self.name}: {description} POST returned HTTP {response.code}"
                + (f": {detail}" if detail else "")
            )

    async def close(self) -> None:
        if self._websocket is not None:
            self._websocket.close()
            self._websocket = None


@dataclass(frozen=True)
class PendingMove:
    source: RelayEndpoint
    destination: RelayEndpoint
    move: chess.Move
    resulting_fen: str


class Relay:
    """Validate and relay a single game between two Picochess endpoints."""

    def __init__(self, first: RelayEndpoint, second: RelayEndpoint, timeout: float = 10.0) -> None:
        self.endpoints = (first, second)
        self.timeout = timeout
        self.pending_move: PendingMove | None = None
        self.pending_deadline: float | None = None
        self.armed = False

    async def _initial_position(self, endpoint: RelayEndpoint) -> None:
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    message = await endpoint.receive()
                    if message is None:
                        raise RelayError(f"{endpoint.name}: connection closed while arming")
                    event = message.get("event")
                    if event == "GameEnd":
                        raise RelayError(f"{endpoint.name}: game has already ended")
                    if event not in ("Game", "Fen"):
                        continue
                    variant = str(message.get("variant", "chess")).lower()
                    if variant != "chess":
                        raise RelayError(
                            f"{endpoint.name}: unsupported variant {variant!r}; MVP supports standard chess only"
                        )
                    board, _ = _canonical_fen(message.get("fen", ""))
                    endpoint.board = board
                    return
        except TimeoutError as exc:
            raise RelayError(f"{endpoint.name}: timed out waiting for an initial position") from exc

    async def arm(self) -> str:
        """Connect, acquire both snapshots, and verify an identical position."""

        if self.armed:
            raise RelayError("relay is already armed")
        await asyncio.gather(*(endpoint.connect() for endpoint in self.endpoints))
        await asyncio.gather(*(self._initial_position(endpoint) for endpoint in self.endpoints))

        first, second = self.endpoints
        assert first.board is not None and second.board is not None
        first_fen = first.board.fen(en_passant="fen")
        second_fen = second.board.fen(en_passant="fen")
        if first_fen != second_fen:
            raise RelayError(
                "positions differ while arming:\n"
                f"  {first.name}: {first_fen}\n"
                f"  {second.name}: {second_fen}"
            )
        self.armed = True
        LOGGER.info("ARMED at %s", first_fen)
        return first_fen

    def _other(self, endpoint: RelayEndpoint) -> RelayEndpoint:
        first, second = self.endpoints
        return second if endpoint is first else first

    @staticmethod
    def _event_position(endpoint: RelayEndpoint, message: dict[str, Any]) -> tuple[chess.Board, str]:
        variant = str(message.get("variant", "chess")).lower()
        if variant != "chess":
            raise RelayError(f"{endpoint.name}: game changed to unsupported variant {variant!r}")
        return _canonical_fen(message.get("fen", ""))

    async def process_event(self, endpoint: RelayEndpoint, message: dict[str, Any]) -> str | None:
        """Process one live event, returning a normal stop reason when applicable."""

        event = message.get("event")
        if event == "GameEnd":
            return f"game ended on {endpoint.name}: {message.get('result') or 'unknown result'}"
        if event == "Game":
            return f"new game detected on {endpoint.name}"
        if event != "Fen":
            return None

        play = message.get("play")
        if play == "computer":
            if self.pending_move is not None:
                raise RelayError(
                    f"{endpoint.name}: engine move arrived while waiting for "
                    f"{self.pending_move.destination.name} to acknowledge {self.pending_move.move.uci()}"
                )
            destination = self._other(endpoint)
            if endpoint.board is None or destination.board is None:
                raise RelayError("relay received a move before it was armed")
            source_fen = endpoint.board.fen(en_passant="fen")
            destination_fen = destination.board.fen(en_passant="fen")
            if source_fen != destination_fen:
                raise RelayError(
                    f"desynchronization before {endpoint.name} engine move: "
                    f"{endpoint.name}={source_fen}, {destination.name}={destination_fen}"
                )
            try:
                move = chess.Move.from_uci(str(message.get("move", "")))
            except ValueError as exc:
                raise RelayError(f"{endpoint.name}: invalid engine move {message.get('move')!r}") from exc
            if move not in endpoint.board.legal_moves:
                raise RelayError(f"{endpoint.name}: illegal engine move {move.uci()} for {source_fen}")

            expected = endpoint.board.copy(stack=True)
            expected.push(move)
            _, reported_fen = self._event_position(endpoint, message)
            expected_fen = expected.fen(en_passant="fen")
            if reported_fen != expected_fen:
                raise RelayError(
                    f"{endpoint.name}: engine move {move.uci()} reported unexpected FEN: "
                    f"expected {expected_fen}, got {reported_fen}"
                )

            endpoint.board = expected
            self.pending_move = PendingMove(endpoint, destination, move, expected_fen)
            await destination.send_move(move, expected_fen)
            self.pending_deadline = asyncio.get_running_loop().time() + self.timeout
            LOGGER.info("relayed %s %s -> %s", move.uci(), endpoint.name, destination.name)
            return None

        if play == "user":
            pending = self.pending_move
            if pending is None or endpoint is not pending.destination:
                raise RelayError(f"{endpoint.name}: unexpected user move acknowledgement")
            try:
                move = chess.Move.from_uci(str(message.get("move", "")))
            except ValueError as exc:
                raise RelayError(f"{endpoint.name}: invalid acknowledged move {message.get('move')!r}") from exc
            _, reported_fen = self._event_position(endpoint, message)
            if move != pending.move or reported_fen != pending.resulting_fen:
                raise RelayError(
                    f"{endpoint.name}: acknowledgement does not match relayed move {pending.move.uci()}"
                )
            if endpoint.board is None or move not in endpoint.board.legal_moves:
                raise RelayError(f"{endpoint.name}: acknowledged move {move.uci()} is not legal locally")
            updated = endpoint.board.copy(stack=True)
            updated.push(move)
            if updated.fen(en_passant="fen") != pending.resulting_fen:
                raise RelayError(f"{endpoint.name}: acknowledgement produced a different position")
            endpoint.board = updated
            self.pending_move = None
            self.pending_deadline = None
            return None

        if play == "reload":
            # Switch Sides publishes a reload even though the position does not
            # change.  That is the intended final action after arming.  Other
            # reload producers (takeback, alternative move, position setup)
            # are safe only when they are also genuinely position-neutral.
            if endpoint.board is None:
                raise RelayError(f"{endpoint.name}: reload arrived before its position was known")
            other = self._other(endpoint)
            if other.board is None:
                raise RelayError(f"{endpoint.name}: reload arrived before both positions were known")
            _, reported_fen = self._event_position(endpoint, message)
            current_fen = endpoint.board.fen(en_passant="fen")
            other_fen = other.board.fen(en_passant="fen")
            if self.pending_move is not None:
                pending = self.pending_move
                if (
                    endpoint is pending.source
                    and endpoint.board.is_game_over()
                    and reported_fen == pending.resulting_fen
                    and reported_fen == current_fen
                ):
                    # After a mating or otherwise terminal engine move, the
                    # source publishes its final PGN as a same-position reload
                    # before publishing GameEnd.  The destination may not have
                    # acknowledged the relayed move yet, so keep the pending
                    # state and wait for either its acknowledgement or GameEnd.
                    LOGGER.info("accepted terminal-position reload from %s", endpoint.name)
                    return None
                raise RelayError(f"{endpoint.name}: unexpected reload while a move is pending")
            if reported_fen != current_fen or reported_fen != other_fen:
                raise RelayError(
                    f"{endpoint.name}: reload changed the armed position: "
                    f"reported={reported_fen}, current={current_fen}, {other.name}={other_fen}"
                )
            LOGGER.info("accepted same-position reload from %s", endpoint.name)
            return None
        if play in ("review", "newgame"):
            raise RelayError(f"{endpoint.name}: unexpected position change ({play})")
        raise RelayError(f"{endpoint.name}: unrecognized Fen event play={play!r}")

    async def run(self) -> str:
        """Arm and relay until a normal stop event or an unsafe condition occurs."""

        read_tasks: dict[asyncio.Task[dict[str, Any] | None], RelayEndpoint] = {}
        try:
            await self.arm()
            read_tasks = {
                asyncio.create_task(endpoint.receive()): endpoint for endpoint in self.endpoints
            }
            while True:
                wait_timeout = None
                if self.pending_deadline is not None:
                    wait_timeout = max(
                        0.0,
                        self.pending_deadline - asyncio.get_running_loop().time(),
                    )
                completed, _ = await asyncio.wait(
                    read_tasks,
                    timeout=wait_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not completed:
                    assert self.pending_move is not None
                    raise RelayError(
                        f"{self.pending_move.destination.name}: timed out waiting for "
                        f"acknowledgement of {self.pending_move.move.uci()}"
                    )
                for task in completed:
                    endpoint = read_tasks.pop(task)
                    message = task.result()
                    if message is None:
                        raise RelayError(f"{endpoint.name}: connection closed")
                    stop_reason = await self.process_event(endpoint, message)
                    if stop_reason is not None:
                        LOGGER.info("STOPPED: %s", stop_reason)
                        return stop_reason
                    read_tasks[asyncio.create_task(endpoint.receive())] = endpoint
        finally:
            for task in read_tasks:
                task.cancel()
            if read_tasks:
                await asyncio.gather(*read_tasks, return_exceptions=True)
            await asyncio.gather(*(endpoint.close() for endpoint in self.endpoints), return_exceptions=True)
