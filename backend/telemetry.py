# -*- coding: utf-8 -*-
"""
backend/telemetry.py — Motor de telemetría fisiológica y ambiental en tiempo real
con enlace directo a los nodos del Modelo 3D (meshNodeId) y animaciones (toolAnimationId).
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from desktop.i18n import tr

from backend.crew_hub import ORDEN_NIVEL, get_crew_hub
from backend.database import (
    get_baseline,
    get_cabina_dataset,
    get_osdr_dataset,
    get_valor_osdr,
)
from backend.triage import (
    evaluar_lectura_determinista,
    listar_anomalias_tripulante,
)


def generar_frame_telemetria(
    crew_id: str = "C003", timepoint: str = "R+1"
) -> Dict[str, Any]:
    """
    Construye un frame completo de telemetría en tiempo real (RealtimeTelemetryFrame)
    combinando los signos vitales continuos de cabina y el panel bioquímico NASA OSDR OSD-575.
    """
    cabina_data = get_cabina_dataset()
    tripulante = cabina_data.get("tripulantes", {}).get(
        crew_id, cabina_data.get("tripulantes", {}).get("C003", {})
    )
    cabina = cabina_data.get("cabina", {})

    # Oscilación fisiológica sutil determinista por segundo (sin alterar la línea base)
    t_sec = time.time()
    osc_hr = int(round(math.sin(t_sec * 0.45) * 1.0))
    osc_temp = round(math.cos(t_sec * 0.25) * 0.04, 1)

    fc_base = int(tripulante.get("frecuenciaCardiacaLpm", 64))
    fc_actual = fc_base + osc_hr
    spo2_actual = int(tripulante.get("spo2Porcentaje", 98))
    temp_actual = round(
        float(tripulante.get("temperaturaCorporalC", 36.7)) + osc_temp, 1
    )

    anomalias_tp = listar_anomalias_tripulante(crew_id, timepoint)
    anomalias_todas = listar_anomalias_tripulante(crew_id)

    # Analito foco (glucosa o primera anomalía activa)
    val_glucosa = get_valor_osdr(crew_id, "glucose", timepoint)
    if val_glucosa is None:
        val_glucosa = get_baseline(crew_id, "glucose").get("mediaPreVuelo", 71.3)
    eval_glucosa = evaluar_lectura_determinista(
        crew_id, "glucose", float(val_glucosa)
    )

    foco = (
        eval_glucosa
        if eval_glucosa["nivel"] != "NOMINAL"
        else (anomalias_tp[0] if anomalias_tp else (anomalias_todas[0] if anomalias_todas else eval_glucosa))
    )

    # Estado de cada nodo 3D del modelo anatómico
    nodos_3d: Dict[str, Dict[str, Any]] = {
        "head_neuro_ocular": {
            "meshNodeId": "head_neuro_ocular",
            "sistema": "neuro-ocular",
            "nivel": "NOMINAL",
            "lecturaPrincipal": tr(
                "{t} °C · {av}",
                t=temp_actual,
                av=tripulante.get("agudezaVisual", "20/20"),
            ),
        },
        "thorax_heart": {
            "meshNodeId": "thorax_heart",
            "sistema": "cardiovascular",
            "nivel": "NOMINAL",
            "lecturaPrincipal": tr(
                "{fc} lpm · {pa} mmHg",
                fc=fc_actual,
                pa=tripulante.get("presionArterial", "118/76"),
            ),
        },
        "thorax_lungs": {
            "meshNodeId": "thorax_lungs",
            "sistema": "respiratorio",
            "nivel": "NOMINAL",
            "lecturaPrincipal": tr(
                "SpO₂ {v}% · CO₂ cab {c} mmHg",
                v=spo2_actual,
                c=cabina.get("presionParcialCo2MmHg", 2.8),
            ),
        },
        "abdomen_hepatic_renal": {
            "meshNodeId": "abdomen_hepatic_renal",
            "sistema": "metabolico",
            "nivel": eval_glucosa["nivel"],
            "lecturaPrincipal": tr(
                "Glucosa {v} mg/dL ({d}%)",
                v=val_glucosa,
                d=f"{eval_glucosa['desvioPorcentajeBaseline']:+.1f}",
            ),
        },
        "limbs_musculoskeletal": {
            "meshNodeId": "limbs_musculoskeletal",
            "sistema": "musculoesqueletico",
            "nivel": "NOMINAL",
            "lecturaPrincipal": f"Calcio {get_valor_osdr(crew_id, 'calcium', timepoint) or '–'} mg/dL",
        },
        "systemic_immune_radiation": {
            "meshNodeId": "systemic_immune_radiation",
            "sistema": "inmune-radiacion",
            "nivel": "NOMINAL",
            "lecturaPrincipal": f"Radiación {cabina.get('radiacionAcumuladaMsv', 1.42)} mSv",
        },
    }

    for anom in anomalias_tp:
        m_id = anom.get("meshNodeId")
        if m_id in nodos_3d:
            nodos_3d[m_id]["nivel"] = anom["nivel"]

    hub_frame = get_crew_hub().frame_actual(crew_id)
    lecturas_vivas = (hub_frame or {}).get("lecturas") or {}
    estado_nodos_3d = (hub_frame or {}).get("estadoNodos3D") or {}

    # Si el runtime 1 Hz tiene lecturas en vivo (incl. anomalías simuladas), enriquecemos signos y nodos 3D.
    if lecturas_vivas:
        if "heart_rate" in lecturas_vivas:
            fc_actual = int(round(float(lecturas_vivas["heart_rate"]["valor"])))
        if "spo2" in lecturas_vivas:
            spo2_actual = int(round(float(lecturas_vivas["spo2"]["valor"])))
        if "core_temperature" in lecturas_vivas:
            temp_actual = round(float(lecturas_vivas["core_temperature"]["valor"]), 1)
        sbp = lecturas_vivas.get("systolic_bp", {}).get("valor")
        dbp = lecturas_vivas.get("diastolic_bp", {}).get("valor")
        pa_viva = (
            f"{int(round(sbp))}/{int(round(dbp))}"
            if sbp is not None and dbp is not None
            else tripulante.get("presionArterial", "118/76")
        )
        rr_vivo = int(
            round(float(lecturas_vivas.get("respiratory_rate", {}).get("valor", tripulante.get("frecuenciaRespiratoriaRpm", 14))))
        )
        for nodo_id, st_nodo in estado_nodos_3d.items():
            if nodo_id in nodos_3d:
                lvl_actual = nodos_3d[nodo_id]["nivel"]
                lvl_vivo = st_nodo.get("nivelMaximo", "NOMINAL")
                if ORDEN_NIVEL.get(lvl_vivo, 0) > ORDEN_NIVEL.get(lvl_actual, 0):
                    nodos_3d[nodo_id]["nivel"] = lvl_vivo
    else:
        pa_viva = tripulante.get("presionArterial", "118/76")
        rr_vivo = tripulante.get("frecuenciaRespiratoriaRpm", 14)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "crewId": crew_id,
        "rol": tr(tripulante.get("rol", "Tripulante")),
        "timepoint": timepoint,
        "entorno": (hub_frame or {}).get("entorno", "nave"),
        "modo": (hub_frame or {}).get("modo", "simulado"),
        "metSegundos": (hub_frame or {}).get("metSegundos", 0),
        "signosVitales": {
            "frecuenciaCardiacaLpm": fc_actual,
            "baseFrecuenciaCardiacaLpm": tripulante.get(
                "baseFrecuenciaCardiacaLpm", 62
            ),
            "spo2Porcentaje": spo2_actual,
            "baseSpo2Porcentaje": tripulante.get("baseSpo2Porcentaje", 99),
            "presionArterial": pa_viva,
            "basePresionArterial": tripulante.get(
                "basePresionArterial", "116/74"
            ),
            "temperaturaCorporalC": temp_actual,
            "baseTemperaturaC": tripulante.get("baseTemperaturaC", 36.6),
            "frecuenciaRespiratoriaRpm": rr_vivo,
            "presionIntracranealMmHg": lecturas_vivas.get("intracranial_pressure_est", {}).get("valor"),
            "agudezaVisual": tripulante.get("agudezaVisual", "20/20"),
            "amsler": tripulante.get("amsler", "Sin distorsión"),
        },
        "cabina": {
            **cabina,
            "presionParcialCo2MmHg": (
                lecturas_vivas.get("cabin_co2", {}).get("valor")
                if "cabin_co2" in lecturas_vivas
                else cabina.get("presionParcialCo2MmHg", 2.8)
            ),
            "radiacionAcumuladaMsv": (
                lecturas_vivas.get("radiation_dose", {}).get("valor")
                if "radiation_dose" in lecturas_vivas
                else cabina.get("radiacionAcumuladaMsv", 1.42)
            ),
        },
        "focoObservacion": foco,
        "anomaliasTimepoint": anomalias_tp,
        "anomaliasSerieCompleta": anomalias_todas,
        "nodosModelo3D": nodos_3d,
        "lecturas": lecturas_vivas,
        "estadoNodos3D": estado_nodos_3d,
    }
