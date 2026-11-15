# -*- coding: utf-8 -*-
"""
backend/sync_tierra.py — Cola de sincronización prioritaria hacia Tierra y respaldo.

Portado de `src/lib/sync/queue.ts`, `src/lib/sync/transport.ts`,
`src/lib/export/backup.ts` y `/api/tierra/route.ts`:
- Prioridades: A=crítico, B=alerta, C=medición/frame nominal, D=bitácora.
- Hash encadenado djb2 (`hash_i = djb2(hash_{i-1} + payload_i)`).
- Modo offline-first configurable: acumula en SQLite cuando el enlace a Tierra
  está caído y drena automáticamente en orden A>B>C>D al reconectar hacia
  `data/tierra/lotes.jsonl` reconciliando `sensor_measurements.sincronizado_tierra`.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from backend.database import (
    DATA_DIR,
    encolar_lote_bd,
    marcar_bitacora_sincronizada,
    marcar_evento_sincronizado,
    marcar_lote_enviado_bd,
    marcar_lote_rechazado_bd,
    marcar_sincronizado,
    marcar_sincronizado_por_frame,
    obtener_ultimo_hash_confirmado_bd,
    reintentar_rechazados_bd,
    stats_cola_bd,
    tomar_siguiente_lote_bd,
)

TIERRA_DIR = os.path.join(DATA_DIR, "tierra")
TIERRA_LOTES_FILE = os.path.join(TIERRA_DIR, "lotes.jsonl")
HASH_SEMILLA = 5381


def djb2_hash(texto: str) -> str:
    h = HASH_SEMILLA
    for ch in texto:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return f"h{h:x}"


def serializar_para_hash(payload: Dict[str, Any]) -> str:
    if "timestamp" in payload and "lecturas" in payload:
        resumen_lecturas = {
            k: [v.get("valor"), v.get("nivel")]
            for k, v in sorted((payload.get("lecturas") or {}).items())
        }
        return json.dumps(
            {
                "t": payload.get("timestamp"),
                "c": payload.get("crewId"),
                "l": resumen_lecturas,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    if "eventoId" in payload:
        return f"evt:{payload['eventoId']}"
    if "bitacoraId" in payload:
        return f"log:{payload['bitacoraId']}"
    if "medicionId" in payload:
        return f"med:{payload['medicionId']}"
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def calcular_hash_encadenado(payload: Dict[str, Any], hash_previo: Optional[str]) -> str:
    base = (hash_previo or "") + serializar_para_hash(payload)
    return djb2_hash(base)


def prioridad_de_frame(frame: Dict[str, Any]) -> str:
    niveles = [str(v.get("nivel", "NOMINAL")) for v in (frame.get("lecturas") or {}).values()]
    if "CRITICO" in niveles:
        return "A"
    if "ATENCION" in niveles:
        return "B"
    return "C"


def guardar_lote_en_tierra(lote: Dict[str, Any], path: str = TIERRA_LOTES_FILE) -> None:
    """Persiste append-only el lote recibido en Tierra (`data/tierra/lotes.jsonl`)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    registro = {
        "id": lote.get("id"),
        "prioridad": lote.get("prioridad"),
        "tipo": lote.get("tipo"),
        "hash": lote.get("hash"),
        "hashPrevio": lote.get("hashPrevio"),
        "creadoEn": lote.get("creadoEn"),
        "recibidoTierraEn": int(time.time() * 1000),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def contar_recibidos_tierra(path: str = TIERRA_LOTES_FILE) -> int:
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def listar_recibidos_tierra(
    limit: int = 20, path: str = TIERRA_LOTES_FILE
) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        salida: List[Dict[str, Any]] = []
        for line in reversed(lines[-int(limit) :]):
            try:
                salida.append(json.loads(line))
            except Exception:
                pass
        return salida
    except Exception:
        return []


class SyncTierraManager:
    """Orquesta cola prioritaria, hash encadenado y transporte hacia Tierra."""

    def __init__(self, lotes_path: str = TIERRA_LOTES_FILE) -> None:
        self._lock = threading.RLock()
        self._estado_red: str = "online"  # "online" | "offline" | "degradado"
        self._lotes_path = lotes_path
        self._listeners: List[Callable[[str], None]] = []

    def estado_red(self) -> str:
        with self._lock:
            return self._estado_red

    def set_estado_red(self, estado: str) -> str:
        if estado not in ("online", "offline", "degradado"):
            raise ValueError(f"Estado de red inválido: {estado}")
        cambio = False
        with self._lock:
            if self._estado_red != estado:
                self._estado_red = estado
                cambio = True
            subs = list(self._listeners)
        if cambio:
            for fn in subs:
                try:
                    fn(estado)
                except Exception:
                    pass
        return estado

    def on_cambio_red(self, fn: Callable[[str], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(fn)

        def unsub() -> None:
            with self._lock:
                if fn in self._listeners:
                    self._listeners.remove(fn)

        return unsub

    def encolar_frame(self, frame: Dict[str, Any]) -> int:
        with self._lock:
            hash_previo = obtener_ultimo_hash_confirmado_bd()
            prio = prioridad_de_frame(frame)
            hash_val = calcular_hash_encadenado(frame, hash_previo)
            payload_json = json.dumps(frame, ensure_ascii=False)
            return encolar_lote_bd(
                prioridad=prio,
                tipo="frame",
                payload_id=int(frame.get("timestamp") or time.time() * 1000),
                payload_json=payload_json,
                hash_val=hash_val,
                hash_previo=hash_previo,
            )

    def encolar_evento(self, evento_id: int, severidad: str) -> int:
        with self._lock:
            hash_previo = obtener_ultimo_hash_confirmado_bd()
            prio = "A" if severidad == "CRITICO" else "B"
            payload = {"eventoId": int(evento_id)}
            hash_val = calcular_hash_encadenado(payload, hash_previo)
            return encolar_lote_bd(
                prioridad=prio,
                tipo="evento",
                payload_id=int(evento_id),
                payload_json=json.dumps(payload, ensure_ascii=False),
                hash_val=hash_val,
                hash_previo=hash_previo,
            )

    def encolar_bitacora(self, bitacora_id: int) -> int:
        with self._lock:
            hash_previo = obtener_ultimo_hash_confirmado_bd()
            payload = {"bitacoraId": int(bitacora_id)}
            hash_val = calcular_hash_encadenado(payload, hash_previo)
            return encolar_lote_bd(
                prioridad="D",
                tipo="bitacora",
                payload_id=int(bitacora_id),
                payload_json=json.dumps(payload, ensure_ascii=False),
                hash_val=hash_val,
                hash_previo=hash_previo,
            )

    def encolar_medicion(self, medicion_id: int, nivel: str = "NOMINAL") -> int:
        with self._lock:
            hash_previo = obtener_ultimo_hash_confirmado_bd()
            prio = "A" if nivel == "CRITICO" else ("B" if nivel == "ATENCION" else "C")
            payload = {"medicionId": int(medicion_id)}
            hash_val = calcular_hash_encadenado(payload, hash_previo)
            return encolar_lote_bd(
                prioridad=prio,
                tipo="medicion",
                payload_id=int(medicion_id),
                payload_json=json.dumps(payload, ensure_ascii=False),
                hash_val=hash_val,
                hash_previo=hash_previo,
            )

    def flush_cola(self, max_lotes: int = 50) -> Dict[str, Any]:
        inicio = time.time()
        with self._lock:
            if self._estado_red == "offline":
                return {
                    "procesados": 0,
                    "exitosos": 0,
                    "fallidos": 0,
                    "duracionMs": 0,
                }
            reintentar_rechazados_bd()
            procesados = 0
            exitosos = 0
            fallidos = 0
            for _ in range(max_lotes):
                lote = tomar_siguiente_lote_bd()
                if lote is None:
                    break
                procesados += 1
                try:
                    guardar_lote_en_tierra(lote, path=self._lotes_path)
                    marcar_lote_enviado_bd(lote["id"])
                    exitosos += 1
                    tipo_lote = lote.get("tipo")
                    payload = lote.get("payload") or {}
                    if tipo_lote == "frame" and "crewId" in payload and "timestamp" in payload:
                        marcar_sincronizado_por_frame(
                            str(payload["crewId"]), int(payload["timestamp"])
                        )
                    elif tipo_lote == "medicion" and "medicionId" in payload:
                        marcar_sincronizado([int(payload["medicionId"])])
                    elif tipo_lote == "evento" and "eventoId" in payload:
                        marcar_evento_sincronizado(int(payload["eventoId"]))
                    elif tipo_lote == "bitacora" and "bitacoraId" in payload:
                        marcar_bitacora_sincronizada(int(payload["bitacoraId"]))
                except Exception:
                    marcar_lote_rechazado_bd(lote["id"])
                    fallidos += 1
                    break
            return {
                "procesados": procesados,
                "exitosos": exitosos,
                "fallidos": fallidos,
                "duracionMs": int((time.time() - inicio) * 1000),
            }

    def stats(self) -> Dict[str, Any]:
        return {
            "cola": stats_cola_bd(),
            "red": self.estado_red(),
            "recibidosTierra": contar_recibidos_tierra(self._lotes_path),
        }


_sync_singleton: Optional[SyncTierraManager] = None
_sync_lock = threading.Lock()


def get_sync_manager() -> SyncTierraManager:
    global _sync_singleton
    with _sync_lock:
        if _sync_singleton is None:
            _sync_singleton = SyncTierraManager()
        return _sync_singleton
