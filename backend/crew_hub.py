# -*- coding: utf-8 -*-
"""
backend/crew_hub.py — Hub de la sala de tripulación (C001–C004) y difusión SSE.

Portado de `src/lib/realtime/crew-hub.ts` (Back 1):
- Mantiene el último RealtimeTelemetryFrame de cada tripulante.
- Calcula estado de enlace: `conectado` (<=5 s), `degradado` (<=15 s), `sin-enlace` (>15 s).
- Persiste snapshot durable en `data/central/snapshot.json` ante reinicios.
- Emite eventos SSE (`snapshot`, `alerta`, `resuelta`, `latido`) a suscriptores.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from backend.database import DATA_DIR
from backend.knowledge import sexo_de
from backend.registry import get_param

VENTANA_DEGRADADO_MS = 5_000
VENTANA_SIN_ENLACE_MS = 15_000
CENTRAL_DIR = os.path.join(DATA_DIR, "central")
SNAPSHOT_FILE = os.path.join(CENTRAL_DIR, "snapshot.json")

ORDEN_NIVEL = {"NOMINAL": 0, "ATENCION": 1, "CRITICO": 2}
CREW_IDS = ("C001", "C002", "C003", "C004")


def _ahora_ms() -> int:
    return int(time.time() * 1000)


def _nivel_mas_grave(a: str, b: str) -> str:
    return a if ORDEN_NIVEL.get(a, 0) >= ORDEN_NIVEL.get(b, 0) else b


def _estado_enlace(recibido_en: int, ahora_ms: int) -> str:
    silencio = ahora_ms - recibido_en
    if silencio > VENTANA_SIN_ENLACE_MS:
        return "sin-enlace"
    if silencio > VENTANA_DEGRADADO_MS:
        return "degradado"
    return "conectado"


def _nivel_global(alertas: Iterable[Dict[str, Any]]) -> str:
    nivel = "NOMINAL"
    for al in alertas:
        nivel = _nivel_mas_grave(nivel, str(al.get("nivel", "NOMINAL")))
    return nivel


class CrewHub:
    """Concentrador thread-safe en memoria + snapshot durable en disco."""

    def __init__(self, snapshot_path: Optional[str] = SNAPSHOT_FILE) -> None:
        self._lock = threading.RLock()
        self._registro: Dict[str, Dict[str, Any]] = {}
        self._suscriptores: List[Callable[[Dict[str, Any]], None]] = []
        self._snapshot_path = snapshot_path
        self._estaciones_aisladas: set[str] = set()
        if self._snapshot_path:
            self._restaurar_snapshot()

    def _emitir(self, evento: Dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._suscriptores)
        for fn in subs:
            try:
                fn(evento)
            except Exception:
                pass

    def _persistir_snapshot(self) -> None:
        if not self._snapshot_path:
            return
        try:
            os.makedirs(os.path.dirname(self._snapshot_path), exist_ok=True)
            data = [
                {
                    "crewId": cid,
                    "frame": item["frame"],
                    "recibidoEn": item["recibidoEn"],
                }
                for cid, item in self._registro.items()
            ]
            tmp = f"{self._snapshot_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self._snapshot_path)
        except Exception:
            pass

    def _restaurar_snapshot(self) -> None:
        if not self._snapshot_path or not os.path.exists(self._snapshot_path):
            return
        try:
            with open(self._snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    frame = item.get("frame")
                    rec = item.get("recibidoEn")
                    if isinstance(frame, dict) and isinstance(rec, int):
                        self.publicar_frame(frame, ahora_ms=rec, persistir=False)
        except Exception:
            pass

    def set_estacion_aislada(self, crew_id: str, aislada: bool) -> None:
        with self._lock:
            if aislada:
                self._estaciones_aisladas.add(crew_id)
            else:
                self._estaciones_aisladas.discard(crew_id)

    def es_estacion_aislada(self, crew_id: str) -> bool:
        with self._lock:
            return crew_id in self._estaciones_aisladas

    def publicar_frame(
        self,
        frame: Dict[str, Any],
        ahora_ms: Optional[int] = None,
        persistir: bool = True,
    ) -> List[Dict[str, Any]]:
        ahora = int(ahora_ms if ahora_ms is not None else _ahora_ms())
        crew_id = str(frame.get("crewId", "C001"))

        eventos_a_emitir: List[Dict[str, Any]] = []
        with self._lock:
            anterior = self._registro.get(crew_id)
            prev_alertas: Dict[str, Dict[str, Any]] = (
                anterior["alertas"] if anterior else {}
            )
            alertas: Dict[str, Dict[str, Any]] = {}

            for param_id, lectura in (frame.get("lecturas") or {}).items():
                nivel = str(lectura.get("nivel", "NOMINAL"))
                if nivel == "NOMINAL":
                    continue
                definicion = get_param(param_id)
                previa = prev_alertas.get(param_id)
                alerta = {
                    "id": f"{crew_id}:{param_id}",
                    "crewId": crew_id,
                    "parametroId": param_id,
                    "nombreParametro": definicion["nombre"] if definicion else param_id,
                    "nivel": nivel,
                    "valor": lectura.get("valor"),
                    "unidad": lectura.get("unidad", ""),
                    "baseline": lectura.get("baselinePersonal"),
                    "razon": lectura.get("razon", ""),
                    "accion": lectura.get("accion", ""),
                    "reglaDisparada": lectura.get("reglaDisparada", ""),
                    "fuente": lectura.get("fuente", ""),
                    "degradado": bool(lectura.get("degradado", False)),
                    "timestamp": previa["timestamp"] if previa else frame.get("timestamp", ahora),
                }
                alertas[param_id] = alerta
                if previa is None or previa["nivel"] != nivel:
                    eventos_a_emitir.append(
                        {"tipo": "alerta", "timestamp": ahora, "alerta": alerta}
                    )

            for param_id in list(prev_alertas.keys()):
                if param_id not in alertas:
                    eventos_a_emitir.append(
                        {
                            "tipo": "resuelta",
                            "timestamp": ahora,
                            "crewId": crew_id,
                            "parametroId": param_id,
                        }
                    )

            self._registro[crew_id] = {
                "frame": frame,
                "recibidoEn": ahora,
                "alertas": alertas,
            }
            if persistir:
                self._persistir_snapshot()

        for ev in eventos_a_emitir:
            self._emitir(ev)
        return list(alertas.values())

    def frame_actual(self, crew_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._registro.get(crew_id)
            return item["frame"] if item else None

    def snapshot(self, ahora_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        ahora = int(ahora_ms if ahora_ms is not None else _ahora_ms())
        with self._lock:
            salida: List[Dict[str, Any]] = []
            for crew_id in CREW_IDS:
                item = self._registro.get(crew_id)
                if item is None:
                    salida.append(
                        {
                            "crewId": crew_id,
                            "sexo": sexo_de(crew_id),
                            "nivel": "NOMINAL",
                            "alertasActivas": [],
                            "ultimaActualizacion": 0,
                            "silencioSegundos": None,
                            "estadoEnlace": "sin-enlace",
                            "frame": None,
                        }
                    )
                    continue
                alertas = sorted(
                    item["alertas"].values(),
                    key=lambda a: (
                        -ORDEN_NIVEL.get(a["nivel"], 0),
                        int(a.get("timestamp", 0)),
                    ),
                )
                enlace = (
                    "sin-enlace"
                    if crew_id in self._estaciones_aisladas
                    else _estado_enlace(item["recibidoEn"], ahora)
                )
                salida.append(
                    {
                        "crewId": crew_id,
                        "sexo": sexo_de(crew_id),
                        "nivel": _nivel_global(alertas),
                        "alertasActivas": alertas,
                        "ultimaActualizacion": item["recibidoEn"],
                        "silencioSegundos": max(0, round((ahora - item["recibidoEn"]) / 1_000)),
                        "estadoEnlace": enlace,
                        "frame": item["frame"],
                    }
                )
            return salida

    def latido(self, ahora_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        ahora = int(ahora_ms if ahora_ms is not None else _ahora_ms())
        with self._lock:
            salida = []
            for crew_id, item in sorted(self._registro.items()):
                enlace = (
                    "sin-enlace"
                    if crew_id in self._estaciones_aisladas
                    else _estado_enlace(item["recibidoEn"], ahora)
                )
                salida.append(
                    {
                        "crewId": crew_id,
                        "nivel": _nivel_global(item["alertas"].values()),
                        "estadoEnlace": enlace,
                    }
                )
            return salida

    def suscribir(self, fn: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        with self._lock:
            if fn not in self._suscriptores:
                self._suscriptores.append(fn)

        def unsub() -> None:
            with self._lock:
                if fn in self._suscriptores:
                    self._suscriptores.remove(fn)

        return unsub

    def numero_suscriptores(self) -> int:
        with self._lock:
            return len(self._suscriptores)

    def limpiar_hub(self) -> None:
        with self._lock:
            self._registro.clear()
            self._suscriptores.clear()
            self._estaciones_aisladas.clear()


_hub_singleton: Optional[CrewHub] = None
_hub_lock = threading.Lock()


def get_crew_hub() -> CrewHub:
    global _hub_singleton
    with _hub_lock:
        if _hub_singleton is None:
            _hub_singleton = CrewHub()
        return _hub_singleton
