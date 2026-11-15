# -*- coding: utf-8 -*-
"""
desktop/views.py — Vistas nativas en PySide6 de V.I.T.A.L.I.S., pensadas para
pantalla TÁCTIL y para leerse a un brazo de distancia:
  1. VistaInicio      -> Estado general, 4 signos vitales, modelo 3D y el analito en foco
  2. VistaCuerpo3D    -> Los 6 sistemas, el modelo 3D y los analitos del sistema elegido
  3. VistaMedicion    -> Pasos de la toma en 0G + teclado numérico en pantalla
  4. VistaHistorial   -> Analitos OSD-575 con su estado y la tendencia del que se toca
  5. VistaEmergencia  -> Protocolos, metrónomo RCP, animación ALSP y alerta SBAR
  6. VistaAjustes     -> TODAS las opciones en un solo sitio (tripulante, pantalla,
                         asistente L.I.S., motor de IA, memoria y créditos)

Criterio de limpieza: cada pantalla enseña sólo lo que el astronauta necesita
para decidir. Lo que es configuración vive en Ajustes; lo que es detalle se ve
al tocar, no de entrada.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QProcess, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.crew_hub import get_crew_hub
from backend.database import (
    actualizar_alias_astronauta,
    crear_solicitud_ayuda,
    get_baseline,
    get_cabina_dataset,
    get_guias_dataset,
    get_indicador_osdr,
    get_osdr_dataset,
    get_protocolos_dataset,
    get_valor_osdr,
    guardar_medicion_local,
    guardar_medicion_sensor,
    limpiar_historial_chat,
    limpiar_memoria_astronauta,
    listar_mediciones_locales,
    listar_series,
    obtener_memoria_astronauta,
    recordar_dato_astronauta,
    sexo_de,
    ventana_reciente,
)
from backend.knowledge import listar_protocolos_disp, protocolo_para
from backend.lis_agent import (
    detectar_mejor_modelo_cloud,
    estado_ollama,
    estado_voz_jarvis,
    resolver_voz_neural_por_idioma,
)
from datetime import datetime
from backend.registry import get_param
from backend.runtime import get_runtime
from backend.sync_tierra import get_sync_manager
from backend.telemetry import generar_frame_telemetria
from backend.triage import (
    evaluar_lectura_determinista,
    listar_anomalias_tripulante,
    obtener_catalogo_parametros,
)
from desktop import theme as t
from desktop.alsp_anim import WidgetAnimacionALSP
from desktop.estado_actual import (
    avisos_actuales as _avisos_actuales,
    etiqueta_momento as _etiqueta_momento,
    nivel_maximo as _nivel_maximo,
    nivel_por_sistema as _nivel_por_sistema,
    nombre_corto as _nombre_corto,
)
from desktop.i18n import tr
from desktop import i18n
from desktop.paneles_bd import formatear_iso, formatear_ts_ms
from desktop.state import CREW_IDS, SISTEMAS, TIMEPOINTS, AppState
from desktop.voice_engine import MotorVozNativo
from desktop.widgets import (
    FilaCabinaMonitor,
    FilaIndicador,
    GraficaTendencia,
    GrupoChips,
    Interruptor,
    Tarjeta,
    TecladoNumerico,
    boton,
    divisor,
    estilo_pastilla,
    etiqueta,
    etiqueta_mono,
    scroll_tactil,
    vaciar_layout,
)

SISTEMAS_DETALLE: Dict[str, Dict[str, Any]] = {
    "neuro-ocular": {
        "titulo": "Neuro-ocular (SANS)",
        "analitos": ["sodium", "potassium", "carbon_dioxide"],
        "principal": "sodium",
    },
    "cardiovascular": {
        "titulo": "Cardiovascular",
        "analitos": ["potassium", "sodium", "calcium"],
        "principal": "potassium",
    },
    "respiratorio": {
        "titulo": "Respiratorio",
        "analitos": ["carbon_dioxide", "chloride", "total_protein"],
        "principal": "carbon_dioxide",
    },
    "metabolico": {
        "titulo": "Metabólico y renal",
        "analitos": ["glucose", "ast", "alt", "creatinine", "urea_nitrogen_bun"],
        "principal": "glucose",
    },
    "musculoesqueletico": {
        "titulo": "Musculoesquelético",
        "analitos": ["calcium", "alkaline_phosphatase", "albumin"],
        "principal": "calcium",
    },
    "inmune-radiacion": {
        "titulo": "Inmune y radiación",
        "analitos": [
            "albumin",
            "globulin",
            "albumin_to_globulin_ratio",
            "total_bilirubin",
        ],
        "principal": "albumin",
    },
}

def nivel_triage(nivel: str) -> Tuple[str, str]:
    """(texto, color) del nivel, desde la única fuente: theme.py."""
    return t.texto_triage(nivel), t.color_triage(nivel)


# ---------------------------------------------------------------------------
# Utilidades de presentación
# ---------------------------------------------------------------------------

def nombre_corto(nombre: str) -> str:
    """Nombre corto del analito (vive en estado_actual para evitar ciclos)."""
    return _nombre_corto(nombre)


_DECIMALES_PARAM: Dict[str, int] = {
    "heart_rate": 0,
    "systolic_bp": 0,
    "diastolic_bp": 0,
    "spo2": 0,
    "respiratory_rate": 0,
    "glucose": 0,
    "sodium": 0,
    "alt": 0,
    "ast": 0,
    "alkaline_phosphatase": 0,
    "chloride": 0,
    "urea_nitrogen_bun": 0,
    "egfr_african_american": 0,
    "egfr_non_african_american": 0,
    "core_temperature": 1,
    "intracranial_pressure_est": 1,
    "potassium": 1,
    "calcium": 1,
    "carbon_dioxide": 1,
    "albumin": 1,
    "globulin": 1,
    "total_protein": 1,
    "albumin_to_globulin_ratio": 1,
    "creatinine": 2,
    "total_bilirubin": 2,
    "cabin_co2": 2,
    "radiation_dose": 2,
}


def _formatear_valor_clinico(param_id: str, valor: Any) -> str:
    """Formatea lecturas numéricas a precisión clínica legible sin ruido decimal."""
    if not isinstance(valor, (int, float)):
        return "–"
    num = float(valor)
    dec = _DECIMALES_PARAM.get(param_id)
    if dec is None:
        return f"{num:.0f}" if abs(num) >= 100 else f"{num:.1f}"
    if dec == 0:
        return str(round(num))
    return f"{num:.{dec}f}"


def _fmt_limite(val: Any) -> str:
    num = float(val)
    if num.is_integer():
        return str(int(num))
    return f"{num:g}"


def _texto_ref_corto(param: Optional[Dict[str, Any]], ind: Optional[Dict[str, Any]], sexo: Optional[str]) -> str:
    """Etiqueta breve del rango de referencia para mostrar junto al valor."""
    rango = None
    if param:
        rango = (param.get("rangoReferenciaPorSexo") or {}).get(sexo or "") or param.get("rangoReferencia")
    if not rango and ind:
        rango = ind.get("rangoReferencia")
    rango = rango or {}
    r_min, r_max = rango.get("min"), rango.get("max")
    if r_min is not None and r_max is not None:
        return tr("Ref. {a}–{b}", a=_fmt_limite(r_min), b=_fmt_limite(r_max))
    if r_min is not None:
        return tr("Ref. ≥ {a}", a=_fmt_limite(r_min))
    if r_max is not None:
        return tr("Ref. ≤ {b}", b=_fmt_limite(r_max))
    return ""


def estado_valor(valor: Any, rango: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """Estado del valor frente al rango de referencia del propio dataset OSD-575."""
    if not isinstance(valor, (int, float)):
        return "Sin dato", t.TERCIARIO
    rango = rango or {}
    r_min, r_max = rango.get("min"), rango.get("max")
    if r_min is not None and valor < r_min:
        return "Bajo", t.ATENCION
    if r_max is not None and valor > r_max:
        return "Alto", t.ATENCION
    return "Normal", t.NORMAL


def estado_triage(crew: str, ind_id: str, valor: Any, rango: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """Como estado_valor, pero el color sigue el nivel del triage: un valor
    crítico se ve en rojo, no en el mismo ámbar que una desviación leve."""
    texto, color = estado_valor(valor, rango)
    if texto in ("Alto", "Bajo"):
        nivel = evaluar_lectura_determinista(crew, ind_id, float(valor))["nivel"]
        _, color = nivel_triage(nivel)
        if nivel == "CRITICO":
            # El texto lleva el nivel: «Bajo · Crítico» no se confunde con una desviación leve.
            texto = f"{tr(texto)} · {tr(t.texto_triage(nivel))}"
    return texto, color


def pastilla(texto: str, color: str) -> QLabel:
    """Etiqueta de estado con fondo tenue del mismo color."""
    lbl = QLabel(tr(texto))
    estilo_pastilla(lbl, color)
    return lbl


def area_desplazable(contenido: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(contenido)
    scroll_tactil(scroll)
    return scroll


def partir_en_dos(texto: str, ancho: int = 26) -> str:
    """Parte un título largo en dos líneas por el espacio más cercano a la mitad."""
    if len(texto) <= ancho:
        return texto
    mitad = len(texto) // 2
    espacios = [i for i, ch in enumerate(texto) if ch == " "]
    if not espacios:
        return texto
    corte = min(espacios, key=lambda i: abs(i - mitad))
    return texto[:corte] + "\n" + texto[corte + 1:]


# ===========================================================================
# 1. VISTA INICIO
# ===========================================================================

class VistaInicio(QWidget):
    def __init__(self, state: AppState, motor_voz: Optional[MotorVozNativo] = None) -> None:
        super().__init__()
        self.state = state
        self.motor_voz = motor_voz
        self._analito_foco = "glucose"
        self._bpm_vivo: float = 64.0
        self._spo2_vivo: float = 98.0
        self._rr_vivo: float = 15.0
        self._nivel_fc_vivo: str = "NOMINAL"
        self._fase_cardiaca: float = 0.0
        self._ultimo_anim_ts: float = time.monotonic()
        self._reloj_monitor_s: float = 0.0
        self._ultimo_latido_audio_s: float = -10.0
        self._crew_historial_cargado: str = ""

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(28)

        # --- Izquierda: estado y 4 signos vitales interactivos ---
        col_izq = QVBoxLayout()
        col_izq.setSpacing(4)
        self.lbl_estado = QLabel(tr("Parámetros en equilibrio"))
        self.lbl_estado.setObjectName("titulo")
        self.lbl_estado.setWordWrap(True)
        self.lbl_sub = etiqueta("Comparado con tu línea base pre-vuelo", t.T_PEQUENO, t.SECUNDARIO)
        col_izq.addWidget(self.lbl_estado)
        col_izq.addWidget(self.lbl_sub)
        col_izq.addSpacing(10)
        col_izq.addWidget(divisor())

        self.ind_fc = FilaIndicador(
            "Frecuencia cardíaca",
            "lpm",
            modo_monitor="ecg",
            rango_min=50.0,
            rango_max=100.0,
            al_pulsar=lambda: self.state.ir_a("historial", paramId="heart_rate", modo="vivo"),
        )
        self.ind_spo2 = FilaIndicador(
            "Oxígeno en sangre",
            "%",
            modo_monitor="pleth",
            rango_min=95.0,
            rango_max=100.0,
            al_pulsar=lambda: self.state.ir_a("historial", paramId="spo2", modo="vivo"),
        )
        self.ind_pa = FilaIndicador(
            "Presión arterial",
            "mmHg",
            modo_monitor="arterial",
            rango_min=90.0,
            rango_max=135.0,
            al_pulsar=lambda: self.state.ir_a("historial", paramId="systolic_bp", modo="vivo"),
        )
        self.ind_temp = FilaIndicador(
            "Temperatura",
            "°C",
            modo_monitor="tendencia",
            rango_min=36.1,
            rango_max=37.2,
            al_pulsar=lambda: self.state.ir_a("historial", paramId="core_temperature", modo="vivo"),
        )
        self._monitores_izq = (self.ind_fc, self.ind_spo2, self.ind_pa, self.ind_temp)
        for fila in self._monitores_izq:
            fila.setToolTip(tr("Tocar para ver historial"))
            col_izq.addWidget(fila)
            col_izq.addWidget(divisor())
        col_izq.addStretch(1)

        w_izq = QWidget()
        w_izq.setLayout(col_izq)
        w_izq.setFixedWidth(340)
        raiz.addWidget(w_izq)

        # --- Centro: visor anatómico 3D compartido ---
        self.contenedor_3d = QVBoxLayout()
        self.contenedor_3d.setContentsMargins(0, 0, 0, 0)
        w_centro = QWidget()
        w_centro.setLayout(self.contenedor_3d)
        raiz.addWidget(w_centro, 1)

        # --- Derecha: analito en foco + cabina ---
        col_der = QVBoxLayout()
        col_der.setContentsMargins(0, 0, 4, 0)
        col_der.setSpacing(14)

        self.card_foco = Tarjeta(margen=20, espacio=6)
        self.lbl_foco_tag = etiqueta_mono("Metabólico")
        self.card_foco.capa.addWidget(self.lbl_foco_tag)
        self.lbl_foco_nombre = etiqueta("Glucosa", t.T_DESTACADO, t.TEXTO_SUAVE)
        self.card_foco.capa.addWidget(self.lbl_foco_nombre)

        fila_val = QHBoxLayout()
        fila_val.setSpacing(10)
        self.lbl_foco_valor = etiqueta("–", 50, None, peso=300)
        self.lbl_foco_unidad = etiqueta("mg/dL", t.T_DESTACADO, t.SECUNDARIO)
        fila_val.addWidget(self.lbl_foco_valor, 0, Qt.AlignBottom)
        fila_val.addWidget(self.lbl_foco_unidad, 0, Qt.AlignBottom)
        fila_val.addStretch(1)
        self.card_foco.capa.addLayout(fila_val)

        self.lbl_foco_desc = etiqueta("", t.T_CUERPO, t.SECUNDARIO, wrap=True)
        self.card_foco.capa.addWidget(self.lbl_foco_desc)

        self.grafica = GraficaTendencia(alto=122)
        self.card_foco.capa.addWidget(self.grafica)

        fila_acc_foco = QHBoxLayout()
        fila_acc_foco.setSpacing(10)
        self.btn_medir = boton(
            "Medir ahora",
            estilo="primario",
            al_pulsar=lambda: self.state.ir_a("medir", indicadorId=self._analito_foco),
        )
        self.btn_hist_foco = boton(
            "Historial",
            al_pulsar=lambda: self.state.ir_a("historial", paramId=self._analito_foco, modo="osdr"),
        )
        fila_acc_foco.addWidget(self.btn_medir, 3)
        fila_acc_foco.addWidget(self.btn_hist_foco, 2)
        self.card_foco.capa.addSpacing(4)
        self.card_foco.capa.addLayout(fila_acc_foco)
        col_der.addWidget(self.card_foco)

        self.card_cabina = Tarjeta(margen=18, espacio=4)
        h_cab = QHBoxLayout()
        h_cab.addWidget(etiqueta_mono("Cabina"))
        h_cab.addStretch(1)
        self.lbl_entorno_cab = pastilla("Nave", t.BORDE_SUAVE)
        h_cab.addWidget(self.lbl_entorno_cab)
        self.card_cabina.capa.addLayout(h_cab)
        self.lbl_rad = etiqueta("–", t.T_DESTACADO, t.TEXTO)
        self.lbl_co2 = etiqueta("–", t.T_DESTACADO, t.TEXTO)
        self.lbl_rr = etiqueta("–", t.T_DESTACADO, t.TEXTO)
        self.lbl_icp = etiqueta("–", t.T_DESTACADO, t.TEXTO)
        self.lbl_retardo = etiqueta("–", t.T_DESTACADO, t.TEXTO)

        self._mon_rad = FilaCabinaMonitor(
            "Radiación acumulada",
            self.lbl_rad,
            modo_monitor="tendencia",
            rango_min=0.0,
            rango_max=1.5,
            al_pulsar=lambda: self.state.ir_a("historial", paramId="radiation_dose", modo="vivo"),
        )
        self._mon_co2 = FilaCabinaMonitor(
            "CO₂ en cabina",
            self.lbl_co2,
            modo_monitor="tendencia",
            rango_min=0.5,
            rango_max=5.0,
            al_pulsar=lambda: self.state.ir_a("historial", paramId="cabin_co2", modo="vivo"),
        )
        self._mon_rr = FilaCabinaMonitor(
            "Frecuencia respiratoria",
            self.lbl_rr,
            modo_monitor="respiratorio",
            rango_min=10.0,
            rango_max=22.0,
            al_pulsar=lambda: self.state.ir_a("historial", paramId="respiratory_rate", modo="vivo"),
        )
        self._mon_icp = FilaCabinaMonitor(
            "Presión intracraneal est.",
            self.lbl_icp,
            modo_monitor="tendencia",
            rango_min=5.0,
            rango_max=20.0,
            al_pulsar=lambda: self.state.ir_a("historial", paramId="intracranial_pressure_est", modo="vivo"),
        )
        self._fila_icp = self._mon_icp
        self._monitores_cabina = (self._mon_rad, self._mon_co2, self._mon_rr, self._mon_icp)
        for fila_mon in self._monitores_cabina:
            fila_mon.setToolTip(tr("Tocar para ver historial"))
            self.card_cabina.capa.addWidget(fila_mon)

        fila_ret_w = QWidget()
        fila_ret = QHBoxLayout(fila_ret_w)
        fila_ret.setContentsMargins(6, 2, 6, 0)
        fila_ret.addWidget(etiqueta("Retardo con Tierra", t.T_CUERPO, t.ETIQUETA))
        fila_ret.addStretch(1)
        fila_ret.addWidget(self.lbl_retardo)
        self.card_cabina.capa.addWidget(fila_ret_w)
        col_der.addWidget(self.card_cabina)
        col_der.addStretch(1)

        w_der_contenido = QWidget()
        w_der_contenido.setLayout(col_der)
        scroll_der = area_desplazable(w_der_contenido)
        scroll_der.setFixedWidth(408)
        raiz.addWidget(scroll_der)

        self.state.crewChanged.connect(self.refrescar)
        self.state.timepointChanged.connect(self.refrescar)
        self.state.sistemaChanged.connect(self.refrescar)
        self.state.entornoCambiado.connect(self.refrescar)
        self.state.configChanged.connect(self._on_config_cambiada)
        self.state.telemetriaEnVivoActualizada.connect(self._tick_telemetria)

        self._pendiente_refresco = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_telemetria)
        self._timer_anim = QTimer(self)
        self._timer_anim.setInterval(33)
        self._timer_anim.timeout.connect(self._on_anim_monitor)
        self.refrescar(forzar=True)

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self._ultimo_anim_ts = time.monotonic()
        if not self._timer.isActive():
            self._timer.start(1500)
        if not self._timer_anim.isActive():
            self._timer_anim.start(33)
        if self._pendiente_refresco:
            self._pendiente_refresco = False
            self.refrescar(forzar=True)
        else:
            self._tick_telemetria(forzar=True)

    def hideEvent(self, ev) -> None:  # noqa: N802
        self._timer.stop()
        self._timer_anim.stop()
        if self.motor_voz is not None:
            self.motor_voz.detener_monitor_cardiaco()
        super().hideEvent(ev)

    def _on_config_cambiada(self, _cfg: Dict[str, Any]) -> None:
        if not bool(self.state.config.get("sonidoMonitorOverview", True)) and self.motor_voz is not None:
            self.motor_voz.detener_monitor_cardiaco()

    def sonido_monitor_activo(self) -> bool:
        return bool(self.state.config.get("sonidoMonitorOverview", True))

    def _cargar_historial_inicial(self, crew_id: str) -> None:
        if crew_id == self._crew_historial_cargado:
            return
        self._crew_historial_cargado = crew_id
        try:
            filas = ventana_reciente(crew_id, minutos=10)
        except Exception:
            filas = []
        por_param: Dict[str, List[float]] = {}
        for row in filas:
            pid = str(row.get("parametroId") or "")
            if not pid:
                continue
            try:
                por_param.setdefault(pid, []).append(float(row["valor"]))
            except Exception:
                pass
        self.ind_fc.cargar_historial(por_param.get("heart_rate", []))
        self.ind_spo2.cargar_historial(por_param.get("spo2", []))
        self.ind_pa.cargar_historial(por_param.get("systolic_bp", []))
        self.ind_temp.cargar_historial(por_param.get("core_temperature", []))
        self._mon_rad.cargar_historial(por_param.get("radiation_dose", []))
        self._mon_co2.cargar_historial(por_param.get("cabin_co2", []))
        self._mon_rr.cargar_historial(por_param.get("respiratory_rate", []))
        self._mon_icp.cargar_historial(por_param.get("intracranial_pressure_est", []))

    def _nivel_vivo_param(
        self,
        crew_id: str,
        param_id: str,
        valor: Optional[float],
        lecturas: Dict[str, Any],
        entorno: str,
    ) -> str:
        item = lecturas.get(param_id)
        if isinstance(item, dict) and item.get("nivel"):
            return str(item["nivel"])
        if valor is None:
            return "NOMINAL"
        try:
            cal = float(item.get("calidad", 1.0)) if isinstance(item, dict) else 1.0
            res = evaluar_lectura_determinista(crew_id, param_id, float(valor), calidad=cal, entorno=entorno)
            return str(res.get("nivel", "NOMINAL"))
        except Exception:
            return "NOMINAL"

    def _emitir_sonido_latido(self) -> bool:
        if self.motor_voz is None:
            return False
        if not bool(self.state.config.get("sonidoMonitorOverview", True)):
            return False
        refractario = max(0.18, min(0.42, 0.55 * (60.0 / max(30.0, self._bpm_vivo))))
        if (self._reloj_monitor_s - self._ultimo_latido_audio_s) < refractario:
            return False
        try:
            vol = max(0.15, min(1.0, float(self.state.config.get("volumenMonitorOverview", 0.35))))
        except Exception:
            vol = 0.35
        self._ultimo_latido_audio_s = self._reloj_monitor_s
        return self.motor_voz.reproducir_latido_monitor(
            bpm=self._bpm_vivo,
            spo2=self._spo2_vivo,
            volumen=vol,
            nivel=self._nivel_fc_vivo,
        )

    def _avanzar_monitor_dt(self, dt_s: float) -> bool:
        dt = max(0.001, min(0.25, float(dt_s)))
        self._reloj_monitor_s += dt
        bpm = max(30.0, min(240.0, float(self._bpm_vivo)))
        hz_c = bpm / 60.0
        f_prev = self._fase_cardiaca
        f_nueva = (f_prev + dt * hz_c) % 1.0
        self._fase_cardiaca = f_nueva

        r_fase = 0.22
        if f_nueva >= f_prev:
            cruzo_r = f_prev < r_fase <= f_nueva
        else:
            cruzo_r = (f_prev < r_fase) or (r_fase <= f_nueva)

        if cruzo_r:
            for mon in (self.ind_fc, self.ind_spo2, self.ind_pa):
                mon.pulso()
            self._emitir_sonido_latido()

        for mon in (self.ind_fc, self.ind_spo2, self.ind_pa):
            mon.avanzar_onda(dt, hz_c, f_nueva)
        self.ind_temp.avanzar_onda(dt, 0.0)
        self._mon_rr.avanzar_onda(dt, max(6.0, min(48.0, float(self._rr_vivo))) / 60.0)
        return cruzo_r

    def _on_anim_monitor(self) -> None:
        if not self.isVisible():
            return
        ahora = time.monotonic()
        dt = min(0.12, max(0.005, ahora - self._ultimo_anim_ts))
        self._ultimo_anim_ts = ahora
        self._avanzar_monitor_dt(dt)

    def _tick_telemetria(self, *_args, forzar: bool = False) -> None:
        if not forzar and not self.isVisible():
            return
        crew_id = self.state.crew_id
        entorno = self.state.entorno
        frame = generar_frame_telemetria(crew_id, self.state.timepoint)
        sv = frame.get("signosVitales", {})
        cab = frame.get("cabina", {})
        lecturas = frame.get("lecturas", {}) if isinstance(frame.get("lecturas"), dict) else {}

        fc = float(sv.get("frecuenciaCardiacaLpm", 64))
        spo2 = float(sv.get("spo2Porcentaje", 98))
        temp = float(sv.get("temperaturaCorporalC", 36.7))

        pa_txt = str(sv.get("presionArterial", "118/76"))
        sbp = lecturas.get("systolic_bp", {}).get("valor")
        dbp = lecturas.get("diastolic_bp", {}).get("valor")
        if sbp is None or dbp is None:
            try:
                partes_pa = pa_txt.split("/")
                sbp = float(partes_pa[0])
                dbp = float(partes_pa[1])
            except Exception:
                sbp, dbp = 118.0, 76.0
        sbp_f, dbp_f = float(sbp), float(dbp)

        niv_fc = self._nivel_vivo_param(crew_id, "heart_rate", fc, lecturas, entorno)
        niv_spo2 = self._nivel_vivo_param(crew_id, "spo2", spo2, lecturas, entorno)
        niv_pa = self._nivel_vivo_param(crew_id, "systolic_bp", sbp_f, lecturas, entorno)
        niv_temp = self._nivel_vivo_param(crew_id, "core_temperature", temp, lecturas, entorno)

        self.ind_fc.registrar_muestra(fc, nivel=niv_fc)
        self.ind_fc.actualizar(int(round(fc)), tr("base {v}", v=sv.get("baseFrecuenciaCardiacaLpm", 62)))

        self.ind_spo2.registrar_muestra(spo2, nivel=niv_spo2)
        self.ind_spo2.actualizar(int(round(spo2)), tr("base {v}", v=sv.get("baseSpo2Porcentaje", 99)))

        self.ind_pa.registrar_muestra(sbp_f, nivel=niv_pa, valor_sec=dbp_f)
        self.ind_pa.actualizar(pa_txt, tr(t.texto_triage(niv_pa)), insignia=True)

        self.ind_temp.registrar_muestra(temp, nivel=niv_temp)
        self.ind_temp.actualizar(f"{temp:.1f}", tr("base {v}", v=sv.get("baseTemperaturaC", 36.6)))

        rad = float(cab.get("radiacionAcumuladaMsv", 0.4))
        co2 = float(cab.get("presionParcialCo2MmHg", 2.8))
        rr = float(sv.get("frecuenciaRespiratoriaRpm", 15))
        icp_raw = sv.get("presionIntracranealMmHg")
        if icp_raw is None:
            icp_raw = lecturas.get("intracranial_pressure_est", {}).get("valor")
        icp = float(icp_raw) if icp_raw is not None else 11.2

        niv_rad = self._nivel_vivo_param(crew_id, "radiation_dose", rad, lecturas, entorno)
        niv_co2 = self._nivel_vivo_param(crew_id, "cabin_co2", co2, lecturas, entorno)
        niv_rr = self._nivel_vivo_param(crew_id, "respiratory_rate", rr, lecturas, entorno)
        niv_icp = self._nivel_vivo_param(crew_id, "intracranial_pressure_est", icp, lecturas, entorno)

        self.lbl_rad.setText(f"{rad:.2f} mSv" if rad < 10 else f"{rad:.1f} mSv")
        self._mon_rad.registrar_muestra(rad, nivel=niv_rad)

        self.lbl_co2.setText(f"{co2:.2f} mmHg" if co2 < 10 else f"{co2:.1f} mmHg")
        self._mon_co2.registrar_muestra(co2, nivel=niv_co2)

        self.lbl_rr.setText(f"{int(round(rr))} rpm")
        self._mon_rr.registrar_muestra(rr, nivel=niv_rr)

        en_luna = entorno == "base-lunar"
        self._fila_icp.setVisible(not en_luna)
        if not en_luna:
            self.lbl_icp.setText(f"{icp:.1f} mmHg")
            self._mon_icp.registrar_muestra(icp, nivel=niv_icp)

        self._bpm_vivo = max(30.0, min(240.0, fc))
        self._spo2_vivo = spo2
        self._rr_vivo = max(6.0, min(48.0, rr))
        self._nivel_fc_vivo = niv_fc

    def refrescar(self, *_args, forzar: bool = False) -> None:
        if not forzar and not self.isVisible():
            self._pendiente_refresco = True
            return
        self._pendiente_refresco = False
        crew_id = self.state.crew_id
        tp = self.state.timepoint
        sis = self.state.sistema

        nombres_ent = {"nave": "Nave", "estacion": "Estación", "base-lunar": "Base lunar"}
        self.lbl_entorno_cab.setText(tr(nombres_ent.get(self.state.entorno, self.state.entorno)))
        estilo_pastilla(self.lbl_entorno_cab, t.NORMAL)

        self._cargar_historial_inicial(crew_id)
        self._tick_telemetria(forzar=True)
        cab = get_cabina_dataset().get("cabina", {})
        self.lbl_retardo.setText(str(cab.get("retardoTierraTexto", "14m 20s")))

        # Mismos avisos que el botón de la barra y el visor 3D (dataset + mediciones locales).
        avisos = _avisos_actuales(crew_id, tp)
        nivel_global = _nivel_maximo(avisos)
        n = len(avisos)
        if nivel_global == "CRITICO":
            texto_estado = tr("Crítico · {n} valor fuera de rango", n=n) if n == 1 else tr("Crítico · {n} valores fuera de rango", n=n)
        elif n:
            texto_estado = tr("Atención · {n} valor a vigilar", n=n) if n == 1 else tr("Atención · {n} valores a vigilar", n=n)
        else:
            texto_estado = tr("Todo en rango")
        self.lbl_estado.setText(texto_estado)
        self.lbl_estado.setStyleSheet(f"color: {t.color_triage(nivel_global)};")

        # El analito en foco es el peor aviso; si no hay, el principal del sistema.
        meta_sis = SISTEMAS_DETALLE.get(sis, SISTEMAS_DETALLE["metabolico"])
        if avisos:
            ind_id = avisos[0]["indicadorId"]
            sis = avisos[0]["sistema"]
        else:
            ind_id = meta_sis["principal"]
        self._analito_foco = ind_id
        ind = get_indicador_osdr(ind_id) or get_indicador_osdr("glucose")
        if not ind:
            return

        base = get_baseline(crew_id, ind_id)
        val = get_valor_osdr(crew_id, ind_id, tp)
        if val is None:
            val = base["mediaPreVuelo"]
        res = evaluar_lectura_determinista(crew_id, ind_id, float(val))
        _, color = nivel_triage(res["nivel"])
        desvio = res["desvioPorcentajeBaseline"]

        self.lbl_foco_tag.setText(tr(SISTEMAS.get(sis, "Metabólico")))
        self.lbl_foco_nombre.setText(nombre_corto(ind["nombre"]))
        self.lbl_foco_valor.setText(str(val))
        self.lbl_foco_unidad.setText(ind["unidad"])
        self.lbl_foco_desc.setText(
            tr(
                "{d} % frente a tu base ({b})",
                d=f"{desvio:+.0f}",
                b=base["mediaPreVuelo"],
            )
        )
        self.lbl_foco_desc.setStyleSheet(
            f"font-family: '{t.FUENTE}'; font-size: {t.T_CUERPO}px; color: {color};"
        )
        self.btn_medir.setText(tr("Medir {x}", x=nombre_corto(ind["nombre"]).lower()))

        serie = ind.get("serie", {}).get(crew_id, [])
        rango = ind.get("rangoReferencia") or {}
        self.grafica.cargar(serie, rango.get("min"), rango.get("max"), tp)

    def aplicar_tema(self) -> None:
        for ind_w in self._monitores_izq:
            ind_w.aplicar_tema()
        for mon_c in self._monitores_cabina:
            mon_c.update()
        self.refrescar(forzar=True)
        self.grafica.update()


# ===========================================================================
# 2. VISTA CUERPO 3D
# ===========================================================================

class VistaCuerpo3D(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._analito_principal = "glucose"
        self._filas_vivas: Dict[str, Dict[str, Any]] = {}

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(24)

        # Izquierda: los 6 sistemas, sólo el nombre y barra cromática de triage
        col_izq = QVBoxLayout()
        col_izq.setSpacing(6)
        col_izq.addWidget(etiqueta_mono("Sistemas"))
        col_izq.addSpacing(4)
        self.botones_sis: Dict[str, QPushButton] = {}
        for key, meta in SISTEMAS_DETALLE.items():
            b = QPushButton(tr(meta["titulo"]))
            b.setObjectName("lista")
            b.setCheckable(True)
            b.setMinimumHeight(60)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.state.set_sistema(k))
            self.botones_sis[key] = b
            col_izq.addWidget(b)
        col_izq.addStretch(1)

        w_izq = QWidget()
        w_izq.setLayout(col_izq)
        w_izq.setFixedWidth(256)
        raiz.addWidget(w_izq)

        self.contenedor_3d = QVBoxLayout()
        self.contenedor_3d.setContentsMargins(0, 0, 0, 0)
        w_centro = QWidget()
        w_centro.setLayout(self.contenedor_3d)
        raiz.addWidget(w_centro, 1)

        # Derecha: cabecera fija + lista desplazable sin colisiones + botón fijo
        col_der = QVBoxLayout()
        col_der.setContentsMargins(0, 0, 0, 0)
        self.card = Tarjeta(margen=22, espacio=8)
        self.lbl_titulo = etiqueta("Sistema", 22, t.TEXTO, peso=600, wrap=True)
        self.card.capa.addWidget(self.lbl_titulo)

        fila_tag = QHBoxLayout()
        fila_tag.setSpacing(8)
        self.lbl_tag = etiqueta("", t.T_PEQUENO, t.SECUNDARIO)
        self.lbl_estado_sis = QLabel("")
        fila_tag.addWidget(self.lbl_tag, 1)
        fila_tag.addWidget(self.lbl_estado_sis, 0, Qt.AlignRight)
        self.card.capa.addLayout(fila_tag)
        self.card.capa.addWidget(divisor())

        self._w_analitos = QWidget()
        self.contenedor_analitos = QVBoxLayout(self._w_analitos)
        self.contenedor_analitos.setContentsMargins(0, 0, 8, 2)
        self.contenedor_analitos.setSpacing(0)
        self.scroll_analitos = area_desplazable(self._w_analitos)
        self.card.capa.addWidget(self.scroll_analitos, 1)

        self.card.capa.addWidget(divisor())
        fila_acc_3d = QHBoxLayout()
        fila_acc_3d.setSpacing(10)
        self.btn_evaluar = boton(
            "Medir",
            estilo="primario",
            al_pulsar=lambda: self.state.ir_a("medir", indicadorId=self._analito_principal),
        )
        self.btn_hist_3d = boton(
            "Historial",
            al_pulsar=lambda: self.state.ir_a("historial", paramId=self._analito_principal),
        )
        fila_acc_3d.addWidget(self.btn_evaluar, 3)
        fila_acc_3d.addWidget(self.btn_hist_3d, 2)
        self.card.capa.addLayout(fila_acc_3d)
        col_der.addWidget(self.card, 1)

        w_der = QWidget()
        w_der.setLayout(col_der)
        w_der.setFixedWidth(430)
        raiz.addWidget(w_der)

        self._pendiente_refresco = False
        self._ultima_estructura_cuerpo = ""
        self._ultima_firma_cuerpo = ""
        self.state.crewChanged.connect(self.refrescar)
        self.state.timepointChanged.connect(self.refrescar)
        self.state.sistemaChanged.connect(self.refrescar)
        self.state.entornoCambiado.connect(self.refrescar)
        self.state.telemetriaEnVivoActualizada.connect(self._on_telemetria_cuerpo)
        self.refrescar(forzar=True)

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self._pendiente_refresco:
            self._pendiente_refresco = False
            self.refrescar(forzar=True)

    def _on_telemetria_cuerpo(self) -> None:
        if not self.isVisible():
            self._pendiente_refresco = True
            return
        self.refrescar()

    def _crear_fila_analito(
        self,
        nombre: str,
        valor_txt: str,
        unidad: str,
        texto_estado: str,
        color_estado: str,
        ref_txt: str,
    ) -> Tuple[QWidget, QLabel, QLabel, QLabel]:
        """Construye una fila de lectura en dos bandas sin recorte ni solapamiento."""
        fila_w = QWidget()
        fila_cap = QVBoxLayout(fila_w)
        fila_cap.setContentsMargins(0, 5, 0, 5)
        fila_cap.setSpacing(3)

        banda_sup = QHBoxLayout()
        banda_sup.setContentsMargins(0, 0, 0, 0)
        banda_sup.setSpacing(8)
        lbl_nom = etiqueta(nombre, t.T_CUERPO, t.ETIQUETA, wrap=True)
        lbl_pill = pastilla(texto_estado, color_estado)
        banda_sup.addWidget(lbl_nom, 1)
        banda_sup.addWidget(lbl_pill, 0, Qt.AlignRight | Qt.AlignTop)
        fila_cap.addLayout(banda_sup)

        banda_inf = QHBoxLayout()
        banda_inf.setContentsMargins(0, 0, 0, 0)
        banda_inf.setSpacing(8)
        lbl_val = etiqueta(valor_txt, 22, t.TEXTO, peso=500)
        lbl_u = etiqueta(unidad, t.T_PEQUENO, t.SECUNDARIO)
        lbl_ref = etiqueta(ref_txt, t.T_PEQUENO, t.TERCIARIO)
        banda_inf.addWidget(lbl_val, 0, Qt.AlignBottom)
        banda_inf.addWidget(lbl_u, 0, Qt.AlignBottom)
        banda_inf.addStretch(1)
        banda_inf.addWidget(lbl_ref, 0, Qt.AlignRight | Qt.AlignBottom)
        fila_cap.addLayout(banda_inf)

        return fila_w, lbl_val, lbl_pill, lbl_ref

    def _reconstruir_lista_analitos(
        self,
        vivos_sis: List[Dict[str, Any]],
        osdr_ids: List[str],
        crew: str,
        tp: str,
        sexo: Optional[str],
    ) -> None:
        self._filas_vivas = {}
        vaciar_layout(self.contenedor_analitos)

        osdr_valido = [ind_id for ind_id in osdr_ids if get_indicador_osdr(ind_id)]

        if vivos_sis:
            hdr_vivo = etiqueta_mono("Telemetría en vivo · 1 Hz")
            hdr_vivo.setContentsMargins(0, 2, 0, 2)
            self.contenedor_analitos.addWidget(hdr_vivo)
            for idx, p_vivo in enumerate(vivos_sis):
                pid = p_vivo["id"]
                fila_w, lbl_val, lbl_pill, lbl_ref = self._crear_fila_analito(
                    nombre_corto(p_vivo["nombre"]),
                    "–",
                    p_vivo["unidad"],
                    tr("Sin dato"),
                    t.TERCIARIO,
                    _texto_ref_corto(p_vivo, None, sexo),
                )
                self._filas_vivas[pid] = {
                    "def": p_vivo,
                    "val": lbl_val,
                    "pill": lbl_pill,
                    "ref": lbl_ref,
                }
                self.contenedor_analitos.addWidget(fila_w)
                if idx < len(vivos_sis) - 1:
                    self.contenedor_analitos.addWidget(divisor())

        if vivos_sis and osdr_valido:
            self.contenedor_analitos.addSpacing(8)

        if osdr_valido:
            hdr_osdr = etiqueta_mono("Panel OSDR OSD-575")
            hdr_osdr.setContentsMargins(0, 2, 0, 2)
            self.contenedor_analitos.addWidget(hdr_osdr)
            for idx, ind_id in enumerate(osdr_valido):
                ind = get_indicador_osdr(ind_id)
                if not ind:
                    continue
                param = get_param(ind_id)
                val = get_valor_osdr(crew, ind_id, tp)
                rango = ((param or {}).get("rangoReferenciaPorSexo") or {}).get(sexo or "") or ind.get("rangoReferencia")
                texto_estado, color = estado_triage(crew, ind_id, val, rango)
                fila_w, _, _, _ = self._crear_fila_analito(
                    nombre_corto(ind["nombre"]),
                    _formatear_valor_clinico(ind_id, val),
                    ind["unidad"],
                    texto_estado,
                    color,
                    _texto_ref_corto(param, ind, sexo),
                )
                self.contenedor_analitos.addWidget(fila_w)
                if idx < len(osdr_valido) - 1:
                    self.contenedor_analitos.addWidget(divisor())

        self.contenedor_analitos.addStretch(1)

    def _actualizar_valores_vivos(
        self, lecturas: Dict[str, Any], crew: str, entorno: str
    ) -> None:
        for pid, widgets_fila in self._filas_vivas.items():
            item = lecturas.get(pid)
            if not isinstance(item, dict):
                widgets_fila["val"].setText("–")
                widgets_fila["pill"].setText(tr("Sin dato"))
                estilo_pastilla(widgets_fila["pill"], t.TERCIARIO)
                continue
            val = float(item.get("valor"))
            calidad = item.get("calidad", 1.0)
            ev = evaluar_lectura_determinista(crew, pid, val, calidad=calidad, entorno=entorno)
            nivel = ev.get("nivel", "NOMINAL")
            texto_e = tr(t.texto_triage(nivel))
            if calidad is not None and float(calidad) < 0.5:
                texto_e = f"{texto_e} · {tr('Señal baja')}"
            widgets_fila["val"].setText(_formatear_valor_clinico(pid, val))
            widgets_fila["pill"].setText(texto_e)
            estilo_pastilla(widgets_fila["pill"], t.color_triage(nivel))

    def refrescar(self, *_args, forzar: bool = False) -> None:
        if not forzar and not self.isVisible():
            self._pendiente_refresco = True
            return
        self._pendiente_refresco = False
        sis = self.state.sistema
        crew = self.state.crew_id
        tp = self.state.timepoint
        entorno = self.state.entorno
        meta = SISTEMAS_DETALLE.get(sis, SISTEMAS_DETALLE["metabolico"])
        self._analito_principal = meta["principal"]
        sexo = sexo_de(crew)

        frame = get_crew_hub().frame_actual(crew) or get_runtime().frame_actual(crew) or {}
        lecturas = frame.get("lecturas", {}) if isinstance(frame, dict) else {}
        vivos_sis = [
            p for p in obtener_catalogo_parametros(entorno=entorno, sistema=sis)
            if not p.get("esDatoRealOSDR")
        ]

        estructura = "|".join([sis, crew, tp, entorno, *(p["id"] for p in vivos_sis)])
        firma = "|".join([
            estructura,
            ",".join(
                f"{p['id']}={_formatear_valor_clinico(p['id'], lecturas.get(p['id'], {}).get('valor'))}:{lecturas.get(p['id'], {}).get('calidad')}"
                for p in vivos_sis
            ),
        ])
        if not forzar and firma == self._ultima_firma_cuerpo:
            return
        self._ultima_firma_cuerpo = firma

        niveles_sis = _nivel_por_sistema(_avisos_actuales(crew, tp))
        for k, b in self.botones_sis.items():
            b.setChecked(k == sis)
            nivel_k = niveles_sis.get(k, "NOMINAL")
            b.setStyleSheet(
                f"QPushButton {{ border-left: 4px solid {t.color_triage(nivel_k)}; padding-left: 12px; }}"
                if nivel_k != "NOMINAL" else ""
            )

        self.lbl_titulo.setText(tr(meta["titulo"]))
        self.lbl_tag.setText(f"{crew} · {tp}")
        nivel_sis = niveles_sis.get(sis, "NOMINAL")
        self.lbl_estado_sis.setText(tr(t.texto_triage(nivel_sis)))
        estilo_pastilla(self.lbl_estado_sis, t.color_triage(nivel_sis))

        if forzar or estructura != self._ultima_estructura_cuerpo:
            sb = self.scroll_analitos.verticalScrollBar()
            mismo_sis = bool(self._ultima_estructura_cuerpo.startswith(f"{sis}|"))
            scroll_prev = sb.value() if (forzar and mismo_sis) else 0
            self._ultima_estructura_cuerpo = estructura
            self.card.setUpdatesEnabled(False)
            try:
                self._reconstruir_lista_analitos(vivos_sis, meta["analitos"], crew, tp, sexo)
                self._actualizar_valores_vivos(lecturas, crew, entorno)
            finally:
                self.card.setUpdatesEnabled(True)
            sb.setValue(scroll_prev)
        else:
            self._actualizar_valores_vivos(lecturas, crew, entorno)

        ind_p = get_indicador_osdr(self._analito_principal)
        if ind_p:
            self.btn_evaluar.setText(tr("Medir {x}", x=nombre_corto(ind_p["nombre"]).lower()))

    def aplicar_tema(self) -> None:
        self.refrescar(forzar=True)


# ===========================================================================
# 3. VISTA MEDICIÓN GUIADA EN 0G
# ===========================================================================

class VistaMedicion(QWidget):
    lecturaGuardada = Signal(str)

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.indicador_id = "glucose"
        self._texto_valor = ""
        self._valor_precargado = True

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(28)

        # Izquierda: qué medir y cómo
        cont_guia = QWidget()
        col_izq = QVBoxLayout(cont_guia)
        col_izq.setContentsMargins(0, 0, 8, 0)
        col_izq.setSpacing(14)

        self.combo_ind = QComboBox()
        self.combo_ind.setMinimumHeight(t.ALTO_TOQUE + 4)
        self._repoblar_combo_parametros()
        self.combo_ind.currentIndexChanged.connect(self._on_cambio_combo)
        col_izq.addWidget(self.combo_ind)

        self.lbl_dispositivo = etiqueta("", t.T_CUERPO, t.SECUNDARIO, wrap=True)
        col_izq.addWidget(self.lbl_dispositivo)
        self.lbl_meta_param = etiqueta("", t.T_PEQUENO, t.TERCIARIO, wrap=True)
        col_izq.addWidget(self.lbl_meta_param)

        self.vbox_pasos = QVBoxLayout()
        self.vbox_pasos.setSpacing(18)
        col_izq.addLayout(self.vbox_pasos)

        self.caja_fallo = QFrame()
        # Con selector por nombre: QLabel también es un QFrame y heredaba el borde.
        self.caja_fallo.setObjectName("cajaFallo")
        v_fallo = QVBoxLayout(self.caja_fallo)
        v_fallo.setContentsMargins(20, 16, 20, 16)
        self.lbl_fallo = etiqueta("", t.T_CUERPO, t.CAJA_FALLO_FG, wrap=True)
        v_fallo.addWidget(self.lbl_fallo)
        self._aplicar_estilo_caja_fallo()
        col_izq.addWidget(self.caja_fallo)
        col_izq.addStretch(1)

        raiz.addWidget(area_desplazable(cont_guia), 1)

        # Derecha: valor con teclado en pantalla
        col_der = QVBoxLayout()
        card_eval = Tarjeta(margen=26, espacio=14)
        card_eval.capa.addWidget(etiqueta_mono("Valor medido"))

        fila_v = QHBoxLayout()
        self.lbl_valor = etiqueta("–", 60, None, peso=300)
        self.lbl_unidad = etiqueta("", t.T_DESTACADO, t.SECUNDARIO)
        fila_v.addWidget(self.lbl_valor, 0, Qt.AlignBottom)
        fila_v.addWidget(self.lbl_unidad, 0, Qt.AlignBottom)
        fila_v.addStretch(1)
        card_eval.capa.addLayout(fila_v)

        self.teclado = TecladoNumerico(alto_tecla=66)
        self.teclado.tecla.connect(self._on_tecla)
        card_eval.capa.addWidget(self.teclado)

        self.txt_nota_med = QLineEdit()
        self.txt_nota_med.setPlaceholderText(
            tr("Nota clínica opcional (ej. post-ejercicio, ayuno)")
        )
        card_eval.capa.addWidget(self.txt_nota_med)

        btn_guardar = boton("Evaluar y guardar", estilo="primario", al_pulsar=self._registrar_lectura)
        card_eval.capa.addWidget(btn_guardar)

        self.fila_resultado = QHBoxLayout()
        card_eval.capa.addLayout(self.fila_resultado)
        self.lbl_resultado_msg = etiqueta(
            "Escribe el valor del analizador y pulsa «Evaluar y guardar».",
            t.T_CUERPO,
            t.SECUNDARIO,
            wrap=True,
        )
        card_eval.capa.addWidget(self.lbl_resultado_msg)
        col_der.addWidget(card_eval)
        col_der.addStretch(1)

        w_der = QWidget()
        w_der.setLayout(col_der)
        w_der.setFixedWidth(430)
        # En ventanas bajas (tablet 800 px) la columna se desplaza con el dedo en vez de solaparse.
        scroll_der_med = area_desplazable(w_der)
        scroll_der_med.setFixedWidth(446)
        raiz.addWidget(scroll_der_med)

        self._pendiente_refresco = False
        self.state.crewChanged.connect(self._refrescar_guia)
        self.state.timepointChanged.connect(self._refrescar_guia)
        self.state.entornoCambiado.connect(self._on_entorno_cambiado)
        self.state.medicionRegistrada.connect(self._on_medicion_externa)
        self.seleccionar_indicador("glucose")

    def _repoblar_combo_parametros(self) -> None:
        actual = self.combo_ind.currentData() or self.indicador_id
        self.combo_ind.blockSignals(True)
        try:
            self.combo_ind.clear()
            for p in obtener_catalogo_parametros(entorno=self.state.entorno):
                self.combo_ind.addItem(f"{nombre_corto(p['nombre'])}  ·  {p['unidad']}", p["id"])
            idx = self.combo_ind.findData(actual)
            if idx < 0:
                idx = self.combo_ind.findData("glucose")
            if idx >= 0:
                self.combo_ind.setCurrentIndex(idx)
                self.indicador_id = str(self.combo_ind.currentData())
        finally:
            self.combo_ind.blockSignals(False)

    def _on_entorno_cambiado(self, *_args) -> None:
        self._repoblar_combo_parametros()
        self._refrescar_guia(forzar=True)

    def _on_medicion_externa(self, indicador_id: str) -> None:
        if indicador_id and indicador_id != self.indicador_id:
            self.seleccionar_indicador(indicador_id)
        else:
            self._refrescar_guia(forzar=True)

    def _aplicar_estilo_caja_fallo(self) -> None:
        self.caja_fallo.setStyleSheet(
            f"QFrame#cajaFallo {{ background: {t.CAJA_FALLO_BG}; border: 1px solid {t.CAJA_FALLO_BORDE}; border-radius: 16px; }}"
        )

    def aplicar_tema(self) -> None:
        self._aplicar_estilo_caja_fallo()
        self._refrescar_guia(forzar=True)

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self._pendiente_refresco:
            self._pendiente_refresco = False
            self._refrescar_guia(forzar=True)

    def seleccionar_indicador(self, indicador_id: str) -> None:
        self.indicador_id = indicador_id
        self.state.indicador_en_pantalla = indicador_id
        idx = self.combo_ind.findData(indicador_id)
        if idx >= 0 and idx != self.combo_ind.currentIndex():
            self.combo_ind.blockSignals(True)
            self.combo_ind.setCurrentIndex(idx)
            self.combo_ind.blockSignals(False)
        self._refrescar_guia(forzar=True)

    def _on_cambio_combo(self) -> None:
        ind_id = self.combo_ind.currentData()
        if ind_id:
            self.indicador_id = ind_id
            self.state.indicador_en_pantalla = ind_id
            self._refrescar_guia(forzar=True)

    def _on_tecla(self, k: str) -> None:
        # La primera tecla sustituye al valor precargado del dataset.
        if self._valor_precargado and k != "⌫":
            self._texto_valor = ""
        self._valor_precargado = False
        if k == "⌫":
            self._texto_valor = self._texto_valor[:-1]
        elif k == ".":
            if "." not in self._texto_valor:
                self._texto_valor = (self._texto_valor or "0") + "."
        elif len(self._texto_valor) < 7:
            self._texto_valor += k
        self.lbl_valor.setText(self._texto_valor or "–")

    def _refrescar_guia(self, *_args, forzar: bool = False) -> None:
        if not forzar and not self.isVisible():
            self._pendiente_refresco = True
            return
        self._pendiente_refresco = False
        crew = self.state.crew_id
        entorno = self.state.entorno
        ind = get_indicador_osdr(self.indicador_id)
        param = get_param(self.indicador_id)
        if not ind and not param:
            ind = get_indicador_osdr("glucose")
            param = get_param("glucose")
        guias = get_guias_dataset()
        guia = guias.get(self.indicador_id, guias.get("glucose", {}))

        val_actual = None
        if ind is not None:
            val_actual = get_valor_osdr(crew, self.indicador_id, self.state.timepoint)
        else:
            frame = get_crew_hub().frame_actual(crew) or get_runtime().frame_actual(crew) or {}
            lect = (frame.get("lecturas") or {}).get(self.indicador_id)
            if isinstance(lect, dict):
                val_actual = lect.get("valor")
        self._texto_valor = "" if val_actual is None else str(val_actual)
        self._valor_precargado = True
        self.lbl_valor.setText(self._texto_valor or "–")
        unidad = (ind or param or {}).get("unidad", "")
        self.lbl_unidad.setText(unidad)

        if self.indicador_id in guias:
            self.lbl_dispositivo.setText(tr(guia.get("tituloDispositivo", "Analizador clínico portátil")))
        else:
            self.lbl_dispositivo.setText(tr("Registro manual de estación · {nom}", nom=nombre_corto((param or {}).get("nombre", self.indicador_id))))

        sexo = sexo_de(crew)
        rango_meta = ""
        if param:
            rango = (param.get("rangoReferenciaPorSexo") or {}).get(sexo) or param.get("rangoReferencia") or {}
            r_min, r_max = rango.get("min"), rango.get("max")
            fuente_u = param.get("fuenteUmbral", "dataset")
            if r_min is not None or r_max is not None:
                suf = " [POR VALIDAR]" if fuente_u == "por-validar" else ""
                rango_meta = tr(
                    "Ref. ({sexo}): {a} – {b} {u}{suf}",
                    sexo=sexo,
                    a=r_min if r_min is not None else "–",
                    b=r_max if r_max is not None else "–",
                    u=unidad,
                    suf=suf,
                )
        elif ind and ind.get("rangoReferencia"):
            r = ind["rangoReferencia"]
            rango_meta = tr(
                "Ref.: {a} – {b} {u}",
                a=r.get("min", "–"),
                b=r.get("max", "–"),
                u=unidad,
            )
        self.lbl_meta_param.setText(rango_meta)

        vaciar_layout(self.vbox_pasos)
        pasos_guia = guias[self.indicador_id].get("pasos", []) if self.indicador_id in guias else [
            {"orden": 1, "titulo": "Verificar sensor o lectura", "descripcion": "Confirma que el valor corresponde al tripulante y entorno seleccionados."},
            {"orden": 2, "titulo": "Ingresar y evaluar", "descripcion": "Captura el dato en el teclado táctil y revisa el nivel de triage antes de actuar."},
        ]
        for p in pasos_guia:
            w = QWidget()
            fila = QHBoxLayout(w)
            fila.setContentsMargins(0, 0, 0, 0)
            fila.setSpacing(18)
            num = QLabel(str(p["orden"]))
            num.setFixedSize(48, 48)
            num.setAlignment(Qt.AlignCenter)
            num.setStyleSheet(
                f"font-size: {t.T_DESTACADO}px; font-weight: 600; color: {t.TEXTO};"
                f"border: 1px solid {t.BORDE_SUAVE}; border-radius: 24px;"
            )
            fila.addWidget(num, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addWidget(etiqueta(p["titulo"], t.T_DESTACADO, t.TEXTO, peso=600, wrap=True))
            col.addWidget(etiqueta(p["descripcion"], t.T_CUERPO, t.TEXTO_SUAVE, wrap=True))
            fila.addLayout(col, 1)
            self.vbox_pasos.addWidget(w)

        fallo = guias.get(self.indicador_id, {}).get("modoFallo0G", {})
        self.caja_fallo.setVisible(bool(fallo))
        self.lbl_fallo.setText(
            tr(
                "Cuidado en 0G · {t}\n{d}",
                t=tr(fallo.get("titulo", "")),
                d=tr(fallo.get("detalle", "")),
            )
        )

        vaciar_layout(self.fila_resultado)
        self.lbl_resultado_msg.setText(
            tr("Escribe el valor del analizador y pulsa «Evaluar y guardar».")
        )

    def _registrar_lectura(self) -> None:
        try:
            val = float(self._texto_valor)
        except ValueError:
            self.lbl_resultado_msg.setText(tr("Escribe primero un valor con el teclado."))
            return
        entorno = self.state.entorno
        crew = self.state.crew_id
        res = evaluar_lectura_determinista(crew, self.indicador_id, val, calidad=1.0, entorno=entorno)
        param = get_param(self.indicador_id)
        nota_extra = self.txt_nota_med.text().strip() if hasattr(self, "txt_nota_med") else ""
        nota_local = _etiqueta_momento(self.state.timepoint)
        if nota_extra:
            nota_local = f"{nota_local} · {nota_extra}"
        guardar_medicion_local(
            crew_id=crew,
            indicador_id=self.indicador_id,
            valor=val,
            unidad=res.get("unidad", "") or (param or {}).get("unidad", ""),
            nivel_triage=res["nivel"],
            # Liga la toma al momento de la misión: sólo cuenta como «actual» ahí.
            notas=nota_local,
        )
        if hasattr(self, "txt_nota_med"):
            self.txt_nota_med.clear()
        sensor_row = guardar_medicion_sensor(
            crew_id=crew,
            parametro_id=self.indicador_id,
            valor=val,
            unidad=res.get("unidad", "") or (param or {}).get("unidad", ""),
            nivel=res["nivel"],
        )
        if sensor_row.get("ok") and sensor_row.get("id"):
            get_sync_manager().encolar_medicion(int(sensor_row["id"]), res["nivel"])
        self.lecturaGuardada.emit(self.indicador_id)
        texto, color = nivel_triage(res["nivel"])
        vaciar_layout(self.fila_resultado)
        self.fila_resultado.addWidget(pastilla(texto, color))
        self.fila_resultado.addWidget(
            etiqueta(
                tr("{d} % frente a tu base", d=f"{res['desvioPorcentajeBaseline']:+.0f}"),
                t.T_CUERPO,
                t.ETIQUETA,
            )
        )
        self.fila_resultado.addStretch(1)
        regla = res.get("reglaDisparada", "")
        fuente = res.get("fuente", "")
        extra = f"\n{regla} · {fuente}" if regla else ""
        self.lbl_resultado_msg.setText(
            f"{tr(res['accionSugerida'])}{extra}\n\n{tr('Guardado y encolado para Tierra ✓')}"
        )
        self._valor_precargado = True


# ===========================================================================
# 4. VISTA HISTORIAL
# ===========================================================================

class VistaHistorial(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._ids: List[str] = []
        self._manuales: List[Dict[str, Any]] = []
        self._vivo_por_param: Dict[str, List[Dict[str, Any]]] = {}
        self._fila_sel: int = 0
        self._seleccion = "glucose"
        self._modo_serie = "osdr"

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(28)

        col_izq = QVBoxLayout()
        col_izq.setSpacing(12)
        self.lbl_tit = etiqueta("Analíticas", t.T_TITULO, t.TEXTO, peso=500)
        col_izq.addWidget(self.lbl_tit)
        self.chips_fuente = GrupoChips(
            ["osdr", "vivo", "1min", "1h", "manuales"],
            etiquetas={
                "osdr": "OSDR OSD-575",
                "vivo": "En vivo 15 min",
                "1min": "Series 1 min",
                "1h": "Series 1 h",
                "manuales": "Manuales",
            },
        )
        self.chips_fuente.marcar("osdr")
        self.chips_fuente.seleccionado.connect(self._on_modo_serie)
        col_izq.addWidget(self.chips_fuente)

        self.tabla = QTableWidget()
        self.tabla.setColumnCount(4)
        self.tabla.setHorizontalHeaderLabels([tr("Analito"), tr("Base"), tr("Valor"), tr("Estado")])
        cab = self.tabla.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            cab.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        cab.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(62)
        self.tabla.setShowGrid(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setFocusPolicy(Qt.NoFocus)
        self.tabla.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        scroll_tactil(self.tabla)
        self.tabla.itemSelectionChanged.connect(self._on_fila)
        col_izq.addWidget(self.tabla, 1)
        raiz.addLayout(col_izq, 1)

        # Derecha: la tendencia del analito tocado
        col_der = QVBoxLayout()
        self.card = Tarjeta(margen=26, espacio=8)
        self.lbl_nombre = etiqueta("", 24, t.TEXTO, peso=600, wrap=True)
        self.card.capa.addWidget(self.lbl_nombre)
        fila_v = QHBoxLayout()
        self.lbl_valor = etiqueta("–", 56, None, peso=300)
        self.lbl_unidad = etiqueta("", t.T_DESTACADO, t.SECUNDARIO)
        fila_v.addWidget(self.lbl_valor, 0, Qt.AlignBottom)
        fila_v.addWidget(self.lbl_unidad, 0, Qt.AlignBottom)
        fila_v.addStretch(1)
        self.card.capa.addLayout(fila_v)
        self.lbl_rango = etiqueta("", t.T_CUERPO, t.SECUNDARIO, wrap=True)
        self.card.capa.addWidget(self.lbl_rango)
        self.grafica = GraficaTendencia(alto=230)
        self.card.capa.addWidget(self.grafica)
        self.btn_medir = boton(
            "Medir", estilo="primario",
            al_pulsar=lambda: self.state.ir_a("medir", indicadorId=self._seleccion),
        )
        self.card.capa.addSpacing(6)
        self.card.capa.addWidget(self.btn_medir)
        col_der.addWidget(self.card)
        col_der.addStretch(1)

        w_der = QWidget()
        w_der.setLayout(col_der)
        w_der.setFixedWidth(460)
        raiz.addWidget(w_der)

        self._pendiente_refresco = False
        self.state.crewChanged.connect(self.refrescar)
        self.state.timepointChanged.connect(self.refrescar)
        self.state.entornoCambiado.connect(self.refrescar)
        self.state.medicionRegistrada.connect(self.refrescar)
        self.state.telemetriaEnVivoActualizada.connect(self._on_vivo_historial)
        self.state.controlHistorialSolicitado.connect(self.seleccionar_analito)
        self.refrescar(forzar=True)

    def _on_modo_serie(self, modo: str) -> None:
        self._modo_serie = modo
        self.refrescar(forzar=True)

    def _on_vivo_historial(self) -> None:
        if self._modo_serie in ("vivo", "1min", "1h") and self.isVisible():
            self.refrescar(forzar=True)

    @staticmethod
    def _submuestrear_puntos(items: List[Dict[str, Any]], max_pts: int = 8) -> List[Dict[str, Any]]:
        if len(items) <= max_pts:
            return list(items)
        indices = [int(round(i * (len(items) - 1) / (max_pts - 1))) for i in range(max_pts)]
        return [items[idx] for idx in indices]

    def seleccionar_analito(self, ind_id: str, modo: Optional[str] = None) -> None:
        modos_validos = ("osdr", "vivo", "1min", "1h", "manuales")
        if modo in modos_validos and modo != self._modo_serie:
            self._modo_serie = modo
            self.chips_fuente.marcar(modo)
            self.refrescar(forzar=True)
        elif ind_id not in self._ids:
            objetivo = "osdr" if get_indicador_osdr(ind_id) else "vivo"
            if objetivo != self._modo_serie:
                self._modo_serie = objetivo
                self.chips_fuente.marcar(objetivo)
            self.refrescar(forzar=True)
        if ind_id in self._ids:
            row = self._ids.index(ind_id)
            self._seleccion = ind_id
            self.tabla.selectRow(row)
            self._mostrar(ind_id)

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self._pendiente_refresco:
            self._pendiente_refresco = False
            self.refrescar(forzar=True)

    def refrescar(self, *_args, forzar: bool = False) -> None:
        if not forzar and not self.isVisible():
            self._pendiente_refresco = True
            return
        self._pendiente_refresco = False
        crew = self.state.crew_id
        tp = self.state.timepoint
        entorno = self.state.entorno

        if self._modo_serie == "manuales":
            self._refrescar_manuales(crew)
            return

        if self._modo_serie == "osdr":
            indicadores = get_osdr_dataset().get("indicadores", [])
            self.lbl_tit.setText(tr("Analíticas · {crew} · {tp}", crew=crew, tp=tp))
            col_2_hdr = tr("Base")
            col_3_hdr = tp
        elif self._modo_serie == "vivo":
            indicadores = obtener_catalogo_parametros(entorno=entorno)
            self._vivo_por_param = {}
            for m in ventana_reciente(crew, minutos=15):
                self._vivo_por_param.setdefault(str(m.get("parametroId") or ""), []).append(m)
            self.lbl_tit.setText(tr("En vivo 15 min (1 Hz) · {crew}", crew=crew))
            col_2_hdr = tr("Mín / Máx (n)")
            col_3_hdr = tr("Último (1 Hz)")
        else:
            indicadores = obtener_catalogo_parametros(entorno=entorno)
            self.lbl_tit.setText(
                tr("Series {res} · {crew}", res=self._modo_serie, crew=crew)
            )
            col_2_hdr = tr("Mín / Máx")
            col_3_hdr = tr("Media ({res})", res=self._modo_serie)

        self.tabla.setUpdatesEnabled(False)
        self.tabla.blockSignals(True)
        try:
            self.tabla.setHorizontalHeaderLabels([tr("Analito"), col_2_hdr, col_3_hdr, tr("Estado")])
            self._ids = []
            self._manuales = []
            self.tabla.setRowCount(len(indicadores))
            fila_sel = 0
            for row, ind in enumerate(indicadores):
                ind_id = ind["id"]
                self._ids.append(ind_id)
                if ind_id == self._seleccion:
                    fila_sel = row
                if self._modo_serie == "osdr":
                    base = get_baseline(crew, ind_id)
                    val = get_valor_osdr(crew, ind_id, tp)
                    texto_estado, color = estado_triage(crew, ind_id, val, ind.get("rangoReferencia"))
                    celdas = [
                        nombre_corto(ind["nombre"]),
                        str(base["mediaPreVuelo"]),
                        f"{val if val is not None else '–'}  {ind['unidad']}",
                        tr(texto_estado),
                    ]
                elif self._modo_serie == "vivo":
                    muestras = self._vivo_por_param.get(ind_id, [])
                    if muestras:
                        vals = [float(x["valor"]) for x in muestras]
                        ultimo = muestras[-1]
                        val = float(ultimo["valor"])
                        rango_s = f"{min(vals):g} – {max(vals):g} ({len(vals)})"
                        texto_estado, color = nivel_triage(str(ultimo.get("nivel") or "NOMINAL"))
                    else:
                        val = None
                        rango_s = "–"
                        texto_estado, color = "Sin dato", t.TERCIARIO
                    celdas = [
                        nombre_corto(ind["nombre"]),
                        rango_s,
                        f"{val if val is not None else '–'}  {ind['unidad']}",
                        tr(texto_estado),
                    ]
                else:
                    series = listar_series(crew, ind_id, resolucion=self._modo_serie)
                    ultimo = series[-1] if series else None
                    val = ultimo["media"] if ultimo else None
                    rango_s = f"{ultimo['min']} – {ultimo['max']}" if ultimo else "–"
                    if val is not None:
                        ev = evaluar_lectura_determinista(crew, ind_id, float(val), entorno=entorno)
                        nivel = ev.get("nivel", "NOMINAL")
                        texto_estado, color = nivel_triage(nivel)
                    else:
                        texto_estado, color = "Sin dato", t.TERCIARIO
                    celdas = [
                        nombre_corto(ind["nombre"]),
                        rango_s,
                        f"{val if val is not None else '–'}  {ind['unidad']}",
                        tr(texto_estado),
                    ]
                for col, texto in enumerate(celdas):
                    item = QTableWidgetItem(texto)
                    if col == 1:
                        item.setForeground(QColor(t.SECUNDARIO))
                    if col == 3:
                        item.setForeground(QColor(color))
                    self.tabla.setItem(row, col, item)
            if self._ids:
                self._fila_sel = fila_sel
                self._seleccion = self._ids[fila_sel]
                self.tabla.selectRow(fila_sel)
        finally:
            self.tabla.blockSignals(False)
            self.tabla.setUpdatesEnabled(True)
        self._mostrar(self._seleccion)

    def _refrescar_manuales(self, crew: str) -> None:
        registros = listar_mediciones_locales(crew_id=crew, limit=100)
        self.lbl_tit.setText(tr("Mediciones manuales · {crew} ({n})", crew=crew, n=len(registros)))
        self.tabla.setUpdatesEnabled(False)
        self.tabla.blockSignals(True)
        try:
            self.tabla.setHorizontalHeaderLabels(
                [tr("Parámetro"), tr("Fecha / hora"), tr("Valor"), tr("Estado")]
            )
            self._manuales = registros
            self._ids = [str(r.get("indicadorId") or "") for r in registros]
            self.tabla.setRowCount(len(registros))
            for row, r in enumerate(registros):
                ind_id = str(r.get("indicadorId") or "")
                meta = get_indicador_osdr(ind_id) or get_param(ind_id) or {"nombre": ind_id}
                texto_est, color = nivel_triage(str(r.get("nivel") or "NOMINAL"))
                celdas = [
                    nombre_corto(str(meta.get("nombre") or ind_id)),
                    formatear_iso(r.get("createdAt")),
                    f"{r.get('valor', '–')}  {r.get('unidad', '')}",
                    tr(texto_est),
                ]
                for col, texto in enumerate(celdas):
                    item = QTableWidgetItem(texto)
                    if col == 1:
                        item.setForeground(QColor(t.SECUNDARIO))
                    if col == 3:
                        item.setForeground(QColor(color))
                    self.tabla.setItem(row, col, item)
            if self._ids:
                self._fila_sel = min(self._fila_sel, len(self._ids) - 1)
                self._seleccion = self._ids[self._fila_sel]
                self.tabla.selectRow(self._fila_sel)
            else:
                self._fila_sel = 0
        finally:
            self.tabla.blockSignals(False)
            self.tabla.setUpdatesEnabled(True)
        self._mostrar(self._seleccion)

    def _on_fila(self) -> None:
        filas = self.tabla.selectionModel().selectedRows()
        if filas and filas[0].row() < len(self._ids):
            self._fila_sel = filas[0].row()
            self._seleccion = self._ids[self._fila_sel]
            self._mostrar(self._seleccion)

    def _mostrar(self, ind_id: str) -> None:
        crew, tp = self.state.crew_id, self.state.timepoint
        if self._modo_serie == "manuales" and not self._manuales:
            self.lbl_nombre.setText(tr("Mediciones manuales en 0G"))
            self.lbl_valor.setText("–")
            self.lbl_unidad.setText("")
            self.lbl_rango.setText(
                tr("Todavía no hay tomas manuales registradas para {crew}.", crew=crew)
            )
            self.grafica.cargar([], None, None, None)
            self.btn_medir.setText(tr("Registrar medición"))
            return

        ind = get_indicador_osdr(ind_id)
        param = get_param(ind_id)
        if not ind and not param:
            return
        self.state.analito_historial = ind_id
        meta = ind or param or {}
        nombre = meta.get("nombre", ind_id)
        unidad = meta.get("unidad", "")
        sexo = sexo_de(crew)
        rango = ((param or {}).get("rangoReferenciaPorSexo") or {}).get(sexo) or meta.get("rangoReferencia") or {}
        r_min, r_max = rango.get("min"), rango.get("max")

        if self._modo_serie == "osdr" and ind is not None:
            val = get_valor_osdr(crew, ind_id, tp)
            base = get_baseline(crew, ind_id)
            self.lbl_nombre.setText(nombre_corto(nombre))
            self.lbl_valor.setText(f"{val if val is not None else '–'}")
            self.lbl_unidad.setText(unidad)
            self.lbl_rango.setText(
                tr(
                    "Rango {a} – {b}   ·   base {c}",
                    a=r_min if r_min is not None else "–",
                    b=r_max if r_max is not None else "–",
                    c=base["mediaPreVuelo"],
                )
            )
            self.grafica.cargar(ind.get("serie", {}).get(crew, []), r_min, r_max, tp)
        elif self._modo_serie == "vivo":
            muestras = self._vivo_por_param.get(ind_id, [])
            ultimo = muestras[-1] if muestras else None
            val = ultimo["valor"] if ultimo else None
            self.lbl_nombre.setText(nombre_corto(nombre))
            self.lbl_valor.setText(f"{val if val is not None else '–'}")
            self.lbl_unidad.setText(unidad)
            self.lbl_rango.setText(
                tr(
                    "Rango {a} – {b}   ·   {n} muestras (15 min · 1 Hz)",
                    a=r_min if r_min is not None else "–",
                    b=r_max if r_max is not None else "–",
                    n=len(muestras),
                )
            )
            sub = self._submuestrear_puntos(muestras, max_pts=8)
            pts = [
                {
                    "timepoint": formatear_ts_ms(s.get("timestamp"), con_fecha=False),
                    "valor": float(s["valor"]),
                }
                for s in sub
            ]
            activo = pts[-1]["timepoint"] if pts else None
            self.grafica.cargar(pts, r_min, r_max, activo)
        elif self._modo_serie == "manuales":
            sel_reg = (
                self._manuales[self._fila_sel]
                if 0 <= self._fila_sel < len(self._manuales)
                else self._manuales[0]
            )
            mismo = [r for r in reversed(self._manuales) if str(r.get("indicadorId") or "") == ind_id]
            sub = self._submuestrear_puntos(mismo, max_pts=8)
            pts = [
                {
                    "timepoint": f"#{r['id']}",
                    "valor": float(r["valor"]),
                }
                for r in sub
            ]
            nota_txt = str(sel_reg.get("notas") or "").strip() or tr("Sin notas clínicas")
            self.lbl_nombre.setText(nombre_corto(nombre))
            self.lbl_valor.setText(f"{sel_reg.get('valor', '–')}")
            self.lbl_unidad.setText(str(sel_reg.get("unidad") or unidad))
            self.lbl_rango.setText(
                tr(
                    "{fecha}   ·   Rango {a} – {b}\nNota: {nota}",
                    fecha=formatear_iso(sel_reg.get("createdAt")),
                    a=r_min if r_min is not None else "–",
                    b=r_max if r_max is not None else "–",
                    nota=nota_txt,
                )
            )
            self.grafica.cargar(pts, r_min, r_max, f"#{sel_reg['id']}")
        else:
            series = listar_series(crew, ind_id, resolucion=self._modo_serie)[-12:]
            ultimo = series[-1] if series else None
            val = ultimo["media"] if ultimo else None
            self.lbl_nombre.setText(nombre_corto(nombre))
            self.lbl_valor.setText(f"{val if val is not None else '–'}")
            self.lbl_unidad.setText(unidad)
            self.lbl_rango.setText(
                tr(
                    "Rango {a} – {b}   ·   {n} cubos ({res})",
                    a=r_min if r_min is not None else "–",
                    b=r_max if r_max is not None else "–",
                    n=len(series),
                    res=self._modo_serie,
                )
            )
            pts = [
                {
                    "timepoint": datetime.fromtimestamp(int(s["inicio"]) / 1000).strftime("%H:%M"),
                    "valor": float(s["media"]),
                }
                for s in series
            ]
            activo = pts[-1]["timepoint"] if pts else None
            self.grafica.cargar(pts, r_min, r_max, activo)
        self.btn_medir.setText(tr("Medir {x}", x=nombre_corto(nombre).lower()))

    def aplicar_tema(self) -> None:
        self.refrescar(forzar=True)
        self.grafica.update()


# ===========================================================================
# 5. VISTA EMERGENCIA
# ===========================================================================

# Paso clínico -> (herramienta ALSP, acto 0-based). Mismo mapa que la app web.
MAPA_ANIM_ALSP: Dict[str, List[Optional[tuple]]] = {
    "cardiovascular": [
        ("dea", 0),  # seguridad y respuesta
        ("dea", 4),  # fijación CMRS + compresiones
        ("dea", 1),  # colocación de parches
        ("via-aerea", 1),  # BVM y O2
        ("farmacos", 4),  # registro para el Flight Surgeon
    ],
    "respiratorio": [
        ("via-aerea", 1),  # sello de mascarilla y ventilación
        ("via-aerea", 0),  # alineación y aspiración
        None,
    ],
}


class VistaEmergencia(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.proto_activo = "cardiovascular"
        self._metronomo_on = False
        self._pulso = False
        self._paso_activo = 0
        self._botones_pasos: List[QPushButton] = []
        self._labels_pasos: List[QLabel] = []

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(24)

        # Izquierda: protocolos + metrónomo + control de alarma roja
        col_izq = QVBoxLayout()
        col_izq.setSpacing(5)
        col_izq.addWidget(etiqueta_mono("Protocolos"))
        col_izq.addSpacing(2)
        self.botones_proto: Dict[str, QPushButton] = {}
        for proto in get_protocolos_dataset().get("protocolos", []):
            pid = proto["id"]
            b = QPushButton(partir_en_dos(tr(proto["titulo"])))
            b.setObjectName("lista")
            b.setStyleSheet(f"font-size: {t.T_CUERPO}px;")
            b.setCheckable(True)
            b.setMinimumHeight(62)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=pid: self.seleccionar_protocolo(k))
            self.botones_proto[pid] = b
            col_izq.addWidget(b)

        col_izq.addSpacing(8)
        card_metro = Tarjeta(margen=14, espacio=8)
        card_metro.capa.addWidget(etiqueta_mono("Metrónomo RCP · 110 / min"))
        self.lbl_metro = QLabel(tr("En espera"))
        self.lbl_metro.setAlignment(Qt.AlignCenter)
        self.lbl_metro.setMinimumHeight(46)
        self._pintar_metro(False, activo=False)
        card_metro.capa.addWidget(self.lbl_metro)
        self.btn_metro = boton("Iniciar metrónomo", estilo="primario", al_pulsar=self._toggle_metronomo)
        card_metro.capa.addWidget(self.btn_metro)
        col_izq.addWidget(card_metro)

        col_izq.addSpacing(6)
        card_alarma = Tarjeta(margen=12, espacio=6)
        card_alarma.capa.addWidget(etiqueta_mono("Alarma sonora · Estado rojo"))
        self.lbl_alarma_em = etiqueta("", t.T_PEQUENO, t.SECUNDARIO, wrap=True)
        card_alarma.capa.addWidget(self.lbl_alarma_em)
        self.btn_alarma_em = boton("Probar tono suave", al_pulsar=self._accion_alarma_em)
        card_alarma.capa.addWidget(self.btn_alarma_em)
        col_izq.addWidget(card_alarma)
        col_izq.addStretch(1)

        w_izq = QWidget()
        w_izq.setLayout(col_izq)
        w_izq.setFixedWidth(330)
        raiz.addWidget(w_izq)

        # Centro: animación de la herramienta, sincronizada con el paso
        col_anim = QVBoxLayout()
        card_anim = Tarjeta(margen=20, espacio=10)

        self.anim = WidgetAnimacionALSP()
        self.anim.actoCambiado.connect(self._on_anim_acto)
        card_anim.capa.addWidget(self.anim, 1)

        self.lbl_anim_vacio = etiqueta(
            "Este paso no tiene animación. Elige una herramienta para ver su procedimiento.",
            t.T_CUERPO,
            t.TEXTO_SUAVE,
            wrap=True,
        )
        self.lbl_anim_vacio.setVisible(False)
        card_anim.capa.addWidget(self.lbl_anim_vacio)

        fila_chips = QHBoxLayout()
        fila_chips.setSpacing(8)
        self.chips_anim: Dict[str, QPushButton] = {}
        for eid, nombre in (("dea", "DEA"), ("iv", "Vía IV"), ("via-aerea", "Vía aérea"), ("farmacos", "Fármacos")):
            b = QPushButton(tr(nombre))
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setMinimumHeight(t.ALTO_TOQUE)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=eid: self._seleccionar_equipo_anim(k))
            self.chips_anim[eid] = b
            fila_chips.addWidget(b)
        card_anim.capa.addLayout(fila_chips)

        self.lbl_anim_meta = etiqueta("", t.T_PEQUENO, t.SECUNDARIO)
        self.lbl_anim_titulo = etiqueta("", t.T_DESTACADO, t.TEXTO, peso=600, wrap=True)
        self.lbl_anim_nota = etiqueta("", t.T_CUERPO, t.SECUNDARIO, wrap=True)
        card_anim.capa.addWidget(self.lbl_anim_meta)
        card_anim.capa.addWidget(self.lbl_anim_titulo)
        card_anim.capa.addWidget(self.lbl_anim_nota)

        fila_ctrl = QHBoxLayout()
        fila_ctrl.setSpacing(10)
        self.btn_anim_prev = boton("◀", al_pulsar=self.anim.anterior_acto)
        self.btn_anim_play = boton("Pausar", al_pulsar=self._toggle_anim)
        self.btn_anim_next = boton("▶", al_pulsar=self.anim.siguiente_acto)
        for b in (self.btn_anim_prev, self.btn_anim_next):
            b.setFixedWidth(84)
        fila_ctrl.addWidget(self.btn_anim_prev)
        fila_ctrl.addWidget(self.btn_anim_play, 1)
        fila_ctrl.addWidget(self.btn_anim_next)
        card_anim.capa.addLayout(fila_ctrl)
        card_anim.capa.addWidget(
            etiqueta("Entrenamiento · dosis y presiones [POR VALIDAR]", t.T_PEQUENO, t.TERCIARIO)
        )

        col_anim.addWidget(card_anim)
        self.w_anim = QWidget()
        self.w_anim.setLayout(col_anim)
        raiz.addWidget(self.w_anim, 5)

        # Derecha: pasos (desplazables) + alerta SBAR siempre a la vista
        col_der = QVBoxLayout()
        col_der.setSpacing(14)
        cont_pasos = QWidget()
        v_pasos = QVBoxLayout(cont_pasos)
        v_pasos.setContentsMargins(0, 0, 8, 0)
        v_pasos.setSpacing(6)
        self.lbl_codigo = etiqueta("", t.T_PEQUENO, t.ALERTA, peso=600)
        self.lbl_titulo = etiqueta("", 26, t.TEXTO, peso=600, wrap=True)
        self.lbl_equipo = etiqueta("", t.T_CUERPO, t.SECUNDARIO, wrap=True)
        v_pasos.addWidget(self.lbl_codigo)
        v_pasos.addWidget(self.lbl_titulo)
        v_pasos.addWidget(self.lbl_equipo)
        v_pasos.addSpacing(10)
        self.vbox_pasos = QVBoxLayout()
        self.vbox_pasos.setSpacing(20)
        v_pasos.addLayout(self.vbox_pasos)
        v_pasos.addSpacing(12)
        self.card_disparadores = Tarjeta(margen=16, espacio=8)
        self.card_disparadores.capa.addWidget(etiqueta_mono("Protocolos por disparador (lenguaje simple)"))
        self.vbox_disparadores = QVBoxLayout()
        self.vbox_disparadores.setSpacing(8)
        self.card_disparadores.capa.addLayout(self.vbox_disparadores)
        v_pasos.addWidget(self.card_disparadores)
        v_pasos.addStretch(1)
        col_der.addWidget(area_desplazable(cont_pasos), 1)

        self.btn_sos = boton("Pedir ayuda médica (SBAR)", estilo="peligro", al_pulsar=self._emitir_sos)
        self.btn_sos.setMinimumHeight(64)
        self.btn_hist_sbar = boton(
            "Ver historial SBAR y eventos",
            al_pulsar=lambda: self.state.ir_a("sala", panel="eventos"),
        )
        self.lbl_sos_ok = etiqueta("", t.T_CUERPO, t.TEXTO_SUAVE, wrap=True)
        col_der.addWidget(self.btn_sos)
        col_der.addWidget(self.btn_hist_sbar)
        col_der.addWidget(self.lbl_sos_ok)
        raiz.addLayout(col_der, 4)

        self._timer_metro = QTimer(self)
        self._timer_metro.timeout.connect(self._tick_metro)
        self.state.controlEmergenciaSolicitado.connect(self._ejecutar_control_emergencia)
        self.state.crewChanged.connect(self._refrescar_disparadores)
        self.state.telemetriaEnVivoActualizada.connect(self._on_vivo_disparadores)
        self.state.alarmaEmergenciaChanged.connect(self._on_alarma_emergencia_cambiada)
        self.seleccionar_protocolo("cardiovascular")
        self._refrescar_disparadores()
        self._on_alarma_emergencia_cambiada(
            self.state.alarma_roja_presente, self.state.alarma_emergencia_sonando
        )

    def _on_vivo_disparadores(self) -> None:
        if self.isVisible():
            self._refrescar_disparadores()

    def _refrescar_disparadores(self, *_args) -> None:
        crew = self.state.crew_id
        avisos = _avisos_actuales(crew, self.state.timepoint)
        activos_ids = set()
        for a in avisos:
            pid_disp = a.get("protocoloDisparadorId")
            if pid_disp:
                activos_ids.add(pid_disp)
            else:
                p_match = protocolo_para(a.get("indicadorId", ""), a.get("nivel", ""))
                if p_match:
                    activos_ids.add(p_match["id"])
        firma = f"{crew}|{self.state.timepoint}|{','.join(sorted(activos_ids))}"
        if firma == getattr(self, "_ultima_firma_disp", None):
            return
        self._ultima_firma_disp = firma
        vaciar_layout(self.vbox_disparadores)
        for p in listar_protocolos_disp():
            es_activo = p["id"] in activos_ids
            w = QWidget()
            vl = QVBoxLayout(w)
            vl.setContentsMargins(0, 4, 0, 4)
            vl.setSpacing(2)
            hl = QHBoxLayout()
            hl.addWidget(etiqueta(p.get("nombre", p["id"]), t.T_CUERPO, t.TEXTO, peso=600, wrap=True), 1)
            nivel_sev = (p.get("disparadores") or [{}])[0].get("nivel", "ATENCION")
            if es_activo:
                hl.addWidget(pastilla("Disparado", t.ALERTA))
            else:
                hl.addWidget(pastilla(t.texto_triage(nivel_sev), t.color_triage(nivel_sev)))
            vl.addLayout(hl)
            pasos_txt = " · ".join(
                f"{paso.get('orden', i + 1) if isinstance(paso, dict) else i + 1}. "
                f"{paso.get('texto', '') if isinstance(paso, dict) else paso}"
                for i, paso in enumerate(p.get("pasos", [])[:3])
            )
            vl.addWidget(etiqueta(pasos_txt, t.T_PEQUENO, t.TEXTO_SUAVE, wrap=True))
            vl.addWidget(
                etiqueta(
                    tr("Escalar a: {dest} [POR VALIDAR]", dest=p.get("escalarA", "CMO")),
                    11,
                    t.TERCIARIO,
                    wrap=True,
                )
            )
            self.vbox_disparadores.addWidget(w)
            self.vbox_disparadores.addWidget(divisor())

    def seleccionar_protocolo(self, proto_id: str) -> None:
        protocolos = get_protocolos_dataset().get("protocolos", [])
        proto = next((p for p in protocolos if p["id"] == proto_id), None)
        if proto is None:
            mapa = {
                "emergencia-cardiorrespiratoria": "cardiovascular",
                "hipercapnia-cabina": "respiratorio",
                "neuro-ocular": "neurologico",
            }
            mapped = mapa.get(proto_id, proto_id)
            proto = next((p for p in protocolos if p["id"] == mapped), protocolos[0])
        self.proto_activo = str(proto["id"])
        self.state.protocolo_emergencia_activo = self.proto_activo
        for k, b in self.botones_proto.items():
            b.setChecked(k == self.proto_activo)

        self.lbl_codigo.setText(f"{tr(proto['prioridad'])}  ·  {proto['codigo']}")
        self.lbl_titulo.setText(tr(proto["titulo"]))
        self.lbl_equipo.setText(tr("Equipo: {x}", x=tr(proto["equipoUbicacion"])))

        vaciar_layout(self.vbox_pasos)
        self._botones_pasos = []
        self._labels_pasos = []
        for i, p in enumerate(proto.get("pasos", [])):
            w = QWidget()
            fila = QHBoxLayout(w)
            fila.setContentsMargins(0, 0, 0, 0)
            fila.setSpacing(14)
            btn = QPushButton(str(p["orden"]))
            btn.setObjectName("pasoPlay")
            btn.setCheckable(True)
            btn.setFixedSize(52, 52)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=i: self._mostrar_paso(k))
            fila.addWidget(btn, 0, Qt.AlignTop)

            col = QVBoxLayout()
            col.setSpacing(4)
            lbl = etiqueta(p["titulo"], t.T_DESTACADO, t.TEXTO, peso=600, wrap=True)
            col.addWidget(lbl)
            col.addWidget(etiqueta(p["instruccion"], t.T_CUERPO, t.TEXTO_SUAVE, wrap=True))
            col.addWidget(
                etiqueta(tr("En 0G: {x}", x=tr(p["nota0G"])), t.T_PEQUENO, t.SECUNDARIO, wrap=True)
            )
            fila.addLayout(col, 1)
            self.vbox_pasos.addWidget(w)
            self._botones_pasos.append(btn)
            self._labels_pasos.append(lbl)

        self._mostrar_paso(0)

    def _pintar_estilos_pasos(self, idx: int) -> None:
        for i, lbl in enumerate(self._labels_pasos):
            lbl.setStyleSheet(
                f"font-family: '{t.FUENTE}'; font-size: {t.T_DESTACADO}px; font-weight: 600; "
                f"color: {t.TEXTO if i == idx else t.SECUNDARIO};"
            )

    def _mostrar_paso(self, idx: int) -> None:
        """Selecciona el paso y lleva la animación al acto que le corresponde."""
        if not self._botones_pasos:
            return
        idx = max(0, min(idx, len(self._botones_pasos) - 1))
        self._paso_activo = idx
        self.state.paso_emergencia = idx
        for i, b in enumerate(self._botones_pasos):
            b.setChecked(i == idx)
        self._pintar_estilos_pasos(idx)

        refs = MAPA_ANIM_ALSP.get(self.proto_activo, [])
        ref = refs[idx] if idx < len(refs) else None
        if ref:
            self.anim.setVisible(True)
            self.lbl_anim_vacio.setVisible(False)
            self.anim.reproduciendo = True
            self.anim.set_equipo(ref[0], ref[1])
            self.btn_anim_play.setText(tr("Pausar"))
        else:
            self.anim.setVisible(False)
            self.lbl_anim_vacio.setVisible(True)
            self.lbl_anim_meta.setText("")
            self.lbl_anim_titulo.setText(tr("Sin animación para este paso"))
            self.lbl_anim_nota.setText("")
            for b in self.chips_anim.values():
                b.setChecked(False)

    def _seleccionar_equipo_anim(self, equipo_id: str) -> None:
        """Navegación libre por las cuatro herramientas del ALSP."""
        for b in self._botones_pasos:
            b.setChecked(False)
        self.anim.setVisible(True)
        self.lbl_anim_vacio.setVisible(False)
        self.anim.reproduciendo = True
        self.anim.set_equipo(equipo_id, 0)
        self.btn_anim_play.setText(tr("Pausar"))

    def _toggle_anim(self) -> None:
        self.anim.toggle()
        self.btn_anim_play.setText(tr("Pausar") if self.anim.reproduciendo else tr("Reproducir"))

    def _on_anim_acto(self, _acto: int) -> None:
        self.state.equipo_alsp_activo = self.anim.equipo_id
        self.state.acto_alsp_activo = self.anim.acto
        pasos = self.anim.pasos()
        if not pasos:
            return
        self.lbl_anim_meta.setText(
            tr("{cod} · paso {n} de {t}", cod=self.anim.codigo(), n=self.anim.acto + 1, t=len(pasos))
        )
        self.lbl_anim_titulo.setText(tr(self.anim.paso_actual().get("titulo", "")))
        nota = self.anim.paso_actual().get("nota0G", "")
        self.lbl_anim_nota.setText(tr("En 0G: {x}", x=tr(nota)) if nota else "")
        for eid, b in self.chips_anim.items():
            b.setChecked(eid == self.anim.equipo_id)

    def _pintar_metro(self, compresion: bool, activo: bool = True) -> None:
        if not activo:
            fondo, color, texto = t.TARJETA, t.SECUNDARIO, tr("En espera")
        elif compresion:
            fondo, color, texto = t.METRO_COMP_BG, t.METRO_COMP_FG, tr("COMPRIME")
        else:
            fondo, color, texto = t.HOVER, t.TEXTO_SUAVE, tr("suelta")
        self.lbl_metro.setText(texto)
        self.lbl_metro.setStyleSheet(
            f"font-family: '{t.FUENTE}'; font-size: 24px; font-weight: 600; color: {color};"
            f"background: {fondo}; border-radius: 14px;"
        )

    def aplicar_tema(self) -> None:
        self.anim.update()
        self._pintar_metro(self._pulso, activo=self._metronomo_on)
        self._pintar_estilos_pasos(self._paso_activo)
        self._ultima_firma_disp = None
        self._refrescar_disparadores()

    def _toggle_metronomo(self) -> None:
        self._metronomo_on = not self._metronomo_on
        self.state.metronomo_activo = self._metronomo_on
        if self._metronomo_on:
            self._timer_metro.start(545)  # 110 LPM
            self.btn_metro.setText(tr("Detener metrónomo"))
        else:
            self._timer_metro.stop()
            self._pintar_metro(False, activo=False)
            self.btn_metro.setText(tr("Iniciar metrónomo"))

    def _ejecutar_control_emergencia(self, tipo: str, datos: Dict[str, Any]) -> None:
        if tipo == "paso":
            proto = datos.get("protocoloId")
            if proto and proto != self.proto_activo:
                self.seleccionar_protocolo(str(proto))
            if "delta" in datos:
                idx = self._paso_activo + int(datos["delta"])
            else:
                idx = int(datos.get("paso", 0))
            self._mostrar_paso(idx)
        elif tipo == "alsp":
            eq = str(datos.get("equipoId") or "").strip().lower()
            cmd = str(datos.get("comando") or "seleccionar").strip().lower()
            if eq in ("dea", "iv", "via-aerea", "farmacos"):
                self._seleccionar_equipo_anim(eq)
                if "paso" in datos and datos["paso"] is not None:
                    self.anim.set_equipo(eq, int(datos["paso"]))
            if cmd == "pausar" and self.anim.reproduciendo:
                self._toggle_anim()
            elif cmd == "reproducir" and not self.anim.reproduciendo:
                self._toggle_anim()
            elif cmd == "siguiente":
                self.anim.siguiente_acto()
            elif cmd == "anterior":
                self.anim.anterior_acto()
        elif tipo == "metronomo":
            accion = str(datos.get("accion") or "alternar").strip().lower()
            if accion == "iniciar" and not self._metronomo_on:
                self._toggle_metronomo()
            elif accion == "detener" and self._metronomo_on:
                self._toggle_metronomo()
            elif accion == "alternar":
                self._toggle_metronomo()

    def _tick_metro(self) -> None:
        self._pulso = not self._pulso
        self._pintar_metro(self._pulso)

    def _on_alarma_emergencia_cambiada(self, hay_rojo: bool, sonando: bool) -> None:
        if not hasattr(self, "lbl_alarma_em") or not isValid(self) or not isValid(self.lbl_alarma_em):
            return
        if not bool(self.state.config.get("alarmaEmergenciaSonora", True)):
            self.lbl_alarma_em.setText(tr("Desactivada en Ajustes"))
            self.lbl_alarma_em.setStyleSheet(f"color: {t.SECUNDARIO}; font-size: {t.T_PEQUENO}px;")
            self.btn_alarma_em.setText(tr("Configurar alarma"))
        elif not hay_rojo:
            self.lbl_alarma_em.setText(tr("En espera (sin estado rojo activo)"))
            self.lbl_alarma_em.setStyleSheet(f"color: {t.SECUNDARIO}; font-size: {t.T_PEQUENO}px;")
            self.btn_alarma_em.setText(tr("Probar tono suave"))
        elif sonando:
            self.lbl_alarma_em.setText(tr("Pulso intermitente activo (sin tono estridente)"))
            self.lbl_alarma_em.setStyleSheet(
                f"color: {t.ALERTA}; font-size: {t.T_PEQUENO}px; font-weight: 600;"
            )
            self.btn_alarma_em.setText(tr("Silenciar alarma"))
        else:
            self.lbl_alarma_em.setText(tr("Alarma silenciada para el episodio actual"))
            self.lbl_alarma_em.setStyleSheet(f"color: {t.TEXTO_SUAVE}; font-size: {t.T_PEQUENO}px;")
            self.btn_alarma_em.setText(tr("Reactivar alarma"))

    def _accion_alarma_em(self) -> None:
        if not bool(self.state.config.get("alarmaEmergenciaSonora", True)):
            self.state.ir_a("lis")
        elif not self.state.alarma_roja_presente:
            self.state.controlEmergenciaSolicitado.emit("alarma", {"accion": "pulso"})
        elif self.state.alarma_emergencia_sonando:
            self.state.controlEmergenciaSolicitado.emit("alarma", {"accion": "silenciar"})
        else:
            self.state.controlEmergenciaSolicitado.emit("alarma", {"accion": "reactivar"})

    def _emitir_sos(self) -> None:
        nueva = crear_solicitud_ayuda(
            crew_id_solicitante=self.state.crew_id,
            destinatario="CMO_A_BORDO_C001",
            nivel="CRITICO",
            motivo=tr(
                "Activación de protocolo {p} por {c}",
                p=self.proto_activo.upper(),
                c=self.state.crew_id,
            ),
            resumen_clinico=tr(
                "Protocolo {p} activado en consola nativa V.I.T.A.L.I.S.", p=self.proto_activo
            ),
            protocolo_sugerido_id=self.proto_activo,
        )
        self.lbl_sos_ok.setText(tr("✓ Alerta {hash} enviada al oficial médico y a Tierra.", hash=nueva["hash"]))
        self.state.ayudaCambiada.emit()


# ===========================================================================
# 6. VISTA AJUSTES (todas las opciones en un solo sitio)
# ===========================================================================

TEMAS_UI = {"oscuro": "Oscuro", "claro": "Claro"}
PERSONALIDADES_UI = {"jarvis-cordial": "Cordial", "directo-clinico": "Directo"}
ESCALAS_UI = {"1.0": "Normal", "1.15": "Grande", "1.3": "Muy grande"}
TIEMPOS_MIC = {"3.0": "3 s", "4.5": "4.5 s", "7.0": "7 s"}
TONOS_ALARMA_UI = {
    "doble-suave": "Doble pulso",
    "pulso-unico": "Pulso único",
    "acorde-tibio": "Acorde suave",
}
INTERVALOS_ALARMA_UI = {
    "2000": "2 s",
    "2800": "2.8 s",
    "4500": "4.5 s",
    "6000": "6 s",
}

MOTORES_IA = {
    "cloud-api-auto": "IA en la nube",
    "ollama-local": "IA local",
    "determinista-puro": "Sin IA",
}

DESCRIPCIONES_MOTOR = {
    "cloud-api-auto": "Conversación libre y natural con el proveedor cloud configurado (requiere conexión).",
    "ollama-local": "Modelo privado en tu equipo vía Ollama (100 % sin internet).",
    "determinista-puro": "Responde al instante sólo con reglas clínicas y datos verificados de NASA OSDR.",
}

VOCES = (
    ("JARVIS (calidad estudio)", "jarvis-clone-latam"),
    ("JARVIS (timbre clásico)", "jarvis-clone-classic"),
    ("Jorge (rápida)", "es-MX-JorgeNeural"),
    ("Álvaro (rápida, castellano)", "es-ES-AlvaroNeural"),
    ("Dalia (rápida, femenina)", "es-MX-DaliaNeural"),
    ("Guy (rápida, inglés)", "en-US-GuyNeural"),
    ("Aria (rápida, femenina, inglés)", "en-US-AriaNeural"),
)


def fila_ajuste(titulo: str, descripcion: str, control: QWidget) -> QWidget:
    """Una opción: texto a la izquierda, control a la derecha, todo tocable."""
    w = QWidget()
    fila = QHBoxLayout(w)
    fila.setContentsMargins(0, 12, 0, 12)
    fila.setSpacing(24)
    col = QVBoxLayout()
    col.setSpacing(2)
    col.addWidget(etiqueta(titulo, t.T_CUERPO + 1, t.TEXTO))
    if descripcion:
        col.addWidget(etiqueta(descripcion, t.T_PEQUENO, t.SECUNDARIO, wrap=True))
    fila.addLayout(col, 1)
    fila.addWidget(control, 0, Qt.AlignVCenter)
    return w


class VistaAjustes(QWidget):
    estadoCloudListo = Signal(str)
    motoresVerificados = Signal(dict)

    def __init__(self, state: AppState, motor_voz: MotorVozNativo) -> None:
        super().__init__()
        self.state = state
        self.motor_voz = motor_voz
        self._pendiente_refresco = False
        self._verificando_motores = False
        self._timer_vel = QTimer(self)
        self._timer_vel.setSingleShot(True)
        self._timer_vel.setInterval(180)
        self._timer_vel.timeout.connect(self._guardar_vel_debounced)
        self._timer_vol_alarma = QTimer(self)
        self._timer_vol_alarma.setSingleShot(True)
        self._timer_vol_alarma.setInterval(160)
        self._timer_vol_alarma.timeout.connect(self._guardar_vol_alarma_debounced)
        self._timer_vol_monitor = QTimer(self)
        self._timer_vol_monitor.setSingleShot(True)
        self._timer_vol_monitor.setInterval(160)
        self._timer_vol_monitor.timeout.connect(self._guardar_vol_monitor_debounced)

        self.estadoCloudListo.connect(self._mostrar_resultado_cloud)
        self.motoresVerificados.connect(self._aplicar_estado_motores)
        cfg = self.state.config

        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        contenido = QWidget()
        col = QVBoxLayout(contenido)
        col.setContentsMargins(0, 0, 12, 24)
        col.setSpacing(20)
        col.addWidget(etiqueta("Ajustes", t.T_TITULO, t.TEXTO, peso=500))

        # --- Tripulante y momento de la misión ---
        c_crew = Tarjeta(margen=26, espacio=10)
        c_crew.capa.addWidget(etiqueta_mono("Tripulante"))
        self.chips_crew = GrupoChips(CREW_IDS, estilo="chip", columnas=4, espacio=10)
        self.chips_crew.marcar(self.state.crew_id)
        self.chips_crew.seleccionado.connect(self.state.set_crew)
        c_crew.capa.addWidget(self.chips_crew)
        self.lbl_rol = etiqueta("", t.T_CUERPO, t.SECUNDARIO)
        c_crew.capa.addWidget(self.lbl_rol)
        c_crew.capa.addSpacing(10)
        c_crew.capa.addWidget(etiqueta_mono("Momento de la misión"))
        self.chips_tp = GrupoChips(TIMEPOINTS, estilo="chipTp", columnas=7, espacio=8)
        self.chips_tp.marcar(self.state.timepoint)
        self.chips_tp.seleccionado.connect(self.state.set_timepoint)
        c_crew.capa.addWidget(self.chips_tp)
        c_crew.capa.addWidget(
            etiqueta("L = días antes del lanzamiento · R = días después del regreso", t.T_PEQUENO, t.SECUNDARIO)
        )
        col.addWidget(c_crew)

        # --- Pantalla y fluidez ---
        c_pant = Tarjeta(margen=26, espacio=2)
        c_pant.capa.addWidget(etiqueta_mono("Pantalla y fluidez"))
        tema_actual = str(cfg.get("temaVisual", "oscuro"))
        self.chips_tema = GrupoChips(list(TEMAS_UI), estilo="chip", etiquetas=TEMAS_UI, espacio=8)
        self.chips_tema.marcar(tema_actual if tema_actual in TEMAS_UI else "oscuro")
        self.chips_tema.seleccionado.connect(lambda v: self.state.actualizar_config(temaVisual=v))
        c_pant.capa.addWidget(
            fila_ajuste(
                "Aspecto de la pantalla",
                "Usa el modo oscuro en entornos tenues o el modo claro con iluminación intensa.",
                self.chips_tema,
            )
        )
        c_pant.capa.addWidget(divisor())

        escala_actual = str(cfg.get("escalaUI", "1.0"))
        self.chips_escala = GrupoChips(list(ESCALAS_UI), estilo="chip", etiquetas=ESCALAS_UI, espacio=8)
        self.chips_escala.marcar(escala_actual if escala_actual in ESCALAS_UI else "1.0")
        self.chips_escala.seleccionado.connect(self._on_escala)
        c_pant.capa.addWidget(fila_ajuste("Tamaño del texto", "Se aplica al reiniciar la aplicación.", self.chips_escala))
        self.btn_reiniciar = boton("Reiniciar ahora", al_pulsar=self._reiniciar_app)
        self.btn_reiniciar.setVisible(
            escala_actual != os.environ.get("VITALIS_ESCALA_APLICADA", "1.0")
        )
        c_pant.capa.addWidget(self.btn_reiniciar, 0, Qt.AlignRight)
        c_pant.capa.addWidget(divisor())

        self.sw_anim3d = Interruptor(bool(cfg.get("animacion3D", True)))
        self.sw_anim3d.cambiado.connect(lambda v: self.state.actualizar_config(animacion3D=v))
        c_pant.capa.addWidget(
            fila_ajuste(
                "Animaciones 3D suaves",
                "Transiciones de cámara y pulso en órganos (desactívalo para respuesta instantánea o ahorro de energía).",
                self.sw_anim3d,
            )
        )
        c_pant.capa.addWidget(divisor())

        self.sw_avisos = Interruptor(bool(cfg.get("mostrarAvisosEmergentes", True)))
        self.sw_avisos.cambiado.connect(lambda v: self.state.actualizar_config(mostrarAvisosEmergentes=v))
        c_pant.capa.addWidget(
            fila_ajuste(
                "Avisos emergentes en pantalla",
                "Muestra alertas flotantes al cambiar de tripulante o etapa; si se apaga, quedan en el botón superior.",
                self.sw_avisos,
            )
        )
        col.addWidget(c_pant)

        # --- Alarma sonora de emergencia (estado rojo) ---
        c_alarma = Tarjeta(margen=26, espacio=2)
        c_alarma.capa.addWidget(etiqueta_mono("Alarma sonora de emergencia"))

        self.sw_alarma_sonora = Interruptor(bool(cfg.get("alarmaEmergenciaSonora", True)))
        self.sw_alarma_sonora.cambiado.connect(
            lambda v: self.state.actualizar_config(alarmaEmergenciaSonora=v)
        )
        c_alarma.capa.addWidget(
            fila_ajuste(
                "Activar alarma en estado rojo",
                "Emite un pulso intermitente suave y no estridente mientras exista un estado crítico activo; se pausa automáticamente si L.I.S. habla o escucha.",
                self.sw_alarma_sonora,
            )
        )
        c_alarma.capa.addWidget(divisor())

        tono_actual = str(cfg.get("alarmaEmergenciaTono", "doble-suave"))
        self.chips_tono_alarma = GrupoChips(
            list(TONOS_ALARMA_UI), estilo="chip", etiquetas=TONOS_ALARMA_UI, espacio=8
        )
        self.chips_tono_alarma.marcar(
            tono_actual if tono_actual in TONOS_ALARMA_UI else "doble-suave"
        )
        self.chips_tono_alarma.seleccionado.connect(
            lambda v: self.state.actualizar_config(alarmaEmergenciaTono=v)
        )
        c_alarma.capa.addWidget(
            fila_ajuste(
                "Timbre del pulso",
                "Señales sinusoidales cálidas diseñadas para avisar sin alarmar en exceso.",
                self.chips_tono_alarma,
            )
        )
        c_alarma.capa.addWidget(divisor())

        try:
            int_actual = str(int(cfg.get("alarmaEmergenciaIntervaloMs", 2800)))
        except Exception:
            int_actual = "2800"
        self.chips_intervalo_alarma = GrupoChips(
            list(INTERVALOS_ALARMA_UI),
            estilo="chip",
            etiquetas=INTERVALOS_ALARMA_UI,
            espacio=8,
        )
        self.chips_intervalo_alarma.marcar(
            int_actual if int_actual in INTERVALOS_ALARMA_UI else "2800"
        )
        self.chips_intervalo_alarma.seleccionado.connect(
            lambda v: self.state.actualizar_config(alarmaEmergenciaIntervaloMs=int(v))
        )
        c_alarma.capa.addWidget(
            fila_ajuste(
                "Intervalo entre pulsos",
                "Pausa entre avisos mientras el episodio crítico no haya sido silenciado.",
                self.chips_intervalo_alarma,
            )
        )
        c_alarma.capa.addWidget(divisor())

        w_vol = QWidget()
        h_vol = QHBoxLayout(w_vol)
        h_vol.setContentsMargins(0, 0, 0, 0)
        h_vol.setSpacing(14)
        self.slider_vol_alarma = QSlider(Qt.Horizontal)
        self.slider_vol_alarma.setRange(25, 100)
        self.slider_vol_alarma.setFixedWidth(240)
        try:
            vol_init = int(round(float(cfg.get("alarmaEmergenciaVolumen", 0.70)) * 100))
        except Exception:
            vol_init = 70
        self.slider_vol_alarma.setValue(max(25, min(100, vol_init)))
        self.slider_vol_alarma.valueChanged.connect(self._on_vol_alarma)
        self.lbl_vol_alarma = etiqueta("", t.T_CUERPO, t.TEXTO)
        self.lbl_vol_alarma.setFixedWidth(64)
        h_vol.addWidget(self.slider_vol_alarma)
        h_vol.addWidget(self.lbl_vol_alarma)
        self._on_vol_alarma(self.slider_vol_alarma.value(), guardar=False)
        c_alarma.capa.addWidget(
            fila_ajuste(
                "Volumen del aviso",
                "Rango acotado para evitar sobresaltos en cabina o con auriculares.",
                w_vol,
            )
        )
        c_alarma.capa.addWidget(divisor())

        self.sw_alarma_sbar = Interruptor(bool(cfg.get("alarmaEmergenciaIncluirSbar", True)))
        self.sw_alarma_sbar.cambiado.connect(
            lambda v: self.state.actualizar_config(alarmaEmergenciaIncluirSbar=v)
        )
        c_alarma.capa.addWidget(
            fila_ajuste(
                "Incluir solicitudes médicas SBAR",
                "Mantiene la alarma intermitente también cuando existe una alerta SBAR abierta.",
                self.sw_alarma_sbar,
            )
        )
        c_alarma.capa.addWidget(divisor())

        w_prob_alarma = QWidget()
        h_prob_a = QHBoxLayout(w_prob_alarma)
        h_prob_a.setContentsMargins(0, 0, 0, 0)
        h_prob_a.setSpacing(8)
        self.btn_probar_alarma = boton("Probar tono suave", al_pulsar=self._probar_alarma)
        h_prob_a.addWidget(self.btn_probar_alarma)
        c_alarma.capa.addWidget(
            fila_ajuste("Probar alarma sonora", "", w_prob_alarma)
        )
        self.lbl_estado_alarma_cfg = etiqueta("", t.T_PEQUENO, t.SECUNDARIO, wrap=True)
        c_alarma.capa.addWidget(self.lbl_estado_alarma_cfg)
        self._actualizar_estado_alarma_cfg()
        c_alarma.capa.addWidget(divisor())

        self.sw_monitor_overview = Interruptor(bool(cfg.get("sonidoMonitorOverview", True)))
        self.sw_monitor_overview.cambiado.connect(
            lambda v: self.state.actualizar_config(sonidoMonitorOverview=v)
        )
        c_alarma.capa.addWidget(
            fila_ajuste(
                "Sonido de monitor en Overview",
                "Emite un pulso hospitalario en tiempo real sincronizado con la frecuencia cardíaca (acelera según los lpm) y modulado por la SpO₂.",
                self.sw_monitor_overview,
            )
        )
        c_alarma.capa.addWidget(divisor())

        w_vol_m = QWidget()
        h_vol_m = QHBoxLayout(w_vol_m)
        h_vol_m.setContentsMargins(0, 0, 0, 0)
        h_vol_m.setSpacing(14)
        self.slider_vol_monitor = QSlider(Qt.Horizontal)
        self.slider_vol_monitor.setRange(15, 100)
        self.slider_vol_monitor.setFixedWidth(240)
        try:
            vol_m_init = int(round(float(cfg.get("volumenMonitorOverview", 0.35)) * 100))
        except Exception:
            vol_m_init = 35
        self.slider_vol_monitor.setValue(max(15, min(100, vol_m_init)))
        self.slider_vol_monitor.valueChanged.connect(self._on_vol_monitor)
        self.lbl_vol_monitor = etiqueta("", t.T_CUERPO, t.TEXTO)
        self.lbl_vol_monitor.setFixedWidth(64)
        h_vol_m.addWidget(self.slider_vol_monitor)
        h_vol_m.addWidget(self.lbl_vol_monitor)
        self._on_vol_monitor(self.slider_vol_monitor.value(), guardar=False)
        c_alarma.capa.addWidget(
            fila_ajuste(
                "Volumen del monitor cardíaco",
                "Nivel suave independiente de la voz de L.I.S. y de la alarma roja.",
                w_vol_m,
            )
        )
        col.addWidget(c_alarma)

        # --- Idioma de la aplicación (interfaz + asistente) ---
        c_idioma = Tarjeta(margen=26, espacio=10)
        c_idioma.capa.addWidget(etiqueta_mono("Idioma"))
        self._idioma_sel = i18n.idioma()
        self._idiomas = i18n.idiomas_disponibles()
        etiquetas_idiomas = {i["codigo"]: i["nativo"] for i in self._idiomas}
        self.chips_idioma = GrupoChips(
            list(etiquetas_idiomas), estilo="chip", etiquetas=etiquetas_idiomas, espacio=8
        )
        self.chips_idioma.marcar(self._idioma_sel)
        self.chips_idioma.seleccionado.connect(self._cambiar_idioma)
        c_idioma.capa.addWidget(
            fila_ajuste(
                "Idioma de la aplicación",
                "Cambia toda la interfaz, las alertas y las respuestas del asistente.",
                self.chips_idioma,
            )
        )
        c_idioma.capa.addWidget(divisor())
        fila_idioma = QHBoxLayout()
        fila_idioma.setSpacing(12)
        self.btn_idioma_pack = boton("Descargar idioma", al_pulsar=self._descargar_idioma)
        self.lbl_idioma_estado = etiqueta("", t.T_PEQUENO, t.SECUNDARIO, wrap=True)
        fila_idioma.addWidget(self.btn_idioma_pack)
        fila_idioma.addWidget(self.lbl_idioma_estado, 1)
        c_idioma.capa.addLayout(fila_idioma)
        self._pintar_estado_idioma()
        col.addWidget(c_idioma)

        # --- Asistente L.I.S. ---
        c_lis = Tarjeta(margen=26, espacio=0)
        c_lis.capa.addWidget(etiqueta_mono("Asistente L.I.S."))
        self.sw_mostrar = Interruptor(bool(cfg.get("mostrarAsistente", True)))
        self.sw_mostrar.cambiado.connect(lambda v: self.state.actualizar_config(mostrarAsistente=v))
        c_lis.capa.addWidget(fila_ajuste("Mostrar el asistente", "Botón flotante en todas las pantallas.", self.sw_mostrar))
        c_lis.capa.addWidget(divisor())
        self.sw_voz = Interruptor(bool(cfg.get("vozActiva", True)))
        self.sw_voz.cambiado.connect(lambda v: self.state.actualizar_config(vozActiva=v))
        c_lis.capa.addWidget(fila_ajuste("Respuestas en voz alta", "", self.sw_voz))
        c_lis.capa.addWidget(divisor())

        self.combo_voz = QComboBox()
        self.combo_voz.setMinimumWidth(320)
        for nombre, vid in VOCES:
            self.combo_voz.addItem(tr(nombre), vid)
        idx_v = self.combo_voz.findData(cfg.get("vozId", "jarvis-clone-latam"))
        if idx_v >= 0:
            self.combo_voz.setCurrentIndex(idx_v)
        self.combo_voz.currentIndexChanged.connect(
            lambda: (
                self.state.actualizar_config(vozId=self.combo_voz.currentData()),
                self.refrescar(forzar=True),
            )
        )
        c_lis.capa.addWidget(
            fila_ajuste(
                "Voz",
                "Las voces rápidas responden con menor latencia que el clon de estudio.",
                self.combo_voz,
            )
        )
        c_lis.capa.addWidget(divisor())

        w_vel = QWidget()
        h_vel = QHBoxLayout(w_vel)
        h_vel.setContentsMargins(0, 0, 0, 0)
        h_vel.setSpacing(14)
        self.slider_vel = QSlider(Qt.Horizontal)
        self.slider_vel.setRange(85, 145)
        self.slider_vel.setFixedWidth(260)
        self.slider_vel.setValue(int(float(cfg.get("velocidadVoz", 1.04)) * 100))
        self.slider_vel.valueChanged.connect(self._on_vel)
        self.lbl_vel = etiqueta("", t.T_CUERPO, t.TEXTO)
        self.lbl_vel.setFixedWidth(64)
        h_vel.addWidget(self.slider_vel)
        h_vel.addWidget(self.lbl_vel)
        self._on_vel(self.slider_vel.value(), guardar=False)
        c_lis.capa.addWidget(fila_ajuste("Velocidad de la voz", "", w_vel))
        c_lis.capa.addWidget(divisor())

        mic_actual = f"{float(cfg.get('duracionMicrofonoSeg', 4.5)):.1f}"
        self.chips_mic = GrupoChips(list(TIEMPOS_MIC), estilo="chip", etiquetas=TIEMPOS_MIC, espacio=8)
        self.chips_mic.marcar(mic_actual if mic_actual in TIEMPOS_MIC else "4.5")
        self.chips_mic.seleccionado.connect(
            lambda v: self.state.actualizar_config(duracionMicrofonoSeg=float(v))
        )
        c_lis.capa.addWidget(
            fila_ajuste("Escucha del micrófono", "Ventana de captura de voz por clic.", self.chips_mic)
        )
        c_lis.capa.addWidget(divisor())

        pers_actual = str(cfg.get("personalidad", "jarvis-cordial"))
        self.chips_pers = GrupoChips(
            list(PERSONALIDADES_UI), estilo="chip", etiquetas=PERSONALIDADES_UI, espacio=8
        )
        self.chips_pers.marcar(pers_actual if pers_actual in PERSONALIDADES_UI else "jarvis-cordial")
        self.chips_pers.seleccionado.connect(lambda v: self.state.actualizar_config(personalidad=v))
        c_lis.capa.addWidget(
            fila_ajuste(
                "Estilo de trato",
                "Cordial estilo L.I.S. o directo y breve en maniobras.",
                self.chips_pers,
            )
        )
        c_lis.capa.addWidget(divisor())

        self.lbl_estado_jarvis = etiqueta("Comprobando motor de voz…", t.T_PEQUENO, t.SECUNDARIO)
        w_probar = QWidget()
        h_prob = QHBoxLayout(w_probar)
        h_prob.setContentsMargins(0, 0, 0, 0)
        h_prob.setSpacing(8)
        h_prob.addWidget(boton("Probar voz", al_pulsar=self._probar_voz))
        c_lis.capa.addWidget(fila_ajuste("Probar la voz", "", w_probar))
        c_lis.capa.addWidget(self.lbl_estado_jarvis)
        c_lis.capa.addWidget(divisor())

        self.sw_nav = Interruptor(bool(cfg.get("permitirNavegacionAutonoma", True)))
        self.sw_nav.cambiado.connect(lambda v: self.state.actualizar_config(permitirNavegacionAutonoma=v))
        c_lis.capa.addWidget(fila_ajuste("Puede cambiar de pantalla", "Cuando se lo pides por voz o texto.", self.sw_nav))
        c_lis.capa.addWidget(divisor())
        self.sw_param = Interruptor(bool(cfg.get("permitirControlParametros", True)))
        self.sw_param.cambiado.connect(lambda v: self.state.actualizar_config(permitirControlParametros=v))
        c_lis.capa.addWidget(fila_ajuste("Puede cambiar tripulante, momento y vista 3D", "", self.sw_param))
        c_lis.capa.addWidget(divisor())
        self.sw_sos = Interruptor(bool(cfg.get("autoEscalarAyudaCritica", True)))
        self.sw_sos.cambiado.connect(lambda v: self.state.actualizar_config(autoEscalarAyudaCritica=v))
        c_lis.capa.addWidget(fila_ajuste(
            "En una emergencia, avisar al oficial médico", "Abre el protocolo y envía la alerta SBAR.", self.sw_sos
        ))
        col.addWidget(c_lis)

        # --- Motor de IA (Nube + Local Ollama) ---
        c_ia = Tarjeta(margen=26, espacio=10)
        c_ia.capa.addWidget(etiqueta_mono("Motor de inteligencia artificial"))
        self.chips_motor = GrupoChips(list(MOTORES_IA), estilo="chip", etiquetas=MOTORES_IA, espacio=8)
        motor = cfg.get("motorLLM", "cloud-api-auto")
        self.chips_motor.marcar(motor if motor in MOTORES_IA else "cloud-api-auto")
        self.chips_motor.seleccionado.connect(self._on_motor_cambiado)
        c_ia.capa.addWidget(self.chips_motor)
        self.lbl_desc_motor = etiqueta(
            DESCRIPCIONES_MOTOR.get(motor, DESCRIPCIONES_MOTOR["cloud-api-auto"]),
            t.T_PEQUENO,
            t.SECUNDARIO,
            wrap=True,
        )
        c_ia.capa.addWidget(self.lbl_desc_motor)
        c_ia.capa.addSpacing(4)

        fila_k = QHBoxLayout()
        fila_k.setSpacing(8)
        self.txt_apikey = QLineEdit(cfg.get("cloudApiKey", ""))
        self.txt_apikey.setEchoMode(QLineEdit.Password)
        self.txt_apikey.setPlaceholderText(tr("Clave de API para la IA en la nube"))
        self.txt_apikey.editingFinished.connect(self._guardar_apikey_si_cambio)
        fila_k.addWidget(self.txt_apikey, 1)
        self.btn_ver_key = boton("Ver", al_pulsar=self._toggle_ver_apikey)
        fila_k.addWidget(self.btn_ver_key)
        fila_k.addWidget(boton("Validar", al_pulsar=self._validar_api_key))
        c_ia.capa.addLayout(fila_k)
        self.lbl_cloud_status = etiqueta("", t.T_PEQUENO, t.TEXTO_SUAVE, wrap=True)
        c_ia.capa.addWidget(self.lbl_cloud_status)
        c_ia.capa.addWidget(divisor())

        c_ia.capa.addWidget(etiqueta("IA local (Ollama)", t.T_CUERPO, t.TEXTO))
        fila_loc = QHBoxLayout()
        fila_loc.setSpacing(8)
        self.txt_ollama_url = QLineEdit(cfg.get("llmEndpointLocal", "http://127.0.0.1:11434"))
        self.txt_ollama_url.setPlaceholderText("http://127.0.0.1:11434")
        self.txt_ollama_url.editingFinished.connect(self._guardar_config_ollama)
        fila_loc.addWidget(self.txt_ollama_url, 1)

        self.combo_ollama_mod = QComboBox()
        self.combo_ollama_mod.setEditable(True)
        self.combo_ollama_mod.setMinimumWidth(240)
        mod_loc = str(cfg.get("llmModeloLocal", "qwen2.5:3b"))
        for m_def in ("qwen2.5:3b", "llama3.2:3b"):
            self.combo_ollama_mod.addItem(m_def)
        if self.combo_ollama_mod.findText(mod_loc) < 0:
            self.combo_ollama_mod.addItem(mod_loc)
        self.combo_ollama_mod.setCurrentText(mod_loc)
        self.combo_ollama_mod.currentTextChanged.connect(lambda _t: self._guardar_config_ollama())
        fila_loc.addWidget(self.combo_ollama_mod)
        fila_loc.addWidget(boton("Detectar", al_pulsar=lambda: self._verificar_motores_async(forzar=True)))
        c_ia.capa.addLayout(fila_loc)
        self.lbl_ollama_status = etiqueta("Comprobando IA local…", t.T_PEQUENO, t.SECUNDARIO, wrap=True)
        c_ia.capa.addWidget(self.lbl_ollama_status)
        col.addWidget(c_ia)

        # --- Memoria y privacidad del tripulante ---
        c_mem = Tarjeta(margen=26, espacio=10)
        c_mem.capa.addWidget(etiqueta_mono("Lo que L.I.S. recuerda de ti"))
        fa = QHBoxLayout()
        fa.setSpacing(10)
        fa.addWidget(etiqueta("Trato / alias preferido:", t.T_PEQUENO, t.ETIQUETA))
        self.txt_alias_mem = QLineEdit()
        self.txt_alias_mem.setPlaceholderText(tr("Ej. Comandante, Dra. Vega, Señor…"))
        self.txt_alias_mem.returnPressed.connect(self._guardar_alias_memoria)
        fa.addWidget(self.txt_alias_mem, 1)
        fa.addWidget(boton("Guardar alias", al_pulsar=self._guardar_alias_memoria))
        c_mem.capa.addLayout(fa)

        self._cat_nota_mem = "observacion"
        fcat = QHBoxLayout()
        fcat.setSpacing(10)
        fcat.addWidget(etiqueta("Categoría:", t.T_PEQUENO, t.ETIQUETA))
        self.chips_cat_mem = GrupoChips(
            ["observacion", "preferencia", "antecedente"],
            etiquetas={
                "observacion": "Observación",
                "preferencia": "Preferencia",
                "antecedente": "Antecedente",
            },
        )
        self.chips_cat_mem.marcar(self._cat_nota_mem)
        self.chips_cat_mem.seleccionado.connect(lambda c: setattr(self, "_cat_nota_mem", c))
        fcat.addWidget(self.chips_cat_mem)
        fcat.addStretch(1)
        c_mem.capa.addLayout(fcat)

        fm = QHBoxLayout()
        fm.setSpacing(10)
        self.txt_nota_mem = QLineEdit()
        self.txt_nota_mem.setPlaceholderText(tr("Añadir una nota o preferencia"))
        self.txt_nota_mem.returnPressed.connect(self._guardar_nota_memoria)
        fm.addWidget(self.txt_nota_mem, 1)
        fm.addWidget(boton("Guardar", al_pulsar=self._guardar_nota_memoria))
        c_mem.capa.addLayout(fm)
        self.lbl_notas_mem = etiqueta("", t.T_PEQUENO, t.SECUNDARIO, wrap=True)
        c_mem.capa.addWidget(self.lbl_notas_mem)
        self.vbox_notas_mem = QVBoxLayout()
        self.vbox_notas_mem.setSpacing(6)
        c_mem.capa.addLayout(self.vbox_notas_mem)
        fila_limp = QHBoxLayout()
        fila_limp.setSpacing(10)
        fila_limp.addWidget(boton("Limpiar notas", al_pulsar=self._limpiar_notas))
        fila_limp.addWidget(boton("Limpiar historial de chat", al_pulsar=self._limpiar_chat))
        fila_limp.addStretch(1)
        self.lbl_mem_msg = etiqueta("", t.T_PEQUENO, t.NORMAL)
        fila_limp.addWidget(self.lbl_mem_msg)
        c_mem.capa.addLayout(fila_limp)
        col.addWidget(c_mem)

        # --- Restablecer + acerca de ---
        c_info = Tarjeta(margen=26, espacio=10)
        c_info.capa.addWidget(etiqueta_mono("Acerca de"))
        c_info.capa.addWidget(etiqueta(
            "V.I.T.A.L.I.S. no es un dispositivo médico: no diagnostica ni prescribe.",
            t.T_CUERPO, t.TEXTO, wrap=True,
        ))
        c_info.capa.addWidget(etiqueta(
            "Datos: NASA OSDR OSD-575 (SpaceX Inspiration4, panel metabólico completo).",
            t.T_PEQUENO, t.SECUNDARIO, wrap=True,
        ))
        c_info.capa.addWidget(etiqueta(
            "Anatomía 3D: BodyParts3D © The Database Center for Life Science (CC BY 4.0); "
            "órganos femeninos: Human Reference Atlas, HuBMAP (CC BY 4.0); cuerpo femenino: "
            "MakeHuman (CC0). Adaptado por open-anatomy-3d, CC BY 4.0.",
            t.T_PEQUENO, t.SECUNDARIO, wrap=True,
        ))
        c_info.capa.addWidget(etiqueta(
            "Equipo ROCKET · NASA Space Apps Challenge 2026 · Tuxtla Gutiérrez",
            t.T_PEQUENO, t.SECUNDARIO,
        ))
        c_info.capa.addSpacing(8)
        c_info.capa.addWidget(
            boton("Restaurar ajustes por defecto", al_pulsar=self._restaurar), 0, Qt.AlignLeft
        )
        col.addWidget(c_info)
        col.addStretch(1)

        capa.addWidget(area_desplazable(contenido))

        self.state.crewChanged.connect(self.refrescar)
        self.state.timepointChanged.connect(self.refrescar)
        self.state.configChanged.connect(self._sincronizar_config_ui)
        self.state.alarmaEmergenciaChanged.connect(self._on_alarma_estado_cambiado)
        self.refrescar(forzar=True)

    # --- idioma --------------------------------------------------------------
    def _cambiar_idioma(self, codigo: str) -> None:
        """Guarda el idioma elegido y deja que la ventana principal reconstruya la UI."""
        self._idioma_sel = codigo
        self._pintar_estado_idioma()
        if codigo != i18n.idioma():
            self.state.actualizar_config(idioma=codigo)

    def _descargar_idioma(self) -> None:
        """Instala el paquete del idioma elegido en data/locales (uso sin conexión)."""
        codigo = self._idioma_sel or i18n.idioma()
        res = i18n.instalar_idioma(codigo)
        if res.get("ok"):
            self._pintar_estado_idioma(tr("Paquete descargado ✓"))
        else:
            self._pintar_estado_idioma(res.get("error") or tr("No se pudo descargar el paquete."))

    def _pintar_estado_idioma(self, mensaje: str = "") -> None:
        codigo = self._idioma_sel or i18n.idioma()
        info = i18n.info_idioma(codigo)
        version = f" · v{info['version']}" if info.get("version") else ""
        if info.get("instalado"):
            estado = tr("Instalado en este equipo") + " · " + tr("Descargado y disponible sin conexión.")
        else:
            estado = tr("Incluido en la aplicación")
        texto = f"{info['nativo']} ({info['codigo']}){version} · {estado}"
        if mensaje:
            texto = f"{mensaje}  ·  {texto}"
        self.lbl_idioma_estado.setText(texto)
        self.btn_idioma_pack.setEnabled(not info.get("instalado"))
        self.btn_idioma_pack.setText(
            tr("Idioma descargado ✓") if info.get("instalado") else tr("Descargar idioma")
        )

    def _sincronizar_config_ui(self, cfg: Dict[str, Any]) -> None:
        tema = str(cfg.get("temaVisual", "oscuro"))
        self.chips_tema.marcar(tema if tema in TEMAS_UI else "oscuro")
        escala = str(cfg.get("escalaUI", "1.0"))
        self.chips_escala.marcar(escala if escala in ESCALAS_UI else "1.0")
        if hasattr(self, "btn_reiniciar"):
            self.btn_reiniciar.setVisible(
                escala != os.environ.get("VITALIS_ESCALA_APLICADA", "1.0")
            )
        pers = str(cfg.get("personalidad", "jarvis-cordial"))
        self.chips_pers.marcar(pers if pers in PERSONALIDADES_UI else "jarvis-cordial")
        mic = f"{float(cfg.get('duracionMicrofonoSeg', 4.5)):.1f}"
        if mic in TIEMPOS_MIC:
            self.chips_mic.marcar(mic)
        codigo_idioma = str(cfg.get("idioma", i18n.idioma()))
        if codigo_idioma in self.chips_idioma.botones:
            self._idioma_sel = codigo_idioma
            self.chips_idioma.marcar(codigo_idioma)
            self._pintar_estado_idioma()
        tono_a = str(cfg.get("alarmaEmergenciaTono", "doble-suave"))
        self.chips_tono_alarma.marcar(
            tono_a if tono_a in TONOS_ALARMA_UI else "doble-suave"
        )
        try:
            int_a = str(int(cfg.get("alarmaEmergenciaIntervaloMs", 2800)))
        except Exception:
            int_a = "2800"
        self.chips_intervalo_alarma.marcar(
            int_a if int_a in INTERVALOS_ALARMA_UI else "2800"
        )
        try:
            vol_a = max(25, min(100, int(round(float(cfg.get("alarmaEmergenciaVolumen", 0.70)) * 100))))
        except Exception:
            vol_a = 70
        if not self._timer_vol_alarma.isActive():
            if self.slider_vol_alarma.value() != vol_a:
                self.slider_vol_alarma.blockSignals(True)
                self.slider_vol_alarma.setValue(vol_a)
                self.slider_vol_alarma.blockSignals(False)
            self.lbl_vol_alarma.setText(f"{vol_a} %")

        try:
            vol_m = max(15, min(100, int(round(float(cfg.get("volumenMonitorOverview", 0.35)) * 100))))
        except Exception:
            vol_m = 35
        if not self._timer_vol_monitor.isActive():
            if self.slider_vol_monitor.value() != vol_m:
                self.slider_vol_monitor.blockSignals(True)
                self.slider_vol_monitor.setValue(vol_m)
                self.slider_vol_monitor.blockSignals(False)
            self.lbl_vol_monitor.setText(f"{vol_m} %")

        for sw, val in (
            (self.sw_anim3d, bool(cfg.get("animacion3D", True))),
            (self.sw_avisos, bool(cfg.get("mostrarAvisosEmergentes", True))),
            (self.sw_alarma_sonora, bool(cfg.get("alarmaEmergenciaSonora", True))),
            (self.sw_alarma_sbar, bool(cfg.get("alarmaEmergenciaIncluirSbar", True))),
            (self.sw_monitor_overview, bool(cfg.get("sonidoMonitorOverview", True))),
            (self.sw_mostrar, bool(cfg.get("mostrarAsistente", True))),
            (self.sw_voz, bool(cfg.get("vozActiva", True))),
            (self.sw_nav, bool(cfg.get("permitirNavegacionAutonoma", True))),
            (self.sw_param, bool(cfg.get("permitirControlParametros", True))),
            (self.sw_sos, bool(cfg.get("autoEscalarAyudaCritica", True))),
        ):
            if sw.isChecked() != val:
                sw.blockSignals(True)
                sw.setChecked(val)
                sw._pintar()
                sw.blockSignals(False)
        idx_v = self.combo_voz.findData(cfg.get("vozId", "jarvis-clone-latam"))
        if idx_v >= 0 and self.combo_voz.currentIndex() != idx_v:
            self.combo_voz.blockSignals(True)
            self.combo_voz.setCurrentIndex(idx_v)
            self.combo_voz.blockSignals(False)
        vel_val = int(round(float(cfg.get("velocidadVoz", 1.04)) * 100))
        if not self._timer_vel.isActive() and self.slider_vel.value() != vel_val:
            self.slider_vel.blockSignals(True)
            self.slider_vel.setValue(vel_val)
            self.slider_vel.blockSignals(False)
            self.lbl_vel.setText(f"{vel_val / 100.0:.2f}×")
        self._actualizar_estado_alarma_cfg()

    # --- acciones ------------------------------------------------------------
    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self._pendiente_refresco:
            self._pendiente_refresco = False
            self.refrescar(forzar=True)
        self._verificar_motores_async()

    def hideEvent(self, ev) -> None:  # noqa: N802
        self.detener_recursos()
        super().hideEvent(ev)

    def _on_vol_alarma(self, val: int, guardar: bool = True) -> None:
        self.lbl_vol_alarma.setText(f"{int(val)} %")
        if guardar:
            self._timer_vol_alarma.start()

    def _guardar_vol_alarma_debounced(self) -> None:
        vol = round(max(25, min(100, self.slider_vol_alarma.value())) / 100.0, 2)
        self.state.actualizar_config(alarmaEmergenciaVolumen=vol)

    def _on_vol_monitor(self, val: int, guardar: bool = True) -> None:
        self.lbl_vol_monitor.setText(f"{int(val)} %")
        if guardar:
            self._timer_vol_monitor.start()

    def _guardar_vol_monitor_debounced(self) -> None:
        vol = round(max(15, min(100, self.slider_vol_monitor.value())) / 100.0, 2)
        self.state.actualizar_config(volumenMonitorOverview=vol)

    def _on_alarma_estado_cambiado(self, *_args) -> None:
        self._actualizar_estado_alarma_cfg()

    def _actualizar_estado_alarma_cfg(self, mensaje: str = "") -> None:
        if (
            not hasattr(self, "lbl_estado_alarma_cfg")
            or not isValid(self)
            or not isValid(self.lbl_estado_alarma_cfg)
        ):
            return
        cfg = self.state.config
        habilitada = bool(cfg.get("alarmaEmergenciaSonora", True))
        vol = int(round(float(cfg.get("alarmaEmergenciaVolumen", 0.70)) * 100))
        cad_key = str(int(cfg.get("alarmaEmergenciaIntervaloMs", 2800)))
        cad_txt = INTERVALOS_ALARMA_UI.get(cad_key, f"{int(cad_key) / 1000.0:.1f} s")
        tono_txt = tr(TONOS_ALARMA_UI.get(str(cfg.get("alarmaEmergenciaTono", "doble-suave")), "Doble pulso"))
        if not habilitada:
            base = tr("Desactivada · los avisos críticos solo se mostrarán en pantalla")
            color = t.SECUNDARIO
        elif self.state.alarma_emergencia_sonando:
            base = tr("Alarma activa en este momento ({t} · {v} % · cada {c})", t=tono_txt, v=vol, c=cad_txt)
            color = t.ALERTA
        elif self.state.alarma_roja_presente:
            base = tr("Silenciada para el episodio actual ({t} · {v} % · cada {c})", t=tono_txt, v=vol, c=cad_txt)
            color = t.TEXTO_SUAVE
        else:
            base = tr("En espera · {t} · volumen {v} % · cada {c}", t=tono_txt, v=vol, c=cad_txt)
            color = t.SECUNDARIO
        self.lbl_estado_alarma_cfg.setText(f"{mensaje} · {base}" if mensaje else base)
        self.lbl_estado_alarma_cfg.setStyleSheet(f"color: {color}; font-size: {t.T_PEQUENO}px;")

    def _probar_alarma(self) -> None:
        if self._timer_vol_alarma.isActive():
            self._timer_vol_alarma.stop()
            self._guardar_vol_alarma_debounced()
        cfg = self.state.config
        vol = max(0.25, min(1.0, float(cfg.get("alarmaEmergenciaVolumen", 0.70))))
        tono = str(cfg.get("alarmaEmergenciaTono", "doble-suave") or "doble-suave")
        ok = self.motor_voz.reproducir_pulso_alarma_emergencia(volumen=vol, tono=tono)
        if ok:
            self._actualizar_estado_alarma_cfg(tr("✓ Pulso suave reproducido"))
        else:
            self._actualizar_estado_alarma_cfg(tr("En espera (voz o micrófono de L.I.S. en uso)"))

    def _on_vel(self, val: int, guardar: bool = True) -> None:
        v = round(val / 100.0, 2)
        self.lbl_vel.setText(f"{v:.2f}×")
        if guardar:
            self._timer_vel.start()

    def _guardar_vel_debounced(self) -> None:
        v = round(self.slider_vel.value() / 100.0, 2)
        self.state.actualizar_config(velocidadVoz=v)

    def _on_escala(self, valor: str) -> None:
        self.state.actualizar_config(escalaUI=valor)
        self.btn_reiniciar.setVisible(
            str(valor) != os.environ.get("VITALIS_ESCALA_APLICADA", "1.0")
        )

    def _on_motor_cambiado(self, valor: str) -> None:
        self.state.actualizar_config(motorLLM=valor)
        self.lbl_desc_motor.setText(tr(DESCRIPCIONES_MOTOR.get(valor, "")))

    def _guardar_apikey_si_cambio(self) -> None:
        if not hasattr(self, "txt_apikey") or not isValid(self.txt_apikey):
            return
        key = self.txt_apikey.text().strip()
        if key != str(self.state.config.get("cloudApiKey", "")):
            self.state.actualizar_config(cloudApiKey=key)

    def _toggle_ver_apikey(self) -> None:
        viendo = self.txt_apikey.echoMode() == QLineEdit.Normal
        self.txt_apikey.setEchoMode(QLineEdit.Password if viendo else QLineEdit.Normal)
        self.btn_ver_key.setText(tr("Ver") if viendo else tr("Ocultar"))

    def _guardar_config_ollama(self) -> None:
        ep = self.txt_ollama_url.text().strip() or "http://127.0.0.1:11434"
        mod = self.combo_ollama_mod.currentText().strip() or "qwen2.5:3b"
        self.state.actualizar_config(llmEndpointLocal=ep, llmModeloLocal=mod)

    def _verificar_motores_async(self, forzar: bool = False) -> None:
        if self._verificando_motores and not forzar:
            return
        self._verificando_motores = True
        endpoint = self.txt_ollama_url.text().strip() or "http://127.0.0.1:11434"

        def _work() -> None:
            jarvis_ok = estado_voz_jarvis()
            oll = estado_ollama(endpoint)
            if not isValid(self):
                return
            try:
                self.motoresVerificados.emit({"jarvis": jarvis_ok, "ollama": oll})
            except RuntimeError:
                pass

        threading.Thread(target=_work, daemon=True, name="lis-check-engines").start()

    def _aplicar_estado_motores(self, info: Dict[str, Any]) -> None:
        self._verificando_motores = False
        voz_sel = self.state.config.get("vozId", "jarvis-clone-latam")
        if voz_sel in ("jarvis-clone-latam", "jarvis-clone-classic"):
            self.lbl_estado_jarvis.setText(
                tr("Voz JARVIS activa (XTTS GPU)")
                if info.get("jarvis")
                else tr("Servidor JARVIS inactivo · usando voz rápida")
            )
        else:
            voz_ef = resolver_voz_neural_por_idioma(voz_sel, i18n.idioma())
            self.lbl_estado_jarvis.setText(tr("Voz rápida activa ({v})", v=voz_ef))

        oll = info.get("ollama") or {}
        modelos = oll.get("modelos") or []
        if oll.get("conectado"):
            actual = self.combo_ollama_mod.currentText().strip()
            self.combo_ollama_mod.blockSignals(True)
            for m in modelos:
                if self.combo_ollama_mod.findText(m) < 0:
                    self.combo_ollama_mod.addItem(m)
            if actual:
                self.combo_ollama_mod.setCurrentText(actual)
            self.combo_ollama_mod.blockSignals(False)
            self.lbl_ollama_status.setText(
                tr("✓ IA local conectada ({n} modelos disponibles)", n=len(modelos))
            )
        else:
            self.lbl_ollama_status.setText(tr("IA local: sin conexión en el endpoint indicado"))

    def _reiniciar_app(self) -> None:
        # Asegura el volcado de ajustes pendientes antes de relanzar.
        self.detener_recursos()
        # La nueva instancia espera a que ésta cierre (mutex de instancia única).
        script = os.path.abspath(sys.argv[0])
        QProcess.startDetached(sys.executable, [script, "--reinicio"])
        QApplication.quit()

    def _probar_voz(self) -> None:
        self.motor_voz.hablar(
            tr("A sus órdenes, señor. Todo en calma a bordo; su pulso y su oxígeno van muy bien."),
            voz_id=self.state.config.get("vozId", "jarvis-clone-latam"),
            velocidad=float(self.state.config.get("velocidadVoz", 1.04)),
            lang=i18n.idioma(),
        )

    def _validar_api_key(self) -> None:
        self._guardar_apikey_si_cambio()
        key = self.txt_apikey.text().strip()
        self.lbl_cloud_status.setText(tr("Comprobando la clave…"))

        def _work() -> None:
            loop = asyncio.new_event_loop()
            try:
                res = loop.run_until_complete(detectar_mejor_modelo_cloud(key))
            finally:
                loop.close()
            if res.get("valido"):
                self.state.actualizar_config(
                    cloudApiKey=key,
                    cloudProvider=res["proveedor"],
                    cloudModeloAuto=res["mejorModelo"],
                    motorLLM="cloud-api-auto",
                )
                msg = tr("✓ {p} · modelo {m}", p=res["nombreProveedor"], m=res["mejorModelo"])
            else:
                msg = tr("✕ {e}", e=res.get("error", tr("Clave no válida")))
            self.estadoCloudListo.emit(msg)

        threading.Thread(target=_work, daemon=True).start()

    def _mostrar_resultado_cloud(self, msg: str) -> None:
        self.lbl_cloud_status.setText(msg)
        if msg.startswith("✓"):
            self.chips_motor.marcar("cloud-api-auto")
            self.lbl_desc_motor.setText(tr(DESCRIPCIONES_MOTOR["cloud-api-auto"]))

    def _guardar_alias_memoria(self) -> None:
        alias = self.txt_alias_mem.text().strip()
        if not alias:
            return
        actualizar_alias_astronauta(self.state.crew_id, alias)
        self.lbl_mem_msg.setText(tr("Alias guardado ✓"))
        self.refrescar(forzar=True)

    def _guardar_nota_memoria(self) -> None:
        txt = self.txt_nota_mem.text().strip()
        if not txt:
            return
        recordar_dato_astronauta(self.state.crew_id, txt, getattr(self, "_cat_nota_mem", "observacion"))
        self.txt_nota_mem.clear()
        self.lbl_mem_msg.setText(tr("Nota guardada ✓"))
        self.refrescar(forzar=True)

    def _limpiar_notas(self) -> None:
        limpiar_memoria_astronauta(self.state.crew_id)
        self.lbl_mem_msg.setText(tr("Notas limpiadas ✓"))
        self.refrescar(forzar=True)

    def _limpiar_chat(self) -> None:
        limpiar_historial_chat(self.state.crew_id)
        self.state.historialLimpiado.emit()
        self.lbl_mem_msg.setText(tr("Historial de chat limpiado ✓"))

    def _restaurar(self) -> None:
        for tm in (self._timer_vel, self._timer_vol_alarma, self._timer_vol_monitor):
            if tm.isActive():
                tm.stop()
        self.state.restaurar_config()
        cfg = self.state.config
        self._sincronizar_config_ui(cfg)
        self.chips_escala.marcar(str(cfg.get("escalaUI", "1.0")))
        motor_r = cfg.get("motorLLM", "cloud-api-auto")
        self.chips_motor.marcar(motor_r)
        self.lbl_desc_motor.setText(tr(DESCRIPCIONES_MOTOR.get(motor_r, "")))
        for w_bloq in (self.txt_apikey, self.txt_ollama_url, self.combo_ollama_mod):
            w_bloq.blockSignals(True)
        try:
            self.txt_apikey.setText(cfg.get("cloudApiKey", ""))
            self.txt_ollama_url.setText(cfg.get("llmEndpointLocal", "http://127.0.0.1:11434"))
            self.combo_ollama_mod.setCurrentText(cfg.get("llmModeloLocal", "qwen2.5:3b"))
        finally:
            for w_bloq in (self.txt_apikey, self.txt_ollama_url, self.combo_ollama_mod):
                w_bloq.blockSignals(False)
        self.lbl_mem_msg.setText(tr("Ajustes restaurados ✓"))
        self.refrescar(forzar=True)
        self._verificar_motores_async(forzar=True)

    def refrescar(self, *_args, forzar: bool = False) -> None:
        if not forzar and not self.isVisible():
            self._pendiente_refresco = True
            return
        self._pendiente_refresco = False
        self.chips_crew.marcar(self.state.crew_id)
        self.chips_tp.marcar(self.state.timepoint)
        self.lbl_rol.setText(tr(self.state.rol_actual()))
        voz_sel = self.state.config.get("vozId", "jarvis-clone-latam")
        if voz_sel not in ("jarvis-clone-latam", "jarvis-clone-classic"):
            voz_ef = resolver_voz_neural_por_idioma(voz_sel, i18n.idioma())
            self.lbl_estado_jarvis.setText(tr("Voz rápida activa ({v})", v=voz_ef))
        prov = self.state.config.get("cloudProvider", "")
        mod = self.state.config.get("cloudModeloAuto", "")
        if prov and mod and hasattr(self, "lbl_cloud_status"):
            self.lbl_cloud_status.setText(tr("✓ {p} · modelo {m}", p=prov, m=mod))
        mem = obtener_memoria_astronauta(self.state.crew_id)
        if hasattr(self, "txt_alias_mem") and not self.txt_alias_mem.hasFocus():
            self.txt_alias_mem.setText(str(mem.get("aliasPreferido") or self.state.crew_id))
        notas = mem.get("notasRecordadas", [])
        self.lbl_notas_mem.setText(
            tr(
                "{n} notas registradas · rol {rol}",
                n=len(notas),
                rol=tr(str(mem.get("rol") or self.state.rol_actual())),
            )
            if notas
            else tr("Todavía no hay notas.")
        )
        if hasattr(self, "vbox_notas_mem"):
            vaciar_layout(self.vbox_notas_mem)
            etiquetas_cat = {
                "observacion": "Observación",
                "preferencia": "Preferencia",
                "antecedente": "Antecedente",
            }
            for n in notas:
                cat = tr(etiquetas_cat.get(str(n.get("categoria", "observacion")), str(n.get("categoria", "observacion"))))
                fecha = formatear_iso(n.get("fecha"))
                self.vbox_notas_mem.addWidget(
                    etiqueta(f"[{cat} · {fecha}] {n.get('texto', '')}", t.T_PEQUENO, t.TEXTO_SUAVE, wrap=True)
                )
        if self.isVisible():
            self._verificar_motores_async()

    def detener_recursos(self) -> None:
        """Vuelca cambios con debounce y campos de texto pendientes al cerrar o reconstruir."""
        if not isValid(self):
            return
        for tm_name, flush_fn in (
            ("_timer_vel", self._guardar_vel_debounced),
            ("_timer_vol_alarma", self._guardar_vol_alarma_debounced),
            ("_timer_vol_monitor", self._guardar_vol_monitor_debounced),
        ):
            tm = getattr(self, tm_name, None)
            if tm is not None and tm.isActive():
                tm.stop()
                flush_fn()
        self._guardar_apikey_si_cambio()
        if (
            hasattr(self, "txt_ollama_url")
            and isValid(self.txt_ollama_url)
            and hasattr(self, "combo_ollama_mod")
            and isValid(self.combo_ollama_mod)
        ):
            ep = self.txt_ollama_url.text().strip() or "http://127.0.0.1:11434"
            mod = self.combo_ollama_mod.currentText().strip() or "qwen2.5:3b"
            if (
                ep != str(self.state.config.get("llmEndpointLocal", "http://127.0.0.1:11434"))
                or mod != str(self.state.config.get("llmModeloLocal", "qwen2.5:3b"))
            ):
                self._guardar_config_ollama()


# Nombre anterior, por compatibilidad con código que aún lo importe.
VistaConfigLIS = VistaAjustes
