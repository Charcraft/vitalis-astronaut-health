# -*- coding: utf-8 -*-
"""
desktop/widgets.py — Componentes nativos reutilizables (QPainter, sin HTML):
tarjetas, filas de signos vitales, gráfica de tendencia, barras segmentadas
y el rostro holográfico de L.I.S.
"""

from __future__ import annotations

from collections import deque
import math
import random
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QButtonGroup,
    QLayout,
    QScroller,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop import theme as t
from desktop.i18n import tr


# ---------------------------------------------------------------------------
# Básicos
# ---------------------------------------------------------------------------

def etiqueta_mono(texto: str, color: Optional[str] = None) -> QLabel:
    """Rótulo de sección. Antes era MAYÚSCULAS de 10 px: ilegible a un brazo de distancia."""
    lbl = QLabel(tr(texto))
    lbl.setObjectName("etiquetaMono")
    if color:
        rol = t.rol_de_color(color)
        lbl.setProperty("_v_mono_role", rol)
        lbl.setStyleSheet(f"color: {t.color_de_rol(rol)};")
    return lbl


def divisor() -> QFrame:
    f = QFrame()
    f.setObjectName("divisor")
    return f


def _css_etiqueta(tam: int, color_hex: str, peso: int, mono: bool) -> str:
    fam = t.FUENTE_MONO if mono else t.FUENTE
    return f"font-family: '{fam}'; font-size: {tam}px; color: {color_hex}; font-weight: {peso};"


def etiqueta(texto: str, tam: int = 12, color: Optional[str] = None, peso: int = 400,
             mono: bool = False, wrap: bool = False) -> QLabel:
    lbl = QLabel(tr(texto))
    rol = t.rol_de_color(color)
    lbl.setProperty("_v_lbl_spec", (tam, rol, peso, mono))
    lbl.setStyleSheet(_css_etiqueta(tam, t.color_de_rol(rol), peso, mono))
    lbl.setWordWrap(wrap)
    return lbl


def estilo_pastilla(lbl: QLabel, rol_o_color: str) -> None:
    """Estiliza un badge de estado según el tema activo."""
    rol = t.rol_de_color(rol_o_color)
    lbl.setProperty("_v_pastilla_role", rol)
    color = t.color_de_rol(rol)
    c = QColor(color)
    alfa = 34 if not t.es_oscuro() else 28
    lbl.setStyleSheet(
        f"font-family: '{t.FUENTE}'; font-size: {t.T_PEQUENO}px; font-weight: 600; color: {color};"
        f"background: rgba({c.red()}, {c.green()}, {c.blue()}, {alfa}); border-radius: 10px; padding: 6px 12px;"
    )


def reaplicar_tema_widgets(raiz: QWidget) -> None:
    """Reaplica colores inline rastreados en todas las etiquetas descendientes."""
    etiquetas = list(raiz.findChildren(QLabel))
    if isinstance(raiz, QLabel):
        etiquetas.append(raiz)
    for lbl in etiquetas:
        spec = lbl.property("_v_lbl_spec")
        if spec:
            tam, rol, peso, mono = spec
            lbl.setStyleSheet(_css_etiqueta(tam, t.color_de_rol(rol), peso, mono))
            continue
        mono_rol = lbl.property("_v_mono_role")
        if mono_rol:
            lbl.setStyleSheet(f"color: {t.color_de_rol(mono_rol)};")
            continue
        past_rol = lbl.property("_v_pastilla_role")
        if past_rol:
            estilo_pastilla(lbl, past_rol)


def icono_engrane(color_hex: str, tam: int = 24) -> QIcon:
    """Dibuja un ícono vectorial nítido de engranaje en resolución @2x para barra táctil."""
    escala = 2
    lado = max(16, int(tam)) * escala
    pm = QPixmap(lado, lado)
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(escala)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color_hex)
    centro = tam / 2.0
    r_diente = tam * 0.42
    r_base = tam * 0.31
    r_centro = tam * 0.14

    p.save()
    p.translate(centro, centro)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    for k in range(8):
        ang = math.radians(k * 45.0)
        p.save()
        p.rotate(math.degrees(ang))
        p.drawRoundedRect(QRectF(-tam * 0.065, -r_diente, tam * 0.13, tam * 0.17), 1.6, 1.6)
        p.restore()
    p.restore()

    pen = QPen(c, 2.2)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(centro, centro), r_base, r_base)
    p.drawEllipse(QPointF(centro, centro), r_centro, r_centro)
    p.end()
    return QIcon(pm)


class Tarjeta(QFrame):
    def __init__(self, margen: int = 24, espacio: int = 12) -> None:
        super().__init__()
        self.setObjectName("tarjeta")
        self.capa = QVBoxLayout(self)
        self.capa.setContentsMargins(margen, margen, margen, margen)
        self.capa.setSpacing(espacio)


def boton(texto: str, estilo: str = "", al_pulsar: Optional[Callable] = None) -> QPushButton:
    b = QPushButton(tr(texto))
    if estilo:
        b.setObjectName(estilo)
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(t.ALTO_TOQUE)
    if al_pulsar:
        b.clicked.connect(al_pulsar)
    return b


def scroll_tactil(area: QAbstractScrollArea) -> None:
    """Desplazamiento cinético con el dedo (y arrastrando con el ratón)."""
    QScroller.grabGesture(area.viewport(), QScroller.LeftMouseButtonGesture)


def vaciar_layout(capa: QLayout) -> None:
    """Quita y destruye los widgets de un layout.

    Sólo con deleteLater() los widgets viejos siguen pintándose encima de los
    nuevos hasta que vuelve el bucle de eventos: era el texto superpuesto que
    se veía en Medición.
    """
    while capa.count():
        it = capa.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            vaciar_layout(it.layout())


class Interruptor(QPushButton):
    """Interruptor grande para pantalla táctil: muestra «Activado» / «Desactivado»."""

    cambiado = Signal(bool)

    def __init__(self, activo: bool = False) -> None:
        super().__init__()
        self.setObjectName("interruptor")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(170, t.ALTO_TOQUE)
        self.setChecked(activo)
        self._pintar()
        self.toggled.connect(self._al_cambiar)

    def _al_cambiar(self, activo: bool) -> None:
        self._pintar()
        self.cambiado.emit(activo)

    def _pintar(self) -> None:
        self.setText(tr("Activado") if self.isChecked() else tr("Desactivado"))


class TecladoNumerico(QWidget):
    """Teclado numérico en pantalla: en una pantalla táctil no hay teclado físico."""

    tecla = Signal(str)

    def __init__(self, alto_tecla: int = 64) -> None:
        super().__init__()
        capa = QGridLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(10)
        teclas = ["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "⌫"]
        self._alto_base = alto_tecla
        self._teclas: List[QPushButton] = []
        for i, k in enumerate(teclas):
            b = QPushButton(k)
            b.setObjectName("tecla")
            b.setMinimumHeight(alto_tecla)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=k: self.tecla.emit(v))
            capa.addWidget(b, i // 3, i % 3)
            self._teclas.append(b)

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self._ajustar_alto()

    def _ajustar_alto(self) -> None:
        """En ventanas bajas (tablet de 800 px) las teclas se compactan para que el teclado no se solape."""
        ventana = self.window()
        alto_v = ventana.height() if ventana is not None else 0
        alto = self._alto_base if (alto_v <= 0 or alto_v >= 860) else min(self._alto_base, 52)
        for b in self._teclas:
            if b.minimumHeight() != alto:
                b.setMinimumHeight(alto)


class GrupoChips(QWidget):
    """Fila de botones exclusivos (tripulación, timepoints, segmentos)."""

    seleccionado = Signal(str)

    def __init__(self, opciones: Iterable[str], estilo: str = "chip",
                 columnas: Optional[int] = None, etiquetas: Optional[Dict[str, str]] = None,
                 espacio: int = 8) -> None:
        super().__init__()
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        self.botones: Dict[str, QPushButton] = {}
        opciones = list(opciones)
        if columnas:
            capa = QGridLayout(self)
            capa.setHorizontalSpacing(espacio)
            capa.setVerticalSpacing(espacio)
        else:
            capa = QHBoxLayout(self)
            capa.setSpacing(espacio)
        capa.setContentsMargins(0, 0, 0, 0)
        for i, op in enumerate(opciones):
            b = QPushButton(tr((etiquetas or {}).get(op, op)))
            b.setObjectName(estilo)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(t.ALTO_TOQUE)
            b.clicked.connect(lambda _=False, v=op: self.seleccionado.emit(v))
            self.grupo.addButton(b)
            self.botones[op] = b
            if columnas:
                capa.addWidget(b, i // columnas, i % columnas)
            else:
                capa.addWidget(b)
        if not columnas:
            capa.addStretch(1)

    def marcar(self, valor: str) -> None:
        b = self.botones.get(valor)
        if b:
            b.setChecked(True)


class BarraSegmentada(QFrame):
    """Barra rectangular inferior estilo Ref1: Cuerpo · Frontal · Lateral · Capas."""

    seleccionado = Signal(str)

    def __init__(self, opciones: List[str]) -> None:
        super().__init__()
        self.setObjectName("barraSegmentada")
        capa = QHBoxLayout(self)
        capa.setContentsMargins(8, 8, 8, 8)
        capa.setSpacing(6)
        self.grupo = QButtonGroup(self)
        self.botones: Dict[str, QPushButton] = {}
        for op in opciones:
            b = QPushButton(tr(op.capitalize()))
            b.setObjectName("segmento")
            b.setCheckable(True)
            b.setMinimumHeight(t.ALTO_TOQUE)
            # Ancho mínimo = el del texto en negrita + relleno: nunca se recorta.
            f = QFont(t.FUENTE)
            f.setPixelSize(t.T_CUERPO)
            f.setBold(True)
            b.setMinimumWidth(QFontMetrics(f).horizontalAdvance(b.text()) + 30)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=op: self.seleccionado.emit(v))
            self.grupo.addButton(b)
            self.botones[op] = b
            capa.addWidget(b)

    def marcar(self, valor: str) -> None:
        if valor in self.botones:
            self.botones[valor].setChecked(True)


# ---------------------------------------------------------------------------
# Fila de signo vital con gráfica en vivo de fondo (Overview)
# ---------------------------------------------------------------------------

def _norm_en_rango(valor: float, vmin: float, vmax: float) -> float:
    span = vmax - vmin
    if span <= 1e-6:
        return 0.5
    return max(0.06, min(0.92, (float(valor) - vmin) / span))


def muestra_onda_monitor(
    modo: str,
    fase: float,
    valor: Optional[float] = None,
    rango_min: Optional[float] = None,
    rango_max: Optional[float] = None,
    valor_sec: Optional[float] = None,
) -> float:
    """Devuelve una muestra normalizada [0.04..0.96] del trazo fisiológico en fase [0, 1)."""
    f = float(fase) % 1.0
    m = str(modo or "tendencia").lower()

    if m == "ecg":
        # Complejo P-QRS-T clínico con pico R exacto en f=0.22
        p = 0.11 * math.exp(-(((f - 0.11) / 0.022) ** 2))
        q = -0.09 * math.exp(-(((f - 0.182) / 0.010) ** 2))
        r = 0.66 * math.exp(-(((f - 0.220) / 0.014) ** 2))
        s = -0.17 * math.exp(-(((f - 0.258) / 0.012) ** 2))
        t_w = 0.18 * math.exp(-(((f - 0.415) / 0.042) ** 2))
        y = 0.28 + p + q + r + s + t_w
        return max(0.05, min(0.96, y))

    if m == "pleth":
        # Onda pletismográfica (SpO2) con muesca dicrótica desplazada fisiológicamente (+0.12)
        fp = (f - 0.12) % 1.0
        sis = math.exp(-(((fp - 0.18) / 0.075) ** 2))
        dic = 0.40 * math.exp(-(((fp - 0.44) / 0.085) ** 2))
        onda = max(sis, dic)
        spo2_v = 98.0 if valor is None else float(valor)
        nivel_sat = _norm_en_rango(spo2_v, 78.0, 100.0)
        base = 0.10 + nivel_sat * 0.24
        amp = 0.28 + nivel_sat * 0.24
        return max(0.05, min(0.95, base + onda * amp))

    if m == "arterial":
        # Contorno de presión arterial pulsátil escalado por sbp/dbp reales en [45..200] mmHg
        fa = (f - 0.08) % 1.0
        sbp = 118.0 if valor is None else float(valor)
        dbp = 76.0 if valor_sec is None else float(valor_sec)
        y_dia = _norm_en_rango(dbp, 45.0, 200.0)
        y_sys = max(y_dia + 0.16, _norm_en_rango(sbp, 45.0, 200.0))
        up = math.exp(-(((fa - 0.17) / 0.065) ** 2))
        dic = 0.48 * math.exp(-(((fa - 0.40) / 0.080) ** 2))
        escurr = max(0.0, 1.0 - fa * 1.15) * 0.20 if fa >= 0.17 else 0.0
        forma = max(up, dic, escurr)
        return max(0.05, min(0.95, y_dia + forma * (y_sys - y_dia)))

    if m == "respiratorio":
        # Curva respiratoria sinusoidal asimétrica sincronizada a rpm
        ciclo = 0.5 - 0.5 * math.cos(2.0 * math.pi * f)
        rr = 15.0 if valor is None else float(valor)
        amp = 0.35 + _norm_en_rango(rr, 8.0, 32.0) * 0.45
        return max(0.08, min(0.92, 0.16 + ciclo * amp))

    # Tendencia directa normalizada para variables continuas (temperatura, CO2, radiación, PIC)
    if valor is not None and rango_min is not None and rango_max is not None:
        return _norm_en_rango(float(valor), float(rango_min) - 0.25 * (float(rango_max) - float(rango_min)),
                              float(rango_max) + 0.25 * (float(rango_max) - float(rango_min)))
    return 0.5


def _pintar_trazo_fondo(
    p: QPainter,
    rect: QRectF,
    muestras: Sequence[float],
    color_hex: str,
    rango_norm: Optional[Tuple[float, float]] = None,
    brillo: float = 0.0,
    compacto: bool = False,
) -> None:
    """Dibuja una gráfica de monitor clínico sutil en el fondo detrás de los números."""
    if rect.width() < 24 or rect.height() < 14:
        return

    c = QColor(color_hex)
    es_oscuro = t.es_oscuro()

    # Banda suave de rango de referencia en el fondo
    if rango_norm is not None and not compacto:
        r0, r1 = max(0.04, min(0.96, rango_norm[0])), max(0.04, min(0.96, rango_norm[1]))
        y_top = rect.bottom() - r1 * rect.height()
        y_bot = rect.bottom() - r0 * rect.height()
        if y_bot > y_top + 1.0:
            p.fillRect(
                QRectF(rect.left(), y_top, rect.width(), y_bot - y_top),
                QColor(c.red(), c.green(), c.blue(), 10 if es_oscuro else 11),
            )

    if len(muestras) < 2:
        return

    n = len(muestras)
    x0 = rect.left()
    dx = rect.width() / max(1, n - 1)
    h = rect.height()
    b = rect.bottom()

    puntos = [
        QPointF(x0 + i * dx, b - max(0.04, min(0.96, float(val))) * h)
        for i, val in enumerate(muestras)
    ]

    ruta = QPainterPath(puntos[0])
    for pt in puntos[1:]:
        ruta.lineTo(pt)

    # Relleno vertical desvanecido debajo de la curva
    ruta_area = QPainterPath(ruta)
    ruta_area.lineTo(QPointF(puntos[-1].x(), rect.bottom()))
    ruta_area.lineTo(QPointF(puntos[0].x(), rect.bottom()))
    ruta_area.closeSubpath()

    grad_fill = QLinearGradient(QPointF(0, rect.top()), QPointF(0, rect.bottom()))
    alfa_fill = (32 if not compacto else 24) if es_oscuro else (26 if not compacto else 20)
    grad_fill.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), alfa_fill))
    grad_fill.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
    p.setPen(Qt.NoPen)
    p.fillPath(ruta_area, QBrush(grad_fill))

    # Trazo con desvanecimiento horizontal para mantener el numeral frontal 100 % legible
    grad_linea = QLinearGradient(QPointF(rect.left(), 0), QPointF(rect.right(), 0))
    if es_oscuro:
        grad_linea.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 42 if not compacto else 36))
        grad_linea.setColorAt(0.45, QColor(c.red(), c.green(), c.blue(), 95 if not compacto else 82))
        grad_linea.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 175 if not compacto else 155))
    else:
        grad_linea.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 48 if not compacto else 40))
        grad_linea.setColorAt(0.45, QColor(c.red(), c.green(), c.blue(), 108 if not compacto else 92))
        grad_linea.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 190 if not compacto else 168))

    pen = QPen(QBrush(grad_linea), 1.8 if not compacto else 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(ruta)

    # Cabezal activo en tiempo real con halo que pulsa con cada latido
    ult = puntos[-1]
    br = max(0.0, min(1.0, float(brillo)))
    rad_halo = (5.0 if compacto else 7.0) + br * (4.0 if compacto else 6.0)
    grad_dot = QRadialGradient(ult, rad_halo)
    grad_dot.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), int(150 + br * 90)))
    grad_dot.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
    p.setPen(Qt.NoPen)
    p.setBrush(grad_dot)
    p.drawEllipse(ult, rad_halo, rad_halo)
    p.setBrush(QColor(c.red(), c.green(), c.blue(), 220))
    p.drawEllipse(ult, 2.2 if compacto else 2.8, 2.2 if compacto else 2.8)


def _normalizar_serie_tendencia(
    valores: Sequence[float],
    rango_min: Optional[float],
    rango_max: Optional[float],
) -> List[float]:
    if not valores:
        return []
    vmin = min(valores)
    vmax = max(valores)
    if rango_min is not None:
        vmin = min(vmin, float(rango_min))
    if rango_max is not None:
        vmax = max(vmax, float(rango_max))
    span = vmax - vmin
    if span <= 1e-6:
        pad = max(abs(vmin) * 0.05, 0.5)
    else:
        pad = span * 0.16
    vmin -= pad
    vmax += pad
    return [_norm_en_rango(v, vmin, vmax) for v in valores]


class _WidgetPulsable(QWidget):
    """Base táctil con realimentación visual al tocar y señal `pulsado`."""

    pulsado = Signal()

    def __init__(self, al_pulsar: Optional[Callable[[], None]] = None, radio_hover: float = 12.0) -> None:
        super().__init__()
        self._hover = False
        self._presionado = False
        self._clickable = al_pulsar is not None
        self._radio_hover = float(radio_hover)
        if al_pulsar is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.pulsado.connect(al_pulsar)

    def _pintar_fondo_hover(self, p: QPainter, margen_v: float = 2.0) -> None:
        if self._clickable and (self._hover or self._presionado):
            fondo = QColor(t.ACTIVO if self._presionado else t.HOVER)
            fondo.setAlpha(155 if t.es_oscuro() else 175)
            p.setPen(Qt.NoPen)
            p.setBrush(fondo)
            r = QRectF(0, margen_v, max(10, self.width()), max(10, self.height() - 2 * margen_v))
            p.drawRoundedRect(r, self._radio_hover, self._radio_hover)

    def enterEvent(self, ev) -> None:  # noqa: N802
        if self._clickable:
            self._hover = True
            self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:  # noqa: N802
        if self._hover or self._presionado:
            self._hover = False
            self._presionado = False
            self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if self._clickable and ev.button() == Qt.LeftButton:
            self._presionado = True
            self.update()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if self._clickable and self._presionado and ev.button() == Qt.LeftButton:
            self._presionado = False
            self.update()
            if self.rect().contains(ev.position().toPoint()):
                self.pulsado.emit()
        super().mouseReleaseEvent(ev)


class FilaIndicador(_WidgetPulsable):
    def __init__(
        self,
        titulo: str,
        unidad: str,
        modo_monitor: str = "tendencia",
        rango_min: Optional[float] = None,
        rango_max: Optional[float] = None,
        al_pulsar: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(al_pulsar=al_pulsar, radio_hover=14.0)
        self._insignia = False
        self._modo_monitor = modo_monitor
        self._rango_min = rango_min
        self._rango_max = rango_max
        self._nivel = "NOMINAL"
        self._bpm = 64.0
        self._valor_num: Optional[float] = None
        self._valor_sec: Optional[float] = None
        self._fase_prev = 0.0
        self._pulso_brillo = 0.0
        self._serie_viva: deque[float] = deque(maxlen=48)
        self._onda_muestras: deque[float] = deque(maxlen=180)
        self._prellenar_onda_inicial()

        self.setMinimumHeight(104)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(8, 14, 8, 14)
        capa.setSpacing(2)
        self.lbl_titulo = etiqueta(titulo, t.T_CUERPO, t.ETIQUETA)
        capa.addWidget(self.lbl_titulo)
        fila = QHBoxLayout()
        fila.setSpacing(10)
        self.lbl_valor = etiqueta("–", t.T_VALOR, None, peso=300)
        self.lbl_unidad = etiqueta(unidad, t.T_DESTACADO, t.SECUNDARIO)
        self.lbl_base = etiqueta("", t.T_PEQUENO, t.TERCIARIO)
        fila.addWidget(self.lbl_valor, 0, Qt.AlignBottom)
        fila.addWidget(self.lbl_unidad, 0, Qt.AlignBottom)
        fila.addSpacing(4)
        fila.addWidget(self.lbl_base, 0, Qt.AlignBottom)
        fila.addStretch(1)
        capa.addLayout(fila)

    def _prellenar_onda_inicial(self) -> None:
        if self._modo_monitor not in ("ecg", "pleth", "arterial", "respiratorio"):
            return
        self._onda_muestras.clear()
        total = 180
        # 2.0 s de historial inicial proporcional al ritmo para abrir sin lienzo vacío
        ciclos = max(1.0, (self._bpm / 60.0) * 2.0)
        for i in range(total):
            f = ((i / max(1, total - 1)) * ciclos) % 1.0
            self._onda_muestras.append(
                muestra_onda_monitor(
                    self._modo_monitor,
                    f,
                    self._valor_num,
                    self._rango_min,
                    self._rango_max,
                    self._valor_sec,
                )
            )

    def cargar_historial(self, valores: Iterable[float]) -> None:
        vals = [float(v) for v in valores if v is not None]
        if vals:
            self._serie_viva.clear()
            for v in vals[-48:]:
                self._serie_viva.append(v)
            self._valor_num = vals[-1]
        self.update()

    def registrar_muestra(
        self,
        valor_num: Optional[float],
        nivel: str = "NOMINAL",
        valor_sec: Optional[float] = None,
        rango_min: Optional[float] = None,
        rango_max: Optional[float] = None,
    ) -> None:
        self._nivel = str(nivel or "NOMINAL").upper()
        if rango_min is not None:
            self._rango_min = float(rango_min)
        if rango_max is not None:
            self._rango_max = float(rango_max)
        if valor_num is not None:
            v = float(valor_num)
            self._valor_num = v
            self._serie_viva.append(v)
            if self._modo_monitor == "ecg":
                self._bpm = max(30.0, min(240.0, v))
        if valor_sec is not None:
            self._valor_sec = float(valor_sec)
        self.update()

    def pulso(self) -> None:
        self._pulso_brillo = 1.0

    def avanzar_onda(self, dt_s: float, ritmo_hz: float, fase_actual: Optional[float] = None) -> None:
        self._pulso_brillo = max(0.0, self._pulso_brillo - max(0.04, dt_s * 3.8))
        if self._modo_monitor not in ("ecg", "pleth", "arterial", "respiratorio"):
            self.update()
            return
        hz = max(0.15, min(4.2, float(ritmo_hz)))
        if fase_actual is not None:
            f_fin = float(fase_actual) % 1.0
            delta = (f_fin - self._fase_prev) % 1.0
            if delta <= 0.0 or delta > 0.6:
                delta = min(0.45, dt_s * hz)
            f_ini = self._fase_prev
            self._fase_prev = f_fin
        else:
            delta = min(0.45, max(0.002, dt_s * hz))
            f_ini = self._fase_prev
            self._fase_prev = (self._fase_prev + delta) % 1.0

        subpasos = 3
        for k in range(1, subpasos + 1):
            f_sub = (f_ini + (delta * k) / subpasos) % 1.0
            self._onda_muestras.append(
                muestra_onda_monitor(
                    self._modo_monitor,
                    f_sub,
                    self._valor_num,
                    self._rango_min,
                    self._rango_max,
                    self._valor_sec,
                )
            )
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._pintar_fondo_hover(p, margen_v=2.0)
        rect = QRectF(4, 10, max(10, self.width() - 8), max(16, self.height() - 20))
        color = t.color_triage(self._nivel)

        rango_norm = None
        if self._modo_monitor == "tendencia":
            vals = list(self._serie_viva)
            if not vals and self._valor_num is not None:
                vals = [self._valor_num, self._valor_num]
            elif len(vals) == 1:
                vals = [vals[0], vals[0]]
            muestras = _normalizar_serie_tendencia(vals, self._rango_min, self._rango_max)
            if self._rango_min is not None and self._rango_max is not None and vals:
                vmin = min(min(vals), self._rango_min)
                vmax = max(max(vals), self._rango_max)
                span = vmax - vmin
                pad = max(abs(vmin) * 0.05, 0.5) if span <= 1e-6 else span * 0.16
                vmin -= pad
                vmax += pad
                rango_norm = (_norm_en_rango(self._rango_min, vmin, vmax), _norm_en_rango(self._rango_max, vmin, vmax))
        else:
            muestras = list(self._onda_muestras)

        _pintar_trazo_fondo(
            p,
            rect,
            muestras,
            color,
            rango_norm=rango_norm,
            brillo=self._pulso_brillo,
            compacto=False,
        )
        super().paintEvent(ev)

    def aplicar_tema(self) -> None:
        self._pintar_base(self._insignia)
        self.update()

    def _pintar_base(self, insignia: bool) -> None:
        if insignia:
            col = t.color_triage(self._nivel)
            c = QColor(col)
            alfa_bg = 30 if t.es_oscuro() else 36
            self.lbl_base.setStyleSheet(
                f"font-family: '{t.FUENTE}'; font-size: {t.T_PEQUENO}px; color: {col};"
                f"border: 1px solid rgba({c.red()}, {c.green()}, {c.blue()}, 115);"
                f"background: rgba({c.red()}, {c.green()}, {c.blue()}, {alfa_bg});"
                f" padding: 4px 10px; border-radius: 8px;"
            )
        else:
            self.lbl_base.setStyleSheet(
                f"font-family: '{t.FUENTE}'; font-size: {t.T_PEQUENO}px; color: {t.TERCIARIO}; border: none;"
            )

    def actualizar(self, valor, base_texto: str = "", insignia: bool = False) -> None:
        self._insignia = insignia
        self.lbl_valor.setText(str(valor))
        self.lbl_base.setText(tr(base_texto))
        self._pintar_base(insignia)


class FilaCabinaMonitor(_WidgetPulsable):
    """Fila compacta para parámetros ambientales/cabina con gráfica en vivo de fondo."""

    def __init__(
        self,
        titulo: str,
        lbl_valor: QLabel,
        modo_monitor: str = "tendencia",
        rango_min: Optional[float] = None,
        rango_max: Optional[float] = None,
        al_pulsar: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(al_pulsar=al_pulsar, radio_hover=10.0)
        self._modo_monitor = modo_monitor
        self._rango_min = rango_min
        self._rango_max = rango_max
        self._nivel = "NOMINAL"
        self._valor_num: Optional[float] = None
        self._fase_prev = 0.0
        self._serie_viva: deque[float] = deque(maxlen=40)
        self._onda_muestras: deque[float] = deque(maxlen=150)
        if modo_monitor == "respiratorio":
            for i in range(150):
                f = ((i / 149.0) * 2.0) % 1.0
                self._onda_muestras.append(muestra_onda_monitor("respiratorio", f, 15.0, rango_min, rango_max))

        self.setMinimumHeight(44)
        fila = QHBoxLayout(self)
        fila.setContentsMargins(8, 6, 8, 6)
        fila.setSpacing(8)
        fila.addWidget(etiqueta(titulo, t.T_CUERPO, t.ETIQUETA))
        fila.addStretch(1)
        fila.addWidget(lbl_valor)

    def cargar_historial(self, valores: Iterable[float]) -> None:
        vals = [float(v) for v in valores if v is not None]
        if vals:
            self._serie_viva.clear()
            for v in vals[-40:]:
                self._serie_viva.append(v)
            self._valor_num = vals[-1]
        self.update()

    def registrar_muestra(self, valor_num: Optional[float], nivel: str = "NOMINAL") -> None:
        self._nivel = str(nivel or "NOMINAL").upper()
        if valor_num is not None:
            v = float(valor_num)
            self._valor_num = v
            self._serie_viva.append(v)
        self.update()

    def avanzar_onda(self, dt_s: float, ritmo_hz: float) -> None:
        if self._modo_monitor != "respiratorio":
            return
        hz = max(0.10, min(1.0, float(ritmo_hz)))
        delta = min(0.35, max(0.002, dt_s * hz))
        f_ini = self._fase_prev
        self._fase_prev = (self._fase_prev + delta) % 1.0
        for k in (1, 2):
            f_sub = (f_ini + (delta * k) / 2.0) % 1.0
            self._onda_muestras.append(
                muestra_onda_monitor("respiratorio", f_sub, self._valor_num, self._rango_min, self._rango_max)
            )
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._pintar_fondo_hover(p, margen_v=1.0)
        rect = QRectF(4, 2, max(10, self.width() - 8), max(12, self.height() - 4))
        color = t.color_triage(self._nivel)
        if self._modo_monitor == "respiratorio":
            muestras = list(self._onda_muestras)
        else:
            vals = list(self._serie_viva)
            if not vals and self._valor_num is not None:
                vals = [self._valor_num, self._valor_num]
            elif len(vals) == 1:
                vals = [vals[0], vals[0]]
            muestras = _normalizar_serie_tendencia(vals, self._rango_min, self._rango_max)
        _pintar_trazo_fondo(p, rect, muestras, color, compacto=True)
        super().paintEvent(ev)


# ---------------------------------------------------------------------------
# Gráfica de tendencia (curva suave + punto activo)
# ---------------------------------------------------------------------------

class GraficaTendencia(QWidget):
    def __init__(self, alto: int = 120) -> None:
        super().__init__()
        self._alto = max(96, int(alto))
        self.setMinimumHeight(self._alto)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.serie: List[Dict] = []
        self.rango_min: Optional[float] = None
        self.rango_max: Optional[float] = None
        self.activo: Optional[str] = None

    def sizeHint(self):  # noqa: N802
        return QSize(240, self._alto)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(160, self._alto)

    def cargar(self, serie: List[Dict], rango_min, rango_max, activo: Optional[str]) -> None:
        self.serie = serie or []
        self.rango_min = rango_min
        self.rango_max = rango_max
        self.activo = activo
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        margen_inf = 30
        area_h = h - margen_inf - 10
        if len(self.serie) < 2:
            p.setPen(QColor(t.SECUNDARIO))
            p.setFont(QFont(t.FUENTE, 12))
            p.drawText(self.rect(), Qt.AlignCenter, tr("Sin datos para este tripulante"))
            return
        valores = [float(pt["valor"]) for pt in self.serie]
        vmin, vmax = min(valores), max(valores)
        if self.rango_min is not None:
            vmin = min(vmin, float(self.rango_min))
        if self.rango_max is not None:
            vmax = max(vmax, float(self.rango_max))
        pad = (vmax - vmin) * 0.12 or 1.0
        vmin -= pad
        vmax += pad

        # 26 px por lado: sitio para centrar la etiqueta del primer y último punto.
        def xy(i: int, v: float) -> QPointF:
            x = 26 + i * (w - 52) / (len(valores) - 1)
            y = 10 + area_h - (v - vmin) / (vmax - vmin) * area_h
            return QPointF(x, y)

        # Banda de referencia
        if self.rango_min is not None and self.rango_max is not None:
            y1 = xy(0, float(self.rango_max)).y()
            y2 = xy(0, float(self.rango_min)).y()
            p.fillRect(QRectF(8, y1, w - 16, y2 - y1), QColor(*t.BANDA_REF_RGBA))
            pen = QPen(QColor(t.LINEA_REF), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(8, y1), QPointF(w - 8, y1))
            p.drawLine(QPointF(8, y2), QPointF(w - 8, y2))

        puntos = [xy(i, v) for i, v in enumerate(valores)]
        ruta = QPainterPath(puntos[0])
        for i in range(1, len(puntos)):
            a, b = puntos[i - 1], puntos[i]
            cx = (a.x() + b.x()) / 2
            ruta.cubicTo(QPointF(cx, a.y()), QPointF(cx, b.y()), b)
        p.setPen(QPen(QColor(t.TEXTO_SUAVE), 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawPath(ruta)

        fuente = QFont(t.FUENTE, 11)
        p.setFont(fuente)
        hr, hg, hb = t.HALO_PUNTO_RGB
        for i, pt in enumerate(self.serie):
            pos = puntos[i]
            es_activo = pt["timepoint"] == self.activo
            if es_activo:
                grad = QRadialGradient(pos, 10)
                grad.setColorAt(0, QColor(hr, hg, hb, 120))
                grad.setColorAt(1, QColor(hr, hg, hb, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(grad)
                p.drawEllipse(pos, 10, 10)
                p.setBrush(QColor(t.PUNTO_ACTIVO))
                p.drawEllipse(pos, 3.5, 3.5)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(t.PUNTO_INACTIVO))
                p.drawEllipse(pos, 3, 3)
            p.setPen(QColor(t.TEXTO if es_activo else t.TERCIARIO))
            p.drawText(QRectF(pos.x() - 26, h - 24, 52, 22), Qt.AlignCenter, pt["timepoint"])


# ---------------------------------------------------------------------------
# Rostro holográfico de L.I.S. (astronauta no humano, casco EVA + visor HUD)
# ---------------------------------------------------------------------------

class RostroLIS(QWidget):
    """Casco EVA holográfico no humano con seguimiento de cursor y vocalizador."""

    def __init__(self, tam: int = 72) -> None:
        super().__init__()
        self.setFixedSize(tam, tam)
        self.expresion = "NOMINAL"
        self.energia = 0.0
        self._fase = 0.0
        self._angulo_anillo = 0.0
        self._parpadeo = 0.0
        self._barras = [0.0] * 9
        self._mirada_x = 0.0
        self._mirada_y = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_expresion(self, expresion: str) -> None:
        self.expresion = expresion
        self.update()

    def set_energia(self, energia: float) -> None:
        self.energia = max(0.0, min(1.0, energia))

    def _tick(self) -> None:
        self._fase += 0.033
        vel_anillo = 2.4 if self.expresion in ("ANALIZANDO", "HABLANDO") else 0.92
        self._angulo_anillo = (self._angulo_anillo + vel_anillo) % 360.0
        if self._parpadeo > 0:
            self._parpadeo = max(0.0, self._parpadeo - 0.2)
        elif random.random() < 0.007:
            self._parpadeo = 1.0

        # Seguimiento suave del cursor del usuario
        try:
            from PySide6.QtGui import QCursor

            local = self.mapFromGlobal(QCursor.pos())
            cx, cy = self.width() / 2.0, self.height() / 2.0
            dx = max(-1.0, min(1.0, (local.x() - cx) / 260.0))
            dy = max(-1.0, min(1.0, (local.y() - cy) / 260.0))
            self._mirada_x += (dx - self._mirada_x) * 0.16
            self._mirada_y += (dy - self._mirada_y) * 0.16
        except Exception:
            pass

        hablando = self.expresion == "HABLANDO"
        for i in range(9):
            centro = 1.0 - abs(i - 4) / 5.0
            if hablando:
                objetivo = (0.28 + self.energia * 0.95) * centro * (0.55 + 0.45 * math.sin(self._fase * 19 + i * 1.4))
            elif self.expresion == "ESCUCHANDO":
                objetivo = 0.2 + 0.14 * math.sin(self._fase * 7 + i * 0.8)
            elif self.expresion == "ANALIZANDO":
                objetivo = 0.16 + 0.28 * max(0.0, math.sin(self._fase * 9 - i * 0.75))
            else:
                objetivo = 0.09 * centro
            self._barras[i] += (abs(objetivo) - self._barras[i]) * 0.35
        self.update()

    def _color(self) -> QColor:
        if not t.es_oscuro():
            if self.expresion in ("CRITICO", "AYUDA_ACTIVA"):
                return QColor("#D92D36")
            if self.expresion == "ATENCION":
                return QColor("#C87600")
            if self.expresion == "ESCUCHANDO":
                return QColor("#0F8B5D")
            if self.expresion == "ANALIZANDO":
                return QColor("#0284C7")
            return QColor("#2563EB")
        if self.expresion in ("CRITICO", "AYUDA_ACTIVA"):
            return QColor("#FF6B70")
        if self.expresion == "ATENCION":
            return QColor("#F2D49B")
        if self.expresion == "ESCUCHANDO":
            return QColor("#A8E6CF")
        if self.expresion == "ANALIZANDO":
            return QColor("#7CE8FF")
        return QColor("#E6F1FF")

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = min(self.width(), self.height())
        c = self._color()
        claro = not t.es_oscuro()
        cx, cy = s / 2.0, s / 2.0
        r = s * 0.45

        # Halo holográfico exterior
        halo = QRadialGradient(QPointF(cx, cy), r * 1.12)
        alfa = (105 if claro else 86) if self.expresion in ("HABLANDO", "ESCUCHANDO", "ANALIZANDO", "CRITICO") else (62 if claro else 40)
        halo.setColorAt(0.55, QColor(c.red(), c.green(), c.blue(), 0))
        halo.setColorAt(0.88, QColor(c.red(), c.green(), c.blue(), alfa))
        halo.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(cx, cy), r * 1.12, r * 1.12)

        # Anillo orbital HUD giratorio (estética holográfica)
        p.save()
        p.translate(cx, cy)
        p.rotate(self._angulo_anillo)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 145 if claro else 95), max(1.0, s * 0.015), Qt.DashLine))
        p.drawArc(QRectF(-r * 0.98, -r * 0.98, r * 1.96, r * 1.96), 20 * 16, 120 * 16)
        p.drawArc(QRectF(-r * 0.98, -r * 0.98, r * 1.96, r * 1.96), 200 * 16, 120 * 16)
        p.restore()

        # Silueta de casco EVA espacial (no humano, geométrico limpio)
        casco = QLinearGradient(0, cy - r, 0, cy + r)
        if claro:
            casco.setColorAt(0.0, QColor("#F8FAFC"))
            casco.setColorAt(0.6, QColor("#E2E8F0"))
            casco.setColorAt(1.0, QColor("#CBD5E1"))
        else:
            casco.setColorAt(0.0, QColor("#181D28"))
            casco.setColorAt(0.6, QColor("#0D1017"))
            casco.setColorAt(1.0, QColor("#07080A"))
        p.setBrush(casco)
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 220 if claro else 190), max(1.2, s * 0.02)))
        p.drawRoundedRect(QRectF(cx - r * 0.78, cy - r * 0.84, r * 1.56, r * 1.66), r * 0.68, r * 0.62)

        # Módulos laterales de comunicación del casco
        p.setBrush(QColor("#D6DEE8" if claro else "#11151E"))
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 170 if claro else 120), 1))
        p.drawRoundedRect(QRectF(cx - r * 0.89, cy - r * 0.24, r * 0.14, r * 0.48), 3, 3)
        p.drawRoundedRect(QRectF(cx + r * 0.75, cy - r * 0.24, r * 0.14, r * 0.48), 3, 3)

        # Visor panorámico holográfico oscuro
        visor = QRectF(cx - r * 0.64, cy - r * 0.42, r * 1.28, r * 0.88)
        vg = QLinearGradient(visor.topLeft(), visor.bottomRight())
        if claro:
            vg.setColorAt(0.0, QColor("#1E293B"))
            vg.setColorAt(0.5, QColor("#0F172A"))
            vg.setColorAt(1.0, QColor("#090E1A"))
        else:
            vg.setColorAt(0.0, QColor("#101928"))
            vg.setColorAt(0.5, QColor("#070B12"))
            vg.setColorAt(1.0, QColor("#030407"))
        p.setBrush(vg)
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 190 if claro else 150), 1.1))
        p.drawRoundedRect(visor, r * 0.34, r * 0.34)

        # Reflejo sutil superior del visor + línea de escaneo holográfico
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawArc(visor.adjusted(3, 3, -3, -visor.height() * 0.45), 25 * 16, 130 * 16)

        scan_y = visor.top() + 3 + ((self._fase * 18.0) % max(4.0, visor.height() - 6))
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 42), 1))
        p.drawLine(QPointF(visor.left() + 5, scan_y), QPointF(visor.right() - 5, scan_y))

        # Ópticas LED no humanas con seguimiento suave del cursor
        c_led = c.lighter(155) if claro else c
        ox = self._mirada_x * r * 0.08
        oy = self._mirada_y * r * 0.06
        alto_ojo = r * 0.15 * (1.0 - 0.9 * self._parpadeo)
        if self.expresion == "ESCUCHANDO":
            alto_ojo *= 1.18
        elif self.expresion in ("CRITICO", "ATENCION"):
            alto_ojo *= 0.72
        ancho_ojo = r * 0.26
        p.setPen(Qt.NoPen)
        for dx in (-r * 0.25, r * 0.25):
            centro = QPointF(cx + dx + ox, cy - r * 0.08 + oy)
            brillo = QRadialGradient(centro, ancho_ojo * 0.95)
            brillo.setColorAt(0, QColor(c_led.red(), c_led.green(), c_led.blue(), 150))
            brillo.setColorAt(1, QColor(c_led.red(), c_led.green(), c_led.blue(), 0))
            p.setBrush(brillo)
            p.drawEllipse(centro, ancho_ojo * 0.95, ancho_ojo * 0.72)
            p.setBrush(c_led)
            p.drawRoundedRect(
                QRectF(
                    centro.x() - ancho_ojo / 2.0,
                    centro.y() - alto_ojo / 2.0,
                    ancho_ojo,
                    max(1.4, alto_ojo),
                ),
                alto_ojo / 2.0,
                alto_ojo / 2.0,
            )

        # Vocalizador holográfico de 9 barras dentro de la base del visor
        base_y = cy + r * 0.24
        paso = r * 0.095
        x0 = cx - paso * 4
        for i, v in enumerate(self._barras):
            alto = max(1.6, v * r * 0.28)
            p.setBrush(QColor(c_led.red(), c_led.green(), c_led.blue(), 225))
            p.drawRoundedRect(
                QRectF(x0 + i * paso - paso * 0.26, base_y - alto / 2.0, paso * 0.52, alto),
                1.1,
                1.1,
            )
