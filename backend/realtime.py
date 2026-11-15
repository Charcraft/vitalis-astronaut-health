# -*- coding: utf-8 -*-
"""
backend/realtime.py — Motor de telemetría en tiempo real (1 Hz), SimulatedSource y OsdrReplaySource.

Portado de `src/lib/realtime/stream-engine.ts`, `demo/sensor-source.ts` y
`osdr-replay-source.ts` (Back 1):
- Emite un `RealtimeTelemetryFrame` evaluado por `backend/triage.py`.
- Soporta modo `simulado` (PRNG mulberry32 determinista) y modo `replay-osdr`
  (reproduce R+1 -> R+194 de OSD-575 comprimido en ~60 s).
- Permite filtrar lecturas por entorno de misión (`nave`, `estacion`, `base-lunar`)
  y simular/limpiar anomalías temporales en cualquier parámetro con umbrales.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.database import baseline_prevuelo_opcional, get_osdr_dataset
from backend.knowledge import sexo_de
from backend.registry import get_or_throw, get_param, list_params, validate_registry
from backend.triage import MESH_AND_TOOL_BY_INDICATOR, evaluar

ARRANQUE_SUPUESTO: Dict[str, float] = {
    "cabin_co2": 2.5,
    "radiation_dose": 0.4,
    "intracranial_pressure_est": 11.0,
}

ORDEN_NIVEL = {"NOMINAL": 0, "ATENCION": 1, "CRITICO": 2}
TIMEPOINTS_POST_VUELO: Tuple[str, ...] = ("R+1", "R+45", "R+82", "R+194")
DIAS_POR_TIMEPOINT: Tuple[int, ...] = (1, 45, 82, 194)

_OFFSET_CREW_SEMILLA = {"C001": 101, "C002": 203, "C003": 307, "C004": 409}


def _mulberry32(semilla: int) -> Callable[[], float]:
    estado = [semilla & 0xFFFFFFFF]

    def siguiente() -> float:
        estado[0] = (estado[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = estado[0]
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4_294_967_296.0

    return siguiente


def _centro(definicion: Dict[str, Any]) -> Optional[float]:
    rr = definicion.get("rangoReferencia") or {}
    r_min, r_max = rr.get("min"), rr.get("max")
    if r_min is not None and r_max is not None:
        return (float(r_min) + float(r_max)) / 2.0
    if r_max is not None:
        return float(r_max) * 0.9
    if r_min is not None:
        return float(r_min) * 1.1
    return None


def _amplitud(definicion: Dict[str, Any], base: float) -> float:
    rr = definicion.get("rangoReferencia") or {}
    r_min, r_max = rr.get("min"), rr.get("max")
    por_rango = (float(r_max) - float(r_min)) * 0.015 if r_min is not None and r_max is not None else 0.0
    return max(por_rango, abs(base) * 0.008, 0.01)


def valor_anomalo(definicion: Dict[str, Any], nivel: str) -> float:
    """Calcula un valor que rebasa el umbral solicitado o lanza ValueError si no hay umbrales."""
    rr = definicion.get("rangoReferencia") or {}
    r_min, r_max = rr.get("min"), rr.get("max")
    c_min, c_max = rr.get("criticoMin"), rr.get("criticoMax")

    if nivel == "CRITICO":
        if c_max is not None:
            return round(float(c_max) * 1.08 + 0.1, 4)
        if c_min is not None:
            return round(float(c_min) * 0.92 - 0.1, 4)
        if r_max is not None:
            return round(float(r_max) * 1.3, 4)
        if r_min is not None:
            return round(float(r_min) * 0.7, 4)
    else:
        if r_max is not None:
            return round(float(r_max) * 1.05 + 0.01, 4)
        if r_min is not None:
            return round(float(r_min) * 0.95 - 0.01, 4)

    raise ValueError(
        f"No se puede simular una anomalía en «{definicion['id']}»: no tiene umbrales definidos en registry.py."
    )


class SimulatedSource:
    """Fuente de sensores simulada [DEMO] con variación fisiológica acotada."""

    def __init__(
        self,
        crew_id: str,
        baseline_fn: Optional[Callable[[str, str], Optional[float]]] = None,
        semilla: Optional[int] = None,
    ) -> None:
        self.crew_id = crew_id
        self._baseline = baseline_fn or baseline_prevuelo_opcional
        semilla_base = semilla if semilla is not None else (20_261_114 + _OFFSET_CREW_SEMILLA.get(crew_id, 0))
        self._rand = _mulberry32(semilla_base)
        self._valores: Dict[str, float] = {}
        self._iniciales: Dict[str, float] = {}
        for definicion in list_params():
            pid = definicion["id"]
            inicial = self._baseline(crew_id, pid)
            if inicial is None:
                inicial = _centro(definicion)
            if inicial is None:
                inicial = ARRANQUE_SUPUESTO.get(pid, 0.0)
            val_ini = float(inicial)
            self._valores[pid] = val_ini
            self._iniciales[pid] = val_ini

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def leer(self, ahora_ms: int) -> List[Dict[str, Any]]:
        lecturas: List[Dict[str, Any]] = []
        for definicion in list_params():
            pid = definicion["id"]
            actual = self._valores.get(pid, 0.0)
            base_ref = self._iniciales.get(pid, actual)
            paso = _amplitud(definicion, actual)
            factor = 0.2 if definicion.get("frecuencia") == "muestra-discreta" else 1.0
            drift = (base_ref - actual) * 0.15
            siguiente = actual + drift + (self._rand() - 0.5) * 2.0 * paso * factor

            rr = definicion.get("rangoReferencia") or {}
            r_min, r_max = rr.get("min"), rr.get("max")
            if pid == "creatinine":
                sexo = sexo_de(self.crew_id)
                rr_s = (definicion.get("rangoReferenciaPorSexo") or {}).get(sexo or "")
                if rr_s:
                    r_min, r_max = rr_s.get("min"), rr_s.get("max")
            if r_min is not None and r_max is not None:
                # Reversión nominal dentro del rango de referencia para evitar falsas alarmas.
                lo = float(r_min) + 0.02 * (float(r_max) - float(r_min))
                hi = float(r_max) - 0.02 * (float(r_max) - float(r_min))
                siguiente = min(hi, max(lo, siguiente))
            elif r_min is not None:
                siguiente = max(float(r_min) + 1.0, siguiente)
            elif abs(actual) > 0:
                siguiente = min(abs(base_ref) * 1.1, max(abs(base_ref) * 0.9, siguiente))

            if pid == "radiation_dose":
                siguiente = max(actual, min(base_ref + 0.15, siguiente))

            self._valores[pid] = siguiente
            calidad = round(0.94 + self._rand() * 0.06, 3)
            lecturas.append(
                {
                    "parametroId": pid,
                    "valor": round(siguiente, 4),
                    "unidad": definicion["unidad"],
                    "timestamp": ahora_ms,
                    "calidad": calidad,
                }
            )
        return lecturas


class OsdrReplaySource:
    """Reproduce la serie real NASA OSDR OSD-575 (R+1 -> R+194) comprimida en ~60 s."""

    def __init__(
        self,
        crew_id: str,
        duracion_total_ms: int = 60_000,
        solo_osdr: bool = True,
        ahora_fn: Optional[Callable[[], int]] = None,
        on_cambio_timepoint: Optional[Callable[[str, int], None]] = None,
    ) -> None:
        self.crew_id = crew_id
        self.duracion_total_ms = max(1_000, int(duracion_total_ms))
        self.solo_osdr = bool(solo_osdr)
        self._ahora = ahora_fn or (lambda: int(time.time() * 1000))
        self._on_cambio = on_cambio_timepoint
        self._inicio_replay = 0
        self._ultimo_tp_emitido: Optional[str] = None

        dataset = get_osdr_dataset()
        self._indicadores = list(dataset.get("indicadores", []))
        self._valores_por_tp: Dict[str, Dict[str, float]] = {}
        for tp in TIMEPOINTS_POST_VUELO:
            mapa: Dict[str, float] = {}
            for ind in self._indicadores:
                for p in ind.get("serie", {}).get(crew_id, []):
                    if p.get("timepoint") == tp and p.get("valor") is not None:
                        mapa[ind["id"]] = float(p["valor"])
            self._valores_por_tp[tp] = mapa

        self._sim_fallback = (
            None if self.solo_osdr else SimulatedSource(crew_id=crew_id)
        )

    def start(self) -> None:
        self._inicio_replay = self._ahora()
        self._ultimo_tp_emitido = None

    def stop(self) -> None:
        self._inicio_replay = 0

    def get_timepoint_actual(self) -> Optional[str]:
        if self._inicio_replay == 0:
            return None
        transcurrido = max(0, self._ahora() - self._inicio_replay)
        if transcurrido >= self.duracion_total_ms:
            return TIMEPOINTS_POST_VUELO[-1]
        idx = min(
            int((transcurrido / self.duracion_total_ms) * len(TIMEPOINTS_POST_VUELO)),
            len(TIMEPOINTS_POST_VUELO) - 1,
        )
        return TIMEPOINTS_POST_VUELO[idx]

    def get_dia_mision(self) -> Optional[int]:
        tp = self.get_timepoint_actual()
        if not tp:
            return None
        idx = TIMEPOINTS_POST_VUELO.index(tp)
        return DIAS_POR_TIMEPOINT[idx]

    def leer(self, ahora_ms: int) -> List[Dict[str, Any]]:
        if self._inicio_replay == 0:
            self.start()
        transcurrido = max(0, ahora_ms - self._inicio_replay)
        if transcurrido >= self.duracion_total_ms:
            tp = TIMEPOINTS_POST_VUELO[-1]
            idx = len(TIMEPOINTS_POST_VUELO) - 1
        else:
            proporcion = transcurrido / self.duracion_total_ms
            idx = min(
                int(proporcion * len(TIMEPOINTS_POST_VUELO)),
                len(TIMEPOINTS_POST_VUELO) - 1,
            )
            tp = TIMEPOINTS_POST_VUELO[idx]

        if tp != self._ultimo_tp_emitido:
            self._ultimo_tp_emitido = tp
            if self._on_cambio:
                self._on_cambio(tp, DIAS_POR_TIMEPOINT[idx])

        valores = self._valores_por_tp.get(tp, {})
        lecturas: List[Dict[str, Any]] = []
        for pid, val in valores.items():
            definicion = get_param(pid)
            if definicion is None:
                continue
            lecturas.append(
                {
                    "parametroId": pid,
                    "valor": val,
                    "unidad": definicion["unidad"],
                    "timestamp": ahora_ms,
                    "calidad": 1.0,
                    "contexto": {"actividad": "replay-historico"},
                }
            )

        if self._sim_fallback is not None:
            osdr_ids = {l["parametroId"] for l in lecturas}
            for sim in self._sim_fallback.leer(ahora_ms):
                if sim["parametroId"] not in osdr_ids:
                    lecturas.append(sim)
        return lecturas


def _nivel_mas_grave(a: str, b: str) -> str:
    return a if ORDEN_NIVEL.get(a, 0) >= ORDEN_NIVEL.get(b, 0) else b


def _acumular_nodo(
    estado: Dict[str, Dict[str, Any]],
    definicion: Dict[str, Any],
    nivel: str,
) -> None:
    nodo_id = definicion.get("meshNodeId")
    if nodo_id is None:
        return
    actual = estado.get(nodo_id)
    nivel_max = _nivel_mas_grave(actual["nivelMaximo"], nivel) if actual else nivel
    anim = (
        definicion.get("toolAnimationId")
        if nivel != "NOMINAL" and definicion.get("toolAnimationId") != "anim_none"
        else None
    )
    estado[nodo_id] = {
        "nivelMaximo": nivel_max,
        "parametroPrincipalId": actual["parametroPrincipalId"] if actual else definicion["id"],
        "animacionActiva": anim if anim is not None else (actual["animacionActiva"] if actual else None),
    }


class StreamEngine:
    """Motor determinista 1 Hz por tripulante sin efectos secundarios en base de datos."""

    def __init__(
        self,
        crew_id: str,
        fuente: Any,
        *,
        entorno: str = "nave",
        modo: str = "simulado",
        baseline_fn: Optional[Callable[[str, str], Optional[float]]] = None,
        ahora_fn: Optional[Callable[[], int]] = None,
        met_inicial_segundos: int = 0,
        respetar_intervalos: bool = False,
    ) -> None:
        validate_registry()
        self.crew_id = crew_id
        self.entorno = entorno
        self.modo = modo
        self.fuente = fuente
        self._baseline = baseline_fn or baseline_prevuelo_opcional
        self._ahora = ahora_fn or (lambda: int(time.time() * 1000))
        self._met_inicial = met_inicial_segundos
        self._respetar_intervalos = respetar_intervalos
        self._inicio_ms = self._ahora()
        self._ultimo_envio: Dict[str, int] = {}
        self._anomalias: Dict[str, Dict[str, Any]] = {}
        self._suscriptores: List[Callable[[Dict[str, Any]], None]] = []

    def set_entorno(self, entorno: str) -> None:
        if entorno in ("nave", "estacion", "base-lunar"):
            self.entorno = entorno

    def subscribe(self, fn: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        if fn not in self._suscriptores:
            self._suscriptores.append(fn)

        def unsub() -> None:
            if fn in self._suscriptores:
                self._suscriptores.remove(fn)

        return unsub

    def forzar_anomalia(
        self, param_id: str, nivel: str, duracion_ms: int = 30_000
    ) -> None:
        if nivel not in ("ATENCION", "CRITICO"):
            raise ValueError(f"Nivel de anomalía inválido: {nivel}")
        definicion = get_or_throw(param_id)
        valor_anomalo(definicion, nivel)
        self._anomalias[param_id] = {
            "nivel": nivel,
            "hasta": self._ahora() + int(duracion_ms),
        }

    def limpiar_anomalia(self, param_id: str) -> None:
        self._anomalias.pop(param_id, None)

    def limpiar_anomalias(self) -> None:
        self._anomalias.clear()

    def anomalias_activas(self) -> List[Dict[str, Any]]:
        ahora = self._ahora()
        activas = []
        expiradas = []
        for pid, info in self._anomalias.items():
            if info["hasta"] > ahora:
                activas.append({"parametroId": pid, "nivel": info["nivel"], "hasta": info["hasta"]})
            else:
                expiradas.append(pid)
        for pid in expiradas:
            self._anomalias.pop(pid, None)
        return activas

    def tick(self) -> Dict[str, Any]:
        ahora = self._ahora()
        lecturas_out: Dict[str, Dict[str, Any]] = {}
        estado_nodos: Dict[str, Dict[str, Any]] = {}
        sexo_eff = sexo_de(self.crew_id)

        for lectura in self.fuente.leer(ahora):
            pid = lectura["parametroId"]
            definicion = get_or_throw(pid)
            if self.entorno not in definicion.get("entornos", ()):
                continue

            if self._respetar_intervalos and definicion.get("intervaloMs") is not None:
                ultimo = self._ultimo_envio.get(pid)
                if ultimo is not None and (ahora - ultimo) < int(definicion["intervaloMs"]):
                    continue
            self._ultimo_envio[pid] = ahora

            anom = self._anomalias.get(pid)
            if anom and ahora >= anom["hasta"]:
                self._anomalias.pop(pid, None)
                anom = None

            valor = valor_anomalo(definicion, anom["nivel"]) if anom else float(lectura["valor"])
            calidad = float(lectura.get("calidad", 1.0))
            baseline = self._baseline(self.crew_id, pid)

            ev = evaluar(
                pid,
                valor,
                baseline,
                entorno=self.entorno,
                calidad=calidad,
                sexo=sexo_eff,
            )

            meta_visual = MESH_AND_TOOL_BY_INDICATOR.get(pid, {})
            lecturas_out[pid] = {
                "valor": valor,
                "unidad": definicion["unidad"],
                "baselinePersonal": baseline,
                "desviacion": ev["desviacion"],
                "nivel": ev["nivel"],
                "meshNodeId": definicion["meshNodeId"],
                "toolAnimationId": definicion["toolAnimationId"],
                "calidad": calidad,
                "razon": ev["razon"],
                "accion": ev["accion"],
                "reglaDisparada": ev["reglaDisparada"],
                "fuente": ev["fuente"],
                "degradado": ev["degradado"],
                "esDatoRealOSDR": bool(definicion.get("esDatoRealOSDR")),
                "sistema": definicion["sistema"],
                "sistemaVisual": meta_visual.get("sistema") or definicion.get("sistemaVisual", "metabolico"),
            }
            if definicion.get("meshNodeId") is not None:
                _acumular_nodo(estado_nodos, definicion, ev["nivel"])

        tp_replay = (
            self.fuente.get_timepoint_actual()
            if hasattr(self.fuente, "get_timepoint_actual")
            else None
        )
        dia_replay = (
            self.fuente.get_dia_mision()
            if hasattr(self.fuente, "get_dia_mision")
            else None
        )
        frame: Dict[str, Any] = {
            "timestamp": ahora,
            "crewId": self.crew_id,
            "entorno": self.entorno,
            "modo": self.modo,
            "timepointReplay": tp_replay,
            "diaMisionReplay": dia_replay,
            "metSegundos": self._met_inicial + max(0, (ahora - self._inicio_ms) // 1_000),
            "lecturas": lecturas_out,
            "estadoNodos3D": estado_nodos,
        }
        for sub in list(self._suscriptores):
            try:
                sub(frame)
            except Exception:
                pass
        return frame
