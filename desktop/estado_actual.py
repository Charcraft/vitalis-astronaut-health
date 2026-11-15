# -*- coding: utf-8 -*-
"""
desktop/estado_actual.py — El estado de salud ACTUAL, en un solo sitio.

«Actual» = tripulante + momento de la misión elegidos. De aquí leen el Inicio,
el Cuerpo 3D, el visor y los avisos, así nunca cuentan cosas distintas.

Un aviso sale de dos fuentes:
  1. El dataset OSD-575: analito fuera de su rango de referencia en ese momento
     (lo decide backend.triage; aquí no se inventa ningún umbral).
  2. Una medición local reciente del mismo tripulante tomada con la app.
     [SUPUESTO] La medición local más reciente de un analito manda sobre el
     dataset: si vuelve a rango, el aviso desaparece; si sale de rango, aparece.
     Las tomadas desde «Medir» llevan en sus notas el momento de la misión en
     que se hicieron (`[R+45]`) y sólo cuentan en ese momento; las que no lo
     llevan (L.I.S., versiones anteriores) cuentan siempre.

Sin Qt: se puede importar desde cualquier vista sin ciclos.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Set

from backend.crew_hub import get_crew_hub
from backend.database import get_osdr_dataset, listar_mediciones_locales
from backend.registry import get_param
from backend.triage import evaluar_lectura_determinista, listar_anomalias_tripulante
from desktop import theme as t
from desktop.i18n import tr

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPA_PATH = os.path.join(ROOT_DIR, "recursos", "datos", "knowledge", "analito-organos.json")

ORDEN_NIVEL = t.TRIAGE_ORDEN

_ORGANOS_VIVO: Dict[str, List[str]] = {
    "heart_rate": ["heart"],
    "systolic_bp": ["heart"],
    "diastolic_bp": ["heart"],
    "spo2": ["lung_tissue_l", "lung_tissue_r"],
    "respiratory_rate": ["lung_tissue_l", "lung_tissue_r"],
    "core_temperature": ["spleen", "lymph_nodes"],
    "intracranial_pressure_est": ["brain", "eye_l", "eye_r"],
    "cabin_co2": ["lung_tissue_l", "lung_tissue_r"],
    "radiation_dose": ["spleen", "lymph_nodes", "bone_marrow"],
}

# Nombre (en plural cuando son pares) de los órganos que puede resaltar un aviso.
NOMBRE_ORGANO = {
    "pancreas": "páncreas", "liver": "hígado", "gallbladder": "vesícula",
    "kidney_l": "riñones", "kidney_r": "riñones", "adrenal_l": "suprarrenales",
    "adrenal_r": "suprarrenales", "heart": "corazón", "brain": "encéfalo",
    "eye_l": "ojos", "eye_r": "ojos",
    "lung_tissue_l": "pulmones", "lung_tissue_r": "pulmones", "parathyroids": "paratiroides",
    "spleen": "bazo", "lymph_nodes": "ganglios", "bone_marrow": "médula ósea",
    "pelvis": "huesos", "femur_l": "huesos", "femur_r": "huesos", "spine_lumbar": "huesos",
}

# Sistema fisiológico -> protocolo de emergencia que le corresponde.
PROTOCOLO_POR_SISTEMA = {
    "cardiovascular": "cardiovascular",
    "respiratorio": "respiratorio",
    "neuro-ocular": "neurologico",
}

_MAPA: Dict[str, List[str]] = {}
_NOMBRES_AMBIGUOS: Optional[Set[str]] = None


def _mapa() -> Dict[str, List[str]]:
    global _MAPA
    if not _MAPA:
        try:
            with open(MAPA_PATH, "r", encoding="utf-8") as f:
                _MAPA = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
        except Exception:
            _MAPA = {}
    return _MAPA


def nombre_corto(nombre: str) -> str:
    """«AST (aspartato aminotransferasa)» -> «AST»: el paréntesis no cabe ni ayuda.

    Salvo si al quitarlo dos analitos quedan iguales («eGFR» y «eGFR (ajuste
    afroamericano)»): entonces se deja el nombre completo.
    """
    global _NOMBRES_AMBIGUOS
    if _NOMBRES_AMBIGUOS is None:
        cortos = [i["nombre"].split(" (")[0].strip() for i in get_osdr_dataset().get("indicadores", [])]
        _NOMBRES_AMBIGUOS = {c for c in cortos if cortos.count(c) > 1}
    corto = (nombre or "").split(" (")[0].strip()
    return tr(nombre if corto in _NOMBRES_AMBIGUOS else corto)


def clave_aviso(crew_id: str, timepoint: str, indicador_id: str, valor: Any) -> str:
    """Identifica un aviso concreto para recordar si ya se revisó."""
    return f"{crew_id}|{timepoint}|{indicador_id}|{valor}"


def _aviso_desde_evaluacion(ev: Dict[str, Any], origen: str, momento: str = "") -> Dict[str, Any]:
    rango = ev.get("rangoReferencia") or {}
    alto = rango.get("max") is not None and ev["valor"] > rango["max"]
    organos = _mapa().get(ev["indicadorId"]) or _ORGANOS_VIVO.get(ev["indicadorId"], [])
    nombres: List[str] = []
    for o in organos:
        n = tr(NOMBRE_ORGANO.get(o, o))
        if n not in nombres:
            nombres.append(n)
    proto_disp = ev.get("protocoloSugerido")
    return {
        "indicadorId": ev["indicadorId"],
        # «por encima/debajo del rango» concuerda con cualquier analito; el rango
        # es el del propio dataset.
        "titulo": tr(
            "{analito} por encima del rango" if alto else "{analito} por debajo del rango",
            analito=nombre_corto(ev["nombre"]),
        ),
        "valor": ev["valor"],
        "unidad": ev.get("unidad", ""),
        "nivel": ev["nivel"],
        "desvio": ev.get("desvioPorcentajeBaseline", 0.0),
        "sistema": ev.get("sistema", "metabolico"),
        "organos": organos,
        "nombresOrganos": nombres,
        "accion": ev.get("accionSugerida", ""),
        "origen": origen,          # "dataset" | "local" | "vivo"
        "momento": momento,        # fecha/hora de la medición local, si la hay
        "protocolo": PROTOCOLO_POR_SISTEMA.get(ev.get("sistema", "")),
        "protocoloDisparadorId": proto_disp.get("id") if isinstance(proto_disp, dict) else None,
        "reglaDisparada": ev.get("reglaDisparada", ""),
        "degradado": bool(ev.get("degradado", False)),
        "revisado": False,
    }


_ETIQUETA_MOMENTO = re.compile(r"^\[([^\]]+)\]")


def etiqueta_momento(timepoint: str) -> str:
    """Prefijo que «Medir» guarda en las notas para ligar la toma a su momento."""
    return f"[{timepoint}]"


def _mediciones_locales_recientes(crew_id: str, timepoint: str) -> Dict[str, Dict[str, Any]]:
    """Última medición local de cada analito que cuenta en este momento."""
    ultimas: Dict[str, Dict[str, Any]] = {}
    for m in listar_mediciones_locales(crew_id=crew_id, limit=60):  # de la más nueva a la más vieja
        ind = m.get("indicadorId") or m.get("indicador_id")
        if not ind or ind in ultimas:
            continue
        etiqueta = _ETIQUETA_MOMENTO.match(str(m.get("notas") or ""))
        if etiqueta and etiqueta.group(1) != timepoint:
            continue
        ultimas[ind] = m
    return ultimas


def avisos_actuales(
    crew_id: str, timepoint: str, revisados: Optional[Iterable[str]] = None
) -> List[Dict[str, Any]]:
    """Avisos del momento actual, del más grave al más leve."""
    revisados_set = set(revisados or ())
    por_analito: Dict[str, Dict[str, Any]] = {}

    for a in listar_anomalias_tripulante(crew_id, timepoint):
        por_analito[a["indicadorId"]] = _aviso_desde_evaluacion(a, "dataset")

    for ind, m in _mediciones_locales_recientes(crew_id, timepoint).items():
        try:
            valor = float(m.get("valor"))
        except (TypeError, ValueError):
            continue
        ev = evaluar_lectura_determinista(crew_id, ind, valor)
        momento = str(m.get("createdAt") or m.get("created_at") or "")[:16].replace("T", " ")
        if ev["nivel"] == "NOMINAL":
            por_analito.pop(ind, None)  # la nueva toma vuelve a rango: aviso resuelto
        else:
            por_analito[ind] = _aviso_desde_evaluacion(ev, "local", momento)

    # Lecturas en vivo del hub (anomalías simuladas o parámetros en tiempo real fuera de rango)
    from backend.runtime import get_runtime

    rt = get_runtime()
    forzados = {a["parametroId"] for a in rt.anomalias_activas(crew_id)}
    hub_frame = get_crew_hub().frame_actual(crew_id)
    modo_vivo = (hub_frame or {}).get("modo", "simulado")
    for param_id, lec in ((hub_frame or {}).get("lecturas") or {}).items():
        if lec.get("nivel") not in ("ATENCION", "CRITICO"):
            continue
        pdef = get_param(param_id) or {}
        if pdef.get("esDatoRealOSDR") and param_id not in forzados and modo_vivo != "replay-osdr":
            # En modo normal, los analitos OSDR obedecen al timepoint OSD-575 o mediciones locales.
            continue
        ev_vivo = evaluar_lectura_determinista(
            crew_id,
            param_id,
            float(lec.get("valor", 0.0)),
            calidad=lec.get("calidad"),
        )
        if ev_vivo["nivel"] in ("ATENCION", "CRITICO"):
            por_analito[param_id] = _aviso_desde_evaluacion(ev_vivo, "vivo", tr("En vivo"))

    avisos = list(por_analito.values())
    for a in avisos:
        a["clave"] = clave_aviso(crew_id, timepoint, a["indicadorId"], a["valor"])
        a["revisado"] = a["clave"] in revisados_set
    avisos.sort(key=lambda x: (x["revisado"], -ORDEN_NIVEL.get(x["nivel"], 0), -abs(x["desvio"])))
    return avisos


def pendientes(avisos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [a for a in avisos if not a.get("revisado")]


def organos_con_problema(avisos: List[Dict[str, Any]]) -> Dict[str, str]:
    """Órgano -> nivel más grave que le afecta."""
    res: Dict[str, str] = {}
    for a in avisos:
        for o in a["organos"]:
            if ORDEN_NIVEL.get(a["nivel"], 0) > ORDEN_NIVEL.get(res.get(o, "NOMINAL"), 0):
                res[o] = a["nivel"]
    return res


def nivel_maximo(avisos: List[Dict[str, Any]]) -> str:
    return max((a["nivel"] for a in avisos), key=lambda n: ORDEN_NIVEL.get(n, 0), default="NOMINAL")


def nivel_por_sistema(avisos: List[Dict[str, Any]]) -> Dict[str, str]:
    """Sistema -> nivel más grave entre sus avisos."""
    res: Dict[str, str] = {}
    for a in avisos:
        s = a["sistema"]
        if ORDEN_NIVEL.get(a["nivel"], 0) > ORDEN_NIVEL.get(res.get(s, "NOMINAL"), 0):
            res[s] = a["nivel"]
    return res


def resumen(avisos: List[Dict[str, Any]]) -> str:
    """«1 crítico · 2 atención», o cadena vacía si no hay nada."""
    n_c = sum(1 for a in avisos if a["nivel"] == "CRITICO")
    n_a = sum(1 for a in avisos if a["nivel"] == "ATENCION")
    partes = []
    if n_c:
        partes.append(tr("{n} crítico", n=n_c) if n_c == 1 else tr("{n} críticos", n=n_c))
    if n_a:
        partes.append(tr("{n} atención", n=n_a))
    return " · ".join(partes)
