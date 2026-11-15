# -*- coding: utf-8 -*-
"""
tablet/server.py — Servidor HTTP + WebSocket del cliente táctil (FastAPI/uvicorn).

Corre en un hilo propio. Toda interacción con Qt pasa por callbacks que el
puente (`bridge.py`) reenvía al hilo principal mediante señales en cola.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Callable, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response

from tablet import PUERTO

log = logging.getLogger("vitalis.tablet.server")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# Tipos de mensaje binario servidor -> cliente
PROTOCOLO = "2"
MSG_VIDEO = 1
MSG_AUDIO = 2
MSG_AUDIO_STOP = 3
# Cliente -> servidor
MSG_MIC = 0x10


class ServidorRemoto:
    """Un único cliente activo: si se abre otra pestaña, la anterior se cierra."""

    def __init__(self, host: str = "127.0.0.1", puerto: int = PUERTO) -> None:
        self.host = host
        self.puerto = puerto
        self.app = FastAPI(title="V.I.T.A.L.I.S. tablet", docs_url=None, redoc_url=None)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws: Optional[WebSocket] = None
        self._hilo: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None
        self._lock = threading.Lock()
        self.pendientes = 0  # tramas enviadas y aún sin confirmar por el cliente
        self.ultimo_ack = 0.0
        self.latencia_ms = 0.0
        self._envios: dict[int, float] = {}
        # Callbacks (se ejecutan en el hilo del servidor)
        self.al_mensaje: Callable[[dict], None] = lambda _m: None
        self.al_mic: Callable[[bytes], None] = lambda _b: None
        self.al_conectar: Callable[[], None] = lambda: None
        self.al_desconectar: Callable[[], None] = lambda: None
        self._montar_rutas()

    # ---- rutas ---------------------------------------------------------
    def _montar_rutas(self) -> None:
        app = self.app

        @app.get("/")
        async def _index() -> Response:
            return FileResponse(
                os.path.join(WEB_DIR, "index.html"),
                headers={"Cache-Control": "no-store"},
            )

        @app.get("/manifest.webmanifest")
        async def _manifest() -> Response:
            return FileResponse(
                os.path.join(WEB_DIR, "manifest.webmanifest"),
                media_type="application/manifest+json",
            )

        @app.get("/icon.png")
        async def _icono() -> Response:
            ruta = os.path.join(WEB_DIR, "icon.png")
            if os.path.exists(ruta):
                return FileResponse(ruta, media_type="image/png")
            return Response(status_code=404)

        @app.get("/health")
        async def _health() -> JSONResponse:
            return JSONResponse({"ok": True, "cliente": self._ws is not None})

        @app.websocket("/ws")
        async def _ws(ws: WebSocket) -> None:
            await ws.accept()
            if ws.query_params.get("v") != PROTOCOLO:
                # Pestaña con una versión antigua de la página: se rechaza sin disputar la sesión.
                await ws.close(code=4001)
                return
            anterior = self._ws
            self._ws = ws
            self.pendientes = 0
            self._envios.clear()
            if anterior is not None:
                try:
                    await anterior.close(code=4000)
                except Exception:
                    pass
            log.info("Cliente táctil conectado: %s", ws.client)
            self.al_conectar()
            try:
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if msg.get("text") is not None:
                        try:
                            datos = json.loads(msg["text"])
                        except Exception:
                            continue
                        if datos.get("t") == "ack":
                            self._on_ack(int(datos.get("n", 0)))
                            continue
                        self.al_mensaje(datos)
                    elif msg.get("bytes") is not None:
                        b = msg["bytes"]
                        if b and b[0] == MSG_MIC:
                            self.al_mic(b[1:])
            except WebSocketDisconnect:
                pass
            except Exception as exc:  # noqa: BLE001
                log.info("WebSocket cerrado: %s", exc)
            finally:
                if self._ws is ws:
                    self._ws = None
                    self.pendientes = 0
                    self.al_desconectar()
                log.info("Cliente táctil desconectado")

    def _on_ack(self, n: int) -> None:
        t0 = self._envios.pop(n, None)
        if t0 is not None:
            self.latencia_ms = 0.8 * self.latencia_ms + 0.2 * (time.monotonic() - t0) * 1000.0
        self.pendientes = max(0, self.pendientes - 1)
        self.ultimo_ack = time.monotonic()

    # ---- ciclo de vida ---------------------------------------------------
    def iniciar(self) -> None:
        cfg = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.puerto,
            log_level="warning",
            ws_max_size=8 * 1024 * 1024,
            ws_ping_interval=20,
            ws_ping_timeout=30,
        )
        self._server = uvicorn.Server(cfg)

        def _run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._server.serve())
            except Exception as exc:  # noqa: BLE001
                log.error("Servidor táctil detenido: %s", exc)

        self._hilo = threading.Thread(target=_run, daemon=True, name="vitalis-tablet-ws")
        self._hilo.start()

    def detener(self) -> None:
        if self._server is not None:
            self._server.should_exit = True

    @property
    def conectado(self) -> bool:
        return self._ws is not None

    # ---- envío (seguro entre hilos) -------------------------------------
    def _enviar(self, coro_factory) -> None:
        loop = self._loop
        if loop is None or self._ws is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(coro_factory(), loop)
        except Exception:
            pass

    def enviar_bytes(self, datos: bytes, contar_ack: Optional[int] = None) -> None:
        ws = self._ws
        if ws is None:
            return
        if contar_ack is not None:
            self.pendientes += 1
            self._envios[contar_ack] = time.monotonic()

        async def _go() -> None:
            try:
                await ws.send_bytes(datos)
            except Exception:
                pass

        self._enviar(lambda: _go())

    def enviar_json(self, objeto: dict) -> None:
        ws = self._ws
        if ws is None:
            return
        texto = json.dumps(objeto, ensure_ascii=False)

        async def _go() -> None:
            try:
                await ws.send_text(texto)
            except Exception:
                pass

        self._enviar(lambda: _go())
