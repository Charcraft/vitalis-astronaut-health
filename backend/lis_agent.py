# -*- coding: utf-8 -*-
"""
backend/lis_agent.py — Motor del Agente Autónomo L.I.S. (Life-support In Space)
en Python:
  1) Grounding estricto sobre NASA OSDR OSD-575 y telemetría de cabina
  2) Cerrojo numérico anti-alucinación (cero invención de datos)
  3) Selector automático del mejor modelo por API Key (Gemini / OpenAI / Groq / OpenRouter)
  4) Conector a LLM Local (Ollama qwen2.5:3b / llama3.2:3b)
  5) Síntesis de voz clonada JARVIS (XTTS v2 GPU en 127.0.0.1:8795 + edge-tts fallback)
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.database import (
    get_alsp_dataset,
    get_baseline,
    get_cabina_dataset,
    get_guias_dataset,
    get_osdr_dataset,
    get_protocolos_dataset,
    get_valor_osdr,
    listar_mediciones_locales,
    obtener_memoria_astronauta,
)
from backend.registry import get_param
from backend.triage import (
    evaluar_lectura_determinista,
    indicacion_mejora_para,
    listar_anomalias_tripulante,
)
from desktop.i18n import idioma, tr

JARVIS_XTTS_URL = "http://127.0.0.1:8795"
_LOG_VOZ = logging.getLogger("vitalis.voz")
_ETIQUETA_TP_RE = re.compile(r"^\[([^\]]+)\]")
_ORDEN_ALERTA = {"NOMINAL": 0, "ATENCION": 1, "CRITICO": 2}


def construir_snapshot_contexto(
    crew_id: str = "C003",
    timepoint: str = "R+1",
    modo_operacion: str = "rutina",
) -> Dict[str, Any]:
    cabina_data = get_cabina_dataset()
    tripulante = cabina_data.get("tripulantes", {}).get(
        crew_id, cabina_data.get("tripulantes", {}).get("C003", {})
    )
    cabina = cabina_data.get("cabina", {})
    dataset = get_osdr_dataset()

    todos_los_parametros: List[Dict[str, Any]] = []
    fuera_por_id: Dict[str, Dict[str, Any]] = {}

    def _item_desde_eval(
        ind_id: str, nombre: str, unidad: str, val: float, eval_res: Dict[str, Any],
        fuente: str, l92: Any = None, r194: Any = None,
    ) -> Dict[str, Any]:
        return {
            "id": ind_id,
            "nombre": nombre,
            "valorActual": val,
            "unidad": unidad,
            "mediaPreVuelo": eval_res["mediaPreVuelo"],
            "desvioPorcentaje": eval_res["desvioPorcentajeBaseline"],
            "rangoMin": eval_res["rangoReferencia"]["min"],
            "rangoMax": eval_res["rangoReferencia"]["max"],
            "valorPreVueloL92": l92,
            "valorRecuperacionR194": r194,
            "nivelDeterminista": eval_res["nivel"],
            "reglaDisparada": eval_res.get("reglaDisparada", ""),
            "accionSugerida": eval_res.get("accionSugerida", ""),
            "sistema": eval_res.get("sistema", "metabolico"),
            "fuente": fuente,
        }

    for ind in dataset.get("indicadores", []):
        ind_id = ind["id"]
        val = get_valor_osdr(crew_id, ind_id, timepoint)
        if val is None:
            continue
        eval_res = evaluar_lectura_determinista(crew_id, ind_id, val)
        item = _item_desde_eval(
            ind_id,
            ind["nombre"],
            ind["unidad"],
            val,
            eval_res,
            "NASA OSDR OSD-575",
            l92=get_valor_osdr(crew_id, ind_id, "L-92"),
            r194=get_valor_osdr(crew_id, ind_id, "R+194"),
        )
        todos_los_parametros.append(item)
        if eval_res["nivel"] != "NOMINAL":
            fuera_por_id[ind_id] = item

    mediciones_locales = listar_mediciones_locales(crew_id, 25)
    locales_vistas: set[str] = set()
    for med in mediciones_locales:
        ind_loc = med.get("indicadorId") or med.get("indicador_id")
        if not ind_loc or ind_loc in locales_vistas:
            continue
        etiqueta = _ETIQUETA_TP_RE.match(str(med.get("notas") or ""))
        if etiqueta and etiqueta.group(1) != timepoint:
            continue
        locales_vistas.add(ind_loc)
        try:
            v_loc = float(med.get("valor"))
        except (TypeError, ValueError):
            continue
        ev_loc = evaluar_lectura_determinista(crew_id, ind_loc, v_loc)
        if ev_loc["nivel"] == "NOMINAL":
            fuera_por_id.pop(ind_loc, None)
        else:
            pdef = get_param(ind_loc) or {}
            fuera_por_id[ind_loc] = _item_desde_eval(
                ind_loc,
                pdef.get("nombre", ind_loc),
                ev_loc.get("unidad", pdef.get("unidad", "")),
                v_loc,
                ev_loc,
                "Medición local 0G",
            )

    try:
        from backend.crew_hub import get_crew_hub
        from backend.runtime import get_runtime

        rt = get_runtime()
        forzados = {a["parametroId"] for a in rt.anomalias_activas(crew_id)}
        hub_frame = get_crew_hub().frame_actual(crew_id) or {}
        modo_vivo = hub_frame.get("modo", "simulado")
        for param_id, lec in (hub_frame.get("lecturas") or {}).items():
            if lec.get("nivel") not in ("ATENCION", "CRITICO"):
                continue
            pdef = get_param(param_id) or {}
            if pdef.get("esDatoRealOSDR") and param_id not in forzados and modo_vivo != "replay-osdr":
                continue
            ev_vivo = evaluar_lectura_determinista(
                crew_id, param_id, float(lec.get("valor", 0.0)), calidad=lec.get("calidad")
            )
            if ev_vivo["nivel"] in ("ATENCION", "CRITICO"):
                fuera_por_id[param_id] = _item_desde_eval(
                    param_id,
                    pdef.get("nombre", param_id),
                    ev_vivo.get("unidad", pdef.get("unidad", "")),
                    float(lec.get("valor", 0.0)),
                    ev_vivo,
                    "Telemetría en vivo V.I.T.A.L.I.S.",
                )
    except Exception:
        pass

    parametros_fuera = sorted(
        fuera_por_id.values(),
        key=lambda p: (
            -_ORDEN_ALERTA.get(p.get("nivelDeterminista", "NOMINAL"), 0),
            -abs(float(p.get("desvioPorcentaje") or 0.0)),
        ),
    )

    return {
        "crewId": crew_id,
        "rolTripulante": tripulante.get("rol", "Tripulante"),
        "timepointActual": timepoint,
        "modoOperacion": modo_operacion,
        "signosCabina": tripulante,
        "ambienteCabina": cabina,
        "parametrosFueraDeRango": parametros_fuera,
        "todosLosParametros": todos_los_parametros,
        "medicionesLocales": mediciones_locales[:4],
    }


def validar_respuesta_sin_alucinacion(
    texto_llm: str, snapshot: Dict[str, Any]
) -> Tuple[bool, List[str]]:
    """
    Extrae todas las cifras numéricas del texto generado por un LLM y verifica
    que pertenezcan a la lista blanca del snapshot oficial (OSD-575 + cabina).
    """
    numeros_permitidos = {
        0.0,
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        7.0,
        10.0,
        19.0,
        20.0,
        30.0,
        44.0,
        45.0,
        82.0,
        90.0,
        92.0,
        100.0,
        194.0,
        575.0,
    }

    signos = snapshot.get("signosCabina", {})
    for k, v in signos.items():
        if isinstance(v, (int, float)):
            numeros_permitidos.add(round(float(v), 2))
        elif isinstance(v, str):
            for m in re.findall(r"\d+(?:\.\d+)?", v):
                numeros_permitidos.add(round(float(m), 2))

    amb = snapshot.get("ambienteCabina", {})
    for k, v in amb.items():
        if isinstance(v, (int, float)):
            numeros_permitidos.add(round(float(v), 2))
        elif isinstance(v, str):
            for m in re.findall(r"\d+(?:\.\d+)?", v):
                numeros_permitidos.add(round(float(m), 2))

    for p in list(snapshot.get("todosLosParametros", [])) + list(
        snapshot.get("parametrosFueraDeRango", [])
    ):
        for key in (
            "valorActual",
            "mediaPreVuelo",
            "desvioPorcentaje",
            "rangoMin",
            "rangoMax",
            "valorPreVueloL92",
            "valorRecuperacionR194",
        ):
            val = p.get(key)
            if isinstance(val, (int, float)):
                numeros_permitidos.add(round(abs(float(val)), 2))

    for med in snapshot.get("medicionesLocales", []):
        mval = med.get("valor")
        if isinstance(mval, (int, float)):
            numeros_permitidos.add(round(abs(float(mval)), 2))

    # Incluir cifras verificadas de protocolos oficiales, equipos ALSP y guías en 0G
    for fuente_ds in (get_protocolos_dataset(), get_alsp_dataset(), get_guias_dataset()):
        for num_str in re.findall(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)", repr(fuente_ds)):
            numeros_permitidos.add(round(float(num_str), 2))
    numeros_permitidos.update({110.0, 120.0, 30.0, 5.0, 6.0, 300.0})

    encontrados = re.findall(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)", texto_llm)
    no_autorizados: List[str] = []
    for num_str in encontrados:
        val = round(abs(float(num_str)), 2)
        if not any(abs(val - perm) <= 0.15 for perm in numeros_permitidos):
            no_autorizados.append(num_str)

    return (len(no_autorizados) == 0, no_autorizados)


def _nombre_cotidiano(param_id: str, nombre_oficial: str) -> str:
    """Traduce nombres clínicos técnicos a lenguaje claro y humano."""
    mapa = {
        "glucose": "azúcar en sangre",
        "potassium": "potasio",
        "calcium": "calcio",
        "sodium": "sodio",
        "creatinine": "función renal",
        "urea_nitrogen_bun": "nitrógeno en sangre",
        "bun": "nitrógeno en sangre",
        "alt": "enzima del hígado",
        "ast": "enzima hepática",
        "total_bilirubin": "bilirrubina",
        "bilirubin": "bilirrubina",
        "albumin": "albúmina",
        "globulin": "globulina",
        "albumin_to_globulin_ratio": "equilibrio de proteínas",
        "albumin_globulin_ratio": "equilibrio de proteínas",
        "total_protein": "proteína total",
        "alkaline_phosphatase": "actividad ósea",
        "chloride": "cloro",
        "carbon_dioxide": "dióxido de carbono en sangre",
        "co2": "dióxido de carbono en sangre",
        "egfr_african_american": "capacidad de filtrado renal",
        "egfr_non_african_american": "capacidad de filtrado renal",
        "hemoglobin": "hemoglobina",
        "hematocrit": "concentración de glóbulos rojos",
        "wbc": "defensas",
        "platelets": "plaquetas",
        "anion_gap": "equilibrio ácido",
        "heart_rate": "pulso",
        "spo2": "oxígeno en sangre",
        "systolic_bp": "presión arterial sistólica",
        "diastolic_bp": "presión arterial diastólica",
        "respiratory_rate": "ritmo respiratorio",
        "core_temperature": "temperatura corporal",
        "intracranial_pressure_est": "presión neuro-ocular estimada",
        "cabin_co2": "dióxido de carbono en cabina",
        "radiation_dose": "dosis de radiación",
    }
    return tr(mapa.get(param_id, (nombre_oficial or param_id).lower()))


def _sistema_por_parametro(param_id: str) -> str:
    mapa = {
        "glucose": "metabolico",
        "potassium": "cardiovascular",
        "calcium": "musculoesqueletico",
        "sodium": "neuro-ocular",
        "creatinine": "metabolico",
        "urea_nitrogen_bun": "metabolico",
        "bun": "metabolico",
        "alt": "metabolico",
        "ast": "metabolico",
        "total_bilirubin": "inmune-radiacion",
        "bilirubin": "metabolico",
        "albumin": "musculoesqueletico",
        "globulin": "inmune-radiacion",
        "albumin_to_globulin_ratio": "inmune-radiacion",
        "albumin_globulin_ratio": "inmune-radiacion",
        "total_protein": "respiratorio",
        "alkaline_phosphatase": "musculoesqueletico",
        "chloride": "respiratorio",
        "carbon_dioxide": "respiratorio",
        "co2": "respiratorio",
        "egfr_african_american": "metabolico",
        "egfr_non_african_american": "metabolico",
        "hemoglobin": "inmune-radiacion",
        "hematocrit": "cardiovascular",
        "wbc": "inmune-radiacion",
        "platelets": "inmune-radiacion",
        "anion_gap": "metabolico",
        "heart_rate": "cardiovascular",
        "spo2": "respiratorio",
        "systolic_bp": "cardiovascular",
        "diastolic_bp": "cardiovascular",
        "respiratory_rate": "respiratorio",
        "core_temperature": "inmune-radiacion",
        "intracranial_pressure_est": "neuro-ocular",
        "cabin_co2": "respiratorio",
        "radiation_dose": "inmune-radiacion",
    }
    if param_id in mapa:
        return mapa[param_id]
    pdef = get_param(param_id) or {}
    return str(pdef.get("sistemaVisual") or "metabolico")


def construir_alerta_proactiva_lis(
    pendientes: List[Dict[str, Any]],
    crew_id: str,
    personalidad: str = "jarvis-cordial",
) -> Dict[str, Any]:
    """Construye aviso proactivo de L.I.S. para alertas rojas o amarillas.

    - Estado crítico (`CRITICO`): tono urgente, protocolo de emergencia y escalamiento al CMO.
    - Estado amarillo (`ATENCION`): aviso preventivo calmado, sin alarma crítica, con
      indicaciones concretas y verificadas de qué puede hacer el tripulante para mejorar.
    """
    cordial = (personalidad or "jarvis-cordial") != "directo-clinico"
    if not pendientes:
        return {
            "nivel": "NOMINAL",
            "lang": idioma(),
            "firma": "",
            "texto": "",
            "textoVoz": "",
            "indicacion": "",
            "accionesSugeridas": [],
            "solicitoAyudaAutomatica": False,
        }

    ordenados = sorted(
        pendientes,
        key=lambda a: (
            -_ORDEN_ALERTA.get(str(a.get("nivel", "NOMINAL")), 0),
            -abs(float(a.get("desvio", 0.0) or 0.0)),
        ),
    )
    a0 = ordenados[0]
    nivel = "CRITICO" if a0.get("nivel") == "CRITICO" else "ATENCION"
    ind_id = str(a0.get("indicadorId") or "")
    nom = _nombre_cotidiano(ind_id, str(a0.get("titulo") or ind_id))
    val = a0.get("valor")
    uni = a0.get("unidad") or ""
    val_txt = f"{val} {uni}".strip() if uni else f"{val}"
    sis = a0.get("sistema") or _sistema_por_parametro(ind_id)
    accion = (
        str(a0.get("accion") or "").strip()
        or indicacion_mejora_para(ind_id, str(a0.get("reglaDisparada") or ""), nivel)
    )
    regla = str(a0.get("reglaDisparada") or "")
    firma = "|".join(
        f"{crew_id}:{a.get('indicadorId')}:{a.get('nivel')}:{a.get('reglaDisparada', '')}"
        if a.get("origen") == "vivo"
        else str(a.get("clave") or f"{crew_id}:{a.get('indicadorId')}:{a.get('nivel')}")
        for a in ordenados
    )

    if nivel == "CRITICO":
        proto = str(
            a0.get("protocoloDisparadorId") or a0.get("protocolo") or "cardiovascular"
        )
        pref = tr("Señor, atención urgente: ") if cordial else tr("Alerta crítica: ")
        texto = tr(
            "{pref}su {nom} alcanzó {val}. {accion}",
            pref=pref,
            nom=nom,
            val=val_txt,
            accion=tr(accion),
        )
        texto_voz = tr(
            "Aviso crítico para {crew}: {titulo} en {val}. {accion}",
            crew=crew_id,
            titulo=a0.get("titulo") or nom,
            val=val_txt,
            accion=tr(accion),
        )
        acciones = [
            {
                "id": f"proto-{proto}",
                "etiqueta": tr("Abrir protocolo"),
                "descripcion": tr("Protocolo de emergencia"),
                "tipo": "ABRIR_EMERGENCIA",
                "protocoloId": proto,
                "prioridad": "critica",
            },
            {
                "id": f"3d-{sis}",
                "etiqueta": tr("Enfocar {s} en 3D", s=tr(sis)),
                "descripcion": tr("Inspeccionar órgano afectado"),
                "tipo": "ENFOCAR_SISTEMA",
                "sistemaId": sis,
                "prioridad": "alta",
            },
            {
                "id": f"med-{ind_id}",
                "etiqueta": tr("Medir {p} en 0G", p=nom),
                "descripcion": tr("Confirmar lectura"),
                "tipo": "INICIAR_MEDICION",
                "parametroId": ind_id,
                "prioridad": "normal",
            },
        ]
        return {
            "nivel": "CRITICO",
            "lang": idioma(),
            "firma": firma,
            "texto": texto,
            "textoVoz": texto_voz,
            "indicacion": tr(accion),
            "accionesSugeridas": acciones,
            "solicitoAyudaAutomatica": False,
        }

    # Estado amarillo (ATENCION): aviso proactivo calmado + pasos prácticos para mejorar
    dir_txt = tr("por debajo de lo habitual") if "BAJO" in regla else (
        tr("por encima de lo habitual") if "ALTO" in regla else tr("fuera de lo habitual")
    )
    otros_n = len(ordenados) - 1
    extra_otros = (
        tr(" ({n} parámetro más en vigilancia)", n=otros_n)
        if otros_n == 1
        else (tr(" ({n} parámetros más en vigilancia)", n=otros_n) if otros_n > 1 else "")
    )
    indicacion_tr = tr(accion)
    if cordial:
        texto = tr(
            "Aviso preventivo, señor: su {nom} está ligeramente {dir} en {val}{otros}. "
            "No es una situación crítica. Para ayudar a que mejore: {accion}",
            nom=nom,
            dir=dir_txt,
            val=val_txt,
            otros=extra_otros,
            accion=indicacion_tr,
        )
        texto_voz = tr(
            "Aviso preventivo para {crew}, señor, sin alarma crítica. "
            "Su {nom} está ligeramente {dir} en {val}. Para ayudar a que mejore: {accion}",
            crew=crew_id,
            nom=nom,
            dir=dir_txt,
            val=val_txt,
            accion=indicacion_tr,
        )
    else:
        texto = tr(
            "Aviso preventivo (amarillo): {nom} ligeramente {dir} en {val}{otros}. "
            "Sin urgencia crítica. Qué hacer para mejorar: {accion}",
            nom=nom,
            dir=dir_txt,
            val=val_txt,
            otros=extra_otros,
            accion=indicacion_tr,
        )
        texto_voz = tr(
            "Aviso preventivo para {crew}, sin urgencia crítica. "
            "{nom} en {val}. Para mejorar su cuadro: {accion}",
            crew=crew_id,
            nom=nom,
            val=val_txt,
            accion=indicacion_tr,
        )
    acciones = [
        {
            "id": f"med-{ind_id}",
            "etiqueta": tr("Volver a medir {p}", p=nom),
            "descripcion": tr("Protocolo guiado en microgravedad"),
            "tipo": "INICIAR_MEDICION",
            "parametroId": ind_id,
            "destinoRuta": f"/medir/{ind_id}",
            "prioridad": "alta",
        },
        {
            "id": f"3d-{sis}",
            "etiqueta": tr("Ver {s} en 3D", s=tr(sis)),
            "descripcion": tr("Inspeccionar en el modelo 3D"),
            "tipo": "ENFOCAR_SISTEMA",
            "sistemaId": sis,
            "prioridad": "normal",
        },
        {
            "id": "ver-avisos",
            "etiqueta": tr("Abrir avisos"),
            "descripcion": tr("Ver lista preventiva"),
            "tipo": "PANEL_AVISOS",
            "valor": "abrir",
            "prioridad": "normal",
        },
    ]
    return {
        "nivel": "ATENCION",
        "lang": idioma(),
        "firma": firma,
        "texto": texto,
        "textoVoz": texto_voz,
        "indicacion": indicacion_tr,
        "accionesSugeridas": acciones,
        "solicitoAyudaAutomatica": False,
    }


ALIAS_ANALITOS_REALES: Dict[str, str] = {
    "glucosa": "glucose",
    "azucar": "glucose",
    "azúcar": "glucose",
    "calcio": "calcium",
    "potasio": "potassium",
    "sodio": "sodium",
    "creatinina": "creatinine",
    "riñon": "creatinine",
    "riñón": "creatinine",
    "funcion renal": "creatinine",
    "función renal": "creatinine",
    "urea": "urea_nitrogen_bun",
    "nitrogeno": "urea_nitrogen_bun",
    "nitrógeno": "urea_nitrogen_bun",
    "bun": "urea_nitrogen_bun",
    "bilirrubina": "total_bilirubin",
    "higado": "alt",
    "hígado": "alt",
    "alt": "alt",
    "ast": "ast",
    "enzima hepatica": "ast",
    "enzima hepática": "ast",
    "hueso": "alkaline_phosphatase",
    "huesos": "alkaline_phosphatase",
    "fosfatasa": "alkaline_phosphatase",
    "actividad osea": "alkaline_phosphatase",
    "actividad ósea": "alkaline_phosphatase",
    "albumina": "albumin",
    "albúmina": "albumin",
    "globulina": "globulin",
    "relacion albumina": "albumin_to_globulin_ratio",
    "relación albúmina": "albumin_to_globulin_ratio",
    "cloro": "chloride",
    "cloruro": "chloride",
    "proteina": "total_protein",
    "proteína": "total_protein",
    "proteinas": "total_protein",
    "proteínas": "total_protein",
    "dioxido de carbono": "carbon_dioxide",
    "dióxido de carbono": "carbon_dioxide",
    "dioxido": "carbon_dioxide",
    "dióxido": "carbon_dioxide",
    "co2": "carbon_dioxide",
    "bicarbonato": "carbon_dioxide",
    "egfr": "egfr_non_african_american",
    "filtrado glomerular": "egfr_non_african_american",
    "filtrado": "egfr_non_african_american",
    # Aliases en inglés para consultas bilingües
    "glucose": "glucose",
    "blood sugar": "glucose",
    "sugar": "glucose",
    "calcium": "calcium",
    "potassium": "potassium",
    "sodium": "sodium",
    "creatinine": "creatinine",
    "kidney": "creatinine",
    "kidney function": "creatinine",
    "renal function": "creatinine",
    "urea nitrogen": "urea_nitrogen_bun",
    "blood nitrogen": "urea_nitrogen_bun",
    "bilirubin": "total_bilirubin",
    "total bilirubin": "total_bilirubin",
    "liver": "alt",
    "liver enzyme": "ast",
    "bone": "alkaline_phosphatase",
    "bones": "alkaline_phosphatase",
    "alkaline phosphatase": "alkaline_phosphatase",
    "phosphatase": "alkaline_phosphatase",
    "bone activity": "alkaline_phosphatase",
    "albumin": "albumin",
    "globulin": "globulin",
    "protein balance": "albumin_to_globulin_ratio",
    "albumin ratio": "albumin_to_globulin_ratio",
    "chloride": "chloride",
    "protein": "total_protein",
    "total protein": "total_protein",
    "carbon dioxide": "carbon_dioxide",
    "bicarbonate": "carbon_dioxide",
    "filtration": "egfr_non_african_american",
    "glomerular filtration": "egfr_non_african_american",
    "kidney filtration": "egfr_non_african_american",
    "hemoglobin": "hemoglobin",
    "hematocrit": "hematocrit",
    "white blood cells": "wbc",
    "immune defenses": "wbc",
    "platelets": "platelets",
    "anion gap": "anion_gap",
    "acid balance": "anion_gap",
}


def _contiene_termino(texto_low: str, termino: str) -> bool:
    return bool(
        re.search(
            rf"(?<![a-z0-9áéíóúñü_]){re.escape(termino.lower())}(?![a-z0-9áéíóúñü_])",
            texto_low,
        )
    )


def resolver_indicador_id(texto: str, defecto: Optional[str] = None) -> Optional[str]:
    low = (texto or "").lower().strip()
    dataset = get_osdr_dataset()
    ids_validos = {ind["id"] for ind in dataset.get("indicadores", [])}
    if low in ids_validos:
        return low
    for ind in dataset.get("indicadores", []):
        base_nom = ind["nombre"].lower().split(" (")[0].strip()
        if _contiene_termino(low, ind["id"]) or (base_nom and _contiene_termino(low, base_nom)):
            return ind["id"]
    for alias, target in ALIAS_ANALITOS_REALES.items():
        if _contiene_termino(low, alias) and target in ids_validos:
            return target
    return defecto


def resolver_protocolo_id(texto: str, defecto: str = "cardiovascular") -> str:
    low = (texto or "").lower().strip()
    if low in ("cardiovascular", "respiratorio", "neurologico", "trauma"):
        return low
    if any(
        k in low
        for k in (
            "respir",
            "hipoxia",
            "hypox",
            "oxigen",
            "oxígen",
            "oxygen",
            "hipercap",
            "co2",
            "asfix",
            "asphyx",
            "breath",
            "airway",
        )
    ):
        return "respiratorio"
    if any(
        k in low
        for k in (
            "neuro",
            "visual",
            "vision",
            "visión",
            "ojo",
            "eye",
            "vertig",
            "vértig",
            "mareo",
            "dizz",
            "sans",
            "cabeza",
            "head",
            "stroke",
            "cranial",
        )
    ):
        return "neurologico"
    if any(
        k in low
        for k in (
            "trauma",
            "hemorrag",
            "hemorrh",
            "sangr",
            "bleed",
            "herid",
            "wound",
            "lesion",
            "lesión",
            "injur",
            "eva",
            "golpe",
            "fract",
            "burn",
            "quemad",
        )
    ):
        return "trauma"
    if any(
        k in low
        for k in (
            "cardio",
            "pecho",
            "chest",
            "corazon",
            "corazón",
            "heart",
            "paro",
            "arrest",
            "rcp",
            "cpr",
            "torac",
            "torác",
            "thorac",
        )
    ):
        return "cardiovascular"
    return defecto


def resolver_equipo_alsp(texto: str, defecto: Optional[str] = None) -> Optional[str]:
    low = (texto or "").lower().strip()
    if low in ("dea", "iv", "via-aerea", "farmacos"):
        return low
    if any(k in low for k in ("dea", "aed", "defib", "desfibril", "parche", "pad", "descarga", "shock", "electro")):
        return "dea"
    if any(
        k in low
        for k in (
            "via aerea",
            "vía aérea",
            "via-aerea",
            "airway",
            "aerea",
            "aérea",
            "intub",
            "mascarilla",
            "mask",
            "laringo",
            "laryngo",
            "bvm",
            "ventil",
            "bag-valve",
            "bag valve",
        )
    ):
        return "via-aerea"
    if any(
        k in low
        for k in (
            "farmac",
            "fármac",
            "medicam",
            "medicat",
            "drug",
            "epinefrin",
            "epineph",
            "adrenalin",
            "atropin",
            "lidocain",
            "lidocaín",
            "dosis",
            "dose",
            "jeringa",
            "syring",
        )
    ):
        return "farmacos"
    if any(
        k in low
        for k in (
            "via iv",
            "vía iv",
            "iv line",
            "intraven",
            "suero",
            "saline",
            "cateter",
            "catéter",
            "cathet",
            "vena",
            "vein",
            "manguito",
            "cuff",
            "presuriz",
            "pressur",
            "gota",
            "drip",
            "bolsa",
            "pressure bag",
            "fluid bag",
        )
    ) or re.search(r"\biv\b", low):
        return "iv"
    return defecto


def _limpiar_para_locucion(texto: str) -> str:
    txt = re.sub(r"\s*\[POR VALIDAR\]", "", tr(texto or ""))
    return re.sub(r"\s{2,}", " ", txt).strip()


def construir_lectura_protocolo(
    proto_id: str, paso_num: Optional[int] = None
) -> Tuple[str, str, Dict[str, Any]]:
    """Prepara texto de pantalla y locución completa de un protocolo de emergencia."""
    protocolos = get_protocolos_dataset().get("protocolos", [])
    pid = resolver_protocolo_id(proto_id, "cardiovascular")
    proto = next((p for p in protocolos if p["id"] == pid), protocolos[0] if protocolos else {})
    pasos = proto.get("pasos", [])
    titulo = _limpiar_para_locucion(proto.get("titulo", pid))
    ubic = _limpiar_para_locucion(proto.get("equipoUbicacion", ""))

    if paso_num is not None and pasos:
        idx = max(0, min(int(paso_num) - 1, len(pasos) - 1))
        p = pasos[idx]
        voz = tr(
            "Paso {n} de {t}: {titulo}. {instruccion}. En cero gravedad: {nota}",
            n=p["orden"],
            t=titulo,
            titulo=_limpiar_para_locucion(p["titulo"]),
            instruccion=_limpiar_para_locucion(p["instruccion"]),
            nota=_limpiar_para_locucion(p.get("nota0G", "")),
        )
        corta = tr(
            "Leyendo paso {n} de {t}, señor: {titulo}.",
            n=p["orden"],
            t=titulo,
            titulo=_limpiar_para_locucion(p["titulo"]),
        )
        return corta, voz, proto

    partes = [tr("Instrucciones del protocolo de {t}.", t=titulo)]
    if ubic:
        partes.append(tr("Ubicación del equipo: {u}.", u=ubic))
    for p in pasos:
        bloque = tr(
            "Paso {n}, {titulo}. {instruccion}",
            n=p["orden"],
            titulo=_limpiar_para_locucion(p["titulo"]),
            instruccion=_limpiar_para_locucion(p["instruccion"]),
        )
        nota0g = _limpiar_para_locucion(p.get("nota0G", ""))
        if nota0g:
            bloque += tr(" En cero gravedad: {n}", n=nota0g)
        partes.append(bloque)
    voz = " ".join(partes)
    corta = tr("Leyendo en voz alta los {n} pasos de {t}, señor.", n=len(pasos), t=titulo)
    return corta, voz, proto


def construir_lectura_alsp(
    equipo_id: str, paso_num: Optional[int] = None, incluir_dosis: bool = False
) -> Tuple[str, str, Dict[str, Any]]:
    """Prepara texto de pantalla y locución completa de una herramienta ALSP de la Bolsa Roja."""
    equipos = get_alsp_dataset().get("equipos", [])
    eid = resolver_equipo_alsp(equipo_id, "dea") or "dea"
    eq = next((e for e in equipos if e["id"] == eid), equipos[0] if equipos else {})
    pasos = eq.get("pasos", [])
    nombre = _limpiar_para_locucion(eq.get("nombre", eid))

    if paso_num is not None and pasos:
        idx = max(0, min(int(paso_num) - 1, len(pasos) - 1))
        p = pasos[idx]
        alerta_txt = _limpiar_para_locucion((p.get("alerta") or {}).get("texto", ""))
        voz = tr(
            "{eq}, paso {n}: {titulo}. {instruccion}. En cero gravedad: {nota}",
            eq=nombre,
            n=p["orden"],
            titulo=_limpiar_para_locucion(p["titulo"]),
            instruccion=_limpiar_para_locucion(p["instruccion"]),
            nota=_limpiar_para_locucion(p.get("nota0G", "")),
        )
        if alerta_txt:
            voz += tr(" Precaución: {a}", a=alerta_txt)
        corta = tr(
            "Leyendo paso {n} de {eq}, señor: {titulo}.",
            n=p["orden"],
            eq=tr(eq.get("nombreCorto", eid)),
            titulo=_limpiar_para_locucion(p["titulo"]),
        )
        return corta, voz, eq

    partes = [
        tr(
            "Instrucciones de uso de {eq}. {funcion}",
            eq=nombre,
            funcion=_limpiar_para_locucion(eq.get("funcion", "")),
        )
    ]
    for p in pasos:
        bloque = tr(
            "Paso {n}, {titulo}. {instruccion}",
            n=p["orden"],
            titulo=_limpiar_para_locucion(p["titulo"]),
            instruccion=_limpiar_para_locucion(p["instruccion"]),
        )
        nota0g = _limpiar_para_locucion(p.get("nota0G", ""))
        if nota0g:
            bloque += tr(" En cero gravedad: {n}", n=nota0g)
        alerta_txt = _limpiar_para_locucion((p.get("alerta") or {}).get("texto", ""))
        if alerta_txt:
            bloque += tr(" Atención: {a}", a=alerta_txt)
        partes.append(bloque)
    if incluir_dosis and eq.get("dosis"):
        dosis_txt = "; ".join(
            f"{_limpiar_para_locucion(d['farmaco'])}: {_limpiar_para_locucion(d['dosis'])}, {_limpiar_para_locucion(d['intervalo'])}"
            for d in eq["dosis"]
        )
        partes.append(tr("Dosis de referencia de entrenamiento: {d}.", d=dosis_txt))
    voz = " ".join(partes)
    corta = tr(
        "Leyendo los {n} pasos de uso de {eq}, señor.",
        n=len(pasos),
        eq=tr(eq.get("nombreCorto", eid)),
    )
    return corta, voz, eq


def construir_lectura_guia_medicion(indicador_id: str) -> Tuple[str, str]:
    """Prepara locución completa de los pasos de medición capilar en 0G."""
    guias = get_guias_dataset()
    ind_id = resolver_indicador_id(indicador_id, "glucose") or "glucose"
    guia = guias.get(ind_id) or guias.get("glucose", {})
    nom_humano = _nombre_cotidiano(ind_id, ind_id)
    partes = [
        tr(
            "Guía para medir {n} en cero gravedad con {d}.",
            n=nom_humano,
            d=_limpiar_para_locucion(guia.get("tituloDispositivo", "el analizador portátil")),
        )
    ]
    for p in guia.get("pasos", []):
        partes.append(
            tr(
                "Paso {n}, {titulo}. {desc}",
                n=p["orden"],
                titulo=_limpiar_para_locucion(p["titulo"]),
                desc=_limpiar_para_locucion(p["descripcion"]),
            )
        )
    fallo = guia.get("modoFallo0G") or {}
    if fallo:
        partes.append(
            tr(
                "Cuidado en cero gravedad, {t}: {d}",
                t=_limpiar_para_locucion(fallo.get("titulo", "")),
                d=_limpiar_para_locucion(fallo.get("detalle", "")),
            )
        )
    voz = " ".join(partes)
    corta = tr("Leyendo los pasos para medir {n} en cero gravedad, señor.", n=nom_humano)
    return corta, voz


def _extraer_numero_paso(lower: str) -> Optional[int]:
    m = re.search(r"\b(?:paso|step)\s*(\d+)\b", lower)
    if m:
        return int(m.group(1))
    mapa_es = {"primer": 1, "primero": 1, "segundo": 2, "tercer": 3, "tercero": 3, "cuarto": 4, "quinto": 5, "sexto": 6}
    for pal, n in mapa_es.items():
        if _contiene_termino(lower, pal) and "paso" in lower:
            return n
    mapa_en = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}
    for pal, n in mapa_en.items():
        if _contiene_termino(lower, pal) and "step" in lower:
            return n
    return None


def generar_respuesta_determinista(
    mensaje_usuario: str,
    crew_id: str = "C003",
    timepoint: str = "R+1",
    modo_operacion: str = "rutina",
    memoria: Optional[Dict[str, Any]] = None,
    ultimas_mediciones: Optional[List[Dict[str, Any]]] = None,
    estado_ui: Optional[Dict[str, Any]] = None,
    personalidad: str = "jarvis-cordial",
) -> Dict[str, Any]:
    """
    Genera una respuesta 100% verificada sobre NASA OSDR OSD-575, telemetría de
    cabina, protocolos de emergencia, herramientas ALSP, guías en 0G y pantalla activa.
    """
    snapshot = construir_snapshot_contexto(crew_id, timepoint, modo_operacion)
    mem = memoria or obtener_memoria_astronauta(crew_id)
    ui = estado_ui or {}
    if ultimas_mediciones is not None:
        snapshot["medicionesLocales"] = ultimas_mediciones

    lower = (mensaje_usuario or "").lower().strip()
    signos = snapshot["signosCabina"]
    amb = snapshot["ambienteCabina"]
    fuera = snapshot["parametrosFueraDeRango"]
    notas_mem = (mem.get("notasRecordadas") or mem.get("notas") or []) if isinstance(mem, dict) else []
    ultima_nota = notas_mem[0].get("texto", "") if notas_mem else ""
    pers = str(ui.get("personalidad") or personalidad or "jarvis-cordial")
    cordial = pers != "directo-clinico"
    trato = tr(", señor") if cordial else ""

    # 0.1) Lectura de instrucciones / uso de herramientas ALSP, protocolos de emergencia o guías 0G
    pide_instrucciones = any(
        k in lower
        for k in (
            "lee ",
            "leer",
            "leeme",
            "léeme",
            "read ",
            "read me",
            "recite",
            "aloud",
            "out loud",
            "en voz alta",
            "instrucciones",
            "instructions",
            "como se usa",
            "cómo se usa",
            "como usar",
            "cómo usar",
            "how to use",
            "how do i use",
            "como funciona",
            "cómo funciona",
            "how does",
            "como se mide",
            "cómo se mide",
            "como medir",
            "cómo medir",
            "how to measure",
            "how do i measure",
            "procedimiento",
            "procedure",
            "explica",
            "explícame",
            "explain",
            "dime los pasos",
            "tell me the steps",
            "que pasos",
            "qué pasos",
            "what steps",
            "paso a paso",
            "step by step",
            "dime el paso",
            "tell me step",
            "dosis",
            "dose",
            "doses",
        )
    ) or bool(_extraer_numero_paso(lower))

    paso_req = _extraer_numero_paso(lower)
    equipo_alsp = resolver_equipo_alsp(lower)
    menciona_medir = any(
        k in lower
        for k in (
            "medir",
            "mide",
            "medicion",
            "medición",
            "measure",
            "measuring",
            "measurement",
            "cartucho",
            "cartridge",
            "capilar",
            "capillary",
            "muestra",
            "sample",
            "analizador",
            "analyzer",
        )
    )
    menciona_emerg = any(
        k in lower
        for k in (
            "protocolo",
            "protocol",
            "emergencia",
            "emergency",
            "rcp",
            "cpr",
            "cardiovascular",
            "respiratorio",
            "respiratory",
            "neurologico",
            "neurológico",
            "neurological",
            "trauma",
            "hemorrag",
            "hemorrh",
            "bleed",
        )
    )

    if pide_instrucciones:
        # A) Herramienta ALSP específica o dosis (o paso mientras ya usa herramienta ALSP)
        if equipo_alsp or (ui.get("pagina") == "emergencia" and any(k in lower for k in ("herramienta", "tool", "equipment"))):
            eid = equipo_alsp or str(ui.get("equipoAlsp") or "dea")
            inc_dosis = "dosis" in lower or "dose" in lower or eid == "farmacos"
            corta, voz, eq = construir_lectura_alsp(
                eid, paso_num=paso_req, incluir_dosis=inc_dosis
            )
            acc_ctrl: List[Dict[str, Any]] = [
                {
                    "tipo": "LEER_ALSP",
                    "equipoId": eid,
                    "paso": paso_req,
                    "incluirDosis": inc_dosis,
                    "comando": "reproducir",
                }
            ]
            return {
                "crewId": crew_id,
                "emisor": "asistente",
                "texto": corta,
                "textoVoz": voz,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "modoVerificacion": "DETERMINISTA_ESTRICTO",
                "nivelAlerta": "ATENCION" if modo_operacion == "emergencia" else "NOMINAL",
                "accionesControl": acc_ctrl,
                "datosCitados": [],
                "accionesSugeridas": [],
            }

        # B) Guía de medición en microgravedad
        if menciona_medir and not menciona_emerg:
            ind_id = resolver_indicador_id(lower) or str(ui.get("indicadorEnPantalla") or "glucose")
            corta, voz = construir_lectura_guia_medicion(ind_id)
            return {
                "crewId": crew_id,
                "emisor": "asistente",
                "texto": corta,
                "textoVoz": voz,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "modoVerificacion": "DETERMINISTA_ESTRICTO",
                "nivelAlerta": "NOMINAL",
                "accionesControl": [{"tipo": "LEER_GUIA_MEDICION", "indicadorId": ind_id}],
                "datosCitados": [],
                "accionesSugeridas": [],
            }

        # C) Protocolo de emergencia (uno nombrado o el activo en pantalla)
        if menciona_emerg or ui.get("pagina") == "emergencia" or "protocolo" in lower or "protocol" in lower:
            proto_def = str(ui.get("protocoloEmergencia") or "cardiovascular")
            pid = resolver_protocolo_id(lower, proto_def)
            corta, voz, _proto = construir_lectura_protocolo(pid, paso_num=paso_req)
            acc_ctrl = [{"tipo": "LEER_PROTOCOLO", "protocoloId": pid}]
            if paso_req:
                acc_ctrl[0]["paso"] = paso_req
            return {
                "crewId": crew_id,
                "emisor": "asistente",
                "texto": corta,
                "textoVoz": voz,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "modoVerificacion": "DETERMINISTA_ESTRICTO",
                "nivelAlerta": "ATENCION" if modo_operacion == "emergencia" else "NOMINAL",
                "accionesControl": acc_ctrl,
                "datosCitados": [],
                "accionesSugeridas": [],
            }

    # 0.2) Consulta sobre avisos clínicos activos (OSDR + telemetría en vivo + mediciones 0G)
    if any(
        k in lower
        for k in (
            "avisos",
            "alertas pendientes",
            "que alertas",
            "qué alertas",
            "tengo avisos",
            "active alerts",
            "any alerts",
            "what alerts",
            "warnings",
            "notifications",
        )
    ):
        anom = list(fuera)
        if not anom:
            anom_osdr = listar_anomalias_tripulante(crew_id, timepoint)
            anom = [
                {
                    "id": a["indicadorId"],
                    "nombre": a["nombre"],
                    "valorActual": a["valor"],
                    "unidad": a.get("unidad", ""),
                    "nivelDeterminista": a["nivel"],
                    "reglaDisparada": a.get("reglaDisparada", ""),
                    "accionSugerida": a.get("accionSugerida", ""),
                }
                for a in anom_osdr
            ]
        if not anom:
            txt_av = tr(
                "No hay avisos activos para {c} en {t}{trato}; todo está dentro de su rango.",
                c=crew_id,
                t=timepoint,
                trato=trato,
            )
            nivel_av = "NOMINAL"
        else:
            p0 = anom[0]
            nivel_av = p0.get("nivelDeterminista", "NOMINAL")
            det_list = ", ".join(
                tr(
                    "{n} en {v}",
                    n=_nombre_cotidiano(a["id"], a["nombre"]),
                    v=a["valorActual"],
                )
                for a in anom[:4]
            )
            guia_mejora = (
                str(p0.get("accionSugerida") or "").strip()
                or indicacion_mejora_para(
                    p0["id"], str(p0.get("reglaDisparada") or ""), nivel_av
                )
            )
            if nivel_av == "ATENCION":
                txt_av = tr(
                    "Tiene {n} aviso preventivo en nivel amarillo{trato}: {lista}. "
                    "No es una urgencia crítica; para ayudar a mejorar: {accion}",
                    n=len(anom),
                    trato=trato,
                    lista=det_list,
                    accion=tr(guia_mejora),
                )
            else:
                txt_av = tr(
                    "Tiene {n} avisos activos en este momento{trato}: {lista}. {accion}",
                    n=len(anom),
                    trato=trato,
                    lista=det_list,
                    accion=tr(guia_mejora),
                )
        return {
            "crewId": crew_id,
            "emisor": "asistente",
            "texto": txt_av,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modoVerificacion": "DETERMINISTA_ESTRICTO",
            "nivelAlerta": nivel_av,
            "accionesControl": [{"tipo": "PANEL_AVISOS", "valor": "abrir"}] if anom else [],
            "datosCitados": [],
            "accionesSugeridas": [],
        }

    # 0.3) Consulta sobre Salud Mental / Emocional, Conducta (NASA BHP), Sueño, PVT o Biofilia
    if any(
        k in lower
        for k in (
            "salud mental",
            "mental health",
            "emocional",
            "emotional",
            "bienestar",
            "wellbeing",
            "animo",
            "ánimo",
            "mood",
            "sueño",
            "sueno",
            "sleep",
            "dormir",
            "fatiga",
            "fatigue",
            "pvt",
            "reflejos",
            "conducta",
            "bhp",
            "aislamiento",
            "isolation",
            "estres",
            "estrés",
            "stress",
            "box breathing",
            "respiracion",
            "respiración",
            "biofilia",
            "biophilia",
            "stroop",
            "cognicion",
            "cognición",
            "bitacora",
            "bitácora",
            "journal",
            "dsn",
        )
    ):
        from backend.database import (
            obtener_estado_gamificacion,
            obtener_evaluaciones_mentales,
        )
        from backend.triage import evaluar_salud_mental_determinista

        cabina = snapshot.get("signosCabina", {})
        horas_s = float(cabina.get("horasSueno", 6.8) or 6.8)
        gam = obtener_estado_gamificacion(crew_id)
        score = int(gam.get("score", 0) or 0)
        racha = int(gam.get("rachaDias", 12) or 12)
        evals = obtener_evaluaciones_mentales(crew_id, limit=1)
        ultima = evals[0] if evals else {}
        pvt_ms = float(ultima.get("pvtLatenciaMs", 0.0) or 0.0)
        pvt_lap = int(ultima.get("pvtLapsus", 0) or 0)
        estres_raw = int(ultima.get("nivelEstres", 3) or 3)
        # Escala interna de bitácora (1..5) normalizada suavemente a escala BHP (1..10)
        estres_10 = estres_raw * 2 if estres_raw <= 5 else estres_raw
        eval_m = evaluar_salud_mental_determinista(
            horas_sueno=horas_s,
            pvt_latencia_ms=pvt_ms,
            pvt_lapsus=pvt_lap,
            estres_score=estres_10,
        )

        txt_bhp = tr(
            "Estado de bienestar y conducta para {c}{trato}: preparación de vuelo en {score} de 100 puntos con racha de {racha} días y {s} horas de sueño. Diagnóstico: {diag}. {acc}",
            c=crew_id,
            trato=trato,
            score=score,
            racha=racha,
            s=f"{horas_s:.1f}",
            diag=eval_m["titulo"],
            acc=eval_m["accion"],
        )
        return {
            "crewId": crew_id,
            "emisor": "asistente",
            "texto": txt_bhp,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "nivelAlerta": "NOMINAL"
            if eval_m["nivel"] == "verde"
            else ("ATENCION" if eval_m["nivel"] == "amarillo" else "CRITICO"),
            "modoVerificacion": "DETERMINISTA_ESTRICTO",
            "accionesControl": [{"tipo": "NAVEGACION", "valor": "salud_mental"}],
            "datosCitados": [
                {"fuente": "NASA HRP BHP [SUPUESTO]", "parametro": "Flight Readiness Score", "valor": f"{score}/100"},
                {"fuente": "Cabina [SUPUESTO]", "parametro": "Horas de sueño", "valor": f"{horas_s:.1f} h"},
            ],
            "accionesSugeridas": [
                tr("Completar test PVT-B"),
                tr("Iniciar respiración 4x4"),
                tr("Abrir bitácora confidencial"),
            ],
        }

    # 1) Pregunta sobre lo que el astronauta está viendo en pantalla ahora mismo
    if ui and any(
        k in lower
        for k in (
            "estoy viendo",
            "tengo en pantalla",
            "qué es esto",
            "que es esto",
            "en qué pantalla",
            "en que pantalla",
            "ves mi pantalla",
            "am i looking at",
            "on my screen",
            "on screen",
            "what is this",
            "what screen",
            "which screen",
            "see my screen",
            "am i viewing",
        )
    ):
        pag = ui.get("pagina", "inicio")
        nom_pag = tr(ui.get("nombrePagina", "Vista general"))
        nom_sis = tr(ui.get("nombreSistema", "Metabólico"))
        organo = ui.get("organoSeleccionado") or ""
        cam = tr(ui.get("modoCamara3d", "cuerpo"))
        if pag in ("inicio", "cuerpo"):
            texto_pan = tr(
                "Está viendo el modelo anatómico en {pag}{trato}, enfocado en el sistema {sis} en vista {cam}{org}.",
                pag=nom_pag,
                trato=trato,
                sis=nom_sis,
                cam=cam,
                org=tr(" con el órgano {o} seleccionado", o=tr(organo)) if organo else "",
            )
        elif pag == "medir":
            ind_id = ui.get("indicadorEnPantalla", "glucose")
            ind_nom = _nombre_cotidiano(ind_id, ind_id)
            texto_pan = tr(
                "Está en la guía de medición en cero gravedad para revisar su {ind}{trato}.",
                ind=ind_nom,
                trato=trato,
            )
        elif pag == "emergencia":
            proto = ui.get("protocoloEmergencia", "cardiovascular")
            paso_act = int(ui.get("pasoEmergencia", 0)) + 1
            eq_act = ui.get("equipoAlsp", "dea")
            proto_lbl = tr(
                {
                    "cardiovascular": "Cardiovascular",
                    "respiratorio": "Respiratorio",
                    "neurologico": "Neurológico",
                    "trauma": "Trauma",
                }.get(proto, proto)
            )
            eq_lbl = tr(
                {
                    "dea": "DEA",
                    "iv": "Vía IV",
                    "via-aerea": "Vía aérea",
                    "farmacos": "Fármacos",
                }.get(eq_act, eq_act)
            )
            texto_pan = tr(
                "Tiene abierta la pantalla de emergencia en el protocolo {proto}, paso {paso}, con la herramienta {eq}{trato}.",
                proto=proto_lbl,
                paso=paso_act,
                eq=eq_lbl,
                trato=trato,
            )
        elif pag == "historial":
            ind_h = ui.get("analitoHistorial", "glucose")
            texto_pan = tr(
                "Está viendo la tabla de laboratorio{trato}, con {ind} seleccionado en la gráfica.",
                trato=trato,
                ind=_nombre_cotidiano(ind_h, ind_h),
            )
        else:
            texto_pan = tr(
                "Está en la sección {pag} en modo {tema}{trato}.",
                pag=nom_pag,
                tema=tr(ui.get("temaVisual", "oscuro")),
                trato=trato,
            )
        return {
            "crewId": crew_id,
            "emisor": "asistente",
            "texto": texto_pan,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modoVerificacion": "DETERMINISTA_ESTRICTO",
            "nivelAlerta": "NOMINAL",
            "datosCitados": [],
            "accionesSugeridas": [],
        }

    # 1.5) Detectar emergencia clínica explícita (incluye SANS, hipoxia, descompresión y trauma)
    palabras_criticas = (
        "dolor",
        "pecho",
        "chest pain",
        "desmayo",
        "faint",
        "passing out",
        "no puedo respirar",
        "can't breathe",
        "cannot breathe",
        "short of breath",
        "hipoxia",
        "hypoxia",
        "ayuda urgente",
        "urgent help",
        "auxilio",
        "socorro",
        "paro",
        "cardiac arrest",
        "vision borrosa",
        "visión borrosa",
        "blurred vision",
        "blurry vision",
        "mareo severo",
        "severe dizziness",
        "sans",
        "descompresion",
        "descompresión",
        "decompression",
        "taquicardia",
        "tachycardia",
        "presion craneal",
        "presión craneal",
        "intracranial",
        "hemorragia",
        "hemorrhage",
        "sangrando",
        "bleeding",
        "herida grave",
        "severe wound",
        "me siento muy mal",
        "emergencia medica",
        "emergencia médica",
        "medical emergency",
    )
    es_urgencia = any(p in lower for p in palabras_criticas) or (
        modo_operacion == "emergencia" and any(k in lower for k in ("ayuda", "help", "sos", "urgente", "urgent", "colapso", "collapse"))
    )

    if es_urgencia:
        protocolo_id = resolver_protocolo_id(lower, "cardiovascular")
        sistema_mapa = {
            "cardiovascular": "cardiovascular",
            "respiratorio": "respiratorio",
            "neurologico": "neuro-ocular",
            "trauma": "musculoesqueletico",
        }
        sistema_3d = sistema_mapa.get(protocolo_id, "cardiovascular")

        extra_mem = (
            tr(" Tomo en cuenta lo que me comentó: {n}.", n=ultima_nota) if ultima_nota else ""
        )
        pref = tr("Señor, estoy con usted. ") if cordial else ""
        texto = tr(
            "{pref}Ya activé la guía de emergencia y avisé al oficial médico a bordo. "
            "Su pulso está en {fc} y su oxígeno en {spo2} por ciento; respire con calma y siga los pasos en pantalla.{mem}",
            pref=pref,
            fc=signos.get("frecuenciaCardiacaLpm"),
            spo2=signos.get("spo2Porcentaje"),
            mem=extra_mem,
        )
        return {
            "crewId": crew_id,
            "emisor": "asistente",
            "texto": texto,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modoVerificacion": "DETERMINISTA_ESTRICTO",
            "nivelAlerta": "CRITICO",
            "solicitoAyudaAutomatica": True,
            "sistema3dSugerido": sistema_3d,
            "protocoloSugerido": protocolo_id,
            "datosCitados": [
                {
                    "indicador": "FC / SpO₂",
                    "valorActual": f"{signos.get('frecuenciaCardiacaLpm')} lpm / {signos.get('spo2Porcentaje')}%",
                    "baselinePersonal": f"Base {signos.get('baseFrecuenciaCardiacaLpm')} lpm",
                    "rangoReferencia": "50–95 lpm",
                    "fuente": "Cabina V.I.T.A.L.I.S.",
                    "esDatoRealOSDR": False,
                }
            ],
            "accionesSugeridas": [
                {
                    "id": "acc-sos-proto",
                    "etiqueta": tr("Abrir protocolo {p}", p=tr(protocolo_id)),
                    "descripcion": tr("Protocolo de emergencia {p}", p=tr(protocolo_id)),
                    "tipo": "ABRIR_EMERGENCIA",
                    "destinoRuta": f"/emergencia/{protocolo_id}",
                    "protocoloId": protocolo_id,
                    "prioridad": "critica",
                },
                {
                    "id": "acc-sos-3d",
                    "etiqueta": tr("Enfocar {s} en 3D", s=tr(sistema_3d)),
                    "descripcion": tr("Inspección anatómica inmediata"),
                    "tipo": "ENFOCAR_SISTEMA",
                    "sistemaId": sistema_3d,
                    "prioridad": "alta",
                },
                {
                    "id": "acc-sos-cmo",
                    "etiqueta": tr("Alertar a CMO (C001)"),
                    "descripcion": tr("Escalamiento urgente para {c}", c=crew_id),
                    "tipo": "PEDIR_AYUDA_CMO",
                    "protocoloId": protocolo_id,
                    "prioridad": "critica",
                },
            ],
        }

    # 2) Reporte resumido para el médico
    if any(k in lower for k in ("sbar", "reporte", "parte medico", "parte médico", "medical report", "summary", "report")):
        resumen_fuera = (
            ", ".join(
                tr(
                    "{n} en {v}",
                    n=_nombre_cotidiano(p["id"], p["nombre"]),
                    v=p["valorActual"],
                )
                for p in fuera[:3]
            )
            if fuera
            else tr("todos sus análisis en equilibrio")
        )
        bg = tr(" Además comentó: {n}.", n=ultima_nota) if ultima_nota else ""
        if cordial:
            texto = tr(
                "Resumen listo, señor. Su pulso va en {fc}, oxígeno en {spo2} por ciento y presión en {pa}.{bg} Destacan {fuera}. Ya quedó preparado el aviso para el oficial médico.",
                fc=signos.get("frecuenciaCardiacaLpm"),
                spo2=signos.get("spo2Porcentaje"),
                pa=signos.get("presionArterial"),
                bg=bg,
                fuera=resumen_fuera,
            )
        else:
            texto = tr(
                "Reporte clínico: pulso {fc}, oxígeno {spo2} por ciento, presión {pa}.{bg} Foco: {fuera}. SBAR listo para oficial médico.",
                fc=signos.get("frecuenciaCardiacaLpm"),
                spo2=signos.get("spo2Porcentaje"),
                pa=signos.get("presionArterial"),
                bg=bg,
                fuera=resumen_fuera,
            )
        acciones = [
            {
                "id": "acc-sbar-cmo",
                "etiqueta": tr("Enviar SBAR a CMO (C001)"),
                "descripcion": tr("Registrar aviso clínico local y cola Tierra"),
                "tipo": "PEDIR_AYUDA_CMO",
                "protocoloId": "cardiovascular",
                "prioridad": "alta" if fuera else "normal",
            }
        ]
        if fuera:
            acciones.append(
                {
                    "id": f"med-{fuera[0]['id']}",
                    "etiqueta": tr("Medir {p} en 0G", p=_nombre_cotidiano(fuera[0]["id"], fuera[0]["nombre"])),
                    "descripcion": tr("Protocolo guiado en microgravedad"),
                    "tipo": "INICIAR_MEDICION",
                    "parametroId": fuera[0]["id"],
                    "destinoRuta": f"/medir/{fuera[0]['id']}",
                    "prioridad": "alta",
                }
            )
        return {
            "crewId": crew_id,
            "emisor": "asistente",
            "texto": texto,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modoVerificacion": "DETERMINISTA_ESTRICTO",
            "nivelAlerta": fuera[0]["nivelDeterminista"] if fuera else "NOMINAL",
            "datosCitados": [],
            "accionesSugeridas": acciones,
        }

    # 3) Consulta sobre ambiente de cabina, radiación o enlace con Tierra
    _consulta_cabina = any(
        k in lower
        for k in (
            "cabina",
            "cabin",
            "radiacion",
            "radiación",
            "radiation",
            "co2",
            "tierra",
            "earth",
            "retardo",
            "delay",
            "signal",
            "temperatura",
            "temperature",
        )
    ) or (
        any(k in lower for k in ("oxigeno", "oxígeno", "oxygen", "presion", "presión", "pressure"))
        and not any(k in lower for k in ("mi oxigen", "my oxygen", "spo2", "arterial", "blood pressure", "mi presion", "mi presión"))
    )
    if _consulta_cabina:
        cab_fuera = [p for p in fuera if p.get("id") in ("cabin_co2", "radiation_dose")]
        if cab_fuera:
            c0 = cab_fuera[0]
            niv_cab = c0.get("nivelDeterminista", "ATENCION")
            cons_cab = (
                str(c0.get("accionSugerida") or "").strip()
                or indicacion_mejora_para(
                    c0["id"], str(c0.get("reglaDisparada") or ""), niv_cab
                )
            )
            nom_cab = _nombre_cotidiano(c0["id"], c0["nombre"])
            if niv_cab == "ATENCION":
                texto = tr(
                    "Aviso preventivo en ambiente de cabina{trato}: {nom} está en {val} {uni}. "
                    "Sin urgencia crítica; para mejorar el ambiente: {accion}",
                    trato=trato,
                    nom=nom_cab,
                    val=c0["valorActual"],
                    uni=c0.get("unidad", ""),
                    accion=tr(cons_cab),
                )
            else:
                texto = tr(
                    "Alerta en cabina{trato}: {nom} en {val} {uni}. {accion}",
                    trato=trato,
                    nom=nom_cab,
                    val=c0["valorActual"],
                    uni=c0.get("unidad", ""),
                    accion=tr(cons_cab),
                )
            nivel_cab = niv_cab
        elif cordial:
            texto = tr(
                "El aire de la cabina está limpio y estable, señor, con {tc} grados y radiación baja en {rad}. La señal con Tierra tarda {rt}, así que seguimos trabajando con total autonomía aquí a bordo.",
                tc=amb.get("temperaturaCabinaC"),
                rad=amb.get("radiacionAcumuladaMsv"),
                rt=tr(str(amb.get("retardoTierraTexto") or "")),
            )
            nivel_cab = "NOMINAL"
        else:
            texto = tr(
                "Cabina estable: {tc} grados, radiación {rad}, enlace con Tierra {rt}. Operación autónoma a bordo.",
                tc=amb.get("temperaturaCabinaC"),
                rad=amb.get("radiacionAcumuladaMsv"),
                rt=tr(str(amb.get("retardoTierraTexto") or "")),
            )
            nivel_cab = "NOMINAL"
        return {
            "crewId": crew_id,
            "emisor": "asistente",
            "texto": texto,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modoVerificacion": "DETERMINISTA_ESTRICTO",
            "nivelAlerta": nivel_cab,
            "datosCitados": [],
            "accionesSugeridas": [
                {
                    "id": "acc-cab-resp",
                    "etiqueta": tr("Enfocar sistema respiratorio 3D"),
                    "descripcion": tr("Revisar impacto de CO₂ y O₂"),
                    "tipo": "ENFOCAR_SISTEMA",
                    "sistemaId": "respiratorio",
                    "prioridad": "normal",
                },
                {
                    "id": "acc-cab-rad",
                    "etiqueta": tr("Enfocar inmune/radiación 3D"),
                    "descripcion": tr("Revisar defensa inmune"),
                    "tipo": "ENFOCAR_SISTEMA",
                    "sistemaId": "inmune-radiacion",
                    "prioridad": "normal",
                },
            ],
        }

    # 4) Consulta por analito específico (incluye comparación temporal L-92 vs actual vs R+194)
    param_objetivo = None
    id_resuelto = resolver_indicador_id(lower)
    for param in snapshot["todosLosParametros"]:
        pid = param["id"].lower()
        pnom = param["nombre"].lower()
        if pid == id_resuelto or pid in lower or pnom in lower:
            param_objetivo = param
            break

    if param_objetivo is not None:
        param = param_objetivo
        signo = "+" if param["desvioPorcentaje"] >= 0 else ""
        v_pre = get_valor_osdr(crew_id, param["id"], "L-92")
        v_rec = get_valor_osdr(crew_id, param["id"], "R+194")
        extra_tendencia = ""
        if any(
            k in lower
            for k in (
                "tendencia",
                "evolucion",
                "evolución",
                "compara",
                "antes",
                "recuperacion",
                "recuperación",
                "trend",
                "evolution",
                "compare",
                "before",
                "recovery",
                "history",
            )
        ):
            if v_pre is not None and v_rec is not None:
                extra_tendencia = tr(
                    " Antes del viaje estaba en {a}, ahora en {b} y después baja a {c}.",
                    a=v_pre,
                    b=param["valorActual"],
                    c=v_rec,
                )
        nom_humano = _nombre_cotidiano(param["id"], param["nombre"])
        extra_mejora = ""
        if param["nivelDeterminista"] == "ATENCION":
            consejo = (
                str(param.get("accionSugerida") or "").strip()
                or indicacion_mejora_para(
                    param["id"], str(param.get("reglaDisparada") or ""), "ATENCION"
                )
            )
            extra_mejora = tr(
                " Está en vigilancia preventiva sin alarma crítica; para ayudar a mejorar: {accion}",
                accion=tr(consejo),
            )
        elif param["nivelDeterminista"] == "CRITICO":
            consejo = str(param.get("accionSugerida") or "").strip()
            if consejo:
                extra_mejora = f" {tr(consejo)}"
        if cordial:
            texto = tr(
                "Su {nom} está en {val}, señor, frente a su nivel habitual de {base}.{extra}{mejora}",
                nom=nom_humano,
                val=param["valorActual"],
                base=param["mediaPreVuelo"],
                extra=extra_tendencia,
                mejora=extra_mejora,
            )
        else:
            texto = tr(
                "{nom}: {val} frente a base de {base}.{extra}{mejora}",
                nom=nom_humano.capitalize(),
                val=param["valorActual"],
                base=param["mediaPreVuelo"],
                extra=extra_tendencia,
                mejora=extra_mejora,
            )
        sis = _sistema_por_parametro(param["id"])
        return {
            "crewId": crew_id,
            "emisor": "asistente",
            "texto": texto,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modoVerificacion": "DETERMINISTA_ESTRICTO",
            "nivelAlerta": param["nivelDeterminista"],
            "datosCitados": [
                {
                    "indicador": tr(param["nombre"]),
                    "valorActual": f"{param['valorActual']} {param['unidad']}",
                    "baselinePersonal": tr("Base {v} {u}", v=param["mediaPreVuelo"], u=param["unidad"]),
                    "rangoReferencia": f"{param['rangoMin']}–{param['rangoMax']} {param['unidad']}",
                    "fuente": "NASA OSDR OSD-575",
                    "esDatoRealOSDR": True,
                }
            ],
            "accionesSugeridas": [
                {
                    "id": f"med-{param['id']}",
                    "etiqueta": tr("Medir {p} en 0G", p=tr(param["nombre"])),
                    "descripcion": tr("Iniciar guía capilar para {p}", p=tr(param["nombre"])),
                    "tipo": "INICIAR_MEDICION",
                    "parametroId": param["id"],
                    "destinoRuta": f"/medir/{param['id']}",
                    "prioridad": "alta"
                    if param["nivelDeterminista"] != "NOMINAL"
                    else "normal",
                },
                {
                    "id": f"3d-{param['id']}",
                    "etiqueta": tr("Ver sistema {s} en 3D", s=tr(sis)),
                    "descripcion": tr("Resaltar órgano vinculado"),
                    "tipo": "ENFOCAR_SISTEMA",
                    "sistemaId": sis,
                    "prioridad": "normal",
                },
            ],
        }

    # 5) Resumen general o valores fuera de lo habitual
    if fuera:
        top = fuera[:3]
        lista_txt = ", ".join(
            tr(
                "{n} en {v}",
                n=_nombre_cotidiano(p["id"], p["nombre"]),
                v=p["valorActual"],
            )
            for p in top
        )
        extra_mem = tr(" Recuerdo que mencionó: {n}.", n=ultima_nota) if ultima_nota else ""
        p0 = fuera[0]
        nivel_p0 = p0.get("nivelDeterminista", "ATENCION")
        sis0 = p0.get("sistema") or _sistema_por_parametro(p0["id"])
        consejo_p0 = (
            str(p0.get("accionSugerida") or "").strip()
            or indicacion_mejora_para(
                p0["id"], str(p0.get("reglaDisparada") or ""), nivel_p0
            )
        )
        if nivel_p0 == "ATENCION":
            if cordial:
                texto = tr(
                    "Aviso preventivo, señor: su pulso en {fc} y oxígeno en {spo2} por ciento están estables, "
                    "pero conviene cuidar {lista}. No es una urgencia crítica; para ayudar a que mejore: {accion}.{mem}",
                    fc=signos.get("frecuenciaCardiacaLpm"),
                    spo2=signos.get("spo2Porcentaje"),
                    lista=lista_txt,
                    accion=tr(consejo_p0),
                    mem=extra_mem,
                )
            else:
                texto = tr(
                    "Estado amarillo (preventivo): pulso {fc}, oxígeno {spo2} %. Vigilar {lista}. "
                    "Sin alarma crítica. Qué hacer para mejorar: {accion}.{mem}",
                    fc=signos.get("frecuenciaCardiacaLpm"),
                    spo2=signos.get("spo2Porcentaje"),
                    lista=lista_txt,
                    accion=tr(consejo_p0),
                    mem=extra_mem,
                )
        elif cordial:
            texto = tr(
                "Atención urgente, señor: su pulso en {fc} y oxígeno en {spo2} por ciento registran desvío importante en {lista}. {accion}.{mem}",
                fc=signos.get("frecuenciaCardiacaLpm"),
                spo2=signos.get("spo2Porcentaje"),
                lista=lista_txt,
                accion=tr(consejo_p0),
                mem=extra_mem,
            )
        else:
            texto = tr(
                "Alerta roja: pulso {fc}, oxígeno {spo2} %. Parámetros críticos: {lista}. {accion}.{mem}",
                fc=signos.get("frecuenciaCardiacaLpm"),
                spo2=signos.get("spo2Porcentaje"),
                lista=lista_txt,
                accion=tr(consejo_p0),
                mem=extra_mem,
            )
        return {
            "crewId": crew_id,
            "emisor": "asistente",
            "texto": texto,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modoVerificacion": "DETERMINISTA_ESTRICTO",
            "nivelAlerta": nivel_p0,
            "datosCitados": [
                {
                    "indicador": tr(p0["nombre"]),
                    "valorActual": f"{p0['valorActual']} {p0['unidad']}",
                    "baselinePersonal": tr("Base {v} {u}", v=p0["mediaPreVuelo"], u=p0["unidad"]),
                    "rangoReferencia": f"{p0['rangoMin']}–{p0['rangoMax']} {p0['unidad']}",
                    "fuente": p0.get("fuente") or "NASA OSDR OSD-575",
                    "esDatoRealOSDR": p0.get("fuente") == "NASA OSDR OSD-575",
                }
            ],
            "accionesSugeridas": [
                {
                    "id": f"med-{p0['id']}",
                    "etiqueta": tr("Medir {p} en 0G", p=tr(p0["nombre"])),
                    "descripcion": tr("Protocolo guiado en microgravedad"),
                    "tipo": "INICIAR_MEDICION",
                    "parametroId": p0["id"],
                    "destinoRuta": f"/medir/{p0['id']}",
                    "prioridad": "alta",
                },
                {
                    "id": f"3d-{sis0}",
                    "etiqueta": tr("Enfocar {s} en 3D", s=tr(sis0)),
                    "descripcion": tr("Inspeccionar órgano afectado"),
                    "tipo": "ENFOCAR_SISTEMA",
                    "sistemaId": sis0,
                    "prioridad": "normal",
                },
            ],
        }

    extra_mem = tr(" Recuerdo su nota: {n}.", n=ultima_nota) if ultima_nota else ""
    if cordial:
        texto_nom = tr(
            "Todo en orden, señor. Su pulso en {fc}, su oxígeno en {spo2} por ciento y sus análisis generales están en buen equilibrio.{mem}",
            fc=signos.get("frecuenciaCardiacaLpm"),
            spo2=signos.get("spo2Porcentaje"),
            mem=extra_mem,
        )
    else:
        texto_nom = tr(
            "Estado nominal: pulso {fc}, oxígeno {spo2} por ciento, parámetros en rango.{mem}",
            fc=signos.get("frecuenciaCardiacaLpm"),
            spo2=signos.get("spo2Porcentaje"),
            mem=extra_mem,
        )
    return {
        "crewId": crew_id,
        "emisor": "asistente",
        "texto": texto_nom,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "modoVerificacion": "DETERMINISTA_ESTRICTO",
        "nivelAlerta": "NOMINAL",
        "datosCitados": [
            {
                "indicador": tr("Signos de cabina"),
                "valorActual": f"{signos.get('frecuenciaCardiacaLpm')} lpm · {signos.get('spo2Porcentaje')}%",
                "baselinePersonal": tr("Base {v} lpm", v=signos.get("baseFrecuenciaCardiacaLpm")),
                "rangoReferencia": tr("Nominal"),
                "fuente": "V.I.T.A.L.I.S.",
                "esDatoRealOSDR": False,
            }
        ],
        "accionesSugeridas": [
            {
                "id": "ver-3d",
                "etiqueta": tr("Inspeccionar Cuerpo 3D"),
                "descripcion": tr("Abrir modelo anatómico 3D"),
                "tipo": "NAVEGAR",
                "destinoRuta": "/cuerpo",
                "prioridad": "normal",
            }
        ],
    }


async def detectar_mejor_modelo_cloud(api_key: str) -> Dict[str, Any]:
    """Detecta el proveedor de la API Key, verifica contra el proveedor real y elige el mejor modelo para L.I.S."""
    clean = (api_key or "").strip()
    if not clean:
        return {"valido": False, "error": "Ingresa una API Key válida."}

    proveedor = "openai"
    if clean.startswith("AIza"):
        proveedor = "gemini"
    elif clean.startswith("gsk_"):
        proveedor = "groq"
    elif clean.startswith("sk-or-"):
        proveedor = "openrouter"
    elif clean.startswith("nvapi-"):
        proveedor = "nvidia"

    async with httpx.AsyncClient(timeout=7.0) as client:
        try:
            if proveedor == "gemini":
                r = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={clean}"
                )
                if r.status_code != 200:
                    return {
                        "valido": False,
                        "proveedor": "gemini",
                        "error": "API Key de Google Gemini inválida o sin acceso.",
                    }
                data = r.json()
                modelos = [
                    m["name"].replace("models/", "")
                    for m in data.get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
                preferencia = [
                    "gemini-2.5-flash",
                    "gemini-2.0-flash",
                    "gemini-1.5-flash",
                    "gemini-1.5-pro",
                ]
                elegido = next(
                    (p for p in preferencia if p in modelos),
                    modelos[0] if modelos else "gemini-2.0-flash",
                )
                return {
                    "valido": True,
                    "proveedor": "gemini",
                    "nombreProveedor": "Google Gemini",
                    "mejorModelo": elegido,
                    "modelosDetectados": len(modelos),
                }

            if proveedor == "groq":
                r = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {clean}"},
                )
                if r.status_code != 200:
                    return {
                        "valido": False,
                        "proveedor": "groq",
                        "error": "API Key de Groq inválida.",
                    }
                modelos = [m["id"] for m in r.json().get("data", [])]
                preferencia = [
                    "llama-3.3-70b-versatile",
                    "llama-3.1-8b-instant",
                    "qwen-2.5-32b",
                ]
                elegido = next(
                    (p for p in preferencia if p in modelos),
                    modelos[0] if modelos else "llama-3.3-70b-versatile",
                )
                return {
                    "valido": True,
                    "proveedor": "groq",
                    "nombreProveedor": "Groq Cloud LPU",
                    "mejorModelo": elegido,
                    "modelosDetectados": len(modelos),
                }

            if proveedor == "openrouter":
                r = await client.get(
                    "https://openrouter.ai/api/v1/auth/key",
                    headers={"Authorization": f"Bearer {clean}"},
                )
                if r.status_code != 200:
                    return {
                        "valido": False,
                        "proveedor": "openrouter",
                        "error": "API Key de OpenRouter inválida.",
                    }
                return {
                    "valido": True,
                    "proveedor": "openrouter",
                    "nombreProveedor": "OpenRouter",
                    "mejorModelo": "google/gemini-2.0-flash-001",
                    "modelosDetectados": 1,
                }

            if proveedor == "nvidia":
                r = await client.get(
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {clean}"},
                )
                if r.status_code != 200:
                    return {
                        "valido": False,
                        "proveedor": "nvidia",
                        "error": "API Key de NVIDIA NIM inválida.",
                    }
                modelos = [m["id"] for m in r.json().get("data", [])]
                preferencia = [
                    "nvidia/nemotron-3.5-lightning-30b-a3b",
                    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                    "mistralai/mistral-large-4-1t-a52b",
                    "meta/llama-3.2-90b-vision-instruct",
                ]
                elegido = next(
                    (p for p in preferencia if p in modelos),
                    modelos[0] if modelos else "nvidia/nemotron-3.5-lightning-30b-a3b",
                )
                return {
                    "valido": True,
                    "proveedor": "nvidia",
                    "nombreProveedor": "NVIDIA NIM",
                    "mejorModelo": elegido,
                    "modelosDetectados": len(modelos),
                }

            # OpenAI por defecto
            r = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {clean}"},
            )
            if r.status_code != 200:
                return {
                    "valido": False,
                    "proveedor": "openai",
                    "error": "API Key de OpenAI inválida o sin saldo.",
                }
            modelos = [m["id"] for m in r.json().get("data", [])]
            preferencia = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"]
            elegido = next(
                (p for p in preferencia if p in modelos),
                modelos[0] if modelos else "gpt-4o-mini",
            )
            return {
                "valido": True,
                "proveedor": "openai",
                "nombreProveedor": "OpenAI",
                "mejorModelo": elegido,
                "modelosDetectados": len(modelos),
            }
        except Exception as exc:
            return {
                "valido": False,
                "proveedor": proveedor,
                "error": f"No se pudo conectar al proveedor ({exc}).",
            }


_PAT_DIACRITICOS_ES = re.compile(r"[áéíóúüñ¿¡]", re.IGNORECASE)
_PAT_CUES_ES = re.compile(
    r"\b(?:el|la|los|las|un|una|unos|unas|de|del|al|en|con|sin|por|para|sobre|entre|hacia|"
    r"desde|su|sus|mi|mis|tu|tus|se|lo|le|les|está|estan|están|son|hay|tiene|tengo|puede|"
    r"debe|señor|senor|todo|toda|todos|todas|ahora|antes|despues|después|mientras|luego|"
    r"ciento|paso|pasos|modo|pulso|oxigeno|oxígeno|presion|presión|azucar|azúcar|cabina|"
    r"protocolo|emergencia|instrucciones|alerta|aviso|avisos|crítico|critico|preventivo|"
    r"buen|bueno|orden|ordenes|órdenes|calma|bordo|gracias|hola|leer|dime|muestra|abre|"
    r"cierra|cambia|activa|activar|desactiva|oscuro|claro|rapida|rápida|lento|despacio|"
    r"silencio|frente|habitual|estudio|rango|encima|debajo|saturación|saturacion|temperatura|"
    r"corporal|notificar|oficial|médico|medico|tripulación|tripulacion|ligeramente|reposo|"
    r"respiraciones|hidrátate|hidratate|repite|medición|medicion|minutos|mejorar)\b",
    re.IGNORECASE,
)
_PAT_CUES_EN = re.compile(
    r"\b(?:the|and|or|of|to|in|on|at|for|with|without|from|into|by|your|my|our|their|"
    r"its|it|this|that|these|those|is|are|was|were|be|been|have|has|had|can|could|"
    r"should|would|will|may|sir|all|now|before|after|while|then|percent|over|step|steps|"
    r"mode|pulse|oxygen|pressure|blood|sugar|liver|kidney|bone|cabin|protocol|emergency|"
    r"instructions|alert|alerts|notice|warning|critical|preventive|good|calm|board|order|"
    r"ready|thanks|thank|hello|hi|please|read|tell|show|open|close|switch|change|activate|"
    r"deactivate|dark|light|fast|faster|slow|slower|quiet|quietly|silence|screen|looking|"
    r"view|model|body|system|heart|rate|lungs|brain|aed|cpr|bvm|baseline|within|range|"
    r"outside|above|below|usual|slightly|saturation|temperature|rest|breaths|hydrate|repeat|"
    r"measurement|notify|officer|medical|crew|check|measure|dose|doses|airway|line|saline|"
    r"epinephrine|milligrams|milliliters|deciliter|beats|minute|seconds|minutes|degrees|"
    r"celsius|mercury|studio)\b",
    re.IGNORECASE,
)

_MAPA_VOZ_EN = {
    "es-MX-JorgeNeural": "en-US-GuyNeural",
    "es-ES-AlvaroNeural": "en-GB-RyanNeural",
    "es-MX-DaliaNeural": "en-US-AriaNeural",
    "en-US-GuyNeural": "en-US-GuyNeural",
    "en-US-AriaNeural": "en-US-AriaNeural",
    "en-GB-RyanNeural": "en-GB-RyanNeural",
    "en-GB-SoniaNeural": "en-GB-SoniaNeural",
}
_MAPA_VOZ_ES = {
    "en-US-GuyNeural": "es-MX-JorgeNeural",
    "en-GB-RyanNeural": "es-ES-AlvaroNeural",
    "en-US-AriaNeural": "es-MX-DaliaNeural",
    "en-GB-SoniaNeural": "es-MX-DaliaNeural",
    "es-MX-JorgeNeural": "es-MX-JorgeNeural",
    "es-ES-AlvaroNeural": "es-ES-AlvaroNeural",
    "es-MX-DaliaNeural": "es-MX-DaliaNeural",
}


def detectar_idioma_texto(texto: str, defecto: Optional[str] = None) -> str:
    """Detecta de forma determinista si una frase está en español ('es') o inglés ('en')."""
    base = "es" if ((defecto if defecto in ("es", "en") else idioma()) == "es") else "en"
    txt = (texto or "").strip()
    if not txt:
        return base

    es_hits = len(_PAT_CUES_ES.findall(txt)) + (2 if _PAT_DIACRITICOS_ES.search(txt) else 0)
    en_hits = len(_PAT_CUES_EN.findall(txt))

    if es_hits == 0 and en_hits == 0:
        return base
    if en_hits >= 2 and en_hits >= es_hits + 2:
        return "en"
    if es_hits >= 2 and es_hits >= en_hits + 2:
        return "es"
    if base == "es" and en_hits >= 2 and es_hits == 0:
        return "en"
    if base == "en" and es_hits >= 2 and en_hits == 0:
        return "es"
    if defecto is None:
        if en_hits > es_hits and es_hits == 0:
            return "en"
        if es_hits > en_hits and en_hits == 0:
            return "es"
    return base


def resolver_voz_neural_por_idioma(voz_id: str, lang: str) -> str:
    """Empareja la voz neural al idioma destino evitando pronunciación cruzada."""
    es_ing = (lang or "es").lower().startswith("en")
    mapa = _MAPA_VOZ_EN if es_ing else _MAPA_VOZ_ES
    if voz_id in mapa:
        return mapa[voz_id]
    return "en-US-GuyNeural" if es_ing else "es-MX-JorgeNeural"


async def sintetizar_voz_lis(
    texto: str,
    voz_id: str = "jarvis-clone-latam",
    rate: float = 1.04,
    lang: Optional[str] = None,
) -> Tuple[bytes, str, str]:
    """
    Sintetiza audio en Python para L.I.S.:
      1) Resuelve el idioma efectivo ('es' / 'en') a partir de lang o el texto/UI.
      2) Si está seleccionada la voz clonada de JARVIS, envía text + voice + language al servidor XTTS v2.
      3) Si no está disponible o se eligió voz rápida, empareja la voz neural edge-tts al idioma exacto.
    """
    clean_text = (texto or "").strip()[:1200]
    if not clean_text:
        return b"", "audio/wav", "empty"

    if lang and str(lang).strip().lower() in ("es", "en", "es-mx", "en-us", "en-gb"):
        lang_eff = "en" if str(lang).strip().lower().startswith("en") else "es"
    else:
        lang_eff = detectar_idioma_texto(clean_text)

    if voz_id in ("jarvis-clone-latam", "jarvis-clone-classic", "jarvis-clone-en"):
        xtts_voice = "jarvis-clone-en" if (lang_eff == "en" and voz_id == "jarvis-clone-latam") else voz_id
        try:
            # XTTS v2 tarda 4–12 s por frase en la RTX 3050 Ti; la app nativa
            # sintetiza en un hilo aparte, así que se puede esperar sin congelar nada.
            async with httpx.AsyncClient(timeout=25.0) as client:
                r = await client.post(
                    f"{JARVIS_XTTS_URL}/synth",
                    json={"text": clean_text, "voice": xtts_voice, "language": lang_eff},
                )
                if r.status_code == 200 and len(r.content) > 500:
                    return r.content, "audio/wav", "jarvis-xtts-clone"
                _LOG_VOZ.warning(
                    "XTTS devolvió estado %s (%d bytes)", r.status_code, len(r.content)
                )
        except Exception as exc:
            _LOG_VOZ.warning("XTTS no disponible (%s); usando respaldo neural.", exc)

    # Respaldo neural inmediato en Python con edge_tts estrictamente separado por idioma
    try:
        import edge_tts

        voice_name = resolver_voz_neural_por_idioma(voz_id, lang_eff)
        pct = int(round((rate - 1.0) * 100))
        rate_str = f"{pct:+d}%"
        pitch_str = "-2Hz" if lang_eff == "en" else "-4Hz"
        communicate = edge_tts.Communicate(
            clean_text, voice=voice_name, rate=rate_str, pitch=pitch_str
        )
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        audio_bytes = buf.getvalue()
        if len(audio_bytes) > 200:
            return audio_bytes, "audio/mpeg", "edge-neural-fallback"
    except Exception as exc:
        _LOG_VOZ.warning("edge_tts no disponible (%s); probando voz SAPI local.", exc)

    # Respaldo local sin conexión en Windows (System.Speech SAPI -> WAV)
    if os.name == "nt":
        tmp_wav = ""
        try:
            fd, tmp_wav = tempfile.mkstemp(prefix="vitalis_sapi_", suffix=".wav")
            os.close(fd)
            env = os.environ.copy()
            env["VITALIS_TTS_TEXT"] = clean_text
            env["VITALIS_TTS_OUT"] = tmp_wav
            env["VITALIS_TTS_LANG"] = "en-US" if lang_eff == "en" else "es-MX"
            ps_script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$lang = $env:VITALIS_TTS_LANG; "
                "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like ($lang.Substring(0,2) + '*') } | Select-Object -First 1; "
                "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
                "$s.SetOutputToWaveFile($env:VITALIS_TTS_OUT); "
                "$s.Speak($env:VITALIS_TTS_TEXT); "
                "$s.Dispose()"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                env=env,
                check=True,
                timeout=12,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if os.path.exists(tmp_wav):
                with open(tmp_wav, "rb") as fh:
                    wav_bytes = fh.read()
                if len(wav_bytes) > 500:
                    return wav_bytes, "audio/wav", "windows-sapi-offline"
        except Exception as exc:
            _LOG_VOZ.warning("Respaldo SAPI offline falló: %s", exc)
        finally:
            if tmp_wav and os.path.exists(tmp_wav):
                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass

    return b"", "audio/wav", "none"


# ---------------------------------------------------------------------------
# Redacción opcional con LLM (local u online) sobre la respuesta determinista.
# El LLM sólo reformula: las cifras salen del snapshot y se validan después.
# Si el texto trae una sola cifra que no está en OSD-575/cabina, se descarta.
# ---------------------------------------------------------------------------

PROMPT_SISTEMA_LIS = (
    "Eres L.I.S., el asistente de cuidado y soporte vital de V.I.T.A.L.I.S. "
    "Hablas en español con naturalidad y calidez humana (nunca robótico). Respeta el ESTILO indicado en el contexto ('jarvis-cordial': cercano y elegante tratando de 'señor'; 'directo-clinico': breve y operativo sin rodeos). "
    "REGLA DE ESTILO OBLIGATORIA: en conversación normal sé muy conciso (1 o 2 frases cortas y directas) y NO uses palabras técnicas ni siglas médicas "
    "(prohibido decir 'analitos', 'timepoint', 'baseline', 'nominal', 'desvío', 'telemetría', 'OSD-575', 'SBAR', 'lpm', 'SpO2', 'mmHg', 'mg/dL'). "
    "Traduce todo a lenguaje cotidiano: di 'pulso', 'oxígeno', 'presión', 'azúcar en sangre', 'enzima del hígado', 'su nivel habitual', 'aire de la cabina'. "
    "Puedes conversar libremente, leer instrucciones en voz alta y controlar TODO el software mediante el arreglo 'acciones'. "
    "REGLA CLÍNICA: si mencionas un número, usa SOLO cifras exactas del SNAPSHOT o de las guías oficiales sin inventar ni redondear. No diagnostiques ni recetes. "
    "Cuando haya parámetros en estado amarillo (ATENCION), avisa de forma serena y tranquilizadora sin generar alarma crítica, y da indicaciones prácticas no farmacológicas de la EVALUACIÓN BASE o guías oficiales sobre qué hacer para mejorar su cuadro (reposo anclado, hidratación, respiración pausada, ventilación, ejercicio resistivo o repetir toma en 0G). "
    "Cuando el usuario pida leer instrucciones de emergencia, pasos de un protocolo, cómo usar un equipo (DEA, vía IV, vía aérea, fármacos) o cómo medir un indicador en cero gravedad: "
    "emite la acción correspondiente (LEER_PROTOCOLO, LEER_ALSP o LEER_GUIA_MEDICION), y en 'respuesta' escribe solo una frase breve confirmando qué leerás en voz alta (el software agregará automáticamente el texto completo verificado a la locución). "
    "Responde SIEMPRE en JSON válido con exactamente estas dos claves:\n"
    "{\n"
    '  "respuesta": "Texto natural y claro (sin tecnicismos, paréntesis, corchetes, guiones ni símbolos).",\n'
    '  "acciones": [\n'
    '    {"tipo": "...", "valor": "...", "indicadorId": "...", "protocoloId": "...", "equipoId": "...", "paso": 1, "comando": "...", "clave": "...", "nota": "..."}\n'
    "  ]\n"
    "}\n"
    "Acciones y valores válidos:\n"
    "- SET_CREW: C001 (Oficial Médico/CMO), C002 (Piloto), C003 (Especialista de Misión), C004 (Comandante)\n"
    "- SET_TIMEPOINT: L-92, L-44, L-3, R+1, R+45, R+82, R+194\n"
    "- SET_SISTEMA: cardiovascular, respiratorio, neuro-ocular, metabolico, musculoesqueletico, inmune-radiacion\n"
    "- SET_CAMARA_3D: cuerpo, frontal, lateral, capas\n"
    "- CONTROL_ZOOM_3D: valor = acercar | alejar | reiniciar\n"
    "- ENFOCAR_ORGANO: valor = corazon | pulmones | higado | riñones | cerebro | ojos | estomago | pancreas | bazo | huesos\n"
    "- IR_A: valor = inicio | cuerpo | medir | historial | sala | salud_mental | emergencia | lis. Opcional: indicadorId (solo medir) o protocoloId (cardiovascular|respiratorio|neurologico|trauma solo emergencia)\n"
    "- SELECCIONAR_ANALITO: selecciona un indicador en Historial (usa indicadorId válido OSD-575)\n"
    "- REGISTRAR_MEDICION: registra una medición nueva en 0G (usa indicadorId y valor numérico explícito dictado por el tripulante)\n"
    "- LEER_PROTOCOLO: narra en voz alta el protocolo completo o un paso (protocoloId: cardiovascular|respiratorio|neurologico|trauma; paso opcional: 1..5)\n"
    "- SELECCIONAR_PASO: salta a un paso del protocolo activo (paso: 1..5 o delta: 1|-1)\n"
    "- CONTROL_ALSP: controla herramienta ALSP (equipoId: dea|iv|via-aerea|farmacos; comando: seleccionar|reproducir|pausar|siguiente|anterior)\n"
    "- LEER_ALSP: selecciona y lee en voz alta las instrucciones de uso 0G de una herramienta ALSP (equipoId: dea|iv|via-aerea|farmacos; paso opcional; incluirDosis bool)\n"
    "- LEER_GUIA_MEDICION: lee los pasos para medir un indicador en 0G (indicadorId)\n"
    "- METRONOMO_RCP: valor = iniciar | detener | alternar (metrónomo RCP 110/min)\n"
    "- PANEL_AVISOS: valor = abrir | cerrar | alternar\n"
    "- CONFIGURAR: cambia ajustes de la app (clave: temaVisual|idioma|vozActiva|vozId|velocidadVoz|animacion3D|mostrarAvisosEmergentes|mostrarAsistente|duracionMicrofonoSeg|personalidad|alarmaEmergenciaSonora|alarmaEmergenciaVolumen|alarmaEmergenciaIntervaloMs|alarmaEmergenciaTono|alarmaEmergenciaIncluirSbar|sonidoMonitorOverview|volumenMonitorOverview, valor)\n"
    "- RECORDAR: guarda nota en memoria del tripulante (campo 'nota')\n"
    "- DISPARAR_SOS: activa alerta SBAR urgente (campos 'motivo' y 'protocoloId')\n"
    "- ATENDER_SOS: marca la alerta SBAR activa como atendida\n"
    "- SILENCIAR_VOZ: detiene inmediatamente la locución actual de L.I.S.\n"
    "Si no hace falta cambiar nada en la interfaz, devuelve \"acciones\": []."
)

# El LLM reformula la respuesta en el idioma activo de la interfaz. El prompt base
# está en español (idioma fuente): aquí solo se indica en qué idioma debe escribir.
DIRECTIVA_IDIOMA = {
    "es": (
        "\nIDIOMA DE RESPUESTA: español (es-MX). Escribe la clave 'respuesta' en español "
        "natural, aunque el contexto llegue en otro idioma."
    ),
    "en": (
        "\nRESPONSE LANGUAGE: English (en-US). Write the 'respuesta' value in natural, plain "
        "English even though the context above is in Spanish. Keep the JSON keys and every "
        "action identifier exactly as specified: they are internal codes, not prose."
    ),
}


def prompt_sistema_lis() -> str:
    """Prompt del sistema + directiva del idioma de interfaz activo."""
    return PROMPT_SISTEMA_LIS + DIRECTIVA_IDIOMA.get(idioma(), DIRECTIVA_IDIOMA["es"])


def _llamar_llm_raw(
    config: Dict[str, Any],
    sistema: str,
    usuario: str,
    temperatura: float = 0.2,
    max_tokens: int = 420,
) -> Tuple[str, str]:
    """Invoca el LLM configurado (Ollama local o Cloud API) y devuelve (texto, etiqueta_motor)."""
    motor = config.get("motorLLM", "determinista-puro")
    if motor == "determinista-puro":
        return "", "determinista"

    texto_llm = ""
    etiqueta = motor
    try:
        with httpx.Client(timeout=20.0) as client:
            if motor == "ollama-local":
                ep = str(config.get("llmEndpointLocal", "http://127.0.0.1:11434")).rstrip("/")
                modelo = config.get("llmModeloLocal", "qwen2.5:3b")
                r = client.post(
                    f"{ep}/api/chat",
                    json={
                        "model": modelo,
                        "stream": False,
                        "options": {"temperature": temperatura},
                        "messages": [
                            {"role": "system", "content": sistema},
                            {"role": "user", "content": usuario},
                        ],
                    },
                )
                if r.status_code == 200:
                    texto_llm = r.json().get("message", {}).get("content", "")
                    etiqueta = f"ollama:{modelo}"
            elif motor == "cloud-api-auto" and config.get("cloudApiKey"):
                key = config["cloudApiKey"]
                prov = config.get("cloudProvider", "")
                modelo = config.get("cloudModeloAuto", "")
                if prov == "gemini":
                    r = client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={key}",
                        json={
                            "systemInstruction": {"parts": [{"text": sistema}]},
                            "contents": [{"role": "user", "parts": [{"text": usuario}]}],
                            "generationConfig": {"temperature": temperatura},
                        },
                    )
                    if r.status_code == 200:
                        cand = r.json().get("candidates", [{}])[0]
                        texto_llm = "".join(
                            p.get("text", "") for p in cand.get("content", {}).get("parts", [])
                        )
                else:
                    base = {
                        "groq": "https://api.groq.com/openai/v1",
                        "openrouter": "https://openrouter.ai/api/v1",
                        "nvidia": "https://integrate.api.nvidia.com/v1",
                    }.get(prov, "https://api.openai.com/v1")
                    payload: Dict[str, Any] = {
                        "model": modelo,
                        "temperature": temperatura,
                        "messages": [
                            {"role": "system", "content": sistema},
                            {"role": "user", "content": usuario},
                        ],
                    }
                    if prov == "nvidia":
                        payload["max_tokens"] = max_tokens
                        payload["chat_template_kwargs"] = {"enable_thinking": False}
                    r = client.post(
                        f"{base}/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json=payload,
                    )
                    if r.status_code == 200:
                        texto_llm = r.json()["choices"][0]["message"]["content"]
                etiqueta = f"{prov}:{modelo}"
    except Exception:
        texto_llm = ""

    return (texto_llm or "").strip(), etiqueta


def _prompt_usuario(mensaje: str, respuesta_det: Dict[str, Any]) -> str:
    return (
        f"PREGUNTA DEL TRIPULANTE: {mensaje}\n"
        f"RESPUESTA VERIFICADA (fuente de verdad, NASA OSDR OSD-575): {respuesta_det.get('texto', '')}\n"
        "Reformula la respuesta verificada de forma natural, sin añadir datos."
    )


def _construir_prompt_libre(
    mensaje: str,
    snapshot: Dict[str, Any],
    respuesta_det: Dict[str, Any],
    estado_ui: Optional[Dict[str, Any]] = None,
    memoria: Optional[Dict[str, Any]] = None,
    historial: Optional[List[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    signos = snapshot.get("signosCabina", {})
    amb = snapshot.get("ambienteCabina", {})
    ui = estado_ui or {}
    cfg = config or {}
    notas = ((memoria or {}).get("notasRecordadas") or (memoria or {}).get("notas") or [])[:3]
    notas_txt = "; ".join(n.get("texto", "") for n in notas) if notas else "ninguna"

    hist_lineas = []
    for m in (historial or [])[-4:]:
        quien = "Tripulante" if m.get("emisor") == "astronauta" else "L.I.S."
        hist_lineas.append(f"{quien}: {m.get('texto', '')}")
    hist_txt = "\n".join(hist_lineas) if hist_lineas else "sin historial previo"

    analitos_txt = "\n".join(
        f"- {p['id']} ({_nombre_cotidiano(p['id'], p['nombre'])}): {p['valorActual']} "
        f"[habitual {p['mediaPreVuelo']}, antes {p.get('valorPreVueloL92')}, después {p.get('valorRecuperacionR194')}, {p['nivelDeterminista']}]"
        for p in snapshot.get("todosLosParametros", [])
    )
    fuera = snapshot.get("parametrosFueraDeRango") or []
    avisos_txt = (
        ", ".join(
            f"{_nombre_cotidiano(p['id'], p['nombre'])} ({p['nivelDeterminista']}: {p['valorActual']} — qué hacer: {p.get('accionSugerida', '')})"
            for p in fuera
        )
        if fuera
        else "sin avisos activos"
    )
    nivel_activo = respuesta_det.get("nivelAlerta") or (
        fuera[0].get("nivelDeterminista", "NOMINAL") if fuera else "NOMINAL"
    )
    meds_loc = snapshot.get("medicionesLocales", [])[:3]
    meds_txt = (
        "; ".join(
            f"{_nombre_cotidiano(m.get('parametroId', ''), m.get('parametroId', ''))} {m.get('valor')} ({m.get('nivelDeterminista')})"
            for m in meds_loc
        )
        if meds_loc
        else "ninguna reciente"
    )
    personalidad = str(ui.get("personalidad") or cfg.get("personalidad") or "jarvis-cordial")
    paso_em = int(ui.get("pasoEmergencia", 0)) + 1
    metro = "activo (110/min)" if ui.get("metronomoActivo") else "detenido"

    return (
        f"CONFIGURACIÓN Y ESTILO ACTIVO:\n"
        f"- Estilo de trato (personalidad): {personalidad}\n"
        f"- Aspecto de pantalla: {ui.get('temaVisual', cfg.get('temaVisual', 'oscuro'))} | "
        f"Voz activa: {ui.get('vozActiva', cfg.get('vozActiva', True))} ({ui.get('vozId', cfg.get('vozId', 'jarvis-clone-latam'))})\n\n"
        f"ESTADO ACTUAL DE LO QUE VE EL TRIPULANTE EN PANTALLA:\n"
        f"- Tripulante: {snapshot.get('crewId')} ({snapshot.get('rolTripulante')}) | Etapa: {snapshot.get('timepointActual')}\n"
        f"- Pantalla abierta: {ui.get('nombrePagina', ui.get('pagina', 'inicio'))} (id={ui.get('pagina', 'inicio')})\n"
        f"- Modelo 3D: vista '{ui.get('modoCamara3d', 'cuerpo')}', sistema '{ui.get('nombreSistema', ui.get('sistema', 'metabolico'))}', órgano seleccionado '{ui.get('organoSeleccionado') or 'ninguno'}'\n"
        f"- Medición en pantalla: '{ui.get('indicadorEnPantalla', 'glucose')}' | Historial seleccionado: '{ui.get('analitoHistorial', 'glucose')}'\n"
        f"- Emergencia en pantalla: protocolo '{ui.get('protocoloEmergencia', 'cardiovascular')}', paso {paso_em}, herramienta ALSP '{ui.get('equipoAlsp', 'dea')}', metrónomo {metro}\n"
        f"- Nivel de alerta activo: {nivel_activo}\n"
        f"- Avisos clínicos activos: {avisos_txt}\n"
        f"- Signos cabina: Pulso {signos.get('frecuenciaCardiacaLpm')}, Oxígeno {signos.get('spo2Porcentaje')}%, "
        f"Presión {signos.get('presionArterial')}, Temp {signos.get('temperaturaCorporalC')} °C\n"
        f"- Ambiente cabina: CO2 {amb.get('presionParcialCo2MmHg')}, Temp {amb.get('temperaturaCabinaC')} °C, "
        f"Radiación {amb.get('radiacionAcumuladaMsv')}, Retardo Tierra {amb.get('retardoTierraTexto')}\n"
        f"- Mediciones locales en 0G: {meds_txt}\n"
        f"- Memoria del tripulante: {notas_txt}\n"
        f"- Conversación reciente:\n{hist_txt}\n"
        f"- Datos de salud (NASA OSDR OSD-575):\n{analitos_txt}\n\n"
        f"EVALUACIÓN BASE: {respuesta_det.get('texto', '')}\n\n"
        f"MENSAJE ACTUAL DEL TRIPULANTE: {mensaje}"
    )


def _enriquecer_lectura_voz_desde_acciones(
    acciones: List[Dict[str, Any]],
    estado_ui: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Construye el texto largo verificado para voz si el LLM pidió leer protocolos, ALSP o guías."""
    ui = estado_ui or {}
    partes: List[str] = []
    for acc in acciones:
        tipo = str(acc.get("tipo", "")).upper()
        if tipo == "LEER_PROTOCOLO":
            pid = str(acc.get("protocoloId") or acc.get("valor") or ui.get("protocoloEmergencia") or "cardiovascular")
            paso = acc.get("paso")
            paso_num = int(paso) if isinstance(paso, (int, float, str)) and str(paso).isdigit() else None
            _corta, voz, _ = construir_lectura_protocolo(pid, paso_num=paso_num)
            partes.append(voz)
        elif tipo == "LEER_ALSP":
            eid = str(acc.get("equipoId") or acc.get("valor") or ui.get("equipoAlsp") or "dea")
            paso = acc.get("paso")
            paso_num = int(paso) if isinstance(paso, (int, float, str)) and str(paso).isdigit() else None
            inc_dosis = bool(acc.get("incluirDosis", False)) or ("farmac" in eid.lower())
            _corta, voz, _ = construir_lectura_alsp(eid, paso_num=paso_num, incluir_dosis=inc_dosis)
            partes.append(voz)
        elif tipo == "LEER_GUIA_MEDICION":
            ind = str(acc.get("indicadorId") or acc.get("valor") or ui.get("indicadorEnPantalla") or "glucose")
            _corta, voz = construir_lectura_guia_medicion(ind)
            partes.append(voz)
    return " ".join(partes).strip() if partes else None


def consultar_agente_libre(
    config: Dict[str, Any],
    mensaje: str,
    snapshot: Dict[str, Any],
    respuesta_det: Dict[str, Any],
    estado_ui: Optional[Dict[str, Any]] = None,
    memoria: Optional[Dict[str, Any]] = None,
    historial: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, List[Dict[str, Any]], str]:
    """
    Permite que L.I.S. converse libremente con el LLM configurado y emita acciones
    estructuradas para controlar todo el software, validando siempre las cifras.
    """
    import json as _json

    texto_det = respuesta_det.get("texto", "")
    acciones_det = list(respuesta_det.get("accionesControl") or [])
    motor = config.get("motorLLM", "determinista-puro")
    if motor == "determinista-puro":
        return texto_det, acciones_det, "determinista"

    prompt_usr = _construir_prompt_libre(
        mensaje, snapshot, respuesta_det, estado_ui, memoria, historial, config=config
    )
    raw, etiqueta = _llamar_llm_raw(
        config,
        prompt_sistema_lis(),
        prompt_usr,
        temperatura=0.25 if respuesta_det.get("nivelAlerta") != "CRITICO" else 0.0,
        max_tokens=500,
    )
    if not raw:
        return texto_det, acciones_det, "determinista (LLM no disponible)"

    respuesta_txt = ""
    acciones: List[Dict[str, Any]] = []
    try:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            obj = _json.loads(m.group(0))
            respuesta_txt = str(obj.get("respuesta", "")).strip()
            raw_acc = obj.get("acciones", [])
            if isinstance(raw_acc, list):
                acciones = [a for a in raw_acc if isinstance(a, dict) and a.get("tipo")]
    except Exception:
        m_resp = re.search(r'"respuesta"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
        if m_resp:
            respuesta_txt = m_resp.group(1).replace('\\"', '"').strip()

    if not respuesta_txt:
        # Si respondió texto libre sin JSON (y no es JSON roto), aprovecharlo si pasa el cerrojo numérico
        if "{" not in raw and '"respuesta"' not in raw:
            respuesta_txt = raw.strip()
        else:
            respuesta_txt = texto_det

    # Limpieza ligera de markdown para que la burbuja y la voz suenen naturales
    respuesta_txt = re.sub(r"[*_`#]+", "", respuesta_txt).strip()

    # Preservar acciones deterministas críticas/lectura si el LLM omitió emitir acciones
    if not acciones and acciones_det:
        acciones = acciones_det

    # Enriquecer locución larga verificada si se solicitó lectura de protocolo/ALSP/guía
    voz_desde_acc = _enriquecer_lectura_voz_desde_acciones(acciones, estado_ui)
    if voz_desde_acc:
        respuesta_det["textoVoz"] = voz_desde_acc

    # En emergencias críticas reales priorizamos la precisión determinista
    if respuesta_det.get("nivelAlerta") == "CRITICO" and respuesta_det.get("solicitoAyudaAutomatica"):
        return texto_det, acciones, f"{etiqueta} (texto crítico determinista)"

    valido, _ = validar_respuesta_sin_alucinacion(respuesta_txt, snapshot)
    if not valido:
        return texto_det, acciones, "determinista (cifra no verificada bloqueada)"

    return respuesta_txt, acciones, etiqueta


def redactar_con_llm(
    config: Dict[str, Any],
    mensaje: str,
    snapshot: Dict[str, Any],
    respuesta_det: Dict[str, Any],
) -> Tuple[str, str]:
    """Compatibilidad con llamadas de reformulación: devuelve (texto, motorUsado)."""
    texto, _acciones, motor = consultar_agente_libre(config, mensaje, snapshot, respuesta_det)
    return texto, motor


def estado_ollama(endpoint: str) -> Dict[str, Any]:
    ep = (endpoint or "http://127.0.0.1:11434").rstrip("/")
    try:
        with httpx.Client(timeout=2.0) as client:
            r = client.get(f"{ep}/api/tags")
            if r.status_code == 200:
                return {
                    "conectado": True,
                    "modelos": [m["name"] for m in r.json().get("models", [])],
                }
    except Exception:
        pass
    return {"conectado": False, "modelos": []}


def estado_voz_jarvis() -> bool:
    try:
        with httpx.Client(timeout=1.2) as client:
            r = client.get(f"{JARVIS_XTTS_URL}/health")
            return r.status_code == 200 and bool(r.json().get("ok"))
    except Exception:
        return False
