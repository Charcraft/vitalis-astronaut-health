# -*- coding: utf-8 -*-
"""
backend/runtime.py — Orquestador de ejecución en vivo (Composition Root).

Portado de `src/lib/runtime.ts`:
Cablea `StreamEngine` (C001–C004) -> `CrewHub` (SSE + snapshot durable)
-> Back 2 SQLite (`sensor_measurements`, `telemetry_series`, `episodes`, `emergency_events`)
-> `SyncTierraManager` (cola prioritaria A/B/C/D + flush hacia Tierra).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from backend.crew_hub import CREW_IDS, CrewHub, get_crew_hub
from backend.database import (
    abrir_episodio,
    agregar_y_persistir_series,
    cerrar_episodio,
    guardar_frame_bd,
    init_db,
    podar_series,
    podar_ventana,
    registrar_evento_emergencia,
)
from backend.realtime import OsdrReplaySource, SimulatedSource, StreamEngine
from backend.sync_tierra import SyncTierraManager, get_sync_manager


class VITALISRuntime:
    """Gestiona los motores de telemetría de la tripulación y su pipeline."""

    def __init__(
        self,
        hub: Optional[CrewHub] = None,
        sync_manager: Optional[SyncTierraManager] = None,
    ) -> None:
        self._lock = threading.RLock()
        self.hub = hub or get_crew_hub()
        self.sync = sync_manager or get_sync_manager()

        self.crew_id_activa: str = "C001"
        self.entorno: str = "nave"
        self.modo: str = "simulado"  # "simulado" | "replay-osdr"
        self.respetar_intervalos: bool = False
        self.iniciado: bool = False

        self._motores: Dict[str, StreamEngine] = {}
        self._ultimo_nivel: Dict[str, str] = {}
        self._suscriptores_ui: List[Callable[[Dict[str, Any]], None]] = []
        self._frames_actuales: Dict[str, Dict[str, Any]] = {}

        self._stop_event = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._ultimo_persistido_s: Dict[str, int] = {}
        self._ultimo_flush_s: float = 0.0
        self._ultimo_bg_s: float = 0.0
        self._ultimo_podado_s: float = 0.0

        self._sync_unsub = self.sync.on_cambio_red(self._al_cambiar_red)

    def _al_cambiar_red(self, estado: str) -> None:
        if estado == "online":
            try:
                self.sync.flush_cola()
            except Exception:
                pass

    def _crear_fuente(self, crew_id: str, modo: str) -> Any:
        if modo == "replay-osdr":
            src = OsdrReplaySource(
                crew_id=crew_id, duracion_total_ms=60_000, solo_osdr=False
            )
            src.start()
            return src
        return SimulatedSource(crew_id=crew_id)

    def _asegurar_motores(self) -> None:
        for cid in CREW_IDS:
            if cid not in self._motores:
                fuente = self._crear_fuente(cid, self.modo)
                self._motores[cid] = StreamEngine(
                    crew_id=cid,
                    fuente=fuente,
                    entorno=self.entorno,
                    modo=self.modo,
                    respetar_intervalos=self.respetar_intervalos,
                )

    def _detectar_emergencia_y_episodios(self, frame: Dict[str, Any]) -> None:
        crew_id = str(frame.get("crewId", "C001"))
        ts_ms = int(frame.get("timestamp") or time.time() * 1000)
        for param_id, lectura in (frame.get("lecturas") or {}).items():
            clave = f"{crew_id}:{param_id}"
            anterior = self._ultimo_nivel.get(clave)
            nivel = str(lectura.get("nivel", "NOMINAL"))

            if nivel == "CRITICO" and anterior != "CRITICO":
                evt_id = registrar_evento_emergencia(
                    crew_id=crew_id,
                    timestamp_ms=ts_ms,
                    severidad="CRITICO",
                    detalle=f"{param_id}: {lectura.get('razon', '')}",
                )
                self.sync.encolar_evento(evt_id, "CRITICO")

            if nivel != "NOMINAL":
                abrir_episodio(crew_id, param_id, nivel, inicio_ms=ts_ms)
            elif anterior is not None and anterior != "NOMINAL":
                cerrar_episodio(crew_id, param_id, fin_ms=ts_ms)

            self._ultimo_nivel[clave] = nivel

    def _procesar_tick_crew(self, crew_id: str, forzar_sync: bool = False) -> Dict[str, Any]:
        motor = self._motores[crew_id]
        frame = motor.tick()
        self._frames_actuales[crew_id] = frame
        self.hub.publicar_frame(frame)
        self._detectar_emergencia_y_episodios(frame)
        agregar_y_persistir_series(frame)

        ahora_s = int(time.time())
        hay_alerta = any(
            l.get("nivel") in ("ATENCION", "CRITICO")
            for l in (frame.get("lecturas") or {}).values()
        )
        ultimo_s = self._ultimo_persistido_s.get(crew_id, 0)
        if forzar_sync or hay_alerta or (ahora_s - ultimo_s >= 5):
            guardar_frame_bd(frame)
            self.sync.encolar_frame(frame)
            self._ultimo_persistido_s[crew_id] = ahora_s

        if crew_id == self.crew_id_activa:
            with self._lock:
                subs = list(self._suscriptores_ui)
            for fn in subs:
                try:
                    fn(frame)
                except Exception:
                    pass
        return frame

    def start(
        self,
        crew_id: Optional[str] = None,
        entorno: Optional[str] = None,
        modo: Optional[str] = None,
        respetar_intervalos: Optional[bool] = None,
    ) -> None:
        init_db()
        with self._lock:
            if crew_id and crew_id in CREW_IDS:
                self.crew_id_activa = crew_id
            if entorno and entorno in ("nave", "estacion", "base-lunar"):
                self.entorno = entorno
            if modo and modo in ("simulado", "replay-osdr"):
                if modo != self.modo:
                    self.modo = modo
                    self._motores.clear()
            if respetar_intervalos is not None:
                self.respetar_intervalos = bool(respetar_intervalos)

            self._asegurar_motores()
            for motor in self._motores.values():
                motor.set_entorno(self.entorno)

            if self.iniciado and self._hilo and self._hilo.is_alive():
                self._procesar_tick_crew(self.crew_id_activa, forzar_sync=True)
                return

            self._stop_event.clear()
            # Sembrar un primer tick inmediato de las 4 estaciones para poblar Sala y vistas.
            for cid in CREW_IDS:
                if not self.hub.es_estacion_aislada(cid):
                    self._procesar_tick_crew(cid, forzar_sync=(cid == self.crew_id_activa))

            self._ultimo_flush_s = time.time()
            self._ultimo_bg_s = time.time()
            self._ultimo_podado_s = time.time()
            self.iniciado = True
            self._hilo = threading.Thread(
                target=self._bucle, name="vitalis-stream-1hz", daemon=True
            )
            self._hilo.start()

    def _bucle(self) -> None:
        while not self._stop_event.wait(1.0):
            try:
                ahora = time.time()
                with self._lock:
                    activa = self.crew_id_activa
                    motores = dict(self._motores)
                if activa in motores and not self.hub.es_estacion_aislada(activa):
                    self._procesar_tick_crew(activa)

                if ahora - self._ultimo_bg_s >= 3.0:
                    self._ultimo_bg_s = ahora
                    for cid in CREW_IDS:
                        if cid != activa and cid in motores and not self.hub.es_estacion_aislada(cid):
                            self._procesar_tick_crew(cid)

                if ahora - self._ultimo_flush_s >= 10.0:
                    self._ultimo_flush_s = ahora
                    if self.sync.estado_red() != "offline":
                        self.sync.flush_cola()

                if ahora - self._ultimo_podado_s >= 3600.0:
                    self._ultimo_podado_s = ahora
                    podar_ventana(30)
                    podar_series(30)
            except Exception:
                pass

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            self.iniciado = False
            hilo = self._hilo
        if hilo and hilo.is_alive():
            hilo.join(timeout=1.5)

    def set_crew_activa(self, crew_id: str) -> Optional[Dict[str, Any]]:
        if crew_id not in CREW_IDS:
            return None
        with self._lock:
            self.crew_id_activa = crew_id
            self._asegurar_motores()
        return self._procesar_tick_crew(crew_id, forzar_sync=True)

    def set_entorno(self, entorno: str) -> None:
        if entorno not in ("nave", "estacion", "base-lunar"):
            raise ValueError(f"Entorno de misión inválido: {entorno}")
        with self._lock:
            self.entorno = entorno
            self._asegurar_motores()
            for motor in self._motores.values():
                motor.set_entorno(entorno)
        self._procesar_tick_crew(self.crew_id_activa, forzar_sync=True)

    def set_modo(self, modo: str) -> None:
        if modo not in ("simulado", "replay-osdr"):
            raise ValueError(f"Modo inválido: {modo}")
        with self._lock:
            if self.modo == modo:
                return
            self.modo = modo
            anomalias_prev: Dict[str, List[Dict[str, Any]]] = {
                cid: m.anomalias_activas() for cid, m in self._motores.items()
            }
            self._motores.clear()
            self._asegurar_motores()
            for cid, lista in anomalias_prev.items():
                if cid in self._motores:
                    for item in lista:
                        self._motores[cid].forzar_anomalia(item["parametroId"], item["nivel"])
        self._procesar_tick_crew(self.crew_id_activa, forzar_sync=True)

    def forzar_anomalia(
        self,
        param_id: str,
        nivel: str,
        crew_id: Optional[str] = None,
        duracion_ms: int = 30_000,
    ) -> Dict[str, Any]:
        cid = crew_id or self.crew_id_activa
        with self._lock:
            self._asegurar_motores()
            motor = self._motores[cid]
            motor.forzar_anomalia(param_id, nivel, duracion_ms=duracion_ms)
        return self._procesar_tick_crew(cid, forzar_sync=True)

    def limpiar_anomalias(self, crew_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        cid = crew_id or self.crew_id_activa
        with self._lock:
            motor = self._motores.get(cid)
            if motor:
                motor.limpiar_anomalias()
        if cid in self._motores:
            return self._procesar_tick_crew(cid, forzar_sync=True)
        return None

    def anomalias_activas(self, crew_id: Optional[str] = None) -> List[Dict[str, Any]]:
        cid = crew_id or self.crew_id_activa
        motor = self._motores.get(cid)
        return motor.anomalias_activas() if motor else []

    def frame_actual(self, crew_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        cid = crew_id or self.crew_id_activa
        with self._lock:
            if cid in self._frames_actuales:
                return self._frames_actuales[cid]
            self._asegurar_motores()
        return self._procesar_tick_crew(cid, forzar_sync=False)

    def tick_una_vez(self, crew_id: Optional[str] = None) -> Dict[str, Any]:
        cid = crew_id or self.crew_id_activa
        with self._lock:
            self._asegurar_motores()
        return self._procesar_tick_crew(cid, forzar_sync=True)

    def subscribe(self, fn: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        with self._lock:
            if fn not in self._suscriptores_ui:
                self._suscriptores_ui.append(fn)

        def unsub() -> None:
            with self._lock:
                if fn in self._suscriptores_ui:
                    self._suscriptores_ui.remove(fn)

        return unsub

    def estado_resumen(self) -> Dict[str, Any]:
        return {
            "iniciado": self.iniciado,
            "crewId": self.crew_id_activa,
            "entorno": self.entorno,
            "modo": self.modo,
            "anomaliasActivas": self.anomalias_activas(),
            "sync": self.sync.stats(),
        }


_runtime_singleton: Optional[VITALISRuntime] = None
_runtime_lock = threading.Lock()


def get_runtime() -> VITALISRuntime:
    global _runtime_singleton
    with _runtime_lock:
        if _runtime_singleton is None:
            _runtime_singleton = VITALISRuntime()
        return _runtime_singleton
