# -*- coding: utf-8 -*-
"""
tablet/bridge.py — Puente Qt <-> tablet.

* Renderiza la ventana REAL de V.I.T.A.L.I.S. (todos sus widgets, popups y el
  visor VTK) a la resolución nativa de la tablet y envía sólo los parches que
  cambian (JPEG), con control de flujo por confirmación.
* Traduce el touch de la tablet a eventos Qt: toque, arrastre, desplazamiento
  con inercia en listas y paneles, pellizco para el zoom 3D.
* Sincroniza el teclado táctil de Android con el campo de texto que tenga el
  foco en Qt.
"""

from __future__ import annotations

import logging
import math
import os
import struct
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import (
    QEvent,
    QSize,
    QObject,
    QPoint,
    QPointF,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QRegion
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

from tablet.server import MSG_VIDEO, ServidorRemoto

try:  # cv2 codifica JPEG ~2x más rápido que Qt; si falta se usa Qt.
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

log = logging.getLogger("vitalis.tablet.bridge")

# Parámetros de la malla de cambios (tiles) y del flujo de imagen.
TILE_COLS, TILE_FILAS = 10, 6
CALIDAD_JPEG = 82
MAX_TRAMAS_EN_VUELO = 2
UMBRAL_TOQUE_PX = 10  # tolerancia (px lógicos) para considerar «toque» y no arrastre
CLASES_ARRASTRE_DIRECTO = ("QAbstractSlider", "QVTKRenderWindowInteractor")


def _es_arrastre_directo(w: Optional[QWidget]) -> bool:
    """Widgets que necesitan el arrastre real (deslizadores, visor 3D)."""
    while w is not None:
        if isinstance(w, QAbstractSlider):
            return True
        if any(c.__name__ in CLASES_ARRASTRE_DIRECTO for c in type(w).__mro__):
            return True
        w = w.parentWidget()
    return False


def _area_desplazable(w: Optional[QWidget]) -> Optional[QAbstractScrollArea]:
    """Primer QAbstractScrollArea ancestro (por su viewport) que realmente desplaza."""
    while w is not None:
        padre = w.parentWidget()
        if isinstance(padre, QAbstractScrollArea) and padre.viewport() is w:
            sb_v, sb_h = padre.verticalScrollBar(), padre.horizontalScrollBar()
            if sb_v.maximum() > sb_v.minimum() or sb_h.maximum() > sb_h.minimum():
                return padre
        w = padre
    return None


class _Puntero:
    __slots__ = (
        "id", "x0", "y0", "x", "y", "modo", "objetivo", "area", "t0",
        "vx", "vy", "tx", "ty", "boton_enviado",
    )

    def __init__(self, pid: int, x: float, y: float) -> None:
        self.id = pid
        self.x0 = self.x = x
        self.y0 = self.y = y
        self.modo = "pendiente"  # pendiente | directo | scroll | pellizco | fin
        self.objetivo: Optional[QWidget] = None
        self.area: Optional[QAbstractScrollArea] = None
        self.t0 = time.monotonic()
        self.vx = self.vy = 0.0
        self.tx = time.monotonic()
        self.ty = 0.0
        self.boton_enviado = False


class PuenteTablet(QObject):
    """Vive en el hilo de Qt. El servidor le entrega mensajes por señales en cola."""

    _mensaje = Signal(object)
    _conexion = Signal(bool)

    def __init__(
        self,
        ventana: QWidget,
        servidor: ServidorRemoto,
        tam_fisico: Tuple[int, int] = (2000, 1200),
        dpr_cliente: float = 1.5,
        minimo_logico: Tuple[int, int] = (1180, 760),
    ) -> None:
        super().__init__(ventana)
        self.ventana = ventana
        self.servidor = servidor
        self.dpr_cliente = float(dpr_cliente)
        self.minimo_logico = minimo_logico
        self._tam_fisico_cliente = tam_fisico
        self._seq = 0
        self._previo: Optional[np.ndarray] = None
        self._forzar_completo = True
        self._ultimo_completo = 0.0
        self._sucio_total = True  # hay que repintar toda la ventana
        self._sucio = QRegion()  # zonas (coords. lógicas de la ventana) que cambiaron
        self._popups_prev: List[QRect] = []
        self._img: Optional[QImage] = None
        self._renderizando = False
        self._vtk_sucio = True
        self._vtk_img: Optional[QImage] = None
        self._vtk_t = 0.0
        self._vtk_filtro = None
        self._vtk_observador = None
        self._pausado = False
        self._punteros: Dict[int, _Puntero] = {}
        self._pellizco_dist = 0.0
        self._fling: Optional[Tuple[QAbstractScrollArea, float, float]] = None
        self._tim_fling = QTimer(self)
        self._tim_fling.setInterval(16)
        self._tim_fling.timeout.connect(self._tick_fling)
        self._hover: List[QWidget] = []
        self._ime_firma: Optional[tuple] = None
        self._ime_texto_enviado: Optional[str] = None
        self._mic_pedido = False
        self.fps = 0.0
        self._cuenta_fps = 0
        self._t_fps = time.monotonic()
        self._est = {"n": 0, "comp": 0.0, "enc": 0.0, "kb": 0.0}
        self._t_log = time.monotonic()

        self._mensaje.connect(self._on_mensaje, Qt.QueuedConnection)
        self._conexion.connect(self._on_conexion, Qt.QueuedConnection)
        servidor.al_mensaje = lambda m: self._mensaje.emit(m)
        servidor.al_conectar = lambda: self._conexion.emit(True)
        servidor.al_desconectar = lambda: self._conexion.emit(False)

        self._tim = QTimer(self)
        self._tim.setInterval(22)
        self._tim.timeout.connect(self._tick)
        self._tim.start()

        self._tim_ime = QTimer(self)
        self._tim_ime.setInterval(120)
        self._tim_ime.timeout.connect(self._sincronizar_ime)
        self._tim_ime.start()

        QApplication.instance().installEventFilter(self)
        self._enganchar_vtk()

    # ------------------------------------------------------------------
    # Dirty tracking
    # ------------------------------------------------------------------
    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        """Acumula las zonas que Qt repinta: sólo eso se vuelve a capturar y enviar."""
        if self._renderizando or not isinstance(obj, QWidget):
            return False
        t = ev.type()
        if t == QEvent.Paint:
            v = self.ventana
            if obj.window() is v:
                try:
                    reg = ev.region().translated(obj.mapTo(v, QPoint(0, 0)))
                    self._sucio = self._sucio.united(reg)
                except Exception:
                    self._sucio_total = True
            elif obj.isVisible():
                self._sucio = self._sucio.united(QRegion(0, 0, 1, 1))  # despierta el ciclo (ventanas emergentes)
        elif t == QEvent.Resize and obj is self.ventana:
            self._sucio_total = True
        return False

    def _enganchar_vtk(self) -> None:
        visor = getattr(self.ventana, "visor_3d", None)
        if visor is None:
            return
        try:
            rw = visor.vtk_widget.GetRenderWindow()
            self._vtk_observador = rw.AddObserver("EndEvent", self._on_vtk_fin)
        except Exception:
            log.exception("No se pudo observar el render VTK")

    def _on_vtk_fin(self, *_a) -> None:
        if not self._renderizando:
            self._vtk_sucio = True

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------
    def _on_conexion(self, conectado: bool) -> None:
        if conectado:
            self._forzar_completo = True
            self._previo = None
            self._sucio_total = True
            self._vtk_sucio = True
            self._pausado = False
            self._ime_firma = None
        else:
            self._soltar_todo()
            self._mic_pedido = False

    def _on_mensaje(self, m: dict) -> None:
        tipo = m.get("t")
        try:
            if tipo == "hello":
                self._on_hello(m)
            elif tipo == "ptr":
                self._on_puntero(m)
            elif tipo == "text":
                self._on_texto(m)
            elif tipo == "key":
                self._on_tecla(m)
            elif tipo == "vis":
                self._pausado = bool(m.get("hidden"))
                if not self._pausado:
                    self._forzar_completo = True
                    self._sucio_total = True
            elif tipo == "resync":
                self._forzar_completo = True
                self._sucio_total = True
            elif tipo == "micerr":
                log.warning("Micrófono de la tablet no disponible: %s", m.get("e"))
        except Exception:
            log.exception("Mensaje táctil fallido: %s", tipo)

    def _on_hello(self, m: dict) -> None:
        pw, ph = int(m.get("pw", 2000)), int(m.get("ph", 1200))
        dpr = float(m.get("dpr", self.dpr_cliente)) or 1.5
        if pw < ph:
            pw, ph = ph, pw
        self._tam_fisico_cliente = (pw, ph)
        self.dpr_cliente = dpr
        cw, ch = int(m.get("cw", 0) or 0), int(m.get("ch", 0) or 0)
        if cw > ch > 300:
            lw, lh = cw, ch  # tamaño CSS real en horizontal
        else:
            lw, lh = int(pw / dpr), int(ph / dpr)
        lw, lh = max(self.minimo_logico[0], lw), max(self.minimo_logico[1], lh)
        v = self.ventana
        if (v.width(), v.height()) != (lw, lh):
            v.setMinimumSize(lw, lh)
            v.setMaximumSize(lw, lh)
            v.resize(lw, lh)
        log.info(
            "Tablet %dx%d px @%.2fx -> ventana lógica %dx%d (DPR Qt %.2f)",
            pw, ph, dpr, lw, lh, v.devicePixelRatioF(),
        )
        self._forzar_completo = True
        self._previo = None
        self._img = None
        self._sucio_total = True
        self._vtk_sucio = True
        self._enviar_init()

    def _tam_imagen(self) -> Tuple[int, int, float]:
        d = max(1.0, self.ventana.devicePixelRatioF())
        return int(round(self.ventana.width() * d)), int(round(self.ventana.height() * d)), d

    def _enviar_init(self) -> None:
        w, h, d = self._tam_imagen()
        self.servidor.enviar_json({
            "t": "init", "w": w, "h": h, "lw": self.ventana.width(), "lh": self.ventana.height(),
        })

    # ------------------------------------------------------------------
    # Captura de pantalla
    # ------------------------------------------------------------------
    def _capturar_vtk(self, ancho: int, alto: int) -> Optional[QImage]:
        visor = getattr(self.ventana, "visor_3d", None)
        if visor is None or not visor.vtk_widget.isVisible():
            return None
        try:
            import vtk  # noqa: WPS433
            from vtk.util import numpy_support

            rw = visor.vtk_widget.GetRenderWindow()
            if self._vtk_filtro is None:
                f = vtk.vtkWindowToImageFilter()
                f.SetInput(rw)
                f.SetInputBufferTypeToRGB()
                f.ReadFrontBufferOff()
                self._vtk_filtro = f
            f = self._vtk_filtro
            f.Modified()
            f.Update()
            salida = f.GetOutput()
            an, al, _ = salida.GetDimensions()
            if an < 2 or al < 2:
                return None
            arr = numpy_support.vtk_to_numpy(salida.GetPointData().GetScalars())
            arr = arr.reshape(al, an, -1)[::-1, :, :3]
            arr = np.ascontiguousarray(arr)
            img = QImage(arr.data, an, al, an * 3, QImage.Format_RGB888).copy()
            if (an, al) != (ancho, alto):
                img = img.scaled(ancho, alto, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            return img
        except Exception:
            log.exception("Captura VTK fallida")
            return None

    def _rects_emergentes(self) -> List[Tuple[QWidget, QRect]]:
        """Menús desplegables y diálogos (ventanas aparte) con su rectángulo en coords. de la ventana."""
        v = self.ventana
        origen_v = v.mapToGlobal(QPoint(0, 0))
        res: List[Tuple[QWidget, QRect]] = []
        for tl in QApplication.topLevelWidgets():
            if tl is v or not tl.isVisible() or tl.width() < 4 or tl.height() < 4:
                continue
            if tl.windowType() == Qt.ToolTip:
                continue
            off = tl.mapToGlobal(QPoint(0, 0)) - origen_v
            res.append((tl, QRect(off, tl.size())))
        return res

    def _componer(self, total: bool) -> Optional[QRect]:
        """Actualiza la imagen persistente repintando sólo lo sucio. Devuelve el rectángulo físico afectado."""
        v = self.ventana
        w, h, d = self._tam_imagen()
        if self._img is None or (self._img.width(), self._img.height()) != (w, h):
            self._img = QImage(w, h, QImage.Format_RGB32)
            self._img.setDevicePixelRatio(d)
            self._img.fill(QColor("#000000"))
            total = True
        img = self._img
        region = QRegion(0, 0, v.width(), v.height()) if total else QRegion(self._sucio)
        emergentes = self._rects_emergentes()
        # Lo que estaba tapado por un menú que se cerró o movió también se repinta.
        for r in self._popups_prev + [r for _, r in emergentes]:
            region = region.united(QRegion(r))
        self._popups_prev = [r for _, r in emergentes]
        visor = getattr(v, "visor_3d", None)
        vtk_visible = visor is not None and visor.vtk_widget.isVisible()
        rect_vtk = QRect()
        if vtk_visible:
            rect_vtk = QRect(visor.vtk_widget.mapTo(v, QPoint(0, 0)), visor.vtk_widget.size())
            if self._vtk_sucio or self._vtk_img is None:
                region = region.united(QRegion(rect_vtk))
        if region.isEmpty():
            return None
        self._renderizando = True
        try:
            p = QPainter(img)
            try:
                p.setClipRegion(region)
                if vtk_visible and region.intersects(rect_vtk):
                    # El 3D es una ventana nativa: Qt no la pinta en render(). Se coloca primero su
                    # imagen y encima la ventana, que no toca esa zona: el dock L.I.S. y los avisos
                    # (translúcidos) se mezclan con el 3D igual que en pantalla.
                    ahora = time.monotonic()
                    if self._vtk_img is None or self._vtk_sucio or ahora - self._vtk_t > 6.0:
                        self._vtk_sucio = False
                        self._vtk_t = ahora
                        _tv = time.perf_counter()
                        self._vtk_img = self._capturar_vtk(
                            int(round(rect_vtk.width() * d)), int(round(rect_vtk.height() * d))
                        )
                        self._n_vtk = getattr(self, "_n_vtk", 0) + 1
                        self._s_vtk = getattr(self, "_s_vtk", 0.0) + (time.perf_counter() - _tv) * 1000.0
                    if self._vtk_img is not None:
                        p.drawImage(rect_vtk, self._vtk_img)
                _tr = time.perf_counter()
                v.render(p, region.boundingRect().topLeft(), region)
                self._s_qt = getattr(self, "_s_qt", 0.0) + (time.perf_counter() - _tr) * 1000.0
                self._n_qt = getattr(self, "_n_qt", 0) + 1
                for tl, r in emergentes:
                    tl.render(p, r.topLeft())
            finally:
                p.end()
        finally:
            self._renderizando = False
        bb = region.boundingRect()
        x0, y0 = max(0, int(bb.left() * d) - 2), max(0, int(bb.top() * d) - 2)
        x1, y1 = min(w, int(round((bb.right() + 1) * d)) + 2), min(h, int(round((bb.bottom() + 1) * d)) + 2)
        return QRect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))

    def _codificar(self, img: QImage) -> bytes:
        img = img.convertToFormat(QImage.Format_BGR888)
        ancho, alto = img.width(), img.height()
        if cv2 is not None:
            arr = np.frombuffer(img.constBits(), dtype=np.uint8).reshape(alto, img.bytesPerLine())
            arr = arr[:, : ancho * 3].reshape(alto, ancho, 3)
            params = [int(cv2.IMWRITE_JPEG_QUALITY), CALIDAD_JPEG]
            try:
                params += [int(cv2.IMWRITE_JPEG_SAMPLING_FACTOR), int(cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444)]
            except Exception:
                pass
            ok, buf = cv2.imencode(".jpg", arr, params)
            if ok:
                return buf.tobytes()
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice

        ba = QByteArray()
        bf = QBuffer(ba)
        bf.open(QIODevice.WriteOnly)
        img.save(bf, "JPEG", CALIDAD_JPEG)
        return bytes(ba)

    def _tick(self) -> None:
        srv = self.servidor
        if not srv.conectado or self._pausado:
            return
        if srv.pendientes >= MAX_TRAMAS_EN_VUELO:
            # Cliente atascado: si no confirma en 4 s se libera para no bloquearse.
            if time.monotonic() - max(srv.ultimo_ack, self._ultimo_completo) > 4.0:
                srv.pendientes = 0
            return
        ahora = time.monotonic()
        if ahora - self._ultimo_completo >= 8.0:
            self._forzar_completo = True  # refresco periódico por si hubo pérdida
        total = self._sucio_total or self._forzar_completo
        hay_algo = total or not self._sucio.isEmpty() or self._vtk_sucio or bool(self._popups_prev)
        if not hay_algo:
            return
        self._sucio_total = False
        t_a = time.perf_counter()
        bb = self._componer(total)
        self._sucio = QRegion()
        if bb is None:
            return
        img = self._img
        t_comp = (time.perf_counter() - t_a) * 1000.0
        w, h = img.width(), img.height()
        arr = np.frombuffer(img.constBits(), dtype=np.uint32).reshape(h, img.bytesPerLine() // 4)[:, :w]
        previo = self._previo
        if self._forzar_completo or previo is None or previo.shape != arr.shape:
            region = QRect(0, 0, w, h)
            self._previo = arr.copy()
            self._ultimo_completo = ahora
            self._forzar_completo = False
        else:
            x0, y0, x1, y1 = bb.left(), bb.top(), bb.left() + bb.width(), bb.top() + bb.height()
            sub, ant = arr[y0:y1, x0:x1], previo[y0:y1, x0:x1]
            cambiado = sub != ant
            filas = np.flatnonzero(cambiado.any(axis=1))
            if filas.size == 0:
                return  # lo repintado quedó idéntico: nada que enviar
            cols = np.flatnonzero(cambiado.any(axis=0))
            region = QRect(x0 + int(cols[0]), y0 + int(filas[0]), int(cols[-1] - cols[0]) + 1, int(filas[-1] - filas[0]) + 1)
            np.copyto(ant, sub)
        parche = img.copy(region)
        t_b = time.perf_counter()
        jpeg = self._codificar(parche)
        t_enc = (time.perf_counter() - t_b) * 1000.0
        self._seq += 1
        cab = struct.pack("<BHHHHI", MSG_VIDEO, region.x(), region.y(), region.width(), region.height(), self._seq)
        srv.enviar_bytes(cab + jpeg, contar_ack=self._seq)
        e = self._est
        e["n"] += 1
        e["comp"] += t_comp
        e["enc"] += t_enc
        e["kb"] += len(jpeg) / 1024.0
        if ahora - self._t_log >= 20.0 and e["n"]:
            n = e["n"]
            log.info(
                "Flujo a la tablet: %.1f tramas/s · captura %.0f ms · JPEG %.0f ms · %.0f KB/trama · RTT cliente %.0f ms"
                " · Qt %.0f ms · VTK %.0f ms (%d)",
                n / (ahora - self._t_log), e["comp"] / n, e["enc"] / n, e["kb"] / n, srv.latencia_ms,
                getattr(self, "_s_qt", 0.0) / max(1, getattr(self, "_n_qt", 0)),
                getattr(self, "_s_vtk", 0.0) / max(1, getattr(self, "_n_vtk", 0)), getattr(self, "_n_vtk", 0),
            )
            self._s_qt = self._n_qt = self._s_vtk = self._n_vtk = 0
            self._est = {"n": 0, "comp": 0.0, "enc": 0.0, "kb": 0.0}
            self._t_log = ahora

    # ------------------------------------------------------------------
    # Entrada táctil
    # ------------------------------------------------------------------
    def _origen(self) -> QPoint:
        return self.ventana.mapToGlobal(QPoint(0, 0))

    def _objetivo_en(self, x: float, y: float) -> Tuple[Optional[QWidget], QPointF, QPointF]:
        """Widget bajo el punto (coordenadas lógicas de la ventana) con sus coords local/global."""
        v = self.ventana
        g = QPointF(self._origen()) + QPointF(x, y)
        gp = QPoint(int(g.x()), int(g.y()))
        candidatos: List[QWidget] = []
        pop = QApplication.activePopupWidget()
        if pop is not None:
            candidatos.append(pop)
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not pop:
            candidatos.append(modal)
        for tl in QApplication.topLevelWidgets():
            if tl is v or tl in candidatos or not tl.isVisible() or tl.windowType() == Qt.ToolTip:
                continue
            if tl.width() > 4 and tl.height() > 4 and tl.windowType() in (Qt.Popup, Qt.Dialog, Qt.Tool):
                candidatos.append(tl)
        for tl in candidatos:
            if tl.frameGeometry().contains(gp):
                loc = tl.mapFromGlobal(gp)
                hijo = tl.childAt(loc)
                w = hijo if hijo is not None else tl
                return w, QPointF(w.mapFromGlobal(gp)), g
        if pop is not None:
            pop.close()  # toque fuera de un menú desplegable: se cierra
            return None, QPointF(), g
        if modal is not None:
            return None, QPointF(), g
        hijo = v.childAt(int(x), int(y))
        w = hijo if hijo is not None else v
        return w, QPointF(w.mapFromGlobal(gp)), g

    def _enviar_raton(self, tipo: QEvent.Type, w: QWidget, x: float, y: float, boton: bool) -> None:
        _, loc, g = self._objetivo_en(x, y)
        loc = QPointF(w.mapFromGlobal(QPoint(int(g.x()), int(g.y()))))
        if tipo == QEvent.MouseButtonPress:
            b, bs = Qt.LeftButton, Qt.LeftButton
        elif tipo == QEvent.MouseButtonRelease:
            b, bs = Qt.LeftButton, Qt.NoButton
        else:
            b, bs = Qt.NoButton, Qt.LeftButton if boton else Qt.NoButton
        if tipo == QEvent.MouseButtonPress:
            self._dar_foco(w)
        ev = QMouseEvent(tipo, loc, g, b, bs, Qt.NoModifier)
        QApplication.sendEvent(w, ev)

    @staticmethod
    def _dar_foco(w: QWidget) -> None:
        """Qt sólo enfoca al hacer clic con eventos espontáneos; aquí se hace a mano."""
        x: Optional[QWidget] = w
        while x is not None and not x.isWindow():
            if x.isEnabled() and (x.focusPolicy() & Qt.ClickFocus):
                x.setFocus(Qt.MouseFocusReason)
                return
            x = x.parentWidget()

    def _marcar_hover(self, w: Optional[QWidget], activo: bool) -> None:
        """Simula el estado :hover/:pressed de QSS durante el toque (y lo quita al soltar)."""
        if activo:
            cadena: List[QWidget] = []
            x: Optional[QWidget] = w
            while x is not None and not x.isWindow():
                cadena.append(x)
                x = x.parentWidget()
            for o in cadena:
                o.setAttribute(Qt.WA_UnderMouse, True)
                o.update()
            self._hover = cadena
        else:
            for o in self._hover:
                try:
                    o.setAttribute(Qt.WA_UnderMouse, False)
                    o.update()
                except RuntimeError:
                    pass
            self._hover = []

    def _soltar_todo(self) -> None:
        for p in list(self._punteros.values()):
            if p.modo == "directo" and p.objetivo is not None:
                try:
                    self._enviar_raton(QEvent.MouseButtonRelease, p.objetivo, p.x, p.y, False)
                except Exception:
                    pass
        self._punteros.clear()
        self._marcar_hover(None, False)
        self._tim_fling.stop()
        self._fling = None

    def _on_puntero(self, m: dict) -> None:
        v = self.ventana
        lw, lh = v.width(), v.height()
        x, y = float(m["x"]) * lw, float(m["y"]) * lh
        fase, pid = m.get("ph"), int(m.get("id", 0))
        if fase == "down":
            self._tim_fling.stop()
            self._fling = None
            p = _Puntero(pid, x, y)
            self._punteros[pid] = p
            if len(self._punteros) >= 2:
                self._iniciar_pellizco()
                return
            w, _, _ = self._objetivo_en(x, y)
            p.objetivo = w
            if w is None:
                p.modo = "fin"
                return
            area = _area_desplazable(w)
            if area is not None and not _es_arrastre_directo(w):
                p.modo = "pendiente"
                p.area = area
            else:
                p.modo = "directo"
                self._marcar_hover(w, True)
                self._enviar_raton(QEvent.MouseButtonPress, w, x, y, True)
            return
        p = self._punteros.get(pid)
        if p is None:
            return
        if fase == "move":
            self._mover(p, x, y)
        elif fase in ("up", "cancel"):
            self._levantar(p, x, y, cancelar=(fase == "cancel"))

    def _mover(self, p: _Puntero, x: float, y: float) -> None:
        if len(self._punteros) >= 2:
            p.x, p.y = x, y
            self._actualizar_pellizco()
            return
        ahora = time.monotonic()
        dx, dy = x - p.x, y - p.y
        if p.modo == "pendiente":
            if math.hypot(x - p.x0, y - p.y0) > UMBRAL_TOQUE_PX:
                p.modo = "scroll"
                p.tx, p.ty = ahora, 0.0
                dx, dy = x - p.x0, y - p.y0
                self._scroll(p, dx, dy)
                p.x, p.y = x, y
                return
        elif p.modo == "scroll":
            dt = max(1e-3, ahora - p.tx)
            p.vx = 0.6 * p.vx + 0.4 * (dx / dt)
            p.vy = 0.6 * p.vy + 0.4 * (dy / dt)
            p.tx = ahora
            self._scroll(p, dx, dy)
        elif p.modo == "directo" and p.objetivo is not None:
            self._enviar_raton(QEvent.MouseMove, p.objetivo, x, y, True)
        p.x, p.y = x, y

    def _scroll(self, p: _Puntero, dx: float, dy: float) -> None:
        a = p.area
        if a is None:
            return
        a = self._area_con_recorrido(a, dx, dy)
        sbv, sbh = a.verticalScrollBar(), a.horizontalScrollBar()
        if sbv.maximum() > sbv.minimum():
            sbv.setValue(int(round(sbv.value() - dy)))
        if sbh.maximum() > sbh.minimum() and abs(dx) > abs(dy) * 0.6:
            sbh.setValue(int(round(sbh.value() - dx)))

    @staticmethod
    def _area_con_recorrido(a: QAbstractScrollArea, dx: float, dy: float) -> QAbstractScrollArea:
        """Si la zona interior ya está en su tope, cede el gesto a la zona exterior."""
        actual: Optional[QAbstractScrollArea] = a
        while actual is not None:
            sb = actual.verticalScrollBar()
            if sb.maximum() > sb.minimum():
                if (dy > 0 and sb.value() > sb.minimum()) or (dy < 0 and sb.value() < sb.maximum()):
                    return actual
            padre = actual.parentWidget()
            sig = _area_desplazable(padre) if padre is not None else None
            if sig is None:
                break
            actual = sig
        return a

    def _levantar(self, p: _Puntero, x: float, y: float, cancelar: bool) -> None:
        self._punteros.pop(p.id, None)
        if p.modo == "pendiente" and not cancelar and p.objetivo is not None:
            # Toque corto dentro de una lista: se entrega como clic completo.
            self._marcar_hover(p.objetivo, True)
            self._enviar_raton(QEvent.MouseButtonPress, p.objetivo, p.x0, p.y0, True)
            self._enviar_raton(QEvent.MouseButtonRelease, p.objetivo, p.x0, p.y0, False)
            self._marcar_hover(None, False)
        elif p.modo == "directo" and p.objetivo is not None:
            self._enviar_raton(QEvent.MouseButtonRelease, p.objetivo, x, y, False)
            self._marcar_hover(None, False)
        elif p.modo == "scroll" and p.area is not None and not cancelar:
            if abs(p.vy) > 250 or abs(p.vx) > 250:
                a = self._area_con_recorrido(p.area, p.vx, p.vy)
                self._fling = (a, p.vx, p.vy)
                self._tim_fling.start()
        if not self._punteros:
            self._pellizco_dist = 0.0

    def _tick_fling(self) -> None:
        if self._fling is None:
            self._tim_fling.stop()
            return
        a, vx, vy = self._fling
        dt = 0.016
        sbv, sbh = a.verticalScrollBar(), a.horizontalScrollBar()
        antes = (sbv.value(), sbh.value())
        if sbv.maximum() > sbv.minimum():
            sbv.setValue(int(round(sbv.value() - vy * dt)))
        if sbh.maximum() > sbh.minimum() and abs(vx) > abs(vy) * 0.6:
            sbh.setValue(int(round(sbh.value() - vx * dt)))
        vx *= 0.94
        vy *= 0.94
        if (abs(vx) < 25 and abs(vy) < 25) or (sbv.value(), sbh.value()) == antes:
            self._tim_fling.stop()
            self._fling = None
            return
        self._fling = (a, vx, vy)

    # ---- pellizco (zoom del visor 3D) -----------------------------------
    def _iniciar_pellizco(self) -> None:
        for p in self._punteros.values():
            if p.modo == "directo" and p.objetivo is not None:
                # Cancela el arrastre en curso sin disparar selección.
                self._enviar_raton(QEvent.MouseButtonRelease, p.objetivo, -9999, -9999, False)
            p.modo = "pellizco"
        self._marcar_hover(None, False)
        self._pellizco_dist = self._distancia_punteros()

    def _distancia_punteros(self) -> float:
        ps = list(self._punteros.values())
        if len(ps) < 2:
            return 0.0
        return math.hypot(ps[0].x - ps[1].x, ps[0].y - ps[1].y)

    def _actualizar_pellizco(self) -> None:
        d = self._distancia_punteros()
        if self._pellizco_dist <= 1.0 or d <= 1.0:
            self._pellizco_dist = d
            return
        ratio = d / self._pellizco_dist
        if abs(ratio - 1.0) < 0.015:
            return
        self._pellizco_dist = d
        visor = getattr(self.ventana, "visor_3d", None)
        ps = list(self._punteros.values())
        cx = sum(p.x for p in ps) / len(ps)
        cy = sum(p.y for p in ps) / len(ps)
        if visor is not None and visor.isVisible():
            o = visor.vtk_widget.mapTo(self.ventana, QPoint(0, 0))
            if QRect(o, visor.vtk_widget.size()).contains(int(cx), int(cy)):
                try:
                    visor._zoom(max(0.7, min(1.4, ratio)))
                except Exception:
                    log.exception("Zoom 3D")

    # ------------------------------------------------------------------
    # Teclado táctil de Android
    # ------------------------------------------------------------------
    def _campo_texto(self) -> Optional[QWidget]:
        w = self.ventana.focusWidget()
        app_w = QApplication.focusWidget()
        w = app_w or w
        if w is None or not w.isVisible() or not w.isEnabled():
            return None
        if isinstance(w, QAbstractSpinBox):
            return w.lineEdit()
        if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit)):
            if getattr(w, "isReadOnly", lambda: False)():
                return None
            return w
        return None

    @staticmethod
    def _texto_de(w: QWidget) -> str:
        if isinstance(w, QLineEdit):
            return w.text()
        return w.toPlainText()  # type: ignore[attr-defined]

    def _sincronizar_ime(self) -> None:
        if not self.servidor.conectado:
            return
        # La ventana vive fuera de la pantalla y Windows no la activa: Qt debe
        # considerarla activa para dibujar el foco y entregar el teclado.
        if QApplication.activeWindow() is None and self.ventana.isVisible():
            try:
                QApplication.setActiveWindow(self.ventana)
            except Exception:
                pass
        w = self._campo_texto()
        if w is None:
            if self._ime_firma is not None:
                log.info("IME off")
                self._ime_firma = None
                self._ime_texto_enviado = None
                self.servidor.enviar_json({"t": "ime", "on": False})
            return
        v = self.ventana
        o = w.mapTo(v, QPoint(0, 0))
        multilinea = not isinstance(w, QLineEdit)
        clave = (id(w), o.x(), o.y(), w.width(), w.height())
        texto = self._texto_de(w)
        pw = isinstance(w, QLineEdit) and w.echoMode() != QLineEdit.Normal
        numerico = isinstance(w.parentWidget(), QAbstractSpinBox)
        if clave != self._ime_firma:
            self._ime_firma = clave
            self._ime_texto_enviado = texto
            log.info("IME on: %s multi=%s", type(w).__name__, multilinea)
            self.servidor.enviar_json({
                "t": "ime", "on": True, "text": texto, "multi": multilinea, "pass": pw, "num": numerico,
                "r": [o.x() / v.width(), o.y() / v.height(), w.width() / v.width(), w.height() / v.height()],
            })
        elif texto != self._ime_texto_enviado:
            self._ime_texto_enviado = texto
            self.servidor.enviar_json({"t": "imetext", "text": texto})

    def _on_texto(self, m: dict) -> None:
        w = self._campo_texto()
        if w is None:
            return
        ini, borrar, ins = int(m.get("s", 0)), int(m.get("d", 0)), str(m.get("i", ""))
        if isinstance(w, QLineEdit):
            t = w.text()
            ini = max(0, min(ini, len(t)))
            w.setSelection(ini, min(borrar, len(t) - ini)) if borrar else w.setCursorPosition(ini)
            if borrar and not ins:
                w.del_()
            elif ins:
                w.insert(ins)
            self._ime_texto_enviado = w.text()
        else:
            from PySide6.QtGui import QTextCursor

            cur = w.textCursor()
            total = len(w.toPlainText())
            ini = max(0, min(ini, total))
            cur.setPosition(ini)
            cur.setPosition(min(total, ini + borrar), QTextCursor.KeepAnchor)
            cur.insertText(ins)
            w.setTextCursor(cur)
            self._ime_texto_enviado = w.toPlainText()

    def _on_tecla(self, m: dict) -> None:
        w = self._campo_texto() or QApplication.focusWidget() or self.ventana.focusWidget()
        if w is None:
            return
        mapa = {
            "Enter": Qt.Key_Return, "Backspace": Qt.Key_Backspace, "Tab": Qt.Key_Tab,
            "Escape": Qt.Key_Escape, "ArrowLeft": Qt.Key_Left, "ArrowRight": Qt.Key_Right,
            "ArrowUp": Qt.Key_Up, "ArrowDown": Qt.Key_Down, "Delete": Qt.Key_Delete,
        }
        k = mapa.get(str(m.get("k")))
        if k is None:
            return
        for tipo in (QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(w, QKeyEvent(tipo, k, Qt.NoModifier))
