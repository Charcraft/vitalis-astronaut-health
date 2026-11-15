# -*- coding: utf-8 -*-
"""
desktop/alsp_anim.py — Animaciones nativas del ALSP para la app de escritorio.

No usa HTML, video ni imágenes raster: dibuja las cuatro herramientas con
QPainter sobre un lienzo virtual de 880×520 y avanza el tiempo con un QTimer.
El contenido clínico (títulos, duraciones y notas 0G) se lee del mismo JSON que
usa la app web, para que ambas interfaces no se separen.

Herramientas: DEA · IV presurizada · Vía aérea · Fármacos.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from desktop.alsp_i18n import translate

ANCHO, ALTO = 880, 520
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(ROOT_DIR, "recursos", "datos", "knowledge", "alsp-equipos.json")

from desktop import theme as _theme
from desktop.i18n import tr

_PAL_ALSP = {
    "oscuro": {
        "FONDO": "#090B0F",
        "SUP": "#12161D",
        "SUP2": "#191F29",
        "SUP3": "#202734",
        "TEXTO": "#ECEFF4",
        "SUAVE": "#8E95A4",
        "DIM": "#555B68",
        "LINEA": "#2A303B",
        "CRIT": "#E5484D",
        "PIE": "#687080",
        "PANTALLA": "#05070A",
        "ECG_BG": "#06080B",
        "ECG_TXT": "#ECEFF4",
        "BOLSA": "#0C1015",
        "GOTERO": "#06080B",
        "BOCA": "#05070A",
        "TINTA_RGB": (236, 239, 244),
        "SUAVE_RGB": (142, 149, 164),
        "VENA_RGB": (169, 176, 190),
    },
    "claro": {
        "FONDO": "#F4F7FB",
        "SUP": "#E8EEF5",
        "SUP2": "#DCE4F0",
        "SUP3": "#CFD9E6",
        "TEXTO": "#0F141C",
        "SUAVE": "#475569",
        "DIM": "#64748B",
        "LINEA": "#CBD5E1",
        "CRIT": "#C92A32",
        "PIE": "#7A8699",
        "PANTALLA": "#0F172A",
        "ECG_BG": "#0F172A",
        "ECG_TXT": "#F1F5F9",
        "BOLSA": "#E2E8F0",
        "GOTERO": "#DCE4F0",
        "BOCA": "#334155",
        "TINTA_RGB": (15, 20, 28),
        "SUAVE_RGB": (71, 85, 105),
        "VENA_RGB": (91, 107, 130),
    },
}

FONDO = "@FONDO"
SUP = "@SUP"
SUP2 = "@SUP2"
SUP3 = "@SUP3"
TEXTO = "@TEXTO"
SUAVE = "@SUAVE"
DIM = "@DIM"
LINEA = "@LINEA"
CRIT = "@CRIT"
PIE = "@PIE"
PANTALLA = "@PANTALLA"
ECG_BG = "@ECG_BG"
ECG_TXT = "@ECG_TXT"
BOLSA = "@BOLSA"
GOTERO = "@GOTERO"
BOCA = "@BOCA"


def _pal() -> dict:
    return _PAL_ALSP["oscuro" if _theme.es_oscuro() else "claro"]


def _qc(val, alpha=None) -> QColor:
    if isinstance(val, str) and val.startswith("@"):
        val = _pal().get(val[1:], val)
    c = QColor(val)
    if alpha is not None:
        c.setAlpha(int(alpha))
    return c


def _c_tinta(alpha: int) -> QColor:
    r, g, b = _pal()["TINTA_RGB"]
    return QColor(r, g, b, int(alpha))


def _c_suave(alpha: int) -> QColor:
    r, g, b = _pal()["SUAVE_RGB"]
    return QColor(r, g, b, int(alpha))


def _c_vena(alpha: int) -> QColor:
    r, g, b = _pal()["VENA_RGB"]
    return QColor(r, g, b, int(alpha))

MONO = "Consolas"


def _cargar_equipos() -> Dict[str, Dict[str, Any]]:
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {e["id"]: e for e in data.get("equipos", [])}
    except Exception:
        # Respaldo mínimo: la app sigue funcionando aunque falte el JSON.
        return {
            "dea": {
                "id": "dea",
                "codigo": "ALSP-01",
                "nombreCorto": "DEA",
                "pasos": [
                    {"titulo": "Uso del DEA", "duracionS": 12, "nota0G": "Ancla los pies."}
                ],
            }
        }


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class WidgetAnimacionALSP(QWidget):
    """Lienzo animado de una herramienta del ALSP."""

    actoCambiado = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(200)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.equipos = _cargar_equipos()
        self.equipo_id = "dea" if "dea" in self.equipos else next(iter(self.equipos))
        self.acto = 0
        self.t = 0.0
        self.reproduciendo = True
        self.fase = 0.0
        # Modo render de video: sin cabecera/pie, solo la escena (HyperFrames).
        self.modo_video = False
        # "es" para la app; "en" para los videos en inglés.
        self.idioma = "es"

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        # El timer arranca en showEvent para no repintar fuera de la vista.

    # ------------------------------------------------------------------ API
    def pasos(self) -> List[Dict[str, Any]]:
        return list(self.equipos.get(self.equipo_id, {}).get("pasos", []))

    def paso_actual(self) -> Dict[str, Any]:
        pasos = self.pasos()
        if not pasos:
            return {"titulo": "Sin datos", "duracionS": 8, "nota0G": ""}
        return pasos[self.acto % len(pasos)]

    def codigo(self) -> str:
        return str(self.equipos.get(self.equipo_id, {}).get("codigo", "ALSP"))

    def nombre_corto(self) -> str:
        return str(self.equipos.get(self.equipo_id, {}).get("nombreCorto", "ALSP"))

    def set_equipo(self, equipo_id: str, acto: int = 0) -> None:
        if equipo_id not in self.equipos:
            return
        self.equipo_id = equipo_id
        self.acto = max(0, min(acto, len(self.pasos()) - 1))
        self.t = 0.0
        self.update()
        self.actoCambiado.emit(self.acto)

    def set_acto(self, acto: int) -> None:
        if not self.pasos():
            return
        self.acto = max(0, min(acto, len(self.pasos()) - 1))
        self.t = 0.0
        self.update()
        self.actoCambiado.emit(self.acto)

    def siguiente_acto(self) -> None:
        self.set_acto(self.acto + 1)

    def anterior_acto(self) -> None:
        self.set_acto(self.acto - 1)

    def toggle(self) -> None:
        self.reproduciendo = not self.reproduciendo

    def _duracion(self) -> float:
        return max(1.0, float(self.paso_actual().get("duracionS", 10)))

    def _progreso(self) -> float:
        return clamp(self.t / self._duracion())

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if not self._timer.isActive():
            self._timer.start(40)

    def hideEvent(self, ev) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(ev)

    def _tick(self) -> None:
        if not self.reproduciendo:
            return
        self.fase += 0.04
        self.t += 0.04
        if self.t >= self._duracion():
            self.t = 0.0
        self.update()

    # -------------------------------------------------------------- pintura
    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, ancho: int) -> int:  # noqa: N802
        return max(200, int(ancho * ALTO / ANCHO))

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), _qc(FONDO))

        w, h = self.width(), self.height()
        if w < 20 or h < 20:
            return
        s = min(w / ANCHO, h / ALTO)
        p.save()
        p.translate((w - ANCHO * s) / 2, (h - ALTO * s) / 2)
        p.scale(s, s)
        p.setClipRect(QRectF(0, 0, ANCHO, ALTO))

        if not self.modo_video:
            self._fondo(p)
        escena = getattr(self, f"_escena_{self.equipo_id.replace('-', '_')}", None)
        if escena:
            escena(p, self.acto, self._progreso())
        if not self.modo_video:
            self._pie(p)
        p.restore()

    # --------------------------------------------------------------- helpers
    def _fondo(self, p: QPainter) -> None:
        p.setPen(QPen(_c_tinta(14), 0.8))
        for x in range(0, ANCHO, 32):
            p.drawLine(QPointF(x, 0), QPointF(x, ALTO))
        for y in range(0, ALTO, 32):
            p.drawLine(QPointF(0, y), QPointF(ANCHO, y))
        p.setPen(QPen(_qc(LINEA), 1))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(16, 34), QPointF(16, 16))
        p.drawLine(QPointF(16, 16), QPointF(34, 16))
        p.drawLine(QPointF(ANCHO - 34, 16), QPointF(ANCHO - 16, 16))
        p.drawLine(QPointF(ANCHO - 16, 16), QPointF(ANCHO - 16, 34))
        self._texto(p, 26, 30, f"{self.codigo()} · {self.nombre_corto().upper()}", 9, SUAVE, tracking=True)
        self._texto(
            p,
            ANCHO - 26,
            30,
            f"0G · PASO {self.acto + 1:02d}/{len(self.pasos()):02d}",
            9,
            DIM,
            derecha=True,
        )
        # Indicador de reproducción: garantiza movimiento visible en todos los actos.
        latido = 0.5 + 0.5 * math.sin(self.fase * 4)
        p.setBrush(_c_tinta(int(80 + 120 * latido)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(ANCHO - 82, 50), 2.6, 2.6)
        self._texto(p, ANCHO - 74, 53, "EN VIVO", 7, DIM)

    def _pie(self, p: QPainter) -> None:
        self._texto(p, 26, 506, "V.I.T.A.L.I.S. · ALSP · DEMOSTRACIÓN PROCEDIMENTAL", 8, PIE)
        self._texto(p, ANCHO - 26, 506, "DOSIS Y PRESIONES · [POR VALIDAR]", 8, PIE, derecha=True)

    def _texto(
        self,
        p: QPainter,
        x: float,
        y: float,
        texto: str,
        tam: float = 9,
        color: str = SUAVE,
        mono: bool = True,
        derecha: bool = False,
        centro: bool = False,
        negrita: bool = False,
        tracking: bool = False,
    ) -> None:
        if self.idioma == "en":
            texto = translate(texto, "en")
        f = QFont(MONO if mono else "Segoe UI", int(tam))
        f.setWeight(QFont.DemiBold if negrita else QFont.Normal)
        if tracking:
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        p.setFont(f)
        p.setPen(_qc(color))
        texto = tr(texto)
        if centro:
            p.drawText(QRectF(x - 220, y - tam, 440, tam * 2.4), Qt.AlignHCenter | Qt.AlignVCenter, texto)
        elif derecha:
            p.drawText(QRectF(x - 420, y - tam, 420, tam * 2.4), Qt.AlignRight | Qt.AlignVCenter, texto)
        else:
            p.drawText(QPointF(x, y), texto)

    def _caja(
        self,
        p: QPainter,
        x: float,
        y: float,
        w: float,
        h: float,
        r: float = 10,
        fill: str = SUP,
        stroke: str = LINEA,
        ancho: float = 1.0,
    ) -> None:
        p.setBrush(_qc(fill))
        p.setPen(QPen(_qc(stroke), ancho))
        p.drawRoundedRect(QRectF(x, y, w, h), r, r)

    def _mano(self, p: QPainter, x: float, y: float, s: float = 1.0, ang: float = 0.0) -> None:
        p.save()
        p.translate(x, y)
        p.rotate(ang)
        p.scale(s, s)
        p.setBrush(_qc(SUP3))
        p.setPen(QPen(_qc(TEXTO), 1.2))
        palma = QPainterPath()
        palma.moveTo(-20, -8)
        palma.quadTo(-24, 16, -12, 24)
        palma.quadTo(0, 30, 12, 24)
        palma.quadTo(24, 16, 20, -8)
        palma.closeSubpath()
        p.drawPath(palma)
        for i, dx in enumerate((-19, -10, -1, 8)):
            p.drawRoundedRect(QRectF(dx, -40 + i * 1.5, 9, 30 - i * 2), 4.5, 4.5)
        p.save()
        p.translate(-25, 4)
        p.rotate(-26)
        p.drawRoundedRect(QRectF(0, 0, 9, 22), 4.5, 4.5)
        p.restore()
        p.restore()

    def _torso(self, p: QPainter, jolt: float = 0.0) -> None:
        p.save()
        p.translate(0, jolt)
        # Cabeza
        p.setBrush(_qc(SUP2))
        p.setPen(QPen(_qc(TEXTO), 1.5))
        p.drawEllipse(QPointF(400, 82), 43, 48)
        p.setPen(QPen(_qc(DIM), 1.0))
        p.drawArc(QRectF(360, 48, 80, 84), 200 * 16, 50 * 16)
        p.drawArc(QRectF(364, 88, 72, 42), 200 * 16, 140 * 16)
        # Silueta torácica
        cuerpo = QPainterPath()
        cuerpo.moveTo(400, 132)
        cuerpo.cubicTo(350, 132, 312, 138, 290, 152)
        cuerpo.cubicTo(262, 168, 246, 188, 242, 212)
        cuerpo.cubicTo(238, 236, 248, 266, 258, 296)
        cuerpo.cubicTo(268, 326, 286, 344, 296, 364)
        cuerpo.cubicTo(306, 384, 300, 406, 300, 426)
        cuerpo.cubicTo(300, 448, 312, 462, 332, 468)
        cuerpo.cubicTo(354, 474, 376, 476, 400, 476)
        cuerpo.cubicTo(424, 476, 446, 474, 468, 468)
        cuerpo.cubicTo(488, 462, 500, 448, 500, 426)
        cuerpo.cubicTo(500, 406, 494, 384, 504, 364)
        cuerpo.cubicTo(514, 344, 532, 326, 542, 296)
        cuerpo.cubicTo(552, 266, 562, 236, 558, 212)
        cuerpo.cubicTo(554, 188, 538, 168, 510, 152)
        cuerpo.cubicTo(488, 138, 450, 132, 400, 132)
        cuerpo.closeSubpath()
        p.setBrush(_qc(SUP))
        p.setPen(QPen(_qc(TEXTO), 1.5))
        p.drawPath(cuerpo)
        # Clavículas y esternón
        p.setPen(QPen(_c_tinta(120), 1.6))
        p.drawArc(QRectF(292, 140, 108, 34), 190 * 16, 150 * 16)
        p.drawArc(QRectF(480, 140, 108, 34), 200 * 16, 150 * 16)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_qc(SUAVE), 0.9))
        p.drawRoundedRect(QRectF(393, 168, 14, 164), 7, 7)
        # Costillas
        p.setPen(QPen(_c_suave(110), 1.0))
        for i in range(5):
            y = 192 + i * 27
            izq = QPainterPath()
            izq.moveTo(402, y)
            izq.quadTo(350, y + 5, 316 - i * 4, y + 36)
            p.drawPath(izq)
            der = QPainterPath()
            der.moveTo(398, y)
            der.quadTo(450, y + 5, 484 + i * 4, y + 36)
            p.drawPath(der)
        # Pectorales y abdomen
        p.setPen(QPen(_qc(DIM), 0.9))
        p.drawArc(QRectF(300, 190, 96, 30), 200 * 16, 110 * 16)
        p.drawArc(QRectF(484, 190, 96, 30), 230 * 16, 110 * 16)
        for y in (366, 390, 414):
            p.drawLine(QPointF(364, y), QPointF(436, y))
        p.drawEllipse(QPointF(400, 404), 2.6, 2.6)
        # Correa CMRS
        p.setBrush(_qc(SUP2))
        p.setPen(QPen(_qc(DIM), 1.0))
        p.drawRoundedRect(QRectF(302, 448, 196, 15), 5, 5)
        p.setBrush(_qc(SUP3))
        p.drawRoundedRect(QRectF(384, 445, 32, 21), 4, 4)
        p.restore()

    def _parche(self, p: QPainter, x: float, y: float, ang: float, letra: str) -> None:
        p.save()
        p.translate(x, y)
        p.rotate(ang)
        p.setBrush(_qc(SUP3))
        p.setPen(QPen(_qc(TEXTO), 1.4))
        p.drawRoundedRect(QRectF(-28, -40, 56, 80), 9, 9)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_qc(DIM), 0.8, Qt.DashLine))
        p.drawRoundedRect(QRectF(-23, -35, 46, 70), 6, 6)
        p.setBrush(_c_tinta(55))
        p.setPen(QPen(_qc(DIM), 0.8))
        p.drawRoundedRect(QRectF(-9, -34, 18, 10), 3, 3)
        p.drawEllipse(QPointF(0, 20), 3.2, 3.2)
        p.setPen(_qc(SUAVE))
        p.setFont(QFont(MONO, 7))
        p.drawText(QRectF(-20, 26, 40, 12), Qt.AlignCenter, letra)
        p.restore()

    def _ecg(
        self,
        p: QPainter,
        x: float,
        y: float,
        w: float,
        h: float,
        t: float,
        tipo: str = "vf",
        color: str = TEXTO,
    ) -> None:
        p.save()
        p.setClipRect(QRectF(x, y, w, h))
        p.fillRect(QRectF(x, y, w, h), _qc(ECG_BG))
        p.setPen(QPen(QColor(236, 239, 244, 16), 0.6))
        for i in range(0, int(w), 20):
            p.drawLine(QPointF(x + i, y), QPointF(x + i, y + h))
        for i in range(0, int(h), 20):
            p.drawLine(QPointF(x, y + i), QPointF(x + w, y + i))
        pts: List[QPointF] = []
        if tipo in ("vf", "tv"):
            for i in range(0, int(w) + 1, 3):
                n = (
                    math.sin(i * 0.19 + t * 7.2) * 0.55
                    + math.sin(i * 0.057 - t * 3.1) * 0.3
                    + math.sin(i * 0.41 + t * 11.3) * 0.15
                )
                pts.append(QPointF(x + i, y + h / 2 - n * h * 0.34))
        elif tipo == "cuadrada":
            ciclo = 90.0
            for i in range(0, int(w) + 1, 3):
                q = ((i + (t * 46) % ciclo) % ciclo) / ciclo
                n = 0.0 if q < 0.1 else (q - 0.1) / 0.08 if q < 0.18 else 1.0 if q < 0.62 else max(0.0, 1.0 - (q - 0.62) / 0.08)
                pts.append(QPointF(x + i, y + h - 4 - min(1.0, n) * (h - 12)))
        else:
            ciclo = 84.0
            for i in range(0, int(w) + 1, 3):
                q = ((i + (t * 34) % ciclo) % ciclo) / ciclo
                n = 0.0
                if 0.12 <= q < 0.18:
                    n = math.sin((q - 0.12) / 0.06 * math.pi) * 0.16
                elif 0.23 <= q < 0.27:
                    n = -0.12
                elif 0.27 <= q < 0.31:
                    n = 1.0
                elif 0.31 <= q < 0.35:
                    n = -0.32
                elif 0.5 <= q < 0.62:
                    n = math.sin((q - 0.5) / 0.12 * math.pi) * 0.24
                pts.append(QPointF(x + i, y + h / 2 - n * h * 0.36))
        trazo_col = ECG_TXT if color == TEXTO else color
        if len(pts) > 1:
            p.setPen(QPen(_qc(trazo_col), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(QPolygonF(pts))
        p.restore()

    def _gauge(
        self,
        p: QPainter,
        x: float,
        y: float,
        r: float,
        valor: float,
        maximo: float,
        etiqueta: str,
    ) -> None:
        p.setBrush(_qc(SUP))
        p.setPen(QPen(_qc(DIM), 1.0))
        p.drawEllipse(QPointF(x, y), r, r)
        p.setPen(QPen(_qc(DIM), 1.0))
        for i in range(9):
            a = math.radians(-120 + 240 * i / 8)
            p.drawLine(
                QPointF(x + math.sin(a) * (r - 8), y - math.cos(a) * (r - 8)),
                QPointF(x + math.sin(a) * (r - 14), y - math.cos(a) * (r - 14)),
            )
        a = math.radians(-120 + 240 * clamp(valor / maximo))
        p.setPen(QPen(_qc(TEXTO), 2.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(
            QPointF(x, y),
            QPointF(x + math.sin(a) * (r - 14), y - math.cos(a) * (r - 14)),
        )
        p.setBrush(_qc(TEXTO))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(x, y), 3, 3)
        self._texto(p, x, y + 20, str(int(valor)), 11, TEXTO, centro=True)
        self._texto(p, x, y + 32, "mmHg", 7, DIM, centro=True)
        self._texto(p, x, y + r + 16, etiqueta, 8, SUAVE, centro=True)

    def _jeringa(
        self,
        p: QPainter,
        x: float,
        y: float,
        escala: float = 1.0,
        ang: float = 0.0,
        dosis: float = 0.0,
        etiqueta: str = "",
    ) -> None:
        p.save()
        p.translate(x, y)
        p.rotate(ang)
        p.scale(escala, escala)
        # capuchón + aguja
        p.setBrush(_qc(SUP3))
        p.setPen(QPen(_qc(SUAVE), 1.0))
        p.drawRoundedRect(QRectF(-5, -242, 10, 48), 4, 4)
        p.setPen(QPen(_qc(SUAVE), 2.0))
        p.drawLine(QPointF(0, -194), QPointF(0, -186))
        # barril
        p.setBrush(_qc(SUP2))
        p.setPen(QPen(_qc(TEXTO), 1.3))
        p.drawRoundedRect(QRectF(-24, -174, 48, 150), 5, 5)
        alto = 150 * (1 - clamp(dosis)) * 0.9
        p.setBrush(_c_tinta(55))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(-19, -24 - alto, 38, alto), 3, 3)
        p.setPen(QPen(_c_tinta(120), 0.8))
        p.drawLine(QPointF(-19, -24 - alto), QPointF(19, -24 - alto))
        # graduaciones
        p.setPen(QPen(_qc(DIM), 0.7))
        for i in range(7):
            p.drawLine(QPointF(-24, -160 + i * 20), QPointF(-14, -160 + i * 20))
        # émbolo
        p.setBrush(_qc(SUP3))
        p.setPen(QPen(_qc(TEXTO), 1.0))
        p.drawRoundedRect(QRectF(-26, -174, 52, 14), 3, 3)
        p.setBrush(_qc(SUP3))
        p.setPen(QPen(_qc(DIM), 1.0))
        p.drawRoundedRect(QRectF(-32, -12, 64, 7), 3, 3)
        p.setPen(QPen(_qc(SUAVE), 3.0))
        p.drawLine(QPointF(0, -6), QPointF(0, 42))
        p.setBrush(_qc(SUP3))
        p.setPen(QPen(_qc(DIM), 1.0))
        p.drawRoundedRect(QRectF(-14, 42, 28, 7), 3.5, 3.5)
        if etiqueta:
            self._texto(p, 0, 64, etiqueta, 8, SUAVE, centro=True)
        p.restore()

    def _panel(self, p: QPainter, x: float, y: float, w: float, h: float, titulo: str) -> None:
        self._caja(p, x, y, w, h, 11, SUP, LINEA)
        self._texto(p, x + 12, y + 19, tr(titulo).upper(), 7.5, SUAVE, tracking=True)

    # --------------------------------------------------------------- escenas
    def _escena_dea(self, p: QPainter, acto: int, pr: float) -> None:
        pA = clamp((pr - 0.08) / 0.42)
        pB = clamp((pr - 0.46) / 0.42)
        pA = pA * pA * (3 - 2 * pA)
        pB = pB * pB * (3 - 2 * pB)
        pa = (346, 202, -10)
        pb = (516, 322, 20)
        if acto == 1:
            ax = 318 + (pa[0] - 318) * pA
            ay = 112 + (pa[1] - 112) * pA
            bx = 604 + (pb[0] - 604) * pB
            by = 148 + (pb[1] - 148) * pB
        else:
            ax, ay, bx, by = pa[0], pa[1], pb[0], pb[1]

        jolt = 0.0
        flash = 0.0
        if acto == 3 and pr > 0.53:
            q = clamp((pr - 0.53) / 0.14)
            flash = math.sin(q * math.pi)
            jolt = -5.0 * flash
        self._torso(p, jolt)

        # sudor
        if acto <= 1:
            alpha = 150 if acto == 0 else int(150 * (1 - clamp(pr / 0.42)))
            p.setBrush(_c_tinta(alpha))
            p.setPen(QPen(_c_suave(120), 0.6))
            for (sx, sy) in ((330, 206), (362, 236), (448, 222), (472, 256), (352, 308), (430, 312)):
                p.drawEllipse(QPointF(sx, sy), 3.2, 2.4)

        # parches
        if acto >= 1:
            self._parche(p, ax, ay, pa[2], "R")
            self._parche(p, bx, by, pb[2], "L")
            if acto == 1:
                self._mano(p, ax + 38, ay + 40, 0.7, -32)
                self._mano(p, bx - 40, by + 42, 0.7, 30)

        if acto == 0:
            self._mano(p, 382, 168, 0.92, -24)
            radio = 7 + 7 * (0.5 + 0.5 * math.sin(self.fase * 4))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_c_tinta(100), 1))
            p.drawEllipse(QPointF(430, 160), radio, radio)
            self._panel(p, 54, 62, 176, 91, "Cabina")
            self._texto(p, 66, 90, "O₂", 8, DIM)
            self._texto(p, 218, 90, "20.9 %", 8, TEXTO, derecha=True)
            self._texto(p, 66, 112, "CO₂", 8, DIM)
            self._texto(p, 218, 112, "0.3 mmHg", 8, TEXTO, derecha=True)
            self._texto(p, 66, 134, "Presión", 8, DIM)
            self._texto(p, 218, 134, "101.3 kPa", 8, TEXTO, derecha=True)
            self._texto(p, 400, 474, "SIN RESPUESTA · SIN RESPIRACIÓN NORMAL", 9, SUAVE, centro=True)

        # gasa
        if acto == 1 and pr < 0.45:
            gx = 455 + math.sin(pr * 34) * 34
            gy = 232 + math.cos(pr * 27) * 16
            p.save()
            p.translate(gx, gy)
            p.rotate(math.sin(pr * 30) * 14)
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.0))
            p.drawRoundedRect(QRectF(-20, -14, 40, 28), 4, 4)
            p.setPen(QPen(_qc(DIM), 0.7))
            for dy in (-6, 0, 6):
                p.drawLine(QPointF(-14, dy), QPointF(14, dy))
            p.restore()
            self._mano(p, gx + 6, gy + 34, 0.78, -14)

        # etiquetas de parches
        if acto == 1 and pr > 0.55:
            self._texto(p, 214, 140, "Parche 1 · infraclavicular derecho", 8, TEXTO)
            self._texto(p, 214, 151, "Bajo la clavícula, paraesternal", 7, DIM)
            p.setPen(QPen(_qc(SUAVE), 0.8))
            p.drawLine(QPointF(346, 168), QPointF(330, 150))
            self._texto(p, 596, 360, "Parche 2 · línea axilar media", 8, TEXTO)
            self._texto(p, 596, 371, "5.º espacio intercostal izquierdo", 7, DIM)
            p.drawLine(QPointF(538, 322), QPointF(590, 350))

        # unidad AED y cable
        if acto >= 2:
            p.setPen(QPen(_qc(SUAVE), 1.2))
            cable = QPainterPath()
            cable.moveTo(pb[0] + 26, pb[1] + 6)
            cable.cubicTo(590, 318, 606, 288, 628, 264)
            cable.lineTo(642, 252)
            p.drawPath(cable)
            self._caja(p, 642, 110, 196, 210, 13, SUP, TEXTO, 1.3)
            p.setBrush(_qc(PANTALLA))
            p.setPen(QPen(_qc(LINEA), 1.0))
            p.drawRoundedRect(QRectF(656, 124, 168, 86), 7, 7)
            self._texto(p, 668, 140, "AED · ALSP-01", 7, DIM)
            if acto == 2:
                self._ecg(p, 664, 150, 152, 50, self.t, "vf", TEXTO)
                estado = "ANALIZANDO · NO TOCAR"
                color_estado = TEXTO
            elif acto == 3 and pr < 0.53:
                self._ecg(p, 664, 150, 152, 50, self.t, "vf", CRIT)
                estado = "DESCARGA RECOMENDADA"
                color_estado = CRIT
            else:
                self._ecg(p, 664, 150, 152, 50, self.t, "sinus", TEXTO)
                estado = "RCP · 30:2"
                color_estado = TEXTO
            self._texto(p, 740, 232, estado, 7.5, color_estado, centro=True)
            # botón
            p.setBrush(_qc(CRIT) if acto == 3 and pr < 0.6 else _qc(SUP3))
            p.setPen(QPen(_qc(CRIT) if acto == 3 and pr < 0.6 else _qc(SUAVE), 1.2))
            p.drawEllipse(QPointF(790, 260), 16, 16)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(790, 260), 9, 9)
            self._texto(p, 790, 290, "DESCARGA", 7, DIM, centro=True)

        if acto == 2:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_c_tinta(55), 0.8, Qt.DashLine))
            p.drawEllipse(QPointF(400, 312), 212, 180)
            self._texto(p, 58, 196, "NADIE EN CONTACTO", 8, SUAVE)
            self._texto(p, 58, 210, "NO TOCAR AL PACIENTE", 7, DIM)

        if acto == 3:
            self._mano(p, 790, 236 + (4 if pr > 0.42 else 0), 0.85, 180)
            if pr > 0.3:
                self._texto(p, 400, 250, "APÁRTENSE", 30, TEXTO, centro=True, negrita=True)
                self._texto(p, 400, 274, "CONTACTO CERO CON PACIENTE Y CAMILLA", 8, CRIT, centro=True)
            self._panel(p, 54, 330, 176, 91, "Antes de descargar")
            self._texto(p, 66, 360, "Nadie en contacto", 8, DIM)
            self._texto(p, 218, 360, "OK" if pr > 0.3 else "—", 8, TEXTO, derecha=True)
            self._texto(p, 66, 382, "Tórax seco", 8, DIM)
            self._texto(p, 218, 382, "OK", 8, TEXTO, derecha=True)
            self._texto(p, 66, 404, "O₂ despejado", 8, DIM)
            self._texto(p, 218, 404, "OK" if pr > 0.4 else "—", 8, TEXTO, derecha=True)
            # tripulante que se aleja
            cx = 606 + 98 * clamp(pr / 0.3)
            cy = 392 + 26 * clamp(pr / 0.3)
            p.setBrush(_qc(SUP2))
            p.setPen(QPen(_qc(SUAVE), 1.0))
            p.drawEllipse(QPointF(cx, cy), 8, 8)
            p.drawRoundedRect(QRectF(cx - 7, cy + 7, 14, 25), 7, 7)
            p.setPen(QPen(_qc(SUAVE), 3.0, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx - 6, cy + 12), QPointF(cx - 18, cy - 2))
            p.drawLine(QPointF(cx + 6, cy + 12), QPointF(cx + 18, cy - 2))
            p.drawLine(QPointF(cx - 4, cy + 32), QPointF(cx - 8, cy + 48))
            p.drawLine(QPointF(cx + 4, cy + 32), QPointF(cx + 8, cy + 48))

        if acto == 4:
            depth = 0.5 - 0.5 * math.cos(self.t * (110 / 60) * math.pi * 2)
            self._mano(p, 400, 292 + depth * 11 + 18, 1.1, 4)
            self._mano(p, 400, 292 + depth * 11, 1.05, -6)
            ciclo = min(30, int(self.t * (110 / 60)) % 30 + 1)
            self._panel(p, 54, 62, 196, 118, "RCP en curso")
            self._texto(p, 68, 120, str(ciclo), 40, TEXTO)
            self._texto(p, 132, 96, "COMPRESIONES", 7, SUAVE)
            self._texto(p, 132, 112, "30:2", 7, DIM)
            self._texto(p, 68, 146, "110 / min · 5–6 cm", 8, SUAVE)
            # inset profundidad
            self._panel(p, 636, 330, 216, 152, "Corte lateral · profundidad")
            p.setBrush(_qc(SUP2))
            p.setPen(QPen(_qc(DIM), 1.0))
            p.drawRoundedRect(QRectF(656, 392, 90, 26), 4, 4)
            p.setBrush(_qc(SUP3))
            p.drawRoundedRect(QRectF(686, 372, 14, 26), 4, 4)
            p.setBrush(_qc(SUP2))
            p.drawEllipse(QPointF(744, 400 + depth * 5), 17 - depth * 2, 14 - depth * 2)
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.0))
            p.drawRoundedRect(QRectF(682, 358 + depth * 8, 22, 12), 5, 5)
            p.drawRoundedRect(QRectF(684, 350 + depth * 8, 20, 10), 5, 5)
            p.setPen(QPen(_qc(LINEA), 0.8))
            p.drawLine(QPointF(804, 362), QPointF(804, 454))
            for i in range(7):
                p.drawLine(QPointF(800, 362 + i * 13), QPointF(808, 362 + i * 13))
                self._texto(p, 812, 365 + i * 13, str(i), 6, DIM)
            p.setPen(QPen(_qc(TEXTO), 0.8, Qt.DashLine))
            p.drawLine(QPointF(760, 372), QPointF(760, 372 + 13 * (5 + depth)))
            self._texto(p, 650, 470, f"{5 + depth:.1f} cm · 5–6 cm", 8, TEXTO)
            # relevo
            self._panel(p, 56, 350, 196, 46, "Relevo del compresor")
            self._texto(p, 70, 386, "02:00 · cambia cada 2 min", 8, TEXTO)
            if pr > 0.9:
                self._panel(p, 54, 236, 196, 52, "Ventilación")
                self._texto(p, 152, 262, "2 ventilaciones", 8, TEXTO, centro=True)
                self._texto(p, 152, 276, "500–600 mL · eleva el tórax", 7, SUAVE, centro=True)

        if flash > 0:
            p.setBrush(QColor(229, 72, 77, int(flash * 40)))
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(0, 0, ANCHO, ALTO))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_c_tinta(int(flash * 150)), 2))
            p.drawEllipse(QPointF(400, 250), 40 + flash * 160, 40 + flash * 160)

    def _escena_iv(self, p: QPainter, acto: int, pr: float) -> None:
        # riel y bolsa
        p.setPen(QPen(_qc(SUAVE), 1.4))
        p.drawLine(QPointF(40, 52), QPointF(330, 52))
        for x in (70, 300):
            p.drawLine(QPointF(x, 46), QPointF(x, 58))
        # manguito
        p.setBrush(_qc(SUP2))
        p.setPen(QPen(_qc(SUAVE), 1.2))
        p.drawRoundedRect(QRectF(96, 66, 128, 204), 14, 14)
        p.setPen(QPen(_qc(LINEA), 0.8))
        for i in range(5):
            p.drawLine(QPointF(100, 92 + i * 36), QPointF(220, 92 + i * 36))
        # bolsa
        bolsa = QPainterPath()
        bolsa.moveTo(112, 86)
        bolsa.quadTo(112, 76, 122, 76)
        bolsa.lineTo(198, 76)
        bolsa.quadTo(208, 76, 208, 86)
        bolsa.lineTo(208, 222)
        bolsa.quadTo(208, 252, 176, 262)
        bolsa.lineTo(160, 266)
        bolsa.lineTo(144, 262)
        bolsa.quadTo(112, 252, 112, 222)
        bolsa.closeSubpath()
        p.setBrush(_qc(BOLSA))
        p.setPen(QPen(_qc(TEXTO), 1.2))
        p.drawPath(bolsa)
        volumen = 500.0
        if acto == 3:
            volumen -= pr * 22
        elif acto == 4:
            volumen -= 22 + pr * 68
        alto = 150 * clamp(volumen / 500)
        p.save()
        p.setClipPath(bolsa)
        p.setBrush(_c_tinta(40))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(112, 256 - alto, 96, alto + 10))
        p.restore()
        p.setPen(_qc(SUAVE))
        p.setFont(QFont(MONO, 8))
        p.save()
        p.translate(160, 170)
        p.rotate(-90)
        self._texto(p, 0, 0, "NaCl 0.9 % · 500 mL", 8, SUAVE, centro=True)
        p.restore()
        # etiquetas de volumen
        p.setPen(QPen(_qc(DIM), 0.7))
        for i in range(5):
            p.drawLine(QPointF(190, 112 + i * 28), QPointF(202, 112 + i * 28))
            self._texto(p, 186, 115 + i * 28, str(400 - i * 100), 6, DIM, derecha=True)
        # gauge / pera
        presion = 0.0 if acto == 0 else 300.0 if acto >= 2 else 300.0 * clamp(pr / 0.30)
        pump = 1 + (math.sin(self.fase * 9) * 0.12 if acto == 1 and pr < 0.7 else 0)
        p.setPen(QPen(_qc(DIM), 2.0))
        p.drawLine(QPointF(220, 150), QPointF(258, 176))
        p.save()
        p.translate(272, 196)
        p.scale(pump, pump)
        p.setBrush(_qc(SUP2))
        p.setPen(QPen(_qc(TEXTO), 1.2))
        p.drawEllipse(QPointF(0, 0), 16, 26)
        p.restore()
        self._gauge(p, 306, 106, 38, presion, 320, "Presión de infusión")
        # gotero
        p.setBrush(_qc(GOTERO))
        p.setPen(QPen(_qc(SUAVE), 1.0))
        p.drawRoundedRect(QRectF(146, 272, 20, 60), 8, 8)
        p.setBrush(_c_tinta(35))
        p.drawRoundedRect(QRectF(148, 316, 16, 14), 4, 4)
        for i in range(3):
            u = (self.fase * (1.5 if acto >= 1 else 0.9) + i / 3) % 1
            p.setBrush(_c_tinta(int(190 * (1 - u * 0.5))))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(156, 280 + u * 44), 2.4, 2.4)
        # línea
        linea = QPainterPath()
        linea.moveTo(156, 332)
        linea.cubicTo(156, 360, 170, 368, 196, 372)
        linea.cubicTo(240, 384, 300, 392, 360, 400)
        linea.cubicTo(430, 410, 490, 416, 534, 420)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_qc(SUAVE), 2.0))
        p.drawPath(linea)
        # pinza
        p.setBrush(_qc(SUP3))
        p.setPen(QPen(_qc(TEXTO), 0.9))
        p.drawRoundedRect(QRectF(293, 391, 14, 26), 4, 4)
        # brazo
        p.save()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_qc(TEXTO), 48, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(828, 458), QPointF(360, 434))
        p.setPen(QPen(_qc(SUP), 44, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(828, 458), QPointF(360, 434))
        p.restore()
        p.setBrush(_qc(SUP))
        p.setPen(QPen(_qc(SUAVE), 1.0))
        p.drawEllipse(QPointF(366, 432), 24, 18)
        p.setPen(QPen(_qc(SUAVE), 1.4))
        for dy in (-8, 0, 8):
            p.drawLine(QPointF(350, 432 + dy), QPointF(334, 430 + dy))
        # venas
        p.setPen(QPen(_c_vena(110), 1.6))
        p.drawLine(QPointF(756, 448), QPointF(520, 440))
        p.drawLine(QPointF(744, 466), QPointF(560, 452))
        # torniquete
        if acto >= 2:
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.0))
            p.drawRect(QRectF(714, 424, 16, 54))
            self._texto(p, 700, 410, "TOURNIQUET", 6, DIM, derecha=True)
        # catéter
        if acto >= 2:
            ins = 1.0 if acto > 2 else clamp((pr - 0.22) / 0.42)
            ang = 22 - 6 * ins
            cx = 566 + 34 * ins
            cy = 410 + 18 * ins
            p.save()
            p.translate(cx, cy)
            p.rotate(ang)
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.0))
            p.drawRoundedRect(QRectF(-66, -9, 30, 18), 4, 4)
            p.setBrush(_qc(SUP2))
            p.drawRoundedRect(QRectF(-38, -6, 18, 12), 2, 2)
            p.setBrush(QColor(229, 72, 77, 140))
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(-36, -4, 14 * clamp((pr - 0.5) / 0.2), 8))
            p.setPen(QPen(_qc(TEXTO), 3.0, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(-20, 0), QPointF(16, 0))
            p.restore()
            p.setBrush(_qc(SUP))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(602, 429), 13, 17)
            p.setBrush(QColor(229, 72, 77, 160))
            p.drawEllipse(QPointF(600, 428), 2.4, 2.4)
            self._mano(p, cx - 58, cy - 22, 0.72, 92)
        # apósito
        if acto >= 3:
            p.setBrush(_c_tinta(10))
            p.setPen(QPen(_qc(SUAVE), 0.8, Qt.DashLine))
            p.drawRoundedRect(QRectF(566, 408, 58, 46), 7, 7)
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(DIM), 0.8))
            p.drawRoundedRect(QRectF(558, 416, 26, 9), 3, 3)
            p.drawRoundedRect(QRectF(600, 446, 34, 9), 3, 3)
        # paneles contextuales
        if acto <= 1:
            self._panel(p, 610, 56, 246, 180, "Control de aire")
            p.setBrush(_qc(GOTERO))
            p.setPen(QPen(_qc(LINEA), 1.0))
            p.drawRoundedRect(QRectF(626, 92, 214, 42), 8, 8)
            p.setPen(QPen(_qc(SUAVE), 7, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(634, 113), QPointF(832, 113))
            p.setPen(QPen(_qc(GOTERO), 4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(634, 113), QPointF(832, 113))
            for i in range(4):
                u = (self.fase * 0.35 + i / 4) % 1
                p.setBrush(_c_tinta(int(255 * (1 - u * 0.6))))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(650 + u * 160, 113), 3, 3)
            self._texto(p, 626, 158, "Burbujas visibles en la línea", 8, SUAVE)
            self._texto(p, 626, 178, "PURGANDO…" if acto == 0 and pr < 0.82 else "LÍNEA LIMPIA ✓", 9, TEXTO)
            self._texto(p, 626, 200, "En 0G el aire no sube: se empuja fuera.", 7, DIM)
        elif acto == 2:
            self._panel(p, 610, 56, 246, 180, "Flashback")
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_qc(SUAVE), 1.0))
            p.drawEllipse(QPointF(700, 132), 48, 48)
            p.setBrush(_qc(SUP2))
            p.drawRoundedRect(QRectF(664, 124, 72, 18), 9, 9)
            p.setBrush(QColor(229, 72, 77, 150))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(674, 127, 18 * clamp((pr - 0.5) / 0.2), 12), 4, 4)
            self._texto(p, 700, 196, "AVANZA EL CATÉTER" if pr < 0.6 else "REFLUJO CONFIRMADO", 8, TEXTO, centro=True)
        elif acto == 3:
            self._panel(p, 610, 56, 246, 180, "Fijación")
            for i, (label, estado) in enumerate(
                (
                    ("Apósito estéril", "OK"),
                    ("Cinta sin comprimir", "OK"),
                    ("Lazada de holgura", "OK"),
                    ("Sin aire en línea", "OK"),
                )
            ):
                self._texto(p, 626, 100 + i * 26, "• " + label, 8, SUAVE)
                self._texto(p, 840, 100 + i * 26, estado, 8, TEXTO, derecha=True)
        else:
            self._panel(p, 610, 56, 246, 180, "Vigilancia del sitio")
            self._texto(p, 626, 100, "Normal", 8, SUAVE)
            self._texto(p, 740, 100, "Infiltración", 8, CRIT)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_qc(SUAVE), 1.2))
            p.drawLine(QPointF(626, 124), QPointF(700, 124))
            p.drawLine(QPointF(748, 124), QPointF(822, 124))
            p.setBrush(_c_tinta(25))
            p.setPen(QPen(_qc(CRIT), 1.0))
            p.drawEllipse(QPointF(785, 124), 16, 9)
            self._texto(p, 626, 160, "DOLOR · EDEMA · PALIDEZ · RESISTENCIA", 7.5, TEXTO)
            self._texto(p, 626, 178, "Cualquiera detiene la infusión.", 7, DIM)
        # HUD
        self._panel(p, 610, 252, 246, 112, "Infusión")
        for i, (lbl, valor_txt) in enumerate(
            (
                ("Volumen", f"{int(volumen)} mL"),
                ("Goteo", "60 gtt/min" if acto >= 1 else "0 gtt/min"),
                ("Presión", f"{int(presion)} mmHg"),
            )
        ):
            self._texto(p, 622, 282 + i * 22, lbl, 8, DIM)
            self._texto(p, 840, 282 + i * 22, valor_txt, 8, TEXTO, derecha=True)
        self._texto(p, 400, 502, "INFUNDIENDO · REVISA EL SITIO CADA 5 MIN" if acto == 4 else "", 8, SUAVE, centro=True)

    def _escena_via_aerea(self, p: QPainter, acto: int, pr: float) -> None:
        # cuello / tórax
        p.setBrush(_qc(SUP2))
        p.setPen(QPen(_qc(DIM), 1.0))
        cuello = QPainterPath()
        cuello.moveTo(318, 372)
        cuello.cubicTo(308, 406, 300, 440, 300, 486)
        cuello.lineTo(470, 486)
        cuello.cubicTo(466, 442, 458, 408, 450, 372)
        cuello.closeSubpath()
        p.drawPath(cuello)
        # perfil
        perfil = QPainterPath()
        perfil.moveTo(330, 105)
        perfil.cubicTo(280, 105, 235, 120, 214, 150)
        perfil.cubicTo(202, 168, 200, 195, 202, 218)
        perfil.cubicTo(203, 232, 204, 238, 205, 246)
        perfil.cubicTo(197, 254, 188, 264, 176, 272)
        perfil.cubicTo(190, 276, 198, 280, 202, 286)
        perfil.cubicTo(198, 296, 200, 304, 204, 310)
        perfil.cubicTo(198, 316, 198, 324, 204, 330)
        perfil.cubicTo(210, 344, 216, 352, 226, 360)
        perfil.cubicTo(244, 374, 268, 382, 296, 388)
        perfil.lineTo(300, 410)
        perfil.lineTo(448, 410)
        perfil.lineTo(452, 330)
        perfil.cubicTo(455, 270, 452, 210, 435, 175)
        perfil.cubicTo(415, 132, 375, 105, 330, 105)
        p.setBrush(_qc(SUP))
        p.setPen(QPen(_qc(TEXTO), 1.4))
        p.drawPath(perfil)
        # encéfalo
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_qc(DIM), 0.8))
        p.drawEllipse(QPointF(330, 220), 78, 62)
        # circunvoluciones: líneas onduladas, no arcos que parezcan una cara
        p.drawLine(QPointF(330, 166), QPointF(330, 274))
        for yy in (188, 208, 228, 248, 264):
            izq = QPainterPath()
            izq.moveTo(298, yy)
            izq.quadTo(312, yy - 7, 326, yy)
            p.drawPath(izq)
            der = QPainterPath()
            der.moveTo(334, yy)
            der.quadTo(348, yy + 7, 362, yy)
            p.drawPath(der)
        # cavidad oral
        boca = QPainterPath()
        boca.moveTo(206, 306)
        boca.cubicTo(230, 312, 262, 320, 292, 330)
        boca.lineTo(300, 356)
        boca.cubicTo(270, 350, 235, 342, 210, 334)
        boca.closeSubpath()
        p.setBrush(_qc(BOCA))
        p.setPen(QPen(_qc(LINEA), 0.8))
        p.drawPath(boca)
        p.setBrush(_qc(SUP2))
        p.setPen(QPen(_qc(DIM), 0.8))
        p.drawEllipse(QPointF(252, 338), 34, 11)
        # cuerdas / tráquea
        p.setPen(QPen(_qc(TEXTO), 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(330, 348), QPointF(352, 346))
        p.drawLine(QPointF(330, 358), QPointF(352, 356))
        p.setPen(QPen(_qc(SUAVE), 1.0))
        p.drawLine(QPointF(356, 366), QPointF(416, 414))
        p.drawLine(QPointF(372, 372), QPointF(424, 414))
        for i in range(4):
            p.drawLine(QPointF(364 + i * 16, 372 + i * 12), QPointF(384 + i * 16, 376 + i * 12))
        # etiquetas
        if acto >= 3:
            self._texto(p, 474, 332, "Cuerdas vocales", 8, TEXTO)
            self._texto(p, 474, 343, "Paso del tubo", 7, DIM)
            p.setPen(QPen(_qc(SUAVE), 0.8))
            p.drawLine(QPointF(352, 352), QPointF(470, 338))
            self._texto(p, 474, 424, "Tráquea", 8, TEXTO)
            self._texto(p, 474, 435, "Anillos cartilaginosos", 7, DIM)
            p.drawLine(QPointF(420, 408), QPointF(470, 420))
        # acto 0: tracción + aspiración
        if acto == 0:
            self._mano(p, 236, 368, 0.86, -28)
            p.setPen(QPen(_qc(SUAVE), 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(118, 392), QPointF(206, 322))
            for i in range(3):
                u = (self.fase * 0.5 + i / 3) % 1
                sx = 206 + (118 - 206) * u
                sy = 322 + (392 - 322) * u
                p.setBrush(_c_tinta(int(50 + 130 * (1 - u))))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(sx, sy), 2.0, 2.0)
            p.setBrush(_qc(SUP2))
            p.setPen(QPen(_qc(SUAVE), 1.0))
            p.drawRoundedRect(QRectF(96, 396, 24, 36), 4, 4)
            if pr > 0.62:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(_qc(TEXTO), 10, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(208, 318), QPointF(262, 360))
                p.setPen(QPen(_qc(SUP), 5, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(208, 318), QPointF(262, 360))
            self._texto(p, 148, 430, "Tracción mandibular", 8, TEXTO)
            self._texto(p, 148, 441, "Alineación neutra · 0G", 7, DIM)
            self._texto(p, 64, 462, "Aspiración", 8, TEXTO)
        # acto 1: BVM
        if acto == 1:
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.2))
            p.drawEllipse(QPointF(196, 300), 27, 35)
            p.drawEllipse(QPointF(196, 300), 19, 26)
            p.setBrush(_qc(SUP2))
            p.setPen(QPen(_qc(TEXTO), 1.2))
            sq = 0.5 + 0.5 * math.sin(self.fase * 4)
            hh = 62 - 12 * sq
            p.drawRoundedRect(QRectF(118, 266 + (68 - hh) / 2, 76, hh), 18, 18)
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(SUAVE), 1.0))
            p.drawRoundedRect(QRectF(142, 288, 26, 22), 5, 5)
            p.setBrush(_qc(SUP2))
            p.setPen(QPen(_qc(DIM), 1.0))
            p.drawRoundedRect(QRectF(156, 344, 76, 20), 9, 9)
            # cilindro O2
            p.setBrush(_qc(SUP2))
            p.setPen(QPen(_qc(SUAVE), 1.0))
            p.drawRoundedRect(QRectF(50, 176, 30, 96), 13, 13)
            self._texto(p, 50, 168, "O₂ · 15 L/min", 7, SUAVE)
            # correa
            p.setPen(QPen(_qc(SUAVE), 2.0, Qt.DashLine))
            p.drawLine(QPointF(214, 282), QPointF(402, 278))
            self._texto(p, 160, 470, "500–600 mL · 1 s · 10 / min", 8, SUAVE)
        # acto 2: bandeja
        if acto == 2:
            self._caja(p, 118, 414, 644, 82, 10, SUP, LINEA)
            self._texto(p, 132, 432, "BANDEJA DE INTUBACIÓN · CHECKLIST", 7, SUAVE)
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.0))
            p.drawRoundedRect(QRectF(150, 438, 14, 46), 5, 5)
            p.setPen(QPen(_qc(TEXTO), 5.0, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(164, 440), QPointF(214, 452))
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.0))
            p.drawRoundedRect(QRectF(300, 440, 60, 10), 4, 4)
            p.drawRoundedRect(QRectF(390, 436, 14, 40), 3, 3)
            p.drawRoundedRect(QRectF(470, 432, 20, 40), 7, 7)
            self._texto(p, 536, 448, "☐ Balón probado", 8, DIM)
            self._texto(p, 536, 464, "☐ Estilete sin sobresalir", 8, DIM)
            self._texto(p, 536, 480, "☐ Luz y aspiración OK", 8, DIM)
            self._texto(p, 536, 496, "☐ O₂ 100 % · preoxigenado", 8, DIM)
            barrido = 432 + (self.fase * 24) % 46
            p.setPen(QPen(_c_tinta(35), 1))
            p.drawLine(QPointF(132, barrido), QPointF(750, barrido))
        # acto 3: laringoscopia + tubo
        if acto == 3:
            lift = clamp((pr - 0.12) / 0.42)
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.0))
            p.drawRoundedRect(QRectF(150, 430, 16, 70), 6, 6)
            p.setPen(QPen(_qc(SUAVE), 6.0, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(164, 434), QPointF(320, 330 - lift * 10))
            tubo = QPainterPath()
            tubo.moveTo(206, 310)
            tubo.cubicTo(240, 318, 270, 324, 300, 336)
            tubo.cubicTo(330, 348, 346, 362, 366, 382)
            tubo.cubicTo(382, 398, 400, 408, 416, 416)
            prog = clamp((pr - 0.34) / 0.52)
            if prog > 0.02:
                n = max(2, int(40 * prog))
                pts = [tubo.pointAtPercent(i / n) for i in range(n + 1)]
                p.setPen(QPen(_qc(TEXTO), 8.0, Qt.SolidLine, Qt.RoundCap))
                p.drawPolyline(QPolygonF(pts))
                p.setPen(QPen(_qc(SUP), 4.0, Qt.SolidLine, Qt.RoundCap))
                p.drawPolyline(QPolygonF(pts))
            self._texto(p, 470, 444, "TUBO 7.5 · 23 cm", 7, SUAVE)
            self._panel(p, 596, 70, 256, 148, "Laringoscopia")
            for i, txt in enumerate(("Hoja en la valécula", "Eleva epiglotis y lengua", "Visualiza cuerdas", "Pasa el tubo sin forzar")):
                self._texto(p, 612, 100 + i * 18, f"{i + 1} · {txt}", 8, SUAVE)
            self._texto(p, 612, 196, "VISUALIZANDO…" if prog < 0.35 else "PASANDO EL TUBO" if prog < 0.98 else "TUBO EN TRÁQUEA", 8, TEXTO)
        # acto >=4: tubo, capnografía
        if acto >= 4:
            tubo = QPainterPath()
            tubo.moveTo(206, 310)
            tubo.cubicTo(240, 318, 270, 324, 300, 336)
            tubo.cubicTo(330, 348, 346, 362, 366, 382)
            tubo.cubicTo(382, 398, 400, 408, 416, 416)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_qc(TEXTO), 8.0, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(tubo)
            p.setPen(QPen(_qc(SUP), 4.0, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(tubo)
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.0))
            p.drawEllipse(QPointF(408, 411), 13, 9)
            self._panel(p, 596, 70, 256, 182, "Confirmación · capnografía")
            self._ecg(p, 612, 102, 224, 64, self.fase, "cuadrada", TEXTO)
            self._texto(p, 612, 186, "EtCO₂ 38 mmHg · ONDA SOSTENIDA", 8, TEXTO)
            self._texto(p, 612, 204, "Auscultación bilateral + epigastrio negativo", 7, DIM)
            self._texto(p, 612, 220, "Fijado a 23 cm en el incisivo", 7, DIM)
            self._texto(p, 470, 444, "TUBO 7.5 · 23 cm", 7, SUAVE)
        if acto == 5:
            self._panel(p, 596, 270, 256, 150, "Vigilancia continua")
            for i, (lbl, val) in enumerate((("SpO₂", "96 %"), ("EtCO₂", "38 mmHg"), ("Balón", "25 cmH₂O"), ("Tubo", "23 cm"))):
                self._texto(p, 612, 300 + i * 22, lbl, 8, DIM)
                self._texto(p, 838, 300 + i * 22, val, 8, TEXTO, derecha=True)
            self._ecg(p, 612, 384, 224, 26, self.fase, "cuadrada", TEXTO)
            self._texto(p, 612, 420, "Aspirador y rescate a la mano.", 6.5, DIM)
        # HUD estado
        if acto <= 3:
            self._panel(p, 596, 240, 256, 92, "Estado")
            self._texto(p, 612, 268, "SpO₂", 8, DIM)
            self._texto(p, 838, 268, "91 %" if acto == 1 else "—", 8, CRIT if acto == 1 else TEXTO, derecha=True)
            self._texto(p, 612, 290, "EtCO₂", 8, DIM)
            self._texto(p, 838, 290, "—", 8, TEXTO, derecha=True)
            self._texto(p, 612, 312, "Vía aérea", 8, DIM)
            self._texto(p, 838, 312, "BVM" if acto == 1 else "Laringoscopia" if acto == 3 else "Abierta", 8, TEXTO, derecha=True)

    def _escena_farmacos(self, p: QPainter, acto: int, pr: float) -> None:
        drogas = (
            ("EPINEFRINA", "1 mg / 10 mL", "Paro · anafilaxia"),
            ("ATROPINA", "1 mg / 10 mL", "Bradicardia"),
            ("LIDOCAÍNA", "100 mg / 5 mL", "Arritmia ventricular"),
            ("ANALGESIA", "titulada", "Dolor intenso"),
        )
        if acto == 0:
            self._caja(p, 86, 96, 748, 272, 16, SUP, LINEA)
            self._texto(p, 104, 120, "BOLSA ROJA · ALSP-04 · BANDEJA DE FÁRMACOS", 7.5, SUAVE)
            p.setPen(QPen(_qc(LINEA), 0.8))
            p.drawLine(QPointF(104, 132), QPointF(816, 132))
            for i, (nombre, dosis, indic) in enumerate(drogas):
                cx = 190 + i * 174
                self._caja(p, cx - 80, 146, 160, 194, 10, SUP2, LINEA)
                self._jeringa(p, cx - 55, 218, 0.5, 90, 0.0)
                self._texto(p, cx, 300, nombre, 8, TEXTO, centro=True)
                self._texto(p, cx, 314, dosis, 7, DIM, centro=True)
                self._texto(p, cx, 330, indic, 7, DIM, centro=True)
            self._texto(p, 104, 394, "Jeringas precargadas · agujas estériles · torundas", 8, DIM)
            self._panel(p, 492, 54, 362, 30, "Verificar en voz alta")
            for i, txt in enumerate(("NOMBRE", "DOSIS", "CADUCIDAD")):
                self._texto(p, 652 + i * 66, 74, "● " + txt, 6.5, TEXTO if pr > 0.3 + i * 0.18 else DIM)
            self._mano(p, 364, 232 + 1.5 * math.sin(self.fase * 3), 0.66, 92)
            self._texto(p, 440, 486, "LEE LA ETIQUETA EN VOZ ALTA · NUNCA ASUMAS EL CONTENIDO", 8, SUAVE, centro=True)
        elif acto == 1:
            self._caja(p, 70, 80, 470, 400, 16, SUP, LINEA)
            self._texto(p, 92, 106, "PURGA · JERINGA EN POSICIÓN VERTICAL", 8, SUAVE)
            self._texto(p, 92, 124, "EPINEFRINA 1 mg / 10 mL", 8, TEXTO)
            self._jeringa(p, 330, 370, 1.35, 0, 0.04 + pr * 0.12, "")
            self._mano(p, 330, 440, 0.95, -4)
            self._mano(p, 292, 252, 0.8, -90)
            self._panel(p, 580, 130, 250, 170, "Control de burbujas")
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_qc(SUAVE), 1.0))
            p.drawRoundedRect(QRectF(596, 156, 58, 74), 6, 6)
            for i in range(3):
                yy = 206 - i * 16 - pr * 14
                p.setBrush(_c_tinta(90))
                p.setPen(QPen(_qc(SUAVE), 0.8))
                p.drawEllipse(QPointF(618 + (i % 2) * 14, yy), 3, 3)
            self._texto(p, 670, 180, "Golpea el barril", 8, SUAVE)
            self._texto(p, 670, 200, "Invierte la jeringa", 8, SUAVE)
            self._texto(p, 670, 220, "Empuja hasta la gota", 8, SUAVE)
            self._texto(p, 596, 262, "SIN BURBUJAS ✓" if pr > 0.82 else "PURGANDO…", 8, TEXTO)
        elif acto == 2:
            self._texto(p, 440, 86, "ELIGE LA VÍA SEGÚN LA INDICACIÓN", 8, SUAVE, centro=True)
            self._caja(p, 76, 112, 356, 318, 14, SUP, TEXTO if pr <= 0.55 else LINEA, 1.1)
            self._texto(p, 96, 138, "PARO CARDIACO · IV / IO", 8, TEXTO)
            p.setPen(QPen(_qc(TEXTO), 56, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(132, 300), QPointF(372, 296))
            p.setPen(QPen(_qc(SUP), 52, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(132, 300), QPointF(372, 296))
            p.setBrush(_qc(SUP))
            p.setPen(QPen(_qc(SUAVE), 1.0))
            p.drawEllipse(QPointF(128, 300), 24, 18)
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.0))
            p.drawEllipse(QPointF(330, 296), 14, 14)
            p.drawEllipse(QPointF(330, 296), 8, 8)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_c_tinta(70), 1))
            pulso = 18 + 5 * (0.5 + 0.5 * math.sin(self.fase * 3))
            p.drawEllipse(QPointF(330, 296), pulso, pulso)
            self._texto(p, 330, 344, "PUERTO IV", 7, TEXTO, centro=True)
            self._texto(p, 96, 402, "Antecubital · 18 G · sin aire en línea", 7, DIM)
            self._caja(p, 452, 112, 352, 318, 14, SUP, TEXTO if pr > 0.55 else LINEA, 1.1)
            self._texto(p, 472, 138, "ANAFILAXIA · IM", 8, TEXTO if pr > 0.55 else SUAVE)
            muslo = QPainterPath()
            muslo.moveTo(556, 196)
            muslo.cubicTo(590, 196, 610, 214, 608, 244)
            muslo.lineTo(600, 320)
            muslo.cubicTo(598, 346, 580, 364, 554, 364)
            muslo.cubicTo(528, 364, 510, 346, 508, 320)
            muslo.lineTo(500, 244)
            muslo.cubicTo(498, 214, 518, 196, 556, 196)
            p.setBrush(_qc(SUP2))
            p.setPen(QPen(_qc(SUAVE), 1.0))
            p.drawPath(muslo)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_qc(TEXTO), 0.9, Qt.DashLine))
            p.drawEllipse(QPointF(596, 284), 18, 18)
            p.setBrush(_qc(TEXTO))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(596, 284), 5, 5)
            self._texto(p, 596, 380, "VASTO LATERAL · 90°", 7, TEXTO if pr > 0.55 else DIM, centro=True)
            self._texto(p, 472, 416, "0.3–0.5 mg · repetir a los 5–15 min [POR VALIDAR]", 7, DIM)
            self._texto(p, 440, 462, "En 0G la absorción IM puede ser más lenta: si hay vía IV permeable, priorízala. [POR VALIDAR]", 7, DIM, centro=True)
        elif acto == 3:
            self._caja(p, 60, 300, 760, 176, 14, SUP, LINEA)
            self._texto(p, 80, 324, "ADMINISTRACIÓN IV · EMPUJE LENTO + BOLO DE 20 mL", 8, SUAVE)
            p.setPen(QPen(_qc(TEXTO), 46, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(110, 430), QPointF(800, 420))
            p.setPen(QPen(_qc(SUP), 42, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(110, 430), QPointF(800, 420))
            p.setBrush(_qc(SUP))
            p.setPen(QPen(_qc(SUAVE), 1.0))
            p.drawEllipse(QPointF(126, 432), 24, 18)
            self._jeringa(p, 360, 424, 0.7, 90, clamp((pr - 0.32) / 0.38))
            self._mano(p, 316, 424, 0.82, 90)
            p.setBrush(_qc(SUP3))
            p.setPen(QPen(_qc(TEXTO), 1.0))
            p.drawEllipse(QPointF(520, 424), 13, 13)
            self._texto(p, 80, 350, "EPINEFRINA 1 mg", 13, TEXTO)
            self._texto(p, 80, 368, "IV · cada 3–5 min · [POR VALIDAR]", 7, DIM)
            if pr > 0.76:
                self._panel(p, 610, 314, 184, 34, "Bolo")
                self._texto(p, 702, 336, "BOLO 20 mL ✓", 8, TEXTO, centro=True)
            if not self.modo_video:
                self._panel(p, 620, 70, 160, 88, "Alternativa IM")
                self._texto(p, 630, 130, "0.3–0.5 mg · vasto lateral", 7, DIM)
            self._texto(p, 440, 496, "REGISTRA LA HORA ANTES DE RETIRAR LA JERINGA", 7, SUAVE, centro=True)
        else:
            self._panel(p, 62, 70, 430, 210, "Monitor · respuesta")
            self._ecg(p, 82, 108, 390, 72, self.fase, "sinus", TEXTO)
            self._texto(p, 82, 206, "FC 104 · PA 94/60 · SpO₂ 95 %", 9, TEXTO)
            self._texto(p, 82, 228, "Vigila ritmo, perfusión y respuesta clínica.", 7, DIM)
            self._panel(p, 520, 70, 294, 210, "Próxima dosis")
            self._texto(p, 536, 136, "03:00", 26, TEXTO)
            self._texto(p, 536, 156, "EPINEFRINA · 3–5 MIN", 7, DIM)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_qc(TEXTO), 2.0))
            p.drawArc(QRectF(716, 92, 56, 56), 90 * 16, -int(360 * clamp(1 - pr * 0.2)) * 16)
            for i, (hora, txt) in enumerate((("14:32:07", "EPI 1 mg IV"), ("14:32:20", "Flush 20 mL"), ("14:32:31", "Ritmo organizado"), ("14:32:40", "Próxima 14:35"))):
                alpha = 1.0 if pr > (0, 0.3, 0.55, 0.75)[i] else 0.2
                p.setPen(_c_tinta(int(255 * alpha)))
                self._texto(p, 536, 184 + i * 16, f"{hora} · {txt}", 7, TEXTO if alpha > 0.5 else DIM)
            self._panel(p, 520, 330, 294, 150, "Paquete al Flight Surgeon")
            self._texto(p, 536, 360, "Fármaco, dosis, vía y hora UTC", 8, DIM)
            self._texto(p, 536, 380, "Ciclos de RCP y respuesta", 8, DIM)
            self._texto(p, 536, 400, "Última bioquímica OSD-575", 8, DIM)
            self._texto(p, 536, 420, "Cola diferida si no hay enlace", 8, DIM)
            self._texto(p, 536, 450, "PAQUETE LISTO ✓" if pr > 0.6 else "EMPAQUETANDO…", 8, TEXTO)
            p.setBrush(_qc(SUP2))
            p.setPen(QPen(_qc(SUAVE), 1.0))
            p.drawRoundedRect(QRectF(160, 392, 144, 86), 10, 10)
            p.setPen(QPen(_qc(TEXTO), 1.2))
            p.drawLine(QPointF(232, 420), QPointF(232, 452))
            p.drawLine(QPointF(216, 436), QPointF(248, 436))
            self._texto(p, 232, 492, "PUNZANTES", 7, DIM, centro=True)
