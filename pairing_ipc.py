import asyncio
import json
import logging
import os
import time
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

PAIRING_SOCKET_PATH = "/tmp/picochess-pairing.sock"

_bridge = None


def set_bridge(bridge) -> None:
    global _bridge
    _bridge = bridge


def is_active() -> bool:
    return _bridge is not None and _bridge.is_active()


async def forward_button(button: int, dev: str) -> None:
    if _bridge is None:
        return
    await _bridge.send_button(button, dev)


class PairingBridge:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        show_text_cb: Callable[[str], Awaitable[None]] | Callable[[str], None],
        socket_path: str = PAIRING_SOCKET_PATH,
    ) -> None:
        self.loop = loop
        self.socket_path = socket_path
        self._show_text_cb = show_text_cb
        self._server: Optional[asyncio.AbstractServer] = None
        self._server_task: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.Task] = None
        self._client_writer: Optional[asyncio.StreamWriter] = None
        self._active = False
        self._deadline: Optional[float] = None

    @property
    def server_task(self) -> Optional[asyncio.Task]:
        return self._server_task

    def is_active(self) -> bool:
        return self._active

    async def start(self) -> None:
        self._remove_socket()
        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        self._server_task = self.loop.create_task(self._server.serve_forever())
        logger.info("pairing IPC listening on %s", self.socket_path)

    async def close(self) -> None:
        await self._deactivate("shutdown")
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._remove_socket()

    async def send_button(self, button: int, dev: str) -> None:
        if not self._active or self._client_writer is None:
            return
        await self._send_event({"event": "button", "button": int(button), "dev": dev})
        if int(button) == 0:
            await self._deactivate("cancel")
            await self._send_event({"event": "cancel"})

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._client_writer is not None:
            try:
                self._client_writer.close()
                await self._client_writer.wait_closed()
            except Exception:
                pass
        self._client_writer = writer
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    payload = json.loads(line.decode("utf-8", errors="ignore").strip())
                except json.JSONDecodeError:
                    continue
                action = payload.get("action")
                if action == "start":
                    timeout = int(payload.get("timeout", 40))
                    await self._activate(timeout)
                    await self._send_event({"event": "started", "timeout": timeout})
                elif action == "stop":
                    await self._deactivate(payload.get("reason", "stop"))
                    await self._send_event({"event": "stopped"})
                elif action == "show_text":
                    text = payload.get("text", "")
                    if text:
                        await self._show_text(text)
                    await self._send_event({"event": "shown"})
                elif action == "ping":
                    await self._send_event({"event": "pong"})
                else:
                    await self._send_event({"event": "error", "error": "unknown_action"})
        finally:
            if self._client_writer is writer:
                self._client_writer = None
                await self._deactivate("disconnect")
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _activate(self, timeout: int) -> None:
        self._active = True
        self._deadline = time.time() + max(1, timeout)
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = self.loop.create_task(self._timeout_watch())

    async def _deactivate(self, reason: str) -> None:
        self._active = False
        self._deadline = None
        if self._timeout_task:
            self._timeout_task.cancel()
            self._timeout_task = None
        if reason == "timeout":
            await self._send_event({"event": "timeout"})

    async def _timeout_watch(self) -> None:
        try:
            while self._active and self._deadline is not None:
                await asyncio.sleep(0.5)
                if time.time() >= self._deadline:
                    await self._deactivate("timeout")
                    break
        except asyncio.CancelledError:
            pass

    async def _show_text(self, text: str) -> None:
        if asyncio.iscoroutinefunction(self._show_text_cb):
            await self._show_text_cb(text)
        else:
            self._show_text_cb(text)

    async def _send_event(self, payload: dict) -> None:
        if self._client_writer is None:
            return
        try:
            data = json.dumps(payload, separators=(",", ":")) + "\n"
            self._client_writer.write(data.encode("utf-8"))
            await self._client_writer.drain()
        except Exception:
            pass

    def _remove_socket(self) -> None:
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except OSError as exc:
            logger.debug("failed to remove pairing socket: %s", exc)
