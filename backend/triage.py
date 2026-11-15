# -*- coding: utf-8 -*-
"""
backend/triage.py — Motor determinista puro de triage clínico + umbrales trazables.

Implementa la arquitectura de Back 2 (`src/lib/rules/thresholds.ts` + `triage.ts`)
y mantiene retrocompatibilidad con `evaluar_lectura_determinista`, `obtener_catalogo_parametros`
y `listar_anomalias_tripulante` usados por la app de escritorio y L.I.S.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.database import (
    baseline_prevuelo_opcional,
    get_baseline,
    get_indicador_osdr,
    get_osdr_dataset,
)
from backend.knowledge import protocolo_para, sexo_de
from backend.registry import (
    get_or_throw,
    get_param,
    list_params,
    listar_por_entorno,
    listar_por_sistema,
)
from desktop.i18n import tr

ETIQUETAS_NO_VALIDADAS = ("[SUPUESTO]", "[POR VALIDAR]")
CALIDAD_MINIMA = 0.5

_ALIAS_INDICADORES = {
    "blood_pressure": "systolic_bp",
    "body_temp": "core_temperature",
}

# Mapa conservado para compatibilidad con vistas anatómicas 3D existentes.
MESH_AND_TOOL_BY_INDICATOR: Dict[str, Dict[str, str]] = {
    "albumin": {
        "meshNodeId": "systemic_immune_radiation",
        "sistema": "inmune-radiacion",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "alkaline_phosphatase": {
        "meshNodeId": "limbs_musculoskeletal",
        "sistema": "musculoesqueletico",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "alt": {
        "meshNodeId": "abdomen_hepatic_renal",
        "sistema": "metabolico",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "ast": {
        "meshNodeId": "abdomen_hepatic_renal",
        "sistema": "metabolico",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "total_bilirubin": {
        "meshNodeId": "abdomen_hepatic_renal",
        "sistema": "metabolico",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "creatinine": {
        "meshNodeId": "abdomen_hepatic_renal",
        "sistema": "metabolico",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "egfr_african_american": {
        "meshNodeId": "abdomen_hepatic_renal",
        "sistema": "metabolico",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "egfr_non_african_american": {
        "meshNodeId": "abdomen_hepatic_renal",
        "sistema": "metabolico",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "urea_nitrogen_bun": {
        "meshNodeId": "abdomen_hepatic_renal",
        "sistema": "metabolico",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "glucose": {
        "meshNodeId": "abdomen_hepatic_renal",
        "sistema": "metabolico",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "calcium": {
        "meshNodeId": "limbs_musculoskeletal",
        "sistema": "musculoesqueletico",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "potassium": {
        "meshNodeId": "thorax_heart",
        "sistema": "cardiovascular",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "sodium": {
        "meshNodeId": "head_neuro_ocular",
        "sistema": "neuro-ocular",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "chloride": {
        "meshNodeId": "thorax_lungs",
        "sistema": "respiratorio",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "carbon_dioxide": {
        "meshNodeId": "thorax_lungs",
        "sistema": "respiratorio",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "anion_gap": {
        "meshNodeId": "thorax_lungs",
        "sistema": "respiratorio",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "total_protein": {
        "meshNodeId": "systemic_immune_radiation",
        "sistema": "inmune-radiacion",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "globulin": {
        "meshNodeId": "systemic_immune_radiation",
        "sistema": "inmune-radiacion",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "albumin_globulin_ratio": {
        "meshNodeId": "systemic_immune_radiation",
        "sistema": "inmune-radiacion",
        "toolAnimationId": "anim_capillary_analyzer",
    },
    "heart_rate": {
        "meshNodeId": "thorax_heart",
        "sistema": "cardiovascular",
        "toolAnimationId": "anim_none",
    },
    "spo2": {
        "meshNodeId": "thorax_lungs",
        "sistema": "respiratorio",
        "toolAnimationId": "anim_pulse_oximeter",
    },
    "systolic_bp": {
        "meshNodeId": "thorax_heart",
        "sistema": "cardiovascular",
        "toolAnimationId": "anim_bp_cuff",
    },
    "diastolic_bp": {
        "meshNodeId": "thorax_heart",
        "sistema": "cardiovascular",
        "toolAnimationId": "anim_bp_cuff",
    },
    "respiratory_rate": {
        "meshNodeId": "thorax_lungs",
        "sistema": "respiratorio",
        "toolAnimationId": "anim_none",
    },
    "core_temperature": {
        "meshNodeId": "systemic_immune_radiation",
        "sistema": "inmune-radiacion",
        "toolAnimationId": "anim_none",
    },
    "intracranial_pressure_est": {
        "meshNodeId": "head_neuro_ocular",
        "sistema": "neuro-ocular",
        "toolAnimationId": "anim_ocular_fundoscope",
    },
    "cabin_co2": {
        "meshNodeId": "thorax_lungs",
        "sistema": "respiratorio",
        "toolAnimationId": "anim_none",
    },
    "radiation_dose": {
        "meshNodeId": "systemic_immune_radiation",
        "sistema": "inmune-radiacion",
        "toolAnimationId": "anim_none",
    },
}


def es_fuente_validada(fuente: str) -> bool:
    return not any(tag in fuente for tag in ETIQUETAS_NO_VALIDADAS)


def obtener_umbrales(param_id: str, sexo: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Resuelve los umbrales efectivos (y sexo-específicos si aplican) desde registry.py."""
    canonical = _ALIAS_INDICADORES.get(param_id, param_id)
    definicion = get_param(canonical)
    if definicion is None:
        return None

    rango_base = definicion.get("rangoReferencia") or {}
    rango_sexo = (definicion.get("rangoReferenciaPorSexo") or {}).get(sexo) if sexo else None
    usa_sexo = rango_sexo is not None
    rango = rango_sexo if usa_sexo else rango_base

    fuente_umbral = definicion["fuenteUmbral"]
    fuente = (
        f"{fuente_umbral} · rango sexo-específico [POR VALIDAR]"
        if usa_sexo
        else fuente_umbral
    )
    return {
        "paramId": definicion["id"],
        "min": rango.get("min"),
        "max": rango.get("max"),
        "criticoMin": rango.get("criticoMin"),
        "criticoMax": rango.get("criticoMax"),
        "referenciaPoblacional": (
            {"min": rango.get("min"), "max": rango.get("max")}
            if usa_sexo
            else dict(definicion.get("referenciaPoblacional") or {})
        ),
        "fuente": fuente,
        "fuenteValidada": es_fuente_validada(fuente),
    }


def obtener_umbrales_or_throw(param_id: str, sexo: Optional[str] = None) -> Dict[str, Any]:
    u = obtener_umbrales(param_id, sexo=sexo)
    if u is None:
        raise KeyError(
            f"Parámetro «{param_id}» no existe en el catálogo. Añádelo en registry.py antes de registrar."
        )
    return u


def validar_umbrales() -> List[str]:
    errores: List[str] = []
    for definicion in list_params():
        u = obtener_umbrales(definicion["id"])
        if not u:
            continue
        r_min, r_max = u["min"], u["max"]
        c_min, c_max = u["criticoMin"], u["criticoMax"]
        if r_min is not None and r_max is not None and r_min > r_max:
            errores.append(f"{definicion['id']}: rango de referencia invertido ({r_min} > {r_max})")
        if c_min is not None and c_max is not None and c_min > c_max:
            errores.append(f"{definicion['id']}: rango crítico invertido ({c_min} > {c_max})")
        if not str(u.get("fuente", "")).strip():
            errores.append(f"{definicion['id']}: umbral sin fuente trazable")
    return errores


def obtener_catalogo_parametros(
    entorno: Optional[str] = None, sistema: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Devuelve el catálogo Plug & Play (26 parámetros), filtrable por entorno o sistema."""
    if entorno and entorno in ("nave", "estacion", "base-lunar"):
        base = listar_por_entorno(entorno)
    else:
        base = list_params()

    if sistema:
        base = [
            p
            for p in base
            if p.get("sistema") == sistema or p.get("sistemaVisual") == sistema
        ]
    return base


# Guías breves, no farmacológicas y verificadas para revertir cuadros leves/amarillos en 0G
_INDICACIONES_MEJORA_ATENCION: Dict[str, Any] = {
    "heart_rate": {
        "ATENCION_ALTO": "Descansa unos minutos anclado en reposo, respira lento y profundo, hidrátate y repite la lectura para confirmar si vuelve a tu base.",
        "ATENCION_BAJO": "Siéntate o ánclate en calma, verifica el contacto del sensor o banda y repite la medición en reposo antes de realizar esfuerzo.",
        "default": "Descansa unos minutos en calma, hidrátate y repite la lectura del pulso en reposo.",
    },
    "systolic_bp": {
        "ATENCION_ALTO": "Permanece en reposo sentado unos minutos, realiza respiración pausada, evita esfuerzo inmediato y repite la toma con el manguito a nivel del corazón.",
        "ATENCION_BAJO": "Ancla el cuerpo en posición estable, hidrátate poco a poco, evita desplazamientos bruscos y repite la toma con el manguito bien ajustado.",
        "default": "Permanece en calma unos minutos, hidrátate y repite la lectura con el manguito a la altura del corazón.",
    },
    "diastolic_bp": {
        "ATENCION_ALTO": "Descansa en quietud con respiración lenta y sostenida, evita esfuerzo físico temporalmente y repite la toma con el manguito a la altura del corazón.",
        "ATENCION_BAJO": "Ancla tu postura con estabilidad, hidrátate progresivamente, evita movimientos bruscos y repite la medición.",
        "default": "Reposa unos minutos en calma, cuida tu hidratación y repite la toma con el manguito bien colocado.",
    },
    "spo2": "Toma respiraciones lentas y profundas, calienta los dedos y reajusta el oxímetro sin apretar en exceso, verifica la ventilación del módulo y repite en reposo.",
    "respiratory_rate": {
        "ATENCION_ALTO": "Haz una pausa en reposo con respiraciones lentas y regulares, comprueba la ventilación del módulo y vuelve a medir tras unos minutos de calma.",
        "ATENCION_BAJO": "Ponte cómodo en una zona bien ventilada, mantente despierto y en calma y repite la medición para confirmar tu patrón respiratorio.",
        "default": "Haz una pausa en reposo, respira de forma lenta y regular, verifica la circulación de aire y repite la medición.",
    },
    "cabin_co2": "Trasládate temporalmente a un módulo con mejor flujo de aire, verifica ventiladores y depuradores de cabina, mantente en reposo y vigila si cede la molestia.",
    "carbon_dioxide": "Descansa en un módulo bien ventilado, cuida tu hidratación, comprueba el flujo de aire en cabina y repite el análisis discreto en reposo.",
    "chloride": "Hidrátate de forma regular según tu pauta de misión, reposa brevemente y repite la muestra capilar limpia en cero gravedad.",
    "anion_gap": "Prioriza descanso, hidratación progresiva y buena ventilación en el módulo; repite el panel discreto para confirmar si se estabiliza.",
    "glucose": {
        "ATENCION_BAJO": "Repite primero la prueba capilar en cero gravedad a noventa grados verificando que no haya burbujas en la tira; si se confirma, ingiere un alimento de tu ración programada y vuelve a medir.",
        "ATENCION_ALTO": "Hidrátate con agua, descansa brevemente, confirma la lectura capilar en cero gravedad con el dedo limpio y registra tu última ingesta.",
        "default": "Confirma la lectura capilar en cero gravedad a noventa grados sin burbujas de aire y relaciónala con tu última ración.",
    },
    "creatinine": "Refuerza tu hidratación con líquidos programados, revisa la escala visual de color de orina y tu carga reciente de ejercicio o caminata espacial, y repite la lectura.",
    "urea_nitrogen_bun": "Aumenta la ingesta hídrica programada, descansa tras actividad intensa y vuelve a medir para comprobar hidratación y recuperación.",
    "egfr_african_american": "Cuida la hidratación gradual con agua, modera esfuerzo físico extenuante temporalmente y repite el panel discreto.",
    "egfr_non_african_american": "Cuida la hidratación gradual con agua, modera esfuerzo físico extenuante temporalmente y repite el panel discreto.",
    "sodium": "Equilibra tu hidratación y ración de electrolitos según el plan de misión, descansa brevemente y repite la lectura capilar limpia.",
    "potassium": "Cuida la hidratación con electrolitos conforme a tu plan nutricional, evita esfuerzo intenso mientras vigilas tu pulso y repite la tira sin burbujas.",
    "calcium": "Mantén al día tus rutinas programadas de ejercicio resistivo y nutrición de misión, hidrátate bien y repite la muestra capilar en reposo.",
    "alkaline_phosphatase": "Sostén tus contramedidas de ejercicio de resistencia y aeróbico a bordo, cuida hidratación y descanso y da seguimiento en tu próximo control.",
    "ast": "Prioriza reposo, hidratación y alimentación regular; reduce temporalmente la carga física intensa y repite el panel discreto.",
    "alt": "Prioriza reposo, buena hidratación y nutrición equilibrada; evita sobrecarga física temporalmente y repite el análisis discreto.",
    "total_bilirubin": "Cuida tu descanso e hidratación, evita ayunos prolongados o esfuerzo intenso y repite la muestra en condiciones estables.",
    "albumin": "Mantén hidratación y aporte nutricional adecuados junto con descanso regular y repite la lectura para verificar estabilidad.",
    "total_protein": "Refuerza tu hidratación y nutrición programada y repite la toma en reposo para descartar concentración leve por fluidos en microgravedad.",
    "globulin": "Prioriza descanso suficiente, higiene en cabina e hidratación regular; registra cualquier síntoma leve y repite seguimiento.",
    "albumin_globulin_ratio": "Cuida tu descanso, nutrición equilibrada e hidratación progresiva y realiza seguimiento en la siguiente lectura.",
    "core_temperature": {
        "ATENCION_ALTO": "Reposa en un área fresca y ventilada, hidrátate con agua, aligera una capa de ropa si es seguro y repite la toma térmica.",
        "ATENCION_BAJO": "Resguárdate de corrientes frías, añade una capa térmica en reposo y repite la medición para confirmar recuperación.",
        "default": "Ajusta confort térmico e hidratación en calma y repite la medición tras unos minutos.",
    },
    "intracranial_pressure_est": "Reduce fatiga visual, descansa en un espacio tranquilo y con luz suave, asegúrate de buena ventilación y anota cualquier molestia visual para el médico.",
    "radiation_dose": "Si es posible, traslada tareas no urgentes hacia una zona más blindada o con estantes de agua, registra el tiempo de exposición y sigue el monitoreo.",
    "hemoglobin": "Cuida hidratación, descanso y nutrición de misión; repite la lectura capilar en calma para descartar desplazamiento de fluidos en cero gravedad.",
    "hematocrit": "Hidrátate de forma constante para compensar redistribución de fluidos en microgravedad, descansa y repite la toma en reposo.",
    "wbc": "Prioriza descanso, sueño en rutina regular e higiene personal y de superficies en cabina; registra síntomas leves y da seguimiento.",
    "platelets": "Evita impactos o esfuerzo extenuante innecesario, mantén descanso e hidratación adecuados y repite el panel discreto en control.",
}
_INDICACION_MEJORA_GENERAL = (
    "Descansa unos minutos en calma, hidrátate bien, revisa la colocación del sensor o tira en cero gravedad "
    "y repite la medición; avisa al Oficial Médico (CMO) si la tendencia continúa."
)


def indicacion_mejora_para(param_id: str, regla: str = "", nivel: str = "ATENCION") -> str:
    """Devuelve indicación preventiva calmada y no prescriptiva para mejorar un parámetro."""
    canonical = _ALIAS_INDICADORES.get(param_id, param_id)
    entrada = _INDICACIONES_MEJORA_ATENCION.get(canonical)
    if isinstance(entrada, dict):
        texto = entrada.get(regla) or entrada.get("default") or _INDICACION_MEJORA_GENERAL
    elif isinstance(entrada, str):
        texto = entrada
    else:
        texto = _INDICACION_MEJORA_GENERAL
    return tr(texto)


def _accion_para(nivel: str, regla: str, param_id: str = "") -> str:
    if regla == "SIN_UMBRAL":
        return tr(
            "Sin umbral de referencia validado: registrar la lectura y marcarla para validación clínica."
        )
    if nivel == "CRITICO":
        return tr(
            "Notificar al Oficial Médico de Tripulación (CMO) y activar el protocolo de emergencia correspondiente."
        )
    if nivel == "ATENCION":
        return indicacion_mejora_para(param_id, regla, nivel)
    return tr("Mantener la rutina de monitoreo programada.")


def _formatear_rango(r_min: Optional[float], r_max: Optional[float]) -> str:
    a = f"{r_min}" if r_min is not None else "–"
    b = f"{r_max}" if r_max is not None else "–"
    return f"{a}–{b}"


def evaluar(
    param_id: str,
    valor: float,
    baseline: Optional[float],
    entorno: Optional[str] = None,
    calidad: Optional[float] = None,
    sexo: Optional[str] = None,
) -> Dict[str, Any]:
    """Motor determinista puro de triage (port exacto de Back 2 `rules/triage.ts`)."""
    canonical = _ALIAS_INDICADORES.get(param_id, param_id)
    definicion = get_or_throw(canonical)
    umbrales = obtener_umbrales_or_throw(canonical, sexo=sexo)

    r_min: Optional[float] = umbrales["min"]
    r_max: Optional[float] = umbrales["max"]
    c_min: Optional[float] = umbrales["criticoMin"]
    c_max: Optional[float] = umbrales["criticoMax"]
    fuente: str = umbrales["fuente"]
    fuente_validada: bool = umbrales["fuenteValidada"]
    unidad: str = definicion["unidad"]

    tiene_umbral = any(x is not None for x in (r_min, r_max, c_min, c_max))

    nivel = "NOMINAL"
    regla = "NOMINAL"
    if c_min is not None and valor <= c_min:
        nivel = "CRITICO"
        regla = "CRITICO_BAJO"
    elif c_max is not None and valor >= c_max:
        nivel = "CRITICO"
        regla = "CRITICO_ALTO"
    elif r_min is not None and valor < r_min:
        nivel = "ATENCION"
        regla = "ATENCION_BAJO"
    elif r_max is not None and valor > r_max:
        nivel = "ATENCION"
        regla = "ATENCION_ALTO"
    elif not tiene_umbral:
        regla = "SIN_UMBRAL"

    senal_baja = calidad is not None and calidad < CALIDAD_MINIMA
    degradado = (not fuente_validada) or (baseline is None) or senal_baja

    if senal_baja and nivel == "CRITICO":
        nivel = "ATENCION"
        regla = "ATENCION_BAJO" if regla == "CRITICO_BAJO" else "ATENCION_ALTO"

    tipo_desv = definicion["tipoDesviacion"]
    if baseline is None:
        desviacion_valor = 0.0
    elif tipo_desv == "delta-absoluto":
        desviacion_valor = round(float(valor) - float(baseline), 1)
    else:
        desviacion_valor = (
            round(((float(valor) - float(baseline)) / float(baseline)) * 100.0, 1)
            if baseline != 0
            else 0.0
        )

    rango_txt = _formatear_rango(r_min, r_max)
    if regla == "CRITICO_BAJO":
        razon = tr(
            "{v} {u} rebasa el umbral crítico inferior ({c} {u}) con rango de referencia {r} {u}.",
            v=valor,
            u=unidad,
            c=c_min,
            r=rango_txt,
        )
    elif regla == "CRITICO_ALTO":
        razon = tr(
            "{v} {u} rebasa el umbral crítico superior ({c} {u}) con rango de referencia {r} {u}.",
            v=valor,
            u=unidad,
            c=c_max,
            r=rango_txt,
        )
    elif regla == "ATENCION_BAJO":
        razon = tr(
            "{v} {u} está por debajo del límite inferior de referencia ({m} {u}).",
            v=valor,
            u=unidad,
            m=r_min,
        )
    elif regla == "ATENCION_ALTO":
        razon = tr(
            "{v} {u} está por encima del límite superior de referencia ({m} {u}).",
            v=valor,
            u=unidad,
            m=r_max,
        )
    elif regla == "SIN_UMBRAL":
        razon = tr(
            "No hay rango de referencia para «{p}»: lectura registrada sin evaluación de nivel.",
            p=canonical,
        )
    else:
        razon = tr(
            "{v} {u} dentro del rango de referencia ({r} {u}).",
            v=valor,
            u=unidad,
            r=rango_txt,
        )

    if baseline is None:
        razon += " " + tr(
            "Línea base personal no disponible: evaluación degradada a referencia poblacional."
        )
    if senal_baja:
        razon += " " + tr("Calidad de señal insuficiente: repetir la medición.")

    return {
        "nivel": nivel,
        "razon": razon,
        "accion": _accion_para(nivel, regla, canonical),
        "fuente": fuente,
        "reglaDisparada": regla,
        "valor": valor,
        "baseline": baseline,
        "desviacion": {"tipo": tipo_desv, "valor": desviacion_valor},
        "degradado": degradado,
    }


def evaluar_lectura_determinista(
    crew_id: str,
    indicador_id: str,
    valor: float,
    calidad: Optional[float] = None,
    entorno: Optional[str] = None,
    sexo: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluación completa compatible con la UI de escritorio, L.I.S. y StreamEngine."""
    canonical = _ALIAS_INDICADORES.get(indicador_id, indicador_id)
    definicion = get_param(canonical)
    if definicion is None:
        return {
            "indicadorId": indicador_id,
            "nombre": tr(indicador_id),
            "valor": valor,
            "unidad": "",
            "nivel": "NOMINAL",
            "mediaPreVuelo": 0.0,
            "desvioPorcentajeBaseline": 0.0,
            "zScorePersonal": 0.0,
            "fueraRangoReferencia": False,
            "rangoReferencia": {"min": None, "max": None},
            "mensaje": tr("Parámetro dentro de límites operativos."),
            "accionSugerida": tr("Continuar monitoreo rutinario."),
            "meshNodeId": "abdomen_hepatic_renal",
            "sistema": "metabolico",
            "toolAnimationId": "anim_none",
            "reglaDisparada": "NOMINAL",
            "degradado": True,
            "fuente": "[POR VALIDAR]",
            "protocoloSugerido": None,
        }

    sexo_eff = sexo if sexo in ("M", "F") else sexo_de(crew_id)
    baseline_val = baseline_prevuelo_opcional(crew_id, canonical)
    baseline_info = get_baseline(crew_id, canonical)
    sd_pre = float(baseline_info.get("desviacionPreVuelo", 0.0))

    ev = evaluar(
        canonical,
        float(valor),
        baseline_val,
        entorno=entorno,
        calidad=calidad,
        sexo=sexo_eff,
    )
    umbrales = obtener_umbrales_or_throw(canonical, sexo=sexo_eff)
    r_min, r_max = umbrales["min"], umbrales["max"]
    fuera = (r_min is not None and valor < r_min) or (r_max is not None and valor > r_max)

    media_pre = float(baseline_val) if baseline_val is not None else 0.0
    desvio_pct = (
        round(((float(valor) - media_pre) / media_pre) * 100.0, 1)
        if media_pre > 0
        else 0.0
    )
    z_score = (
        round((float(valor) - media_pre) / sd_pre, 2)
        if media_pre > 0 and sd_pre > 0.05
        else (
            round((float(valor) - media_pre) / max(media_pre * 0.05, 0.1), 2)
            if media_pre > 0
            else 0.0
        )
    )

    meta_3d = MESH_AND_TOOL_BY_INDICATOR.get(
        canonical,
        {
            "meshNodeId": definicion.get("meshNodeId") or "abdomen_hepatic_renal",
            "sistema": definicion.get("sistemaVisual", "metabolico"),
            "toolAnimationId": definicion.get("toolAnimationId", "anim_none"),
        },
    )
    proto = protocolo_para(canonical, ev["nivel"])

    return {
        "indicadorId": canonical,
        "nombre": tr(definicion["nombre"]),
        "valor": float(valor),
        "unidad": definicion["unidad"],
        "nivel": ev["nivel"],
        "mediaPreVuelo": media_pre,
        "desvioPorcentajeBaseline": desvio_pct,
        "zScorePersonal": z_score,
        "fueraRangoReferencia": fuera,
        "rangoReferencia": {"min": r_min, "max": r_max},
        "criticoMin": umbrales["criticoMin"],
        "criticoMax": umbrales["criticoMax"],
        "mensaje": ev["razon"],
        "razon": ev["razon"],
        "accionSugerida": ev["accion"],
        "accion": ev["accion"],
        "meshNodeId": meta_3d["meshNodeId"],
        "sistema": meta_3d["sistema"],
        "sistemaClinico": definicion["sistema"],
        "toolAnimationId": meta_3d["toolAnimationId"],
        "reglaDisparada": ev["reglaDisparada"],
        "fuente": ev["fuente"],
        "degradado": ev["degradado"],
        "desviacion": ev["desviacion"],
        "esDatoRealOSDR": bool(definicion.get("esDatoRealOSDR")),
        "calidad": calidad if calidad is not None else 1.0,
        "protocoloSugerido": proto,
    }


def listar_anomalias_tripulante(
    crew_id: str, timepoint: Optional[str] = None
) -> List[Dict[str, Any]]:
    dataset = get_osdr_dataset()
    anomalias: List[Dict[str, Any]] = []
    sexo_eff = sexo_de(crew_id)
    for ind in dataset.get("indicadores", []):
        ind_id = ind["id"]
        umbrales = obtener_umbrales(ind_id, sexo=sexo_eff) or {}
        r_min = umbrales.get("min")
        r_max = umbrales.get("max")
        puntos = ind.get("serie", {}).get(crew_id, [])
        for pt in puntos:
            tp = pt.get("timepoint")
            if timepoint and tp != timepoint:
                continue
            if pt.get("valor") is None:
                continue
            val = float(pt["valor"])
            if (r_min is not None and val < r_min) or (
                r_max is not None and val > r_max
            ):
                eval_res = evaluar_lectura_determinista(crew_id, ind_id, val, sexo=sexo_eff)
                eval_res["timepoint"] = tp
                anomalias.append(eval_res)
    return anomalias


def evaluar_salud_mental_determinista(
    horas_sueno: float,
    pvt_latencia_ms: float = 0.0,
    pvt_lapsus: int = 0,
    estres_score: int = 3,
    aislamiento_score: int = 3,
) -> Dict[str, Any]:
    """
    Evaluación determinista de bienestar emocional, vigilancia y rendimiento
    conforme al marco NASA HRP Behavioral Health and Performance (BHP) [POR VALIDAR].
    Devuelve nivel (verde, amarillo, rojo), estado operativo y protocolo de acción.
    """
    es_rojo = (
        (pvt_latencia_ms > 450.0)
        or pvt_lapsus >= 3
        or horas_sueno < 5.0
        or estres_score >= 8
    )

    if es_rojo:
        razones = []
        if pvt_latencia_ms > 450.0:
            razones.append(
                tr("Latencia psicomotora crítica ({ms} ms > 450 ms)", ms=int(pvt_latencia_ms))
            )
        if pvt_lapsus >= 3:
            razones.append(tr("{n} lapsus de atención > 500 ms", n=int(pvt_lapsus)))
        if horas_sueno < 5.0:
            razones.append(tr("Privación severa de sueño ({h:.1f}h < 5.0h)", h=horas_sueno))
        if estres_score >= 8:
            razones.append(tr("Sobrecarga de estrés agudo ({s}/10)", s=int(estres_score)))

        return {
            "nivel": "rojo",
            "aptoOperacionesCriticas": False,
            "titulo": tr("Restricción operativa · Fatiga severa"),
            "razon": "; ".join(razones),
            "accion": tr(
                "Suspender EVA, pilotaje manual y atraque [POR VALIDAR]. Notificar al Oficial Médico (CMO) y aplicar protocolo de descanso protegido."
            ),
            "protocoloId": "NASA-BHP-FATIGUE-RED",
            "fuente": "NASA HRP BHP Flight Rules & PVT-B [POR VALIDAR]",
        }

    es_amarillo = (
        (pvt_latencia_ms >= 355.0)
        or pvt_lapsus in (1, 2)
        or horas_sueno < 6.5
        or estres_score >= 6
        or aislamiento_score >= 7
    )

    if es_amarillo:
        razones = []
        if pvt_latencia_ms >= 355.0:
            razones.append(tr("Latencia psicomotora elevada ({ms} ms)", ms=int(pvt_latencia_ms)))
        if pvt_lapsus in (1, 2):
            razones.append(tr("{n} lapsus de atención", n=int(pvt_lapsus)))
        if horas_sueno < 6.5:
            razones.append(tr("Descanso por debajo de línea base ({h:.1f}h < 6.5h)", h=horas_sueno))
        if estres_score >= 6:
            razones.append(tr("Tensión percibida moderada ({s}/10)", s=int(estres_score)))
        if aislamiento_score >= 7:
            razones.append(tr("Desconexión o aislamiento ({s}/10)", s=int(aislamiento_score)))

        return {
            "nivel": "amarillo",
            "aptoOperacionesCriticas": False,
            "titulo": tr("Alerta de fatiga · Precaución operativa"),
            "razon": "; ".join(razones),
            "accion": tr(
                "Tareas nominales bajo verificación cruzada [POR VALIDAR]. Evitar EVA en solitario; hacer respiración 4-4-4-4 y descanso corto."
            ),
            "protocoloId": "NASA-BHP-FATIGUE-YELLOW",
            "fuente": "NASA HRP BHP Flight Rules & PVT-B [POR VALIDAR]",
        }

    if pvt_latencia_ms > 0:
        razon_verde = tr(
            "Vigilancia psicomotora en margen esperado ({ms} ms, 0 lapsus), descanso de {h:.1f} h y estrés contenido ({s}/10).",
            ms=int(pvt_latencia_ms),
            h=horas_sueno,
            s=int(estres_score),
        )
    else:
        razon_verde = tr(
            "Descanso de {h:.1f} h y niveles de estrés contenidos ({s}/10).",
            h=horas_sueno,
            s=int(estres_score),
        )

    return {
        "nivel": "verde",
        "aptoOperacionesCriticas": True,
        "titulo": tr("Apto para operaciones críticas"),
        "razon": razon_verde,
        "accion": tr("Continuar el plan nominal de vuelo y sostener las rutinas diarias de bienestar."),
        "protocoloId": "NASA-BHP-NOMINAL",
        "fuente": "NASA HRP BHP Flight Rules & PVT-B [POR VALIDAR]",
    }
