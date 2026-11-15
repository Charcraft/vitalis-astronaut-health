# -*- coding: utf-8 -*-
"""
backend/registry.py — Catálogo Plug & Play de 26 parámetros de V.I.T.A.L.I.S. / AEGIS.

Portado fielmente de la nueva arquitectura (`src/lib/realtime/registry.ts`):
- 17 analitos reales de NASA OSDR OSD-575 (panel CMP de Inspiration4).
- 9 parámetros fisiológicos y ambientales en tiempo real (simulados).
- Trazabilidad obligatoria (`fuenteTrazable`, `fuenteUmbral`), entornos de misión
  (`nave`, `estacion`, `base-lunar`), `meshNodeId` 3D y `toolAnimationId`.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

FUENTE_OSDR = "OSDR OSD-575 (rango de referencia incluido en el dataset)"
FUENTE_FISIO = "docs/INDICATORS.md"
FUENTE_SUPUESTO = "[SUPUESTO] Pendiente de validación clínica"

INTERVALO_LAB_MS = 24 * 60 * 60 * 1000
INTERVALO_VITAL_MS = 1_000

ENTORNOS_MISION: Tuple[str, ...] = ("nave", "estacion", "base-lunar")

MESH_NODES: Tuple[str, ...] = (
    "head_neuro_ocular",
    "thorax_heart",
    "thorax_lungs",
    "abdomen_hepatic_renal",
    "limbs_musculoskeletal",
    "systemic_immune_radiation",
)

ETIQUETAS_NODOS_3D: Dict[str, str] = {
    "head_neuro_ocular": "Cabeza y sistema neuro-ocular",
    "thorax_heart": "Tórax · corazón",
    "thorax_lungs": "Tórax · pulmones",
    "abdomen_hepatic_renal": "Abdomen · hígado y riñón",
    "limbs_musculoskeletal": "Extremidades · músculo y hueso",
    "systemic_immune_radiation": "Sistémico · inmune y radiación",
}

TOOL_ANIMATIONS: Tuple[str, ...] = (
    "anim_none",
    "anim_capillary_analyzer",
    "anim_bp_cuff",
    "anim_pulse_oximeter",
    "anim_ocular_fundoscope",
    "anim_cpr_cmrs_restraint",
    "anim_pba_oxygen_mask",
)

_SISTEMA_OSDR: Dict[str, str] = {
    "albumin": "proteina",
    "alkaline_phosphatase": "hepatico",
    "alt": "hepatico",
    "ast": "hepatico",
    "total_bilirubin": "hepatico",
    "calcium": "electrolitos",
    "carbon_dioxide": "electrolitos",
    "chloride": "electrolitos",
    "creatinine": "renal",
    "egfr_african_american": "renal",
    "egfr_non_african_american": "renal",
    "globulin": "proteina",
    "glucose": "metabolico",
    "potassium": "electrolitos",
    "total_protein": "proteina",
    "sodium": "electrolitos",
    "urea_nitrogen_bun": "renal",
}

# Equivalencia con los 6 sistemas anatómicos del visor VTK 3D de escritorio.
_SISTEMA_VISUAL_POR_PARAMETRO: Dict[str, str] = {
    "albumin": "inmune-radiacion",
    "alkaline_phosphatase": "musculoesqueletico",
    "alt": "metabolico",
    "ast": "metabolico",
    "total_bilirubin": "metabolico",
    "calcium": "musculoesqueletico",
    "carbon_dioxide": "respiratorio",
    "chloride": "respiratorio",
    "creatinine": "metabolico",
    "egfr_african_american": "metabolico",
    "egfr_non_african_american": "metabolico",
    "globulin": "inmune-radiacion",
    "glucose": "metabolico",
    "potassium": "cardiovascular",
    "total_protein": "inmune-radiacion",
    "sodium": "neuro-ocular",
    "urea_nitrogen_bun": "metabolico",
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


def _laboratorio(
    *,
    id: str,
    nombre: str,
    unidad: str,
    es_derivado: bool,
    rango_referencia: Dict[str, Optional[float]],
    metodo: Optional[str] = None,
    rango_por_sexo: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
) -> Dict[str, Any]:
    definicion: Dict[str, Any] = {
        "id": id,
        "nombre": nombre,
        "unidad": unidad,
        "unidadCanonica": unidad,
        "sistema": _SISTEMA_OSDR[id],
        "sistemaVisual": _SISTEMA_VISUAL_POR_PARAMETRO.get(id, "metabolico"),
        "categoria": "bioquimico-osdr",
        "frecuencia": "muestra-discreta",
        "intervaloMs": INTERVALO_LAB_MS,
        "tipoDato": "escalar",
        "esDerivado": es_derivado,
        "requiereContexto": False,
        "tipoDesviacion": "z-score",
        "rangoReferencia": dict(rango_referencia),
        "referenciaPoblacional": {
            "min": rango_referencia.get("min"),
            "max": rango_referencia.get("max"),
        },
        "fuenteUmbral": FUENTE_OSDR,
        "meshNodeId": "abdomen_hepatic_renal",
        "toolAnimationId": "anim_capillary_analyzer",
        "fuenteTrazable": f"{FUENTE_OSDR} · recursos/datos/seed/osdr-inspiration4-cmp.json",
        "esDatoRealOSDR": True,
        "entornos": ["nave", "estacion", "base-lunar"],
    }
    if metodo is not None:
        definicion["metodo"] = metodo
    if rango_por_sexo is not None:
        definicion["rangoReferenciaPorSexo"] = deepcopy(rango_por_sexo)
    return definicion


PARAMETROS_OSDR: Tuple[Dict[str, Any], ...] = (
    _laboratorio(
        id="albumin",
        nombre="Albúmina",
        unidad="g/dL",
        es_derivado=False,
        rango_referencia={"min": 3.6, "max": 5.1, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="alkaline_phosphatase",
        nombre="Fosfatasa alcalina",
        unidad="U/L",
        es_derivado=False,
        rango_referencia={"min": 36.0, "max": 130.0, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="alt",
        nombre="ALT (alanina aminotransferasa)",
        unidad="U/L",
        es_derivado=False,
        rango_referencia={"min": 9.0, "max": 46.0, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="ast",
        nombre="AST (aspartato aminotransferasa)",
        unidad="U/L",
        es_derivado=False,
        rango_referencia={"min": 10.0, "max": 40.0, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="total_bilirubin",
        nombre="Bilirrubina total",
        unidad="mg/dL",
        es_derivado=False,
        rango_referencia={"min": 0.2, "max": 1.2, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="calcium",
        nombre="Calcio",
        unidad="mg/dL",
        es_derivado=False,
        rango_referencia={"min": 8.6, "max": 10.3, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="carbon_dioxide",
        nombre="CO₂ total",
        unidad="mmol/L",
        es_derivado=False,
        rango_referencia={"min": 20.0, "max": 32.0, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="chloride",
        nombre="Cloruro",
        unidad="mmol/L",
        es_derivado=False,
        rango_referencia={"min": 98.0, "max": 110.0, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="creatinine",
        nombre="Creatinina",
        unidad="mg/dL",
        es_derivado=False,
        rango_referencia={"min": 0.6, "max": 1.35, "criticoMin": None, "criticoMax": None},
        # [Fuente: Creatinine blood test (Normal Results) — UCSF Health / A.D.A.M. — https://www.ucsfhealth.org/medical-tests/creatinine-blood-test — consultado 2026-11-14] [POR VALIDAR]
        rango_por_sexo={
            "M": {"min": 0.7, "max": 1.3, "criticoMin": None, "criticoMax": None},
            "F": {"min": 0.5, "max": 0.95, "criticoMin": None, "criticoMax": None},
        },
    ),
    _laboratorio(
        id="egfr_african_american",
        nombre="eGFR (ajuste afroamericano)",
        unidad="mL/min/1.73m²",
        es_derivado=True,
        metodo="Ecuación CKD-EPI, ajuste afroamericano",
        rango_referencia={"min": 60.0, "max": None, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="egfr_non_african_american",
        nombre="eGFR",
        unidad="mL/min/1.73m²",
        es_derivado=True,
        metodo="Ecuación CKD-EPI",
        rango_referencia={"min": 60.0, "max": None, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="globulin",
        nombre="Globulina",
        unidad="g/dL",
        es_derivado=True,
        metodo="Proteína total − albúmina",
        rango_referencia={"min": 1.9, "max": 3.7, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="glucose",
        nombre="Glucosa",
        unidad="mg/dL",
        es_derivado=False,
        rango_referencia={"min": 65.0, "max": 99.0, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="potassium",
        nombre="Potasio",
        unidad="mmol/L",
        es_derivado=False,
        rango_referencia={"min": 3.5, "max": 5.3, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="total_protein",
        nombre="Proteína total",
        unidad="g/dL",
        es_derivado=False,
        rango_referencia={"min": 6.1, "max": 8.1, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="sodium",
        nombre="Sodio",
        unidad="mmol/L",
        es_derivado=False,
        rango_referencia={"min": 135.0, "max": 146.0, "criticoMin": None, "criticoMax": None},
    ),
    _laboratorio(
        id="urea_nitrogen_bun",
        nombre="Nitrógeno ureico (BUN)",
        unidad="mg/dL",
        es_derivado=False,
        rango_referencia={"min": 7.0, "max": 25.0, "criticoMin": None, "criticoMax": None},
    ),
)

PARAMETROS_SIMULADOS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "heart_rate",
        "sistema": "cardiovascular",
        "sistemaVisual": "cardiovascular",
        "nombre": "Frecuencia cardíaca",
        "unidad": "bpm",
        "unidadCanonica": "bpm",
        "categoria": "biologico-fisico",
        "frecuencia": "tiempo-real-continuo",
        "intervaloMs": INTERVALO_VITAL_MS,
        "tipoDato": "escalar",
        "esDerivado": False,
        "requiereContexto": True,
        "tipoDesviacion": "delta-absoluto",
        "rangoReferencia": {"min": 50.0, "max": 90.0, "criticoMin": 40.0, "criticoMax": 110.0},
        "referenciaPoblacional": {"min": 60.0, "max": 100.0},
        "fuenteUmbral": f"{FUENTE_FISIO} §1 [POR VALIDAR]",
        "meshNodeId": "thorax_heart",
        "toolAnimationId": "anim_none",
        "fuenteTrazable": f"{FUENTE_FISIO} §1",
        "entornos": ["nave", "estacion", "base-lunar"],
        "esDatoRealOSDR": False,
    },
    {
        "id": "spo2",
        "sistema": "respiratorio",
        "sistemaVisual": "respiratorio",
        "nombre": "Saturación de oxígeno (SpO₂)",
        "unidad": "%",
        "unidadCanonica": "%",
        "categoria": "biologico-fisico",
        "frecuencia": "tiempo-real-continuo",
        "intervaloMs": INTERVALO_VITAL_MS,
        "tipoDato": "escalar",
        "esDerivado": False,
        "requiereContexto": True,
        "tipoDesviacion": "delta-absoluto",
        "rangoReferencia": {"min": 95.0, "max": 100.0, "criticoMin": 90.0, "criticoMax": None},
        "referenciaPoblacional": {"min": 95.0, "max": 100.0},
        "fuenteUmbral": f"{FUENTE_FISIO} §3",
        "meshNodeId": "thorax_lungs",
        "toolAnimationId": "anim_pulse_oximeter",
        "fuenteTrazable": f"{FUENTE_FISIO} §3",
        "entornos": ["nave", "estacion", "base-lunar"],
        "esDatoRealOSDR": False,
    },
    {
        "id": "systolic_bp",
        "sistema": "cardiovascular",
        "sistemaVisual": "cardiovascular",
        "nombre": "Presión arterial sistólica",
        "unidad": "mmHg",
        "unidadCanonica": "mmHg",
        "categoria": "biologico-fisico",
        "frecuencia": "tiempo-real-continuo",
        "intervaloMs": 60_000,
        "tipoDato": "escalar",
        "esDerivado": False,
        "requiereContexto": True,
        "tipoDesviacion": "delta-absoluto",
        "rangoReferencia": {"min": 90.0, "max": 139.0, "criticoMin": 90.0, "criticoMax": 180.0},
        "referenciaPoblacional": {"min": 90.0, "max": 120.0},
        "fuenteUmbral": f"{FUENTE_FISIO} §2 [POR VALIDAR]",
        "meshNodeId": "thorax_heart",
        "toolAnimationId": "anim_bp_cuff",
        "fuenteTrazable": f"{FUENTE_FISIO} §2",
        "entornos": ["nave", "estacion", "base-lunar"],
        "esDatoRealOSDR": False,
    },
    {
        "id": "diastolic_bp",
        "sistema": "cardiovascular",
        "sistemaVisual": "cardiovascular",
        "nombre": "Presión arterial diastólica",
        "unidad": "mmHg",
        "unidadCanonica": "mmHg",
        "categoria": "biologico-fisico",
        "frecuencia": "tiempo-real-continuo",
        "intervaloMs": 60_000,
        "tipoDato": "escalar",
        "esDerivado": False,
        "requiereContexto": True,
        "tipoDesviacion": "delta-absoluto",
        "rangoReferencia": {"min": 60.0, "max": 89.0, "criticoMin": 60.0, "criticoMax": 120.0},
        "referenciaPoblacional": {"min": 60.0, "max": 80.0},
        "fuenteUmbral": f"{FUENTE_FISIO} §2 [POR VALIDAR]",
        "meshNodeId": "thorax_heart",
        "toolAnimationId": "anim_bp_cuff",
        "fuenteTrazable": f"{FUENTE_FISIO} §2",
        "entornos": ["nave", "estacion", "base-lunar"],
        "esDatoRealOSDR": False,
    },
    {
        "id": "respiratory_rate",
        "sistema": "respiratorio",
        "sistemaVisual": "respiratorio",
        "nombre": "Frecuencia respiratoria",
        "unidad": "rpm",
        "unidadCanonica": "rpm",
        "categoria": "biologico-fisico",
        "frecuencia": "tiempo-real-continuo",
        "intervaloMs": INTERVALO_VITAL_MS,
        "tipoDato": "escalar",
        "esDerivado": False,
        "requiereContexto": True,
        "tipoDesviacion": "delta-absoluto",
        "rangoReferencia": {"min": 12.0, "max": 20.0, "criticoMin": 10.0, "criticoMax": 24.0},
        "referenciaPoblacional": {"min": 12.0, "max": 20.0},
        "fuenteUmbral": f"{FUENTE_FISIO} §4",
        "meshNodeId": "thorax_lungs",
        "toolAnimationId": "anim_none",
        "fuenteTrazable": f"{FUENTE_FISIO} §4",
        "entornos": ["nave", "estacion", "base-lunar"],
        "esDatoRealOSDR": False,
    },
    {
        "id": "core_temperature",
        "sistema": "termorregulacion",
        "sistemaVisual": "inmune-radiacion",
        "nombre": "Temperatura corporal",
        "unidad": "°C",
        "unidadCanonica": "°C",
        "categoria": "biologico-fisico",
        "frecuencia": "tiempo-real-continuo",
        "intervaloMs": 60_000,
        "tipoDato": "escalar",
        "esDerivado": False,
        "requiereContexto": True,
        "tipoDesviacion": "delta-absoluto",
        "rangoReferencia": {"min": 36.0, "max": 37.3, "criticoMin": 35.0, "criticoMax": 38.0},
        "referenciaPoblacional": {"min": 36.1, "max": 37.2},
        "fuenteUmbral": f"{FUENTE_FISIO} §5 [POR VALIDAR]",
        "meshNodeId": "systemic_immune_radiation",
        "toolAnimationId": "anim_none",
        "fuenteTrazable": f"{FUENTE_FISIO} §5",
        "entornos": ["nave", "estacion", "base-lunar"],
        "esDatoRealOSDR": False,
    },
    {
        "id": "intracranial_pressure_est",
        "sistema": "neuro-ocular",
        "sistemaVisual": "neuro-ocular",
        "nombre": "Presión intracraneal estimada",
        "unidad": "mmHg",
        "unidadCanonica": "mmHg",
        "categoria": "biologico-fisico",
        "frecuencia": "tiempo-real-continuo",
        "intervaloMs": 5_000,
        "tipoDato": "escalar",
        "esDerivado": True,
        "metodo": "Estimación indirecta (ocular/ótica), no invasiva",
        "requiereContexto": True,
        "tipoDesviacion": "delta-absoluto",
        "rangoReferencia": {"min": None, "max": None, "criticoMin": None, "criticoMax": None},
        "referenciaPoblacional": {"min": None, "max": None},
        "fuenteUmbral": FUENTE_SUPUESTO,
        "meshNodeId": "head_neuro_ocular",
        "toolAnimationId": "anim_ocular_fundoscope",
        "fuenteTrazable": FUENTE_SUPUESTO,
        # SANS / desplazamiento de fluidos documentado en microgravedad (nave y estación).
        "entornos": ["nave", "estacion"],
        "esDatoRealOSDR": False,
    },
    {
        "id": "cabin_co2",
        "sistema": "ambiental",
        "sistemaVisual": "respiratorio",
        "nombre": "CO₂ parcial en cabina",
        "unidad": "mmHg",
        "unidadCanonica": "mmHg",
        "categoria": "ambiental",
        "frecuencia": "ambiental-cabina",
        "intervaloMs": 5_000,
        "tipoDato": "escalar",
        "esDerivado": False,
        "requiereContexto": False,
        "tipoDesviacion": "delta-absoluto",
        "rangoReferencia": {"min": None, "max": None, "criticoMin": None, "criticoMax": None},
        "referenciaPoblacional": {"min": None, "max": None},
        "fuenteUmbral": FUENTE_SUPUESTO,
        "meshNodeId": None,
        "toolAnimationId": "anim_none",
        "fuenteTrazable": FUENTE_SUPUESTO,
        "entornos": ["nave", "estacion", "base-lunar"],
        "esDatoRealOSDR": False,
    },
    {
        "id": "radiation_dose",
        "sistema": "ambiental",
        "sistemaVisual": "inmune-radiacion",
        "nombre": "Dosis de radiación acumulada",
        "unidad": "mSv",
        "unidadCanonica": "mSv",
        "categoria": "ambiental",
        "frecuencia": "ambiental-cabina",
        "intervaloMs": 60_000,
        "tipoDato": "escalar",
        "esDerivado": False,
        "requiereContexto": False,
        "tipoDesviacion": "delta-absoluto",
        "rangoReferencia": {"min": None, "max": None, "criticoMin": None, "criticoMax": None},
        "referenciaPoblacional": {"min": None, "max": None},
        "fuenteUmbral": FUENTE_SUPUESTO,
        "meshNodeId": "systemic_immune_radiation",
        "toolAnimationId": "anim_none",
        "fuenteTrazable": FUENTE_SUPUESTO,
        "entornos": ["nave", "estacion", "base-lunar"],
        "esDatoRealOSDR": False,
    },
)

TODOS_PARAMETROS: Tuple[Dict[str, Any], ...] = PARAMETROS_OSDR + PARAMETROS_SIMULADOS
_INDICE: Dict[str, Dict[str, Any]] = {p["id"]: p for p in TODOS_PARAMETROS}
PARAMETER_IDS: Tuple[str, ...] = tuple(p["id"] for p in TODOS_PARAMETROS)


def list_params() -> List[Dict[str, Any]]:
    """Devuelve copias del catálogo completo (26 parámetros)."""
    return [deepcopy(p) for p in TODOS_PARAMETROS]


def get_param(param_id: str) -> Optional[Dict[str, Any]]:
    p = _INDICE.get(param_id)
    return deepcopy(p) if p is not None else None


def get_or_throw(param_id: str) -> Dict[str, Any]:
    p = _INDICE.get(param_id)
    if p is None:
        raise KeyError(
            f"Parámetro «{param_id}» no existe en el catálogo. Añádelo en registry.py antes de registrar."
        )
    return deepcopy(p)


def ids_por_categoria(categoria: str) -> List[str]:
    return [p["id"] for p in TODOS_PARAMETROS if p["categoria"] == categoria]


def listar_por_entorno(entorno: str) -> List[Dict[str, Any]]:
    return [deepcopy(p) for p in TODOS_PARAMETROS if entorno in p.get("entornos", ())]


def listar_por_sistema(sistema: str) -> List[Dict[str, Any]]:
    return [
        deepcopy(p)
        for p in TODOS_PARAMETROS
        if p.get("sistema") == sistema or p.get("sistemaVisual") == sistema
    ]


def validate_registry() -> None:
    """Verifica las invariantes del catálogo en tests y arranque del motor."""
    if len(TODOS_PARAMETROS) != len(_INDICE):
        raise ValueError("Catálogo inválido: hay IDs duplicados en registry.py.")
    for p in TODOS_PARAMETROS:
        if not str(p.get("fuenteTrazable", "")).strip():
            raise ValueError(f"Parámetro «{p['id']}» sin fuenteTrazable.")
        if not str(p.get("fuenteUmbral", "")).strip():
            raise ValueError(f"Parámetro «{p['id']}» sin fuenteUmbral.")
        if p.get("unidad") != p.get("unidadCanonica"):
            raise ValueError(f"Unidad no canónica en «{p['id']}».")
        if p.get("categoria") == "ambiental" and p.get("requiereContexto"):
            raise ValueError(
                f"Parámetro ambiental «{p['id']}» no debe requerir contexto del tripulante."
            )
        if not p.get("entornos"):
            raise ValueError(f"Parámetro «{p['id']}» sin entornos de misión.")
        if not str(p.get("sistema", "")).strip():
            raise ValueError(f"Parámetro «{p['id']}» sin sistema fisiológico.")
        rr = p.get("rangoReferencia") or {}
        r_min, r_max = rr.get("min"), rr.get("max")
        c_min, c_max = rr.get("criticoMin"), rr.get("criticoMax")
        if r_min is not None and r_max is not None and r_min > r_max:
            raise ValueError(f"Rango invertido en «{p['id']}»: min {r_min} > max {r_max}.")
        if c_min is not None and c_max is not None and c_min > c_max:
            raise ValueError(
                f"Rango crítico invertido en «{p['id']}»: {c_min} > {c_max}."
            )
