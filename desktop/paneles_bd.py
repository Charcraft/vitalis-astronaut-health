# -*- coding: utf-8 -*-
"""
desktop/paneles_bd.py — Subpaneles de inspección de base de datos para V.I.T.A.L.I.S.

Expone en UI nativa los registros que ya persiste SQLite (`mission_log`,
`emergency_events`, `episodes`, `help_requests`, `sync_queue`, `data/tierra/lotes.jsonl`)
reutilizando la paleta Dual (`oscuro`/`claro`) y los widgets táctiles de la consola.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.database import (
    atender_solicitud_ayuda,
    listar_bitacora,
    listar_cola_sync_bd,
    listar_episodios,
    listar_eventos_emergencia,
    listar_solicitudes_ayuda,
    registrar_bitacora,
    reintentar_rechazados_bd,
)
from backend.sync_tierra import get_sync_manager, listar_recibidos_tierra
from desktop import theme as t
from desktop.estado_actual import nombre_corto
from desktop.i18n import tr
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

_ACTORES_BITACORA = {
    "TRIPULACION": "Tripulación",
    "CMO": "CMO",
    "TIERRA": "Tierra",
}

_ALCANCES_FILTRO = {
    "activo": "Estación activa",
    "todos": "Toda la tripulación",
}


def formatear_ts_ms(ts_ms: Optional[int], con_fecha: bool = True) -> str:
    """Convierte milisegundos epoch a texto legible local."""
    if ts_ms is None:
        return "–"
    try:
        dt = datetime.fromtimestamp(int(ts_ms) / 1000.0)
        return dt.strftime("%Y-%m-%d %H:%M:%S" if con_fecha else "%H:%M:%S")
    except Exception:
        return "–"


def formatear_iso(texto_iso: Optional[str]) -> str:
    """Normaliza timestamps ISO-8601 a `YYYY-MM-DD HH:MM:SS`."""
    if not texto_iso:
        return "–"
    txt = str(texto_iso).strip()
    if len(txt) >= 19 and "T" in txt:
        return txt[:19].replace("T", " ")
    return txt[:16].replace("T", " ")


def crear_tabla_vitalis(
    columnas: List[str],
    altura_fila: int = 54,
    cols_stretch: Optional[List[int]] = None,
) -> QTableWidget:
    """Tabla táctil monocromática coherente con Historial."""
    tabla = QTableWidget()
    tabla.setColumnCount(len(columnas))
    tabla.setHorizontalHeaderLabels([tr(c) for c in columnas])
    cab = tabla.horizontalHeader()
    estirar = set(cols_stretch or [0])
    for idx in range(len(columnas)):
        modo = QHeaderView.Stretch if idx in estirar else QHeaderView.ResizeToContents
        cab.setSectionResizeMode(idx, modo)
    cab.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    tabla.verticalHeader().setVisible(False)
    tabla.verticalHeader().setDefaultSectionSize(altura_fila)
    tabla.setShowGrid(False)
    tabla.setEditTriggers(QTableWidget.NoEditTriggers)
    tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
    tabla.setSelectionMode(QAbstractItemView.SingleSelection)
    tabla.setFocusPolicy(Qt.NoFocus)
    tabla.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    scroll_tactil(tabla)
    return tabla


def _pastilla(texto: str, color: str) -> QLabel:
    lbl = QLabel(tr(texto))
    estilo_pastilla(lbl, color)
    return lbl


class PanelBitacoraMision(QWidget):
    """Alta y consulta cronológica de `mission_log` con estado de envío a Tierra."""

    bitacoraActualizada = Signal()

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._actor = "TRIPULACION"
        self._alcance = "todos"
        self._firma_render = ""

        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 4, 0)
        capa.setSpacing(16)

        # --- Tarjeta de captura ---
        card_form = Tarjeta(margen=20, espacio=12)
        h_f = QHBoxLayout()
        h_f.addWidget(etiqueta_mono("Bitácora de misión"))
        h_f.addStretch(1)
        self.lbl_estacion_form = etiqueta("", t.T_PEQUENO, t.SECUNDARIO)
        h_f.addWidget(self.lbl_estacion_form)
        card_form.capa.addLayout(h_f)

        fila_actor = QHBoxLayout()
        fila_actor.setSpacing(12)
        fila_actor.addWidget(etiqueta("Emisor:", t.T_PEQUENO, t.ETIQUETA))
        self.chips_actor = GrupoChips(
            ["TRIPULACION", "CMO", "TIERRA"],
            etiquetas=_ACTORES_BITACORA,
        )
        self.chips_actor.marcar(self._actor)
        self.chips_actor.seleccionado.connect(self._on_actor)
        fila_actor.addWidget(self.chips_actor)
        fila_actor.addStretch(1)
        card_form.capa.addLayout(fila_actor)

        fila_input = QHBoxLayout()
        fila_input.setSpacing(10)
        self.txt_nota = QLineEdit()
        self.txt_nota.setPlaceholderText(
            tr("Registrar novedad clínica, observación de cabina o nota de turno…")
        )
        self.txt_nota.returnPressed.connect(self._guardar_entrada)
        fila_input.addWidget(self.txt_nota, 1)
        self.btn_guardar = boton("Registrar nota", estilo="primario", al_pulsar=self._guardar_entrada)
        fila_input.addWidget(self.btn_guardar)
        card_form.capa.addLayout(fila_input)

        self.lbl_feedback = etiqueta("", t.T_PEQUENO, t.NORMAL, wrap=True)
        card_form.capa.addWidget(self.lbl_feedback)
        capa.addWidget(card_form)

        # --- Tarjeta de entradas ---
        card_list = Tarjeta(margen=20, espacio=12)
        h_l = QHBoxLayout()
        h_l.setSpacing(12)
        h_l.addWidget(etiqueta_mono("Entradas registradas"))
        self.lbl_conteo = etiqueta("", t.T_PEQUENO, t.TERCIARIO)
        h_l.addWidget(self.lbl_conteo)
        h_l.addStretch(1)
        self.chips_alcance = GrupoChips(["todos", "activo"], etiquetas=_ALCANCES_FILTRO)
        self.chips_alcance.marcar(self._alcance)
        self.chips_alcance.seleccionado.connect(self._on_alcance)
        h_l.addWidget(self.chips_alcance)
        h_l.addWidget(boton("Actualizar", al_pulsar=lambda: self.refrescar(forzar=True)))
        card_list.capa.addLayout(h_l)

        self.vbox_entradas = QVBoxLayout()
        self.vbox_entradas.setSpacing(8)
        card_list.capa.addLayout(self.vbox_entradas)
        capa.addWidget(card_list)
        capa.addStretch(1)

    def _on_actor(self, actor: str) -> None:
        self._actor = actor

    def _on_alcance(self, alcance: str) -> None:
        self._alcance = alcance
        self.refrescar(forzar=True)

    def _guardar_entrada(self) -> None:
        texto = self.txt_nota.text().strip()
        if not texto:
            self.lbl_feedback.setText(tr("Escribe una nota antes de guardar."))
            return
        crew = self.state.crew_id
        bid = registrar_bitacora(texto=texto, actor=self._actor, crew_id=crew)
        get_sync_manager().encolar_bitacora(bid)
        self.txt_nota.clear()
        self.lbl_feedback.setText(
            tr("Entrada #{id} registrada y encolada para Tierra (prioridad D) ✓", id=bid)
        )
        self.refrescar(forzar=True)
        self.bitacoraActualizada.emit()

    def refrescar(self, forzar: bool = False) -> None:
        crew = self.state.crew_id
        self.lbl_estacion_form.setText(tr("Estación asociada: {crew}", crew=crew))
        filtro_crew = crew if self._alcance == "activo" else None
        filas = listar_bitacora(limit=60, crew_id=filtro_crew)
        firma = f"{crew}:{self._alcance}:{len(filas)}:" + ",".join(
            f"{f['id']}:{int(bool(f['sincronizadoTierra']))}" for f in filas[:15]
        )
        if not forzar and firma == self._firma_render:
            return
        self._firma_render = firma

        self.lbl_conteo.setText(tr("{n} registros", n=len(filas)))
        vaciar_layout(self.vbox_entradas)
        if not filas:
            self.vbox_entradas.addWidget(
                etiqueta("Todavía no hay entradas en la bitácora de misión.", t.T_CUERPO, t.SECUNDARIO)
            )
            return

        for f in filas:
            fila = QFrame()
            vl = QVBoxLayout(fila)
            vl.setContentsMargins(0, 6, 0, 6)
            vl.setSpacing(6)

            top = QHBoxLayout()
            top.setSpacing(8)
            est = f.get("crewId") or tr("General")
            actor_lbl = tr(_ACTORES_BITACORA.get(str(f.get("actor")), str(f.get("actor"))))
            top.addWidget(etiqueta(f"{formatear_ts_ms(f.get('timestamp'))}", t.T_PEQUENO, t.SECUNDARIO, mono=True))
            top.addWidget(_pastilla(str(est), t.ETIQUETA))
            top.addWidget(_pastilla(actor_lbl, t.TERCIARIO))
            top.addStretch(1)
            if f.get("sincronizadoTierra"):
                top.addWidget(_pastilla("Tierra: Sincronizado", t.NORMAL))
            else:
                top.addWidget(_pastilla("Tierra: Pendiente", t.ATENCION))
            vl.addLayout(top)

            vl.addWidget(etiqueta(str(f.get("texto") or ""), t.T_CUERPO, t.TEXTO, wrap=True))
            self.vbox_entradas.addWidget(fila)
            self.vbox_entradas.addWidget(divisor())


def _formatear_duracion_ms(inicio_ms: Optional[int], fin_ms: Optional[int]) -> str:
    if fin_ms is None or inicio_ms is None:
        return tr("En curso")
    seg = max(0, (int(fin_ms) - int(inicio_ms)) // 1000)
    if seg < 60:
        return f"{seg} s"
    return f"{seg // 60} min {seg % 60} s"


def _pintar_celda_color(tabla: QTableWidget, fila: int, col: int, texto: str, color: str) -> None:
    item = QTableWidgetItem(texto)
    item.setForeground(QColor(color))
    tabla.setItem(fila, col, item)


class PanelEventosYSbar(QWidget):
    """Desglose completo de `help_requests`, `emergency_events` y `episodes`."""

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._alcance = "activo"
        self._filtro_sbar = "todas"
        self._filtro_ep = "todos"
        self._firma_render = ""

        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 4, 0)
        capa.setSpacing(16)

        # --- Filtros globales del panel ---
        card_head = Tarjeta(margen=18, espacio=8)
        h_top = QHBoxLayout()
        h_top.setSpacing(12)
        h_top.addWidget(etiqueta_mono("Eventos clínicos, emergencias y solicitudes SBAR"))
        h_top.addStretch(1)
        self.chips_alcance = GrupoChips(["activo", "todos"], etiquetas=_ALCANCES_FILTRO)
        self.chips_alcance.marcar(self._alcance)
        self.chips_alcance.seleccionado.connect(self._on_alcance)
        h_top.addWidget(self.chips_alcance)
        h_top.addWidget(boton("Actualizar", al_pulsar=lambda: self.refrescar(forzar=True)))
        card_head.capa.addLayout(h_top)
        capa.addWidget(card_head)

        # --- Bandeja SBAR ---
        card_sbar = Tarjeta(margen=20, espacio=12)
        h_sb = QHBoxLayout()
        h_sb.setSpacing(10)
        h_sb.addWidget(etiqueta_mono("Solicitudes médicas SBAR"))
        self.lbl_sbar_conteo = etiqueta("", t.T_PEQUENO, t.TERCIARIO)
        h_sb.addWidget(self.lbl_sbar_conteo)
        h_sb.addStretch(1)
        self.chips_sbar = GrupoChips(
            ["todas", "activas"],
            etiquetas={"todas": "Todas", "activas": "Solo activas"},
        )
        self.chips_sbar.marcar(self._filtro_sbar)
        self.chips_sbar.seleccionado.connect(self._on_filtro_sbar)
        h_sb.addWidget(self.chips_sbar)
        card_sbar.capa.addLayout(h_sb)
        self.vbox_sbar = QVBoxLayout()
        self.vbox_sbar.setSpacing(8)
        card_sbar.capa.addLayout(self.vbox_sbar)
        capa.addWidget(card_sbar)

        # --- Eventos de emergencia ---
        card_evt = Tarjeta(margen=20, espacio=12)
        h_ev = QHBoxLayout()
        h_ev.addWidget(etiqueta_mono("Eventos de emergencia registrados"))
        h_ev.addStretch(1)
        self.lbl_evt_conteo = etiqueta("", t.T_PEQUENO, t.TERCIARIO)
        h_ev.addWidget(self.lbl_evt_conteo)
        card_evt.capa.addLayout(h_ev)
        self.tabla_eventos = crear_tabla_vitalis(
            ["Detalle", "Tripulante", "Nivel", "Hora", "Tierra"],
            altura_fila=54,
            cols_stretch=[0],
        )
        self.tabla_eventos.setMinimumHeight(250)
        card_evt.capa.addWidget(self.tabla_eventos)
        capa.addWidget(card_evt)

        # --- Episodios clínicos ---
        card_ep = Tarjeta(margen=20, espacio=12)
        h_ep = QHBoxLayout()
        h_ep.setSpacing(10)
        h_ep.addWidget(etiqueta_mono("Historial de episodios"))
        self.lbl_ep_conteo = etiqueta("", t.T_PEQUENO, t.TERCIARIO)
        h_ep.addWidget(self.lbl_ep_conteo)
        h_ep.addStretch(1)
        self.chips_ep = GrupoChips(
            ["todos", "abiertos"],
            etiquetas={"todos": "Todos", "abiertos": "Solo abiertos"},
        )
        self.chips_ep.marcar(self._filtro_ep)
        self.chips_ep.seleccionado.connect(self._on_filtro_ep)
        h_ep.addWidget(self.chips_ep)
        card_ep.capa.addLayout(h_ep)
        self.tabla_episodios = crear_tabla_vitalis(
            ["Parámetro", "Tripulante", "Nivel", "Inicio", "Duración", "Estado"],
            altura_fila=54,
            cols_stretch=[0],
        )
        self.tabla_episodios.setMinimumHeight(250)
        card_ep.capa.addWidget(self.tabla_episodios)
        capa.addWidget(card_ep)
        capa.addStretch(1)

    def _on_alcance(self, alcance: str) -> None:
        self._alcance = alcance
        self.refrescar(forzar=True)

    def _on_filtro_sbar(self, filtro: str) -> None:
        self._filtro_sbar = filtro
        self.refrescar(forzar=True)

    def _on_filtro_ep(self, filtro: str) -> None:
        self._filtro_ep = filtro
        self.refrescar(forzar=True)

    def _atender_sbar(self, req_id: int) -> None:
        atender_solicitud_ayuda(int(req_id))
        self.state.ayudaCambiada.emit()
        self.refrescar(forzar=True)

    def refrescar(self, forzar: bool = False) -> None:
        crew = self.state.crew_id
        filtro_crew = crew if self._alcance == "activo" else None
        sbar = listar_solicitudes_ayuda(solo_activas=(self._filtro_sbar == "activas"))
        if filtro_crew:
            sbar = [s for s in sbar if s.get("crewIdSolicitante") == filtro_crew]
        eventos = listar_eventos_emergencia(crew_id=filtro_crew, limit=80)
        episodios = listar_episodios(
            crew_id=filtro_crew, solo_abiertos=(self._filtro_ep == "abiertos"), limit=80
        )

        firma = "|".join([
            crew,
            self._alcance,
            self._filtro_sbar,
            self._filtro_ep,
            f"s:{len(sbar)}:{','.join(str(s['id']) + ':' + s['estado'] for s in sbar[:10])}",
            f"v:{len(eventos)}:{','.join(str(e['id']) + ':' + str(int(bool(e['sincronizadoTierra']))) for e in eventos[:10])}",
            f"p:{len(episodios)}:{','.join(str(p['id']) + ':' + str(int(bool(p['abierto']))) for p in episodios[:10])}",
        ])
        if not forzar and firma == self._firma_render:
            return
        self._firma_render = firma

        self._pintar_sbar(sbar)
        self._pintar_eventos(eventos)
        self._pintar_episodios(episodios)

    def _pintar_sbar(self, solicitudes: List[Dict[str, Any]]) -> None:
        activas = sum(1 for s in solicitudes if s.get("estado") == "ACTIVA")
        self.lbl_sbar_conteo.setText(
            tr("{tot} solicitudes ({act} activas)", tot=len(solicitudes), act=activas)
        )
        vaciar_layout(self.vbox_sbar)
        if not solicitudes:
            self.vbox_sbar.addWidget(
                etiqueta("Sin solicitudes SBAR registradas en este filtro.", t.T_CUERPO, t.SECUNDARIO)
            )
            return

        for s in solicitudes:
            fila = QFrame()
            vl = QVBoxLayout(fila)
            vl.setContentsMargins(0, 6, 0, 6)
            vl.setSpacing(6)

            top = QHBoxLayout()
            top.setSpacing(8)
            estado = str(s.get("estado") or "ACTIVA")
            top.addWidget(etiqueta(f"{s['hash']} · {formatear_iso(s.get('timestamp'))}", t.T_PEQUENO, t.SECUNDARIO, mono=True))
            top.addWidget(_pastilla(f"{s['crewIdSolicitante']} → {s['destinatario']}", t.ETIQUETA))
            top.addWidget(_pastilla(t.texto_triage(s.get("nivel")), t.color_triage(s.get("nivel"))))
            top.addStretch(1)
            top.addWidget(_pastilla("Activa" if estado == "ACTIVA" else "Atendida", t.ALERTA if estado == "ACTIVA" else t.NORMAL))
            vl.addLayout(top)

            vl.addWidget(etiqueta(str(s.get("motivo") or ""), t.T_CUERPO, t.TEXTO, peso=600, wrap=True))
            if s.get("resumenClinico"):
                vl.addWidget(etiqueta(str(s["resumenClinico"]), t.T_PEQUENO, t.TEXTO_SUAVE, wrap=True))

            acc = QHBoxLayout()
            acc.setSpacing(8)
            proto_id = s.get("protocoloSugeridoId")
            if proto_id:
                acc.addWidget(
                    boton(
                        "Abrir protocolo",
                        al_pulsar=lambda _=False, p=str(proto_id): self.state.ir_a("emergencia", protocoloId=p),
                    )
                )
            if estado == "ACTIVA":
                acc.addWidget(
                    boton(
                        "Marcar atendida",
                        estilo="primario",
                        al_pulsar=lambda _=False, rid=int(s["id"]): self._atender_sbar(rid),
                    )
                )
            acc.addStretch(1)
            vl.addLayout(acc)
            self.vbox_sbar.addWidget(fila)
            self.vbox_sbar.addWidget(divisor())

    def _pintar_eventos(self, eventos: List[Dict[str, Any]]) -> None:
        self.lbl_evt_conteo.setText(tr("{n} eventos", n=len(eventos)))
        self.tabla_eventos.setHorizontalHeaderLabels(
            [tr("Detalle"), tr("Tripulante"), tr("Nivel"), tr("Hora"), tr("Tierra")]
        )
        self.tabla_eventos.setUpdatesEnabled(False)
        try:
            self.tabla_eventos.setRowCount(len(eventos))
            for idx, ev in enumerate(eventos):
                sev = str(ev.get("severidad") or "ATENCION")
                sinc = bool(ev.get("sincronizadoTierra"))
                self.tabla_eventos.setItem(idx, 0, QTableWidgetItem(str(ev.get("detalle") or "")))
                _pintar_celda_color(self.tabla_eventos, idx, 1, str(ev.get("crewId") or ""), t.SECUNDARIO)
                _pintar_celda_color(self.tabla_eventos, idx, 2, tr(t.texto_triage(sev)), t.color_triage(sev))
                _pintar_celda_color(self.tabla_eventos, idx, 3, formatear_ts_ms(ev.get("timestamp")), t.SECUNDARIO)
                _pintar_celda_color(
                    self.tabla_eventos,
                    idx,
                    4,
                    tr("Sincronizado" if sinc else "Pendiente"),
                    t.NORMAL if sinc else t.ATENCION,
                )
        finally:
            self.tabla_eventos.setUpdatesEnabled(True)

    def _pintar_episodios(self, episodios: List[Dict[str, Any]]) -> None:
        self.lbl_ep_conteo.setText(tr("{n} episodios", n=len(episodios)))
        self.tabla_episodios.setHorizontalHeaderLabels(
            [tr("Parámetro"), tr("Tripulante"), tr("Nivel"), tr("Inicio"), tr("Duración"), tr("Estado")]
        )
        self.tabla_episodios.setUpdatesEnabled(False)
        try:
            self.tabla_episodios.setRowCount(len(episodios))
            for idx, ep in enumerate(episodios):
                niv = str(ep.get("nivelMaximo") or "ATENCION")
                abierto = bool(ep.get("abierto"))
                self.tabla_episodios.setItem(idx, 0, QTableWidgetItem(nombre_corto(str(ep.get("parametroId") or ""))))
                _pintar_celda_color(self.tabla_episodios, idx, 1, str(ep.get("crewId") or ""), t.SECUNDARIO)
                _pintar_celda_color(self.tabla_episodios, idx, 2, tr(t.texto_triage(niv)), t.color_triage(niv))
                _pintar_celda_color(self.tabla_episodios, idx, 3, formatear_ts_ms(ep.get("inicio")), t.SECUNDARIO)
                _pintar_celda_color(
                    self.tabla_episodios, idx, 4, _formatear_duracion_ms(ep.get("inicio"), ep.get("fin")), t.SECUNDARIO
                )
                _pintar_celda_color(
                    self.tabla_episodios,
                    idx,
                    5,
                    tr("Abierto" if abierto else "Cerrado"),
                    t.ALERTA if abierto else t.SECUNDARIO,
                )
        finally:
            self.tabla_episodios.setUpdatesEnabled(True)


class PanelColaTierra(QWidget):
    """Inspector de `sync_queue` (prioridad A>B>C>D) y lotes confirmados en Tierra."""

    colaActualizada = Signal()

    def __init__(self, state: AppState, mostrar_cabecera: bool = True) -> None:
        super().__init__()
        self.state = state
        self._estado_filtro = "todos"
        self._firma_render = ""

        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 4, 0)
        capa.setSpacing(16)

        # --- Resumen y controles ---
        card_top = Tarjeta(margen=20, espacio=12)
        h_top = QHBoxLayout()
        h_top.setSpacing(10)
        h_top.addWidget(etiqueta_mono("Cola prioritaria y lotes en Tierra"))
        h_top.addStretch(1)
        self.lbl_resumen = etiqueta("", t.T_PEQUENO, t.TEXTO_SUAVE, wrap=True)
        card_top.capa.addLayout(h_top)
        card_top.capa.addWidget(self.lbl_resumen)

        h_btn = QHBoxLayout()
        h_btn.setSpacing(8)
        h_btn.addWidget(boton("Sincronizar ahora", estilo="primario", al_pulsar=self._forzar_flush))
        h_btn.addWidget(boton("Reintentar rechazados", al_pulsar=self._reintentar))
        h_btn.addWidget(boton("Actualizar", al_pulsar=lambda: self.refrescar(forzar=True)))
        h_btn.addStretch(1)
        card_top.capa.addLayout(h_btn)
        self.lbl_feedback = etiqueta("", t.T_PEQUENO, t.SECUNDARIO, wrap=True)
        card_top.capa.addWidget(self.lbl_feedback)
        card_top.setVisible(mostrar_cabecera)
        capa.addWidget(card_top)

        # --- Cola de envío local ---
        card_cola = Tarjeta(margen=20, espacio=12)
        h_c = QHBoxLayout()
        h_c.setSpacing(10)
        h_c.addWidget(etiqueta_mono("Cola local de envío"))
        self.lbl_cola_conteo = etiqueta("", t.T_PEQUENO, t.TERCIARIO)
        h_c.addWidget(self.lbl_cola_conteo)
        h_c.addStretch(1)
        self.chips_estado = GrupoChips(
            ["todos", "pendiente", "enviado", "rechazado"],
            etiquetas={
                "todos": "Todos",
                "pendiente": "Pendientes",
                "enviado": "Enviados",
                "rechazado": "Rechazados",
            },
        )
        self.chips_estado.marcar(self._estado_filtro)
        self.chips_estado.seleccionado.connect(self._on_filtro)
        h_c.addWidget(self.chips_estado)
        card_cola.capa.addLayout(h_c)

        self.tabla_cola = crear_tabla_vitalis(
            ["Hash / Cadena", "Tipo", "Prio", "Estado", "Intentos", "Hora"],
            altura_fila=54,
            cols_stretch=[0],
        )
        self.tabla_cola.setMinimumHeight(250)
        card_cola.capa.addWidget(self.tabla_cola)
        capa.addWidget(card_cola)

        # --- Lotes recibidos en Tierra ---
        card_tierra = Tarjeta(margen=20, espacio=12)
        h_t = QHBoxLayout()
        h_t.addWidget(etiqueta_mono("Confirmados en Tierra"))
        h_t.addStretch(1)
        self.lbl_tierra_conteo = etiqueta("", t.T_PEQUENO, t.TERCIARIO)
        h_t.addWidget(self.lbl_tierra_conteo)
        card_tierra.capa.addLayout(h_t)
        self.tabla_tierra = crear_tabla_vitalis(
            ["Hash / Cadena", "Tipo", "Prio", "Lote", "Recibido en Tierra"],
            altura_fila=54,
            cols_stretch=[0],
        )
        self.tabla_tierra.setMinimumHeight(230)
        card_tierra.capa.addWidget(self.tabla_tierra)
        capa.addWidget(card_tierra)
        capa.addStretch(1)

    def _on_filtro(self, estado: str) -> None:
        self._estado_filtro = estado
        self.refrescar(forzar=True)

    def _forzar_flush(self) -> None:
        sync = get_sync_manager()
        if sync.estado_red() == "offline":
            self.lbl_feedback.setText(tr("Sin conexión: los lotes siguen retenidos en cola local."))
            return
        res = sync.flush_cola()
        self.lbl_feedback.setText(
            tr(
                "Envío ejecutado: {ok} confirmados · {fail} fallidos ({ms} ms).",
                ok=int(res.get("exitosos", 0)),
                fail=int(res.get("fallidos", 0)),
                ms=int(res.get("duracionMs", 0)),
            )
        )
        self.refrescar(forzar=True)
        self.colaActualizada.emit()

    def _reintentar(self) -> None:
        n = reintentar_rechazados_bd()
        self.lbl_feedback.setText(tr("{n} lotes rechazados devueltos a pendiente.", n=n))
        self.refrescar(forzar=True)
        self.colaActualizada.emit()

    def refrescar(self, forzar: bool = False) -> None:
        sync = get_sync_manager()
        stats = sync.stats()
        cola_st = stats.get("cola", {})
        por_p = cola_st.get("porPrioridad", {})
        filtro = None if self._estado_filtro == "todos" else self._estado_filtro
        lotes_cola = listar_cola_sync_bd(limit=80, estado=filtro)
        lotes_tierra = listar_recibidos_tierra(limit=50, path=sync._lotes_path)

        firma = "|".join([
            self._estado_filtro,
            str(stats.get("red")),
            str(cola_st.get("pendientes", 0)),
            str(cola_st.get("enviados", 0)),
            str(stats.get("recibidosTierra", 0)),
            f"q:{lotes_cola[0]['id'] if lotes_cola else 0}:{len(lotes_cola)}",
            f"t:{lotes_tierra[0].get('hash') if lotes_tierra else ''}:{len(lotes_tierra)}",
        ])
        if not forzar and firma == self._firma_render:
            return
        self._firma_render = firma

        self.lbl_resumen.setText(
            tr(
                "Pendientes: {pend} (A:{a} · B:{b} · C:{c} · D:{d}) · Confirmados: {env} · Recibidos en Tierra: {rec}",
                pend=int(cola_st.get("pendientes", 0)),
                a=int(por_p.get("A", 0)),
                b=int(por_p.get("B", 0)),
                c=int(por_p.get("C", 0)),
                d=int(por_p.get("D", 0)),
                env=int(cola_st.get("enviados", 0)),
                rec=int(stats.get("recibidosTierra", 0)),
            )
        )
        self._pintar_tabla_cola(lotes_cola)
        self._pintar_tabla_tierra(lotes_tierra)

    def _pintar_tabla_cola(self, lotes: List[Dict[str, Any]]) -> None:
        self.lbl_cola_conteo.setText(tr("{n} mostrados", n=len(lotes)))
        self.tabla_cola.setHorizontalHeaderLabels(
            [tr("Hash / Cadena"), tr("Tipo"), tr("Prio"), tr("Estado"), tr("Intentos"), tr("Hora")]
        )
        self.tabla_cola.setUpdatesEnabled(False)
        try:
            self.tabla_cola.setRowCount(len(lotes))
            for idx, l in enumerate(lotes):
                est = str(l.get("estado") or "pendiente")
                prio = str(l.get("prioridad") or "C")
                h_txt = f"#{l['id']} · {l.get('hash') or '–'} ← {l.get('hashPrevio') or 'semilla'}"
                color_est = t.NORMAL if est == "enviado" else (t.ALERTA if est == "rechazado" else t.ATENCION)
                color_prio = t.ALERTA if prio == "A" else (t.ATENCION if prio == "B" else t.SECUNDARIO)
                self.tabla_cola.setItem(idx, 0, QTableWidgetItem(h_txt))
                _pintar_celda_color(self.tabla_cola, idx, 1, str(l.get("tipo") or ""), t.TEXTO_SUAVE)
                _pintar_celda_color(self.tabla_cola, idx, 2, prio, color_prio)
                _pintar_celda_color(self.tabla_cola, idx, 3, tr(est.capitalize()), color_est)
                _pintar_celda_color(self.tabla_cola, idx, 4, str(l.get("intentos", 0)), t.SECUNDARIO)
                _pintar_celda_color(self.tabla_cola, idx, 5, formatear_ts_ms(l.get("creadoEn")), t.SECUNDARIO)
        finally:
            self.tabla_cola.setUpdatesEnabled(True)

    def _pintar_tabla_tierra(self, lotes: List[Dict[str, Any]]) -> None:
        self.lbl_tierra_conteo.setText(tr("{n} recientes", n=len(lotes)))
        self.tabla_tierra.setHorizontalHeaderLabels(
            [tr("Hash / Cadena"), tr("Tipo"), tr("Prio"), tr("Lote"), tr("Recibido en Tierra")]
        )
        self.tabla_tierra.setUpdatesEnabled(False)
        try:
            self.tabla_tierra.setRowCount(len(lotes))
            for idx, l in enumerate(lotes):
                h_txt = f"{l.get('hash') or '–'} ← {l.get('hashPrevio') or 'semilla'}"
                prio = str(l.get("prioridad") or "C")
                color_prio = t.ALERTA if prio == "A" else (t.ATENCION if prio == "B" else t.SECUNDARIO)
                self.tabla_tierra.setItem(idx, 0, QTableWidgetItem(h_txt))
                _pintar_celda_color(self.tabla_tierra, idx, 1, str(l.get("tipo") or ""), t.TEXTO_SUAVE)
                _pintar_celda_color(self.tabla_tierra, idx, 2, prio, color_prio)
                _pintar_celda_color(self.tabla_tierra, idx, 3, f"#{l.get('id', '–')}", t.SECUNDARIO)
                _pintar_celda_color(
                    self.tabla_tierra, idx, 4, formatear_ts_ms(l.get("recibidoTierraEn")), t.NORMAL
                )
        finally:
            self.tabla_tierra.setUpdatesEnabled(True)
