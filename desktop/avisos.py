# -*- coding: utf-8 -*-
"""
desktop/avisos.py — Interfaz de los avisos del estado ACTUAL.

Los datos (qué está fuera de rango, qué órganos toca, qué protocolo aplica)
salen de `desktop/estado_actual.py`. Aquí sólo viven las tres piezas que se
tocan: el botón de la barra, el panel de tarjetas y el aviso emergente.
"""

from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop import theme as t
from desktop.estado_actual import (  # noqa: F401  (reexportados para main_window)
    avisos_actuales,
    clave_aviso,
    nivel_maximo,
    organos_con_problema,
    pendientes,
    resumen,
)
from desktop.i18n import tr
from desktop.views import area_desplazable, pastilla
from desktop.widgets import boton, etiqueta, vaciar_layout


def _sombra(w: QWidget) -> None:
    s = QGraphicsDropShadowEffect(w)
    s.setBlurRadius(32)
    s.setOffset(0, 10)
    s.setColor(QColor(*t.SOMBRA_RGB))
    w.setGraphicsEffect(s)


def _actualizar_sombra(w: QWidget) -> None:
    eff = w.graphicsEffect()
    if isinstance(eff, QGraphicsDropShadowEffect):
        eff.setColor(QColor(*t.SOMBRA_RGB))


# ---------------------------------------------------------------------------
# Botón de la barra superior
# ---------------------------------------------------------------------------

class BotonAvisos(QPushButton):
    def __init__(self) -> None:
        super().__init__("Sin avisos")
        self._n = 0
        self._nivel = "NOMINAL"
        self._n_total = 0
        self._nivel_total = "NOMINAL"
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(t.ALTO_TOQUE)
        self.set_estado(0, "NOMINAL")

    def aplicar_tema(self) -> None:
        self.set_estado(self._n, self._nivel, self._n_total, self._nivel_total)

    def retraducir(self) -> None:
        self.set_estado(self._n, self._nivel, self._n_total, self._nivel_total)

    def set_estado(self, n: int, nivel: str, n_total: int = 0, nivel_total: str = "NOMINAL") -> None:
        """`n` son los avisos PENDIENTES; `n_total` incluye los ya revisados.

        Revisado no es resuelto: si todo está revisado pero sigue fuera de
        rango, el botón no dice «sin avisos», dice cuántos hay revisados y
        conserva el borde del nivel.
        """
        self._n = n
        self._nivel = nivel
        self._n_total = n_total
        self._nivel_total = nivel_total
        if n == 0 and n_total > 0:
            self.setText(tr("✓ {n} revisado", n=n_total) if n_total == 1 else tr("✓ {n} revisados", n=n_total))
            borde, fondo, color = t.color_triage(nivel_total), "transparent", t.SECUNDARIO
        elif n == 0:
            self.setText(tr("✓ Sin avisos"))
            borde, fondo, color = t.BORDE, "transparent", t.SECUNDARIO
        else:
            c = QColor(t.color_triage(nivel))
            self.setText(tr("●  {n} aviso", n=n) if n == 1 else tr("●  {n} avisos", n=n))
            borde = c.name()
            alfa = 28 if not t.es_oscuro() else 30
            fondo = f"rgba({c.red()}, {c.green()}, {c.blue()}, {alfa})"
            color = c.name()
        self.setStyleSheet(
            f"QPushButton {{ border: 1px solid {borde}; background: {fondo}; color: {color};"
            f" border-radius: 12px; padding: 10px 18px; font-size: {t.T_CUERPO}px; font-weight: 600; }}"
        )


# ---------------------------------------------------------------------------
# Panel desplegable con las tarjetas de aviso
# ---------------------------------------------------------------------------

class PanelAvisos(QFrame):
    verEn3D = Signal(dict)
    medir = Signal(str)
    protocolo = Signal(str)
    revisar = Signal(dict)
    cerrado = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("panelAvisos")
        self._avisos: List[Dict[str, Any]] = []
        self._crew = ""
        self._tp = ""
        _sombra(self)
        self.setFixedWidth(520)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 18, 18, 22)
        capa.setSpacing(10)

        cab = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        self.lbl_titulo_panel = etiqueta("Avisos", 24, None, peso=600)
        col.addWidget(self.lbl_titulo_panel)
        self.lbl_contexto = etiqueta("", t.T_PEQUENO, t.SECUNDARIO)
        col.addWidget(self.lbl_contexto)
        cab.addLayout(col, 1)
        btn_cerrar = boton("✕", al_pulsar=self._cerrar)
        btn_cerrar.setFixedSize(52, 52)
        btn_cerrar.setStyleSheet("font-size: 20px; padding: 0px;")
        cab.addWidget(btn_cerrar, 0, Qt.AlignTop)
        capa.addLayout(cab)

        # Leyenda de colores: la misma en todo el programa.
        self.lbl_leyenda = QLabel("")
        capa.addWidget(self.lbl_leyenda)

        cont = QWidget()
        self.lista = QVBoxLayout(cont)
        self.lista.setContentsMargins(0, 0, 6, 0)
        self.lista.setSpacing(12)
        self.scroll = area_desplazable(cont)
        capa.addWidget(self.scroll, 1)
        self.aplicar_tema()
        self.hide()

    def aplicar_tema(self) -> None:
        self.setStyleSheet(
            f"QFrame#panelAvisos {{ background: {t.PANEL_OPACO}; border: 1px solid {t.BORDE_PANEL}; border-radius: 22px; }}"
        )
        _actualizar_sombra(self)
        self._pintar_leyenda()
        if self._crew:
            self.cargar(self._avisos, self._crew, self._tp)

    def _pintar_leyenda(self) -> None:
        partes = []
        for nivel in ("CRITICO", "ATENCION", "NOMINAL"):
            partes.append(
                f"<span style='color:{t.color_triage(nivel)}; font-size:{t.T_PEQUENO}px;'>●</span>"
                f"<span style='color:{t.SECUNDARIO}; font-size:{t.T_PEQUENO}px;'> {tr(t.texto_triage(nivel))}</span>"
            )
        self.lbl_leyenda.setText("&nbsp;&nbsp;&nbsp;".join(partes))

    def _cerrar(self) -> None:
        self.hide()
        self.cerrado.emit()

    def retraducir(self) -> None:
        self.lbl_titulo_panel.setText(tr("Avisos"))
        self._pintar_leyenda()
        if self._crew:
            self.cargar(self._avisos, self._crew, self._tp)

    def cargar(self, avisos: List[Dict[str, Any]], crew: str, tp: str) -> None:
        self._avisos = list(avisos)
        self._crew = crew
        self._tp = tp
        res = resumen(pendientes(avisos))
        self.lbl_contexto.setText(f"{crew} · {tp}" + (f"   ·   {res}" if res else ""))
        self.setUpdatesEnabled(False)
        try:
            vaciar_layout(self.lista)
            if not avisos:
                self.lista.addWidget(etiqueta(
                    tr("Todo en rango para {crew} en {tp}.", crew=crew, tp=tp),
                    t.T_CUERPO, t.TEXTO_SUAVE, wrap=True,
                ))
            for a in avisos:
                self.lista.addWidget(self._tarjeta(a))
            self.lista.addStretch(1)
        finally:
            self.setUpdatesEnabled(True)

    def _tarjeta(self, a: Dict[str, Any]) -> QFrame:
        color = t.color_triage(a["nivel"])
        revisado = bool(a.get("revisado"))
        f = QFrame()
        f.setObjectName("tarjetaAviso")
        borde_izq = t.BORDE if revisado else color
        f.setStyleSheet(
            f"QFrame#tarjetaAviso {{ background: {t.TARJETA}; border: 1px solid {t.BORDE};"
            f" border-left: 4px solid {borde_izq}; border-radius: 16px; }}"
        )
        v = QVBoxLayout(f)
        v.setContentsMargins(20, 16, 16, 16)
        v.setSpacing(6)

        fila = QHBoxLayout()
        fila.addWidget(etiqueta(a["titulo"], t.T_DESTACADO, t.SECUNDARIO if revisado else None, peso=600), 1)
        fila.addWidget(pastilla(t.texto_triage(a["nivel"]), color))
        v.addLayout(fila)

        v.addWidget(etiqueta(
            tr("{valor} {unidad}   ·   {d} % frente a tu base",
               valor=a["valor"], unidad=a["unidad"], d=f"{a['desvio']:+.0f}"),
            t.T_CUERPO, t.TEXTO_SUAVE,
        ))
        if a.get("origen") == "local":
            v.addWidget(etiqueta(
                tr("Medición tomada con la app · {cuando}", cuando=a.get("momento") or ""),
                t.T_PEQUENO, t.ETIQUETA,
            ))
        if a["nombresOrganos"]:
            v.addWidget(etiqueta(
                tr("Órganos: {lista}", lista=", ".join(a["nombresOrganos"])),
                t.T_PEQUENO, t.SECUNDARIO, wrap=True,
            ))
        if a.get("accion"):
            pref = tr("Qué hacer para mejorar: ") if a["nivel"] == "ATENCION" else ""
            v.addWidget(etiqueta(pref + tr(a["accion"]), t.T_PEQUENO, t.TEXTO_SUAVE, wrap=True))

        botones = QHBoxLayout()
        botones.setSpacing(10)
        botones.addWidget(boton("Ver en 3D", estilo="primario",
                                al_pulsar=lambda _=False, x=a: self.verEn3D.emit(x)), 1)
        botones.addWidget(boton("Medir", al_pulsar=lambda _=False, i=a["indicadorId"]: self.medir.emit(i)), 1)
        if a["nivel"] == "CRITICO" and a.get("protocolo"):
            botones.addWidget(boton("Protocolo", estilo="peligro",
                                    al_pulsar=lambda _=False, p=a["protocolo"]: self.protocolo.emit(p)), 1)
        v.addSpacing(4)
        v.addLayout(botones)

        b_rev = boton(tr("Marcar como pendiente") if revisado else tr("Marcar como revisado"),
                      al_pulsar=lambda _=False, x=a: self.revisar.emit(x))
        b_rev.setStyleSheet(f"border: none; color: {t.SECUNDARIO}; text-align: left; padding-left: 0px;")
        v.addWidget(b_rev)
        return f


# ---------------------------------------------------------------------------
# Aviso emergente (aparece al cambiar de tripulante o de momento, o tras medir)
# ---------------------------------------------------------------------------

class AvisoEmergente(QFrame):
    abrir = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("avisoEmergente")
        self._avisos: List[Dict[str, Any]] = []
        self._crew = ""
        self._tp = ""
        _sombra(self)
        self.setFixedWidth(520)
        capa = QHBoxLayout(self)
        capa.setContentsMargins(20, 12, 12, 12)
        capa.setSpacing(12)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        capa.addWidget(self.lbl, 1)
        self.btn_ver = boton("Ver", estilo="primario", al_pulsar=self._ver)
        self.btn_ver.setFixedWidth(96)
        capa.addWidget(self.btn_ver)
        btn_x = boton("✕", al_pulsar=self.hide)
        btn_x.setFixedSize(52, 52)
        btn_x.setStyleSheet("font-size: 18px; padding: 0px;")
        capa.addWidget(btn_x)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def aplicar_tema(self) -> None:
        _actualizar_sombra(self)
        if self._avisos:
            self._pintar_banner(self._avisos, self._crew, self._tp)

    def retraducir(self) -> None:
        self.btn_ver.setText(tr("Ver"))
        self.aplicar_tema()

    def _ver(self) -> None:
        self.hide()
        self.abrir.emit()

    def _pintar_banner(self, avisos: List[Dict[str, Any]], crew: str, tp: str) -> str:
        nivel = nivel_maximo(avisos)
        color = t.color_triage(nivel)
        self.setStyleSheet(
            f"QFrame#avisoEmergente {{ background: {t.PANEL_OPACO}; border: 1px solid {color}; border-radius: 18px; }}"
        )
        a0 = avisos[0]
        titulo_res = (
            tr("Aviso preventivo · {res}", res=resumen(avisos))
            if nivel == "ATENCION"
            else resumen(avisos)
        )
        consejo = tr(str(a0.get("accion") or ""))
        extra_consejo = (
            f"<br><span style='color:{t.TEXTO}; font-size:{t.T_PEQUENO}px;'>{consejo}</span>"
            if nivel == "ATENCION" and consejo
            else ""
        )
        self.lbl.setText(
            f"<span style='color:{color}; font-size:{t.T_DESTACADO}px; font-weight:600;'>"
            f"{titulo_res}</span><br>"
            f"<span style='color:{t.TEXTO_SUAVE}; font-size:{t.T_CUERPO}px;'>"
            f"{crew} · {tp} · {a0['titulo']}</span>"
            f"{extra_consejo}"
        )
        return nivel

    def mostrar(self, avisos: List[Dict[str, Any]], crew: str, tp: str) -> None:
        self._avisos = list(avisos)
        self._crew = crew
        self._tp = tp
        nivel = self._pintar_banner(avisos, crew, tp)
        self.adjustSize()
        self.show()
        self.raise_()
        # Lo crítico se queda hasta que se toca; lo amarillo da tiempo suficiente y se va solo.
        if nivel == "CRITICO":
            self._timer.stop()
        elif nivel == "ATENCION":
            self._timer.start(10000)
        else:
            self._timer.start(8000)
