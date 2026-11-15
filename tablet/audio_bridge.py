# -*- coding: utf-8 -*-
"""
tablet/audio_bridge.py — Redirige el audio de la app a la tablet.

La app usa `sounddevice` (sd.play, sd.OutputStream, sd.InputStream). Al
activar este módulo esas llamadas se sustituyen por equivalentes que envían el
PCM por WebSocket a la tablet (reproducción con Web Audio) y reciben el
micrófono de la tablet para la voz de L.I.S. Si no hay tablet conectada, el
audio se descarta respetando los tiempos (nada se bloquea ni se acumula).
"""

from __future__ import annotations

import logging
import struct
import threading
import time
from typing import Any, Callable, Optional

import numpy as np

from tablet.server import MSG_AUDIO, MSG_AUDIO_STOP, ServidorRemoto

log = logging.getLogger("vitalis.tablet.audio")

_srv: Optional[ServidorRemoto] = None
_ids = iter(range(1, 60000))
_ids_lock = threading.Lock()
_play_fin = 0.0
_mic_activos: list["_EntradaRemota"] = []
_mic_lock = threading.Lock()
BUFFER_ADELANTE_S = 0.30  # cuánto audio se deja «en vuelo» hacia la tablet


def _nuevo_id() -> int:
    with _ids_lock:
        return next(_ids)


def _a_pcm16(datos: np.ndarray) -> tuple[bytes, int]:
    arr = np.asarray(datos)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    canales = arr.shape[1]
    if arr.dtype.kind == "f":
        arr = np.clip(arr, -1.0, 1.0) * 32767.0
    elif arr.dtype == np.int16:
        pass
    else:
        arr = arr.astype(np.float32)
    return np.ascontiguousarray(arr.astype("<i2")).tobytes(), canales


def _enviar_audio(stream_id: int, datos: np.ndarray, sr: int) -> float:
    """Envía un bloque PCM; devuelve su duración en segundos."""
    pcm, canales = _a_pcm16(datos)
    frames = len(pcm) // (2 * canales)
    if _srv is not None and _srv.conectado and frames:
        cab = struct.pack("<BHIB", MSG_AUDIO, stream_id & 0xFFFF, int(sr), canales)
        _srv.enviar_bytes(cab + pcm)
    return frames / float(sr or 1)


def _parar_audio(stream_id: int) -> None:
    if _srv is not None and _srv.conectado:
        _srv.enviar_bytes(struct.pack("<BH", MSG_AUDIO_STOP, stream_id & 0xFFFF))


class _SalidaRemota:
    """Sustituto de sd.OutputStream: write() bloquea al ritmo del tiempo real."""

    def __init__(self, samplerate: int = 22050, channels: int = 1, dtype: str = "float32", **_kw: Any) -> None:
        self.sr = int(samplerate)
        self.ch = int(channels)
        self.id = _nuevo_id()
        self._fin = 0.0
        self.active = False

    def __enter__(self) -> "_SalidaRemota":
        self.start()
        return self

    def __exit__(self, *_a: Any) -> None:
        self.close()

    def start(self) -> None:
        self.active = True
        self._fin = time.monotonic()

    def write(self, datos: np.ndarray) -> None:
        dur = _enviar_audio(self.id, datos, self.sr)
        ahora = time.monotonic()
        self._fin = max(self._fin, ahora) + dur
        espera = (self._fin - ahora) - BUFFER_ADELANTE_S
        if espera > 0:
            time.sleep(espera)

    def stop(self) -> None:
        self.active = False

    def abort(self) -> None:
        self.active = False
        _parar_audio(self.id)

    def close(self) -> None:
        # Deja terminar lo ya enviado (igual que el stream real al salir del `with`).
        restante = self._fin - time.monotonic()
        if restante > 0 and self.active:
            time.sleep(min(restante, 1.5))
        self.active = False


class _EntradaRemota:
    """Sustituto de sd.InputStream alimentado por el micrófono de la tablet."""

    def __init__(
        self, samplerate: int = 16000, channels: int = 1, dtype: str = "float32",
        blocksize: int = 0, callback: Optional[Callable] = None, **_kw: Any,
    ) -> None:
        self.sr = int(samplerate)
        self.bloque = int(blocksize) or max(256, int(self.sr * 0.05))
        self.callback = callback
        self._buf = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()
        self._activo = False

    def __enter__(self) -> "_EntradaRemota":
        self.start()
        return self

    def __exit__(self, *_a: Any) -> None:
        self.close()

    def start(self) -> None:
        self._activo = True
        with _mic_lock:
            _mic_activos.append(self)
        if _srv is not None:
            _srv.enviar_json({"t": "mic", "on": True, "sr": self.sr})

    def stop(self) -> None:
        self.close()

    def abort(self) -> None:
        self.close()

    def close(self) -> None:
        if not self._activo:
            return
        self._activo = False
        with _mic_lock:
            if self in _mic_activos:
                _mic_activos.remove(self)
            quedan = bool(_mic_activos)
        if _srv is not None and not quedan:
            _srv.enviar_json({"t": "mic", "on": False})

    def _alimentar(self, muestras: np.ndarray) -> None:
        if not self._activo:
            return
        with self._lock:
            self._buf = np.concatenate([self._buf, muestras])
            while len(self._buf) >= self.bloque:
                trozo, self._buf = self._buf[: self.bloque], self._buf[self.bloque :]
                if self.callback is not None:
                    try:
                        self.callback(trozo.reshape(-1, 1).copy(), len(trozo), None, None)
                    except Exception:
                        log.exception("callback de micrófono")


def _al_mic(datos: bytes) -> None:
    if len(datos) < 2:
        return
    pcm = np.frombuffer(datos[: len(datos) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    with _mic_lock:
        activos = list(_mic_activos)
    for e in activos:
        e._alimentar(pcm)


def activar(servidor: ServidorRemoto) -> None:
    """Sustituye las funciones de `sounddevice` usadas por la app."""
    global _srv
    import sounddevice as sd

    _srv = servidor
    servidor.al_mic = _al_mic
    original = {k: getattr(sd, k, None) for k in ("play", "stop", "wait", "OutputStream", "InputStream", "check_input_settings", "query_devices")}

    def play(data, samplerate=None, **_kw):
        global _play_fin
        sr = int(samplerate or 22050)
        _parar_audio(0)
        dur = _enviar_audio(0, np.asarray(data), sr)
        _play_fin = time.monotonic() + dur

    def stop(*_a, **_kw):
        global _play_fin
        _play_fin = 0.0
        _parar_audio(0)

    def wait(*_a, **_kw):
        while True:
            resto = _play_fin - time.monotonic()
            if resto <= 0:
                return
            time.sleep(min(0.05, resto))

    def check_input_settings(*_a, **_kw):
        return None

    def query_devices(device=None, kind=None):
        info = {"name": "Micrófono de la tablet", "default_samplerate": 16000.0, "max_input_channels": 1, "max_output_channels": 2}
        return info if kind else [info]

    sd.play, sd.stop, sd.wait = play, stop, wait
    sd.OutputStream, sd.InputStream = _SalidaRemota, _EntradaRemota
    sd.check_input_settings, sd.query_devices = check_input_settings, query_devices
    sd._vitalis_original = original  # type: ignore[attr-defined]
    log.info("Audio de V.I.T.A.L.I.S. redirigido a la tablet")


def desactivar() -> None:
    """Restaura las funciones originales de `sounddevice` (pruebas)."""
    global _srv
    import sounddevice as sd

    original = getattr(sd, "_vitalis_original", None)
    if original:
        for k, f in original.items():
            if f is not None:
                setattr(sd, k, f)
        del sd._vitalis_original  # type: ignore[attr-defined]
    _srv = None
