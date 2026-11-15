# -*- coding: utf-8 -*-
"""
desktop/vista_sala.py — Control de Misión organizado en 5 pasos claros y táctiles.

Separa el monitoreo en vivo de la tripulación y parámetros (`Estación y vivo`),
la configuración de entorno/fuente/anomalías (`Escenario`), los eventos clínicos
(`Eventos y SBAR`), la bitácora (`Bitácora`) y el enlace con Tierra (`Enlace Tierra`),
con explicación breve en cada paso para entender qué mueve cada control.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from backend.crew_hub import get_crew_hub
from backend.database import (
    DATA_DIR,
    ROOT_DIR,
    exportar_respaldo_completo,
    listar_episodios,
    listar_eventos_emergencia,
    sexo_de,
)
from backend.registry import get_param, listar_por_entorno
from backend.runtime import get_runtime
from backend.sync_tierra import get_sync_manager
from backend.triage import evaluar_lectura_determinista
from desktop import theme as t
from desktop.estado_actual import nombre_corto
from desktop.i18n import tr
from desktop.paneles_bd import (
    PanelBitacoraMision,
    PanelColaTierra,
    PanelEventosYSbar,
    formatear_ts_ms,
)
from desktop.state import AppState
from desktop.widgets import (
    GrupoChips,
    Tarjeta,
    boton,
    divisor,
    estilo_pastilla,
    etiqueta,
    etiqueta_mono,
    scroll_tactil,
    vaciar_layout,
)


_PARAMETROS_VIVO_ORDER = [
    "heart_rate",
    "spo2",
    "systolic_bp",
    "diastolic_bp",
    "respiratory_rate",
    "core_temperature",
    "intracranial_pressure_est",
    "cabin_co2",
    "radiation_dose",
]

_ETIQUETAS_ENTORNO = {
    "nave": "Nave",
    "estacion": "Estación",
    "base-lunar": "Base lunar",
}

_ETIQUETAS_MODO = {
    "simulado": "Simulación 1 Hz",
    "replay-osdr": "Replay OSDR",
}

_ETIQUETAS_RED = {
    "online": "En línea",
    "offline": "Sin conexión",
    "degradado": "Degradado",
}

_PANELES_SALA = {
    "vivo": "1 · Estación y vivo",
    "escenario": "2 · Escenario",
    "eventos": "3 · Eventos y SBAR",
    "bitacora": "4 · Bitácora",
    "cola": "5 · Enlace Tierra",
}

_DESCRIPCIONES_PANEL = {
    "vivo": (
        "Supervisa los 4 tripulantes (C001–C004) y los signos en tiempo real; "
        "toca cualquier parámetro para abrir su tendencia histórica."
    ),
    "escenario": (
        "Define el entorno de misión, alterna entre Simulación y Replay NASA OSDR "
        "e inyecta anomalías de prueba sobre la estación activa."
    ),
    "eventos": (
        "Atiende solicitudes médicas SBAR, revisa eventos de emergencia "
        "y consulta el historial de episodios clínicos."
    ),
    "bitacora": (
        "Registra novedades de turno de la tripulación o del CMO "
        "y supervisa su sincronización hacia Tierra."
    ),
    "cola": (
        "Controla el enlace con Tierra, envía los lotes pendientes de la cola "
        "y exporta respaldos completos en JSON."
    ),
}


def _pastilla(texto: str, color: str) -> QLabel:
    lbl = QLabel(tr(texto))
    estilo_pastilla(lbl, color)
    return lbl


def _area_desplazable(contenido: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(contenido)
    scroll_tactil(scroll)
    return scroll


def _color_enlace(estado: str) -> str:
    if estado == "conectado":
        return t.NORMAL
    if estado == "degradado":
        return t.ATENCION
    return t.ALERTA


def _texto_enlace(estado: str) -> str:
    if estado == "conectado":
        return "Conectado"
    if estado == "degradado":
        return "Degradado"
    return "Sin enlace"


class _MarcoTactil(QFrame):
    """Tarjeta táctil que emite `pulsado` al tocarla sin estorbar botones internos."""

    pulsado = Signal()

    def __init__(
        self,
        al_pulsar: Optional[Callable[[], None]] = None,
        nombre_objeto: str = "celdaTactil",
    ) -> None:
        super().__init__()
        self.setObjectName(nombre_objeto)
        self.setAttribute(Qt.WA_Hover, True)
        self._inicio = None
        if al_pulsar is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.pulsado.connect(al_pulsar)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._inicio = ev.position().toPoint()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton and self._inicio is not None:
            delta = (ev.position().toPoint() - self._inicio).manhattanLength()
            self._inicio = None
            if delta <= 14 and self.rect().contains(ev.position().toPoint()):
                self.pulsado.emit()
                ev.accept()
                return
        self._inicio = None
        super().mouseReleaseEvent(ev)


class VistaSala(QWidget):
    """Control de Misión organizado por flujo de tareas claro y táctil."""

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._pendiente_refresco = False
        self._crew_cards: Dict[str, Dict[str, Any]] = {}
        self._tele_cards: Dict[str, Dict[str, Any]] = {}
        self._panel_actual = "vivo"
        self.botones_flujo: Dict[str, QPushButton] = {}

        capa_ext = QVBoxLayout(self)
        capa_ext.setContentsMargins(0, 0, 0, 0)
        capa_ext.setSpacing(14)

        # --- Barra superior unificada: Estado global + 5 pasos + explicación ---
        barra = Tarjeta(margen=18, espacio=10)
        h_top = QHBoxLayout()
        h_top.setSpacing(10)
        h_top.addWidget(etiqueta_mono("Control de Misión"))
        self.lbl_resumen_entorno = _pastilla("Estación · 9 parámetros", t.ETIQUETA)
        self.lbl_replay_badge = _pastilla("Simulación 1 Hz · activo", t.NORMAL)
        self.lbl_red_badge = _pastilla("En línea", t.NORMAL)
        h_top.addStretch(1)
        h_top.addWidget(self.lbl_resumen_entorno)
        h_top.addWidget(self.lbl_replay_badge)
        h_top.addWidget(self.lbl_red_badge)
        barra.capa.addLayout(h_top)

        h_flujo = QHBoxLayout()
        h_flujo.setSpacing(8)
        self._grupo_flujo = QButtonGroup(self)
        self._grupo_flujo.setExclusive(True)
        for pid, titulo in _PANELES_SALA.items():
            btn = QPushButton(tr(titulo))
            btn.setObjectName("subnavFlujo")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(54)
            btn.clicked.connect(lambda _=False, k=pid: self.seleccionar_panel(k))
            self._grupo_flujo.addButton(btn)
            self.botones_flujo[pid] = btn
            h_flujo.addWidget(btn, 1)
        barra.capa.addLayout(h_flujo)

        self.lbl_flujo_desc = etiqueta(
            _DESCRIPCIONES_PANEL["vivo"],
            t.T_PEQUENO,
            t.SECUNDARIO,
            wrap=True,
        )
        barra.capa.addWidget(self.lbl_flujo_desc)
        capa_ext.addWidget(barra)

        # --- Páginas del flujo ---
        self.stack_sala = QStackedWidget()

        pag_vivo = self._construir_pagina_vivo()
        pag_escenario = self._construir_pagina_escenario()
        self.panel_eventos = PanelEventosYSbar(self.state)
        self.panel_bitacora = PanelBitacoraMision(self.state)
        pag_cola = self._construir_pagina_cola()

        self.panel_bitacora.bitacoraActualizada.connect(lambda: self.refrescar(forzar=True))
        self.panel_cola.colaActualizada.connect(lambda: self.refrescar(forzar=True))

        self._indice_paneles = {
            "vivo": self.stack_sala.addWidget(_area_desplazable(pag_vivo)),
            "escenario": self.stack_sala.addWidget(_area_desplazable(pag_escenario)),
            "eventos": self.stack_sala.addWidget(_area_desplazable(self.panel_eventos)),
            "bitacora": self.stack_sala.addWidget(_area_desplazable(self.panel_bitacora)),
            "cola": self.stack_sala.addWidget(_area_desplazable(pag_cola)),
        }
        capa_ext.addWidget(self.stack_sala, 1)

        # Señales del estado global
        self.state.crewChanged.connect(self.refrescar)
        self.state.entornoCambiado.connect(self._on_entorno_cambiado_ext)
        self.state.modoTelemetriaCambiado.connect(self.refrescar)
        self.state.enlaceTierraCambiado.connect(self.refrescar)
        self.state.ayudaCambiada.connect(self._on_ayuda_cambiada_sala)
        self.state.telemetriaEnVivoActualizada.connect(self._refrescar_si_visible)

        self._repoblar_combo_anomalias()
        self.seleccionar_panel("vivo")
        self.refrescar(forzar=True)

    # ------------------------------------------------------------------
    # Construcción de páginas separadas por tarea
    # ------------------------------------------------------------------

    def _construir_pagina_vivo(self) -> QWidget:
        cont = QWidget()
        capa = QVBoxLayout(cont)
        capa.setContentsMargins(0, 0, 4, 0)
        capa.setSpacing(16)

        # 1. Tripulación en 2x2 amplio
        card_crew = Tarjeta(margen=20, espacio=10)
        card_crew.capa.addWidget(etiqueta_mono("Tripulación y puesto activo (C001–C004)"))
        card_crew.capa.addWidget(
            etiqueta(
                "Sexo biológico [SUPUESTO] · toca un tripulante para supervisarlo",
                t.T_PEQUENO,
                t.TERCIARIO,
                wrap=True,
            )
        )

        grid_crew = QGridLayout()
        grid_crew.setSpacing(12)
        for idx, cid in enumerate(("C001", "C002", "C003", "C004")):
            w = self._crear_tarjeta_crew(cid)
            grid_crew.addWidget(w, idx // 2, idx % 2)
        card_crew.capa.addLayout(grid_crew)
        capa.addWidget(card_crew)

        # 2. Telemetría en vivo interactiva (3x3 táctil)
        card_vivo = Tarjeta(margen=20, espacio=12)
        h_v = QHBoxLayout()
        h_v.setSpacing(10)
        col_tv = QVBoxLayout()
        col_tv.setSpacing(2)
        self.lbl_titulo_vivo = etiqueta_mono("Telemetría en vivo")
        self.lbl_sub_vivo = etiqueta("", t.T_PEQUENO, t.SECUNDARIO)
        col_tv.addWidget(self.lbl_titulo_vivo)
        col_tv.addWidget(self.lbl_sub_vivo)
        h_v.addLayout(col_tv)
        h_v.addStretch(1)
        btn_escenario_v = boton(
            "Cambiar escenario / inyectar",
            al_pulsar=lambda: self.seleccionar_panel("escenario"),
        )
        btn_resumen_v = boton(
            "Abrir Resumen",
            estilo="primario",
            al_pulsar=lambda: self.state.ir_a("inicio"),
        )
        h_v.addWidget(btn_escenario_v)
        h_v.addWidget(btn_resumen_v)
        card_vivo.capa.addLayout(h_v)

        grid_vivo = QGridLayout()
        grid_vivo.setSpacing(12)
        for idx, pid in enumerate(_PARAMETROS_VIVO_ORDER):
            w = self._crear_celda_vivo(pid)
            grid_vivo.addWidget(w, idx // 3, idx % 3)
        card_vivo.capa.addLayout(grid_vivo)
        capa.addWidget(card_vivo)

        # 3. Resumen rápido y accesos al resto del flujo
        card_res = Tarjeta(margen=20, espacio=12)
        h_r = QHBoxLayout()
        h_r.setSpacing(10)
        h_r.addWidget(etiqueta_mono("Actividad reciente y accesos rápidos"))
        h_r.addStretch(1)
        self.lbl_epi_resumen = etiqueta("", t.T_PEQUENO, t.TERCIARIO)
        h_r.addWidget(self.lbl_epi_resumen)
        card_res.capa.addLayout(h_r)

        self.lbl_ultimo_evento = etiqueta("", t.T_PEQUENO, t.SECUNDARIO, wrap=True)
        card_res.capa.addWidget(self.lbl_ultimo_evento)

        self.vbox_episodios = QVBoxLayout()
        self.vbox_episodios.setSpacing(6)
        card_res.capa.addLayout(self.vbox_episodios)

        h_acc = QHBoxLayout()
        h_acc.setSpacing(10)
        h_acc.addWidget(boton("Escenario y anomalías", al_pulsar=lambda: self.seleccionar_panel("escenario")), 1)
        h_acc.addWidget(boton("Eventos y SBAR", al_pulsar=lambda: self.seleccionar_panel("eventos")), 1)
        h_acc.addWidget(boton("Abrir bitácora", al_pulsar=lambda: self.seleccionar_panel("bitacora")), 1)
        h_acc.addWidget(boton("Enlace Tierra", al_pulsar=lambda: self.seleccionar_panel("cola")), 1)
        card_res.capa.addLayout(h_acc)
        capa.addWidget(card_res)
        capa.addStretch(1)
        return cont

    def _construir_pagina_escenario(self) -> QWidget:
        cont = QWidget()
        capa = QVBoxLayout(cont)
        capa.setContentsMargins(0, 0, 4, 0)
        capa.setSpacing(12)

        # Paso 1: Entorno físico
        card_ent = Tarjeta(margen=16, espacio=8)
        h_e = QHBoxLayout()
        h_e.addWidget(etiqueta_mono("1 · Entorno físico de misión"))
        h_e.addStretch(1)
        self.lbl_entorno_nota = etiqueta("", t.T_PEQUENO, t.SECUNDARIO)
        h_e.addWidget(self.lbl_entorno_nota)
        card_ent.capa.addLayout(h_e)
        card_ent.capa.addWidget(
            etiqueta(
                "Ajusta las reglas de evaluación y sensores visibles; en Base lunar se omite ICP por gravedad lunar.",
                t.T_PEQUENO,
                t.SECUNDARIO,
                wrap=True,
            )
        )
        self.chips_entorno = GrupoChips(
            ["nave", "estacion", "base-lunar"],
            etiquetas=_ETIQUETAS_ENTORNO,
        )
        self.chips_entorno.marcar(self.state.entorno)
        self.chips_entorno.seleccionado.connect(self._on_entorno_elegido)
        card_ent.capa.addWidget(self.chips_entorno)
        capa.addWidget(card_ent)

        # Paso 2: Fuente de telemetría
        card_fuente = Tarjeta(margen=16, espacio=8)
        h_f = QHBoxLayout()
        h_f.addWidget(etiqueta_mono("2 · Fuente de telemetría"))
        h_f.addStretch(1)
        self.lbl_replay_escenario = etiqueta("", t.T_PEQUENO, t.SECUNDARIO)
        h_f.addWidget(self.lbl_replay_escenario)
        card_fuente.capa.addLayout(h_f)
        card_fuente.capa.addWidget(
            etiqueta(
                "Cambia entre el generador fisiológico continuo (1 Hz) y las lecturas históricas NASA OSDR en modo Replay.",
                t.T_PEQUENO,
                t.SECUNDARIO,
                wrap=True,
            )
        )
        self.chips_modo = GrupoChips(
            ["simulado", "replay-osdr"],
            etiquetas=_ETIQUETAS_MODO,
        )
        self.chips_modo.marcar(self.state.modo_telemetria)
        self.chips_modo.seleccionado.connect(self._on_modo_elegido)
        card_fuente.capa.addWidget(self.chips_modo)
        capa.addWidget(card_fuente)

        # Paso 3: Simulador de anomalías
        card_anom = Tarjeta(margen=16, espacio=8)
        h_a = QHBoxLayout()
        h_a.addWidget(etiqueta_mono("3 · Inyector de anomalías en vivo"))
        h_a.addStretch(1)
        self.lbl_crew_escenario = _pastilla(f"Destino: {self.state.crew_id}", t.ETIQUETA)
        h_a.addWidget(self.lbl_crew_escenario)
        card_anom.capa.addLayout(h_a)
        card_anom.capa.addWidget(
            etiqueta(
                "Fuerza durante 30 s un desvío amarillo (Atención) o rojo (Crítico) para probar alertas, protocolos e IA.",
                t.T_PEQUENO,
                t.SECUNDARIO,
                wrap=True,
            )
        )
        self.combo_anomalia = QComboBox()
        self.combo_anomalia.setMinimumHeight(t.ALTO_TOQUE)
        card_anom.capa.addWidget(self.combo_anomalia)

        fila_btn_anom = QHBoxLayout()
        fila_btn_anom.setSpacing(10)
        self.btn_inyectar_atn = boton(
            "Inyectar Atención",
            al_pulsar=lambda: self._inyectar_anomalia("ATENCION"),
        )
        self.btn_inyectar_crit = boton(
            "Inyectar Crítico",
            estilo="peligro",
            al_pulsar=lambda: self._inyectar_anomalia("CRITICO"),
        )
        self.btn_limpiar_anom = boton(
            "Restablecer",
            al_pulsar=self._limpiar_anomalias,
        )
        fila_btn_anom.addWidget(self.btn_inyectar_atn, 1)
        fila_btn_anom.addWidget(self.btn_inyectar_crit, 1)
        fila_btn_anom.addWidget(self.btn_limpiar_anom, 1)
        card_anom.capa.addLayout(fila_btn_anom)

        self.lbl_anom_estado = etiqueta(
            "Sin anomalías forzadas activas",
            t.T_PEQUENO,
            t.SECUNDARIO,
            wrap=True,
        )
        card_anom.capa.addWidget(self.lbl_anom_estado)

        h_post = QHBoxLayout()
        h_post.setSpacing(10)
        h_post.addWidget(
            boton(
                "Ver impacto en Estación y vivo",
                al_pulsar=lambda: self.seleccionar_panel("vivo"),
            ),
            1,
        )
        h_post.addWidget(
            boton(
                "Ver eventos y SBAR generados",
                al_pulsar=lambda: self.seleccionar_panel("eventos"),
            ),
            1,
        )
        card_anom.capa.addLayout(h_post)
        capa.addWidget(card_anom)
        capa.addStretch(1)
        return cont

    def _construir_pagina_cola(self) -> QWidget:
        cont = QWidget()
        capa = QVBoxLayout(cont)
        capa.setContentsMargins(0, 0, 4, 0)
        capa.setSpacing(16)

        card_sync = Tarjeta(margen=20, espacio=12)
        h_sy = QHBoxLayout()
        h_sy.addWidget(etiqueta_mono("Control de enlace con Tierra y respaldos"))
        h_sy.addStretch(1)
        self.lbl_red_estado_card = _pastilla("En línea", t.NORMAL)
        h_sy.addWidget(self.lbl_red_estado_card)
        card_sync.capa.addLayout(h_sy)
        card_sync.capa.addWidget(
            etiqueta(
                "Cambia el estado de enlace para probar retención en cola local o transmisión inmediata hacia Tierra.",
                t.T_PEQUENO,
                t.SECUNDARIO,
                wrap=True,
            )
        )

        self.chips_red = GrupoChips(
            ["online", "offline", "degradado"],
            etiquetas=_ETIQUETAS_RED,
        )
        self.chips_red.marcar("online" if self.state.enlace_tierra_online else "offline")
        self.chips_red.seleccionado.connect(self._on_red_elegida)
        card_sync.capa.addWidget(self.chips_red)

        self.lbl_cola_resumen = etiqueta("", t.T_CUERPO, t.TEXTO_SUAVE, wrap=True)
        self.lbl_hash_cadena = etiqueta("", t.T_PEQUENO, t.SECUNDARIO, mono=True, wrap=True)
        card_sync.capa.addWidget(self.lbl_cola_resumen)
        card_sync.capa.addWidget(self.lbl_hash_cadena)

        fila_sync = QHBoxLayout()
        fila_sync.setSpacing(10)
        self.btn_sync_flush = boton(
            "Sincronizar ahora",
            estilo="primario",
            al_pulsar=self._forzar_flush,
        )
        btn_reintentar = boton(
            "Reintentar rechazados",
            al_pulsar=lambda: (self.panel_cola._reintentar(), self.refrescar(forzar=True)),
        )
        btn_act_cola = boton(
            "Actualizar",
            al_pulsar=lambda: (self.panel_cola.refrescar(forzar=True), self.refrescar(forzar=True)),
        )
        self.btn_exportar_json = boton(
            "Exportar respaldo JSON",
            al_pulsar=self._exportar_respaldo,
        )
        fila_sync.addWidget(self.btn_sync_flush, 2)
        fila_sync.addWidget(btn_reintentar, 1)
        fila_sync.addWidget(btn_act_cola, 1)
        fila_sync.addWidget(self.btn_exportar_json, 2)
        card_sync.capa.addLayout(fila_sync)

        self.lbl_sync_feedback = etiqueta("", t.T_PEQUENO, t.SECUNDARIO, wrap=True)
        card_sync.capa.addWidget(self.lbl_sync_feedback)
        capa.addWidget(card_sync)

        self.panel_cola = PanelColaTierra(self.state, mostrar_cabecera=False)
        capa.addWidget(self.panel_cola)
        return cont

    def _crear_tarjeta_crew(self, cid: str) -> QFrame:
        marco = _MarcoTactil(
            al_pulsar=lambda c=cid: self.state.set_crew(c),
            nombre_objeto="tarjeta",
        )
        vl = QVBoxLayout(marco)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(8)

        h_top = QHBoxLayout()
        lbl_id = etiqueta(f"{cid} · {sexo_de(cid)}", t.T_DESTACADO, t.TEXTO, peso=600)
        lbl_link = _pastilla("Conectado", t.NORMAL)
        h_top.addWidget(lbl_id)
        h_top.addStretch(1)
        h_top.addWidget(lbl_link)
        vl.addLayout(h_top)

        lbl_det = etiqueta("Sin alertas activas", t.T_PEQUENO, t.SECUNDARIO, wrap=True)
        vl.addWidget(lbl_det)

        h_btn = QHBoxLayout()
        h_btn.setSpacing(8)
        btn_ver = boton("Ver estación", al_pulsar=lambda _=False, c=cid: self.state.set_crew(c))
        btn_ver.setMinimumHeight(t.ALTO_TOQUE)
        btn_aislar = boton("Aislar", al_pulsar=lambda _=False, c=cid: self._toggle_aislar(c))
        btn_aislar.setMinimumHeight(t.ALTO_TOQUE)
        h_btn.addWidget(btn_ver, 1)
        h_btn.addWidget(btn_aislar)
        vl.addLayout(h_btn)

        self._crew_cards[cid] = {
            "marco": marco,
            "lbl_id": lbl_id,
            "lbl_link": lbl_link,
            "lbl_det": lbl_det,
            "btn_ver": btn_ver,
            "btn_aislar": btn_aislar,
        }
        return marco

    def _crear_celda_vivo(self, pid: str) -> QFrame:
        marco = _MarcoTactil(
            al_pulsar=lambda p=pid: self.state.ir_a("historial", paramId=p, modo="vivo"),
            nombre_objeto="celdaTactil",
        )
        vl = QVBoxLayout(marco)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(6)

        param = get_param(pid) or {"nombre": pid, "unidad": ""}
        h_top = QHBoxLayout()
        h_top.setSpacing(8)
        lbl_nom = etiqueta(nombre_corto(param["nombre"]), t.T_PEQUENO, t.ETIQUETA, peso=600, wrap=True)
        lbl_estado = _pastilla("Normal", t.NORMAL)
        h_top.addWidget(lbl_nom, 1)
        h_top.addWidget(lbl_estado, 0)
        vl.addLayout(h_top)

        h_val = QHBoxLayout()
        h_val.setSpacing(6)
        lbl_val = etiqueta("–", 26, t.TEXTO, peso=300)
        lbl_uni = etiqueta(str(param.get("unidad", "")), t.T_PEQUENO, t.SECUNDARIO)
        h_val.addWidget(lbl_val, 0, Qt.AlignBottom)
        h_val.addWidget(lbl_uni, 0, Qt.AlignBottom)
        h_val.addStretch(1)
        vl.addLayout(h_val)

        h_pie = QHBoxLayout()
        h_pie.setSpacing(8)
        lbl_regla = etiqueta("", t.T_PEQUENO, t.TERCIARIO, wrap=True)
        lbl_hint = etiqueta("Historial →", t.T_PEQUENO - 1, t.TERCIARIO)
        h_pie.addWidget(lbl_regla, 1)
        h_pie.addWidget(lbl_hint, 0, Qt.AlignRight | Qt.AlignBottom)
        vl.addLayout(h_pie)

        self._tele_cards[pid] = {
            "marco": marco,
            "lbl_nom": lbl_nom,
            "lbl_val": lbl_val,
            "lbl_uni": lbl_uni,
            "lbl_estado": lbl_estado,
            "lbl_regla": lbl_regla,
        }
        return marco

    # ------------------------------------------------------------------
    # Navegación interna y eventos
    # ------------------------------------------------------------------

    def seleccionar_panel(self, panel: str) -> None:
        if panel not in self._indice_paneles:
            return
        self._panel_actual = panel
        btn = self.botones_flujo.get(panel)
        if btn is not None:
            btn.setChecked(True)
        desc = _DESCRIPCIONES_PANEL.get(panel, "")
        self.lbl_flujo_desc.setText(tr(desc) if desc else "")
        self.stack_sala.setCurrentIndex(self._indice_paneles[panel])
        if panel == "bitacora":
            self.panel_bitacora.refrescar(forzar=True)
        elif panel == "eventos":
            self.panel_eventos.refrescar(forzar=True)
        elif panel == "cola":
            self.panel_cola.refrescar(forzar=True)
            self.refrescar(forzar=True)
        else:
            self.refrescar(forzar=True)

    def _on_ayuda_cambiada_sala(self) -> None:
        if self._panel_actual == "eventos":
            self.panel_eventos.refrescar(forzar=True)
        else:
            self._pendiente_refresco = True

    def _on_entorno_elegido(self, entorno: str) -> None:
        self.state.set_entorno(entorno)
        self.refrescar(forzar=True)

    def _on_entorno_cambiado_ext(self, entorno: str) -> None:
        self.chips_entorno.marcar(entorno)
        self._repoblar_combo_anomalias()
        self.refrescar()

    def _on_modo_elegido(self, modo: str) -> None:
        self.state.set_modo_telemetria(modo)
        self.refrescar(forzar=True)

    def _on_red_elegida(self, estado: str) -> None:
        get_sync_manager().set_estado_red(estado)
        self.state.set_enlace_tierra(estado != "offline")
        self.refrescar(forzar=True)

    def _toggle_aislar(self, cid: str) -> None:
        hub = get_crew_hub()
        actual = hub.es_estacion_aislada(cid)
        hub.set_estacion_aislada(cid, not actual)
        self.refrescar(forzar=True)

    def _repoblar_combo_anomalias(self) -> None:
        actual = self.combo_anomalia.currentData()
        self.combo_anomalia.blockSignals(True)
        try:
            self.combo_anomalia.clear()
            entorno = self.state.entorno
            activos = {p["id"]: p for p in listar_por_entorno(entorno)}
            vistos = set()
            for pid in _PARAMETROS_VIVO_ORDER:
                if pid in activos:
                    p = activos[pid]
                    self.combo_anomalia.addItem(f"{nombre_corto(p['nombre'])} ({p['unidad']})", pid)
                    vistos.add(pid)
            for pid, p in activos.items():
                if pid not in vistos:
                    self.combo_anomalia.addItem(f"{nombre_corto(p['nombre'])} ({p['unidad']})", pid)
            if actual:
                idx = self.combo_anomalia.findData(actual)
                if idx >= 0:
                    self.combo_anomalia.setCurrentIndex(idx)
        finally:
            self.combo_anomalia.blockSignals(False)

    def _inyectar_anomalia(self, nivel: str) -> None:
        pid = self.combo_anomalia.currentData()
        if not pid:
            return
        rt = get_runtime()
        try:
            rt.forzar_anomalia(str(pid), nivel, crew_id=self.state.crew_id, duracion_ms=30_000)
            self.lbl_anom_estado.setText(
                tr(
                    "Anomalía {nivel} activa en {param} (30 s)",
                    nivel=tr(t.texto_triage(nivel)),
                    param=str(pid),
                )
            )
        except Exception as exc:
            self.lbl_anom_estado.setText(str(exc))
        self.refrescar(forzar=True)

    def _limpiar_anomalias(self) -> None:
        get_runtime().limpiar_anomalias(self.state.crew_id)
        self.lbl_anom_estado.setText(tr("Sin anomalías forzadas activas"))
        self.refrescar(forzar=True)

    def _forzar_flush(self) -> None:
        mgr = get_sync_manager()
        if mgr.estado_red() == "offline":
            self.lbl_sync_feedback.setText(tr("Sin conexión: lotes retenidos en cola local."))
        else:
            res = mgr.flush_cola()
            cola = mgr.stats().get("cola", {})
            self.lbl_sync_feedback.setText(
                tr(
                    "Lote enviado: {env} confirmados · {pend} pendientes · hash {h}",
                    env=int(res.get("exitosos", 0)),
                    pend=int(cola.get("pendientes", 0)),
                    h=str(cola.get("ultimoHash") or "–")[:12],
                )
            )
        self.panel_cola.refrescar(forzar=True)
        self.refrescar(forzar=True)

    def _exportar_respaldo(self) -> None:
        payload = exportar_respaldo_completo()
        destino_dir = Path(DATA_DIR) / "central"
        destino_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        archivo = destino_dir / f"respaldo-vitalis-{ts}.json"
        archivo.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            rel = str(archivo.relative_to(Path(ROOT_DIR))).replace("\\", "/")
        except ValueError:
            rel = str(archivo)
        self.lbl_sync_feedback.setText(tr("Respaldo guardado en {ruta}", ruta=rel))

    # ------------------------------------------------------------------
    # Refresco de UI
    # ------------------------------------------------------------------

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self._pendiente_refresco:
            self._pendiente_refresco = False
            self.refrescar(forzar=True)

    def _refrescar_si_visible(self) -> None:
        if self.isVisible():
            self.refrescar(forzar=True)
        else:
            self._pendiente_refresco = True

    def refrescar(self, *_args, forzar: bool = False) -> None:
        if not forzar and not self.isVisible():
            self._pendiente_refresco = True
            return
        self._pendiente_refresco = False

        rt = get_runtime()
        hub = get_crew_hub()
        sync = get_sync_manager()
        entorno = self.state.entorno
        crew = self.state.crew_id
        self.chips_entorno.marcar(entorno)
        self.chips_modo.marcar(self.state.modo_telemetria)
        self.chips_red.marcar(sync.estado_red())
        self.lbl_crew_escenario.setText(tr("Destino: {crew}", crew=crew))
        estilo_pastilla(self.lbl_crew_escenario, t.ETIQUETA)

        snap = hub.snapshot()
        resumen_rt = rt.estado_resumen()

        # Pastillas de estado global en barra superior y paso Escenario
        n_activos = len(listar_por_entorno(entorno))
        ent_txt = tr(_ETIQUETAS_ENTORNO.get(entorno, entorno))
        self.lbl_resumen_entorno.setText(f"{ent_txt} · {n_activos}")
        estilo_pastilla(self.lbl_resumen_entorno, t.ETIQUETA)

        motor_activo = getattr(rt, "_motores", {}).get(crew)
        tp_replay = (
            motor_activo.fuente.get_timepoint_actual()
            if motor_activo is not None and hasattr(motor_activo.fuente, "get_timepoint_actual")
            else None
        )
        if self.state.modo_telemetria == "replay-osdr":
            tps = ["R+1", "R+44", "R+82", "R+118", "R+150", "R+175", "R+194"]
            tp_act = tp_replay or "R+1"
            paso = tps.index(tp_act) + 1 if tp_act in tps else 1
            replay_str = f"Replay OSDR · {tp_act} ({paso}/{len(tps)})"
            self.lbl_replay_badge.setText(replay_str)
            self.lbl_replay_escenario.setText(replay_str)
            estilo_pastilla(self.lbl_replay_badge, t.ATENCION)
        else:
            modo_str = tr("Simulación 1 Hz · activo")
            self.lbl_replay_badge.setText(modo_str)
            self.lbl_replay_escenario.setText(modo_str)
            estilo_pastilla(self.lbl_replay_badge, t.NORMAL)

        if entorno == "base-lunar":
            self.lbl_entorno_nota.setText(
                tr("{n} parámetros activos · sin microgravedad (ICP omitido)", n=n_activos)
            )
        else:
            self.lbl_entorno_nota.setText(tr("{n} parámetros activos", n=n_activos))

        # 4 tarjetas de tripulación
        estaciones = {e["crewId"]: e for e in snap}
        for cid, ui in self._crew_cards.items():
            est = estaciones.get(cid, {})
            enlace = str(est.get("estadoEnlace", "sin-enlace"))
            silencio_val = est.get("silencioSegundos")
            silencio_s = float(silencio_val if silencio_val is not None else 0.0)
            ui["lbl_link"].setText(tr(_texto_enlace(enlace)))
            estilo_pastilla(ui["lbl_link"], _color_enlace(enlace))

            alertas = est.get("alertasActivas", []) or []
            nivel_m = str(est.get("nivel", "NOMINAL"))
            if alertas:
                titulos = ", ".join(a.get("parametroId", "") for a in alertas[:2])
                ui["lbl_det"].setText(
                    tr(
                        "{n} alertas ({nivel}): {lista}",
                        n=len(alertas),
                        nivel=tr(t.texto_triage(nivel_m)),
                        lista=titulos,
                    )
                )
            elif silencio_val is None:
                ui["lbl_det"].setText(tr("Sin lectura"))
            else:
                ui["lbl_det"].setText(tr("En rango · señal hace {s:.0f} s", s=silencio_s))

            borde = t.TEXTO if cid == crew else t.BORDE
            grosor = 2 if cid == crew else 1
            if nivel_m == "CRITICO" or enlace == "sin-enlace":
                borde = t.ALERTA
            ui["marco"].setStyleSheet(
                f"QFrame#tarjeta {{ background: {t.TARJETA}; border: {grosor}px solid {borde}; border-radius: 16px; }}"
            )
            aislada = hub.es_estacion_aislada(cid)
            ui["btn_aislar"].setText(tr("Reconectar" if aislada else "Aislar"))
            ui["btn_ver"].setText(tr("Activa" if cid == crew else "Ver estación"))
            ui["btn_ver"].setEnabled(cid != crew)

        # Telemetría en vivo de la estación seleccionada
        self.lbl_titulo_vivo.setText(tr("TELEMETRÍA EN VIVO · {crew}", crew=crew))
        modo_lbl = tr(_ETIQUETAS_MODO.get(self.state.modo_telemetria, self.state.modo_telemetria))
        self.lbl_sub_vivo.setText(f"{ent_txt} · {modo_lbl}")
        frame = hub.frame_actual(crew) or rt.frame_actual(crew) or {}
        lecturas = frame.get("lecturas", {}) if isinstance(frame, dict) else {}
        permitidos = {p["id"] for p in listar_por_entorno(entorno)}

        for pid, ui in self._tele_cards.items():
            visible = pid in permitidos
            ui["marco"].setVisible(visible)
            if not visible:
                continue
            item = lecturas.get(pid)
            if isinstance(item, dict):
                val = item.get("valor")
                calidad = item.get("calidad", 1.0)
                ev = evaluar_lectura_determinista(crew, pid, float(val), calidad=calidad, entorno=entorno)
                nivel = ev.get("nivel", "NOMINAL")
                ui["lbl_val"].setText(f"{val}")
                texto_p = t.texto_triage(nivel)
                if ev.get("degradado"):
                    texto_p = f"{tr(texto_p)} · {tr('Calidad baja')}"
                    estilo_pastilla(
                        ui["lbl_estado"],
                        t.ATENCION if nivel == "NOMINAL" else t.color_triage(nivel),
                    )
                    ui["lbl_estado"].setText(texto_p)
                else:
                    ui["lbl_estado"].setText(tr(texto_p))
                    estilo_pastilla(ui["lbl_estado"], t.color_triage(nivel))
                ui["lbl_regla"].setText(str(ev.get("reglaDisparada", "")))
            else:
                ui["lbl_val"].setText("–")
                ui["lbl_estado"].setText(tr("Sin lectura"))
                estilo_pastilla(ui["lbl_estado"], t.TERCIARIO)
                ui["lbl_regla"].setText("")

        # Anomalías forzadas activas
        anoms = resumen_rt.get("anomaliasActivas", [])
        if anoms:
            resumen_a = ", ".join(f"{a['parametroId']} ({a['nivel']})" for a in anoms)
            self.lbl_anom_estado.setText(tr("Activas: {lista}", lista=resumen_a))
        else:
            self.lbl_anom_estado.setText(tr("Sin anomalías forzadas activas"))

        # Episodios y eventos recientes (resumen compacto)
        episodios = listar_episodios(crew)[:4]
        eventos = listar_eventos_emergencia(crew)
        abiertos = [ep for ep in episodios if ep.get("abierto")]
        self.lbl_epi_resumen.setText(
            tr("{ab} abiertos · {ev} eventos", ab=len(abiertos), ev=len(eventos))
        )
        vaciar_layout(self.vbox_episodios)
        if not episodios:
            self.vbox_episodios.addWidget(etiqueta("Sin episodios registrados", t.T_PEQUENO, t.SECUNDARIO))
        else:
            for ep in episodios:
                fila = QWidget()
                hl = QHBoxLayout(fila)
                hl.setContentsMargins(0, 4, 0, 4)
                hl.setSpacing(8)
                estado_ep = "Abierto" if ep.get("abierto") else "Cerrado"
                nivel_ep = str(ep.get("nivelMaximo", "ATENCION"))
                hl.addWidget(
                    etiqueta(
                        f"{nombre_corto(ep['parametroId'])}",
                        t.T_PEQUENO,
                        t.TEXTO,
                        peso=600,
                    )
                )
                hl.addStretch(1)
                hl.addWidget(_pastilla(t.texto_triage(nivel_ep), t.color_triage(nivel_ep)))
                hl.addWidget(_pastilla(estado_ep, t.ALERTA if estado_ep == "Abierto" else t.TERCIARIO))
                self.vbox_episodios.addWidget(fila)
                self.vbox_episodios.addWidget(divisor())

        if eventos:
            ev0 = eventos[0]
            self.lbl_ultimo_evento.setText(
                tr(
                    "Último evento: {hora} · {sev} · {det}",
                    hora=formatear_ts_ms(ev0.get("timestamp"), con_fecha=False),
                    sev=tr(t.texto_triage(ev0.get("severidad"))),
                    det=str(ev0.get("detalle") or ""),
                )
            )
        else:
            self.lbl_ultimo_evento.setText(tr("Sin eventos de emergencia registrados"))

        # Estado de cola y enlace con Tierra
        stats = sync.stats()
        red = str(stats.get("red", sync.estado_red()))
        cola = stats.get("cola", {})
        red_color = t.NORMAL if red == "online" else (t.ALERTA if red == "offline" else t.ATENCION)
        red_txt = tr(_ETIQUETAS_RED.get(red, red))
        for badge in (self.lbl_red_badge, self.lbl_red_estado_card):
            badge.setText(red_txt)
            estilo_pastilla(badge, red_color)

        por_prio = cola.get("porPrioridad", {})
        self.lbl_cola_resumen.setText(
            tr(
                "Pendientes: {pend} (A:{a} · B:{b} · C:{c} · D:{d}) · Confirmados: {env} · Lotes en Tierra: {rec}",
                pend=int(cola.get("pendientes", 0)),
                a=int(por_p := por_prio.get("A", 0)),
                b=int(por_prio.get("B", 0)),
                c=int(por_prio.get("C", 0)),
                d=int(por_prio.get("D", 0)),
                env=int(cola.get("enviados", 0)),
                rec=int(stats.get("recibidosTierra", 0)),
            )
        )
        hash_ult = cola.get("ultimoHash") or "–"
        self.lbl_hash_cadena.setText(f"Hash cadena: {hash_ult}")

        if self._panel_actual == "bitacora":
            self.panel_bitacora.refrescar(forzar=False)
        elif self._panel_actual == "eventos":
            self.panel_eventos.refrescar(forzar=False)
        elif self._panel_actual == "cola":
            self.panel_cola.refrescar(forzar=False)

    def aplicar_tema(self) -> None:
        self.refrescar(forzar=True)
        self.panel_bitacora.refrescar(forzar=True)
        self.panel_eventos.refrescar(forzar=True)
        self.panel_cola.refrescar(forzar=True)
