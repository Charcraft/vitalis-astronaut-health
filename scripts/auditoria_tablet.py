# -*- coding: utf-8 -*-
"""
scripts/auditoria_tablet.py — Auditoría de diseño y touch al tamaño de la tablet.

Abre la app REAL con el tamaño lógico de la tablet (por defecto 2000×1200 px a 1.5× →
1333×800), recorre todas las vistas y subpaneles y, en cada una:

  · guarda una captura PNG (la misma que recibe la tablet),
  · lista los controles táctiles menores de 44 px (objetivo mínimo para el dedo),
  · detecta controles interactivos que se solapan entre sí,
  · detecta controles cortados por el borde de la ventana o de su contenedor.

Uso:   python scripts/auditoria_tablet.py [--tam 2000x1200] [--dpr 1.5] [--salida logs/auditoria-tablet]
Sale con código 1 si hay solapes o controles cortados (los objetivos pequeños son avisos).
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import sys
import tempfile
import time
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MIN_TOQUE = 44  # px lógicos (≈ 7 mm a 160 dpi): mínimo cómodo para un dedo


def _escala_sistema() -> float:
    try:
        return max(1.0, ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0)
    except Exception:
        return 1.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tam", default="2000x1200")
    ap.add_argument("--dpr", type=float, default=1.5)
    ap.add_argument("--salida", default=os.path.join(ROOT, "logs", "auditoria-tablet"))
    ap.add_argument("--db", default="", help="BD alterna; por defecto una copia temporal")
    args = ap.parse_args()
    pw, ph = (int(v) for v in args.tam.lower().split("x"))

    os.environ.pop("QT_SCALE_FACTOR", None)
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    os.environ["QT_SCALE_FACTOR"] = f"{args.dpr / _escala_sistema():.6f}"

    import backend.database as bd

    tmp = tempfile.mkdtemp(prefix="vitalis-audit-")
    if args.db:
        bd.DB_PATH = os.path.abspath(args.db)
    else:
        origen = bd.DB_PATH
        bd.DB_PATH = os.path.join(tmp, "audit.db")
        if os.path.exists(origen):
            shutil.copyfile(origen, bd.DB_PATH)
    bd.init_db()

    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtWidgets import (
        QAbstractButton, QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication,
        QComboBox, QLabel, QLineEdit, QPlainTextEdit, QTextEdit, QWidget,
    )

    from desktop.main_window import VentanaPrincipalVitalis
    from tablet.bridge import PuenteTablet
    from tablet.server import ServidorRemoto

    app = QApplication(sys.argv[:1])
    v = VentanaPrincipalVitalis()
    lw, lh = max(1180, round(pw / args.dpr)), max(760, round(ph / args.dpr))
    v.setFixedSize(lw, lh)
    v.move(-(int(lw * app.primaryScreen().devicePixelRatio()) + 400), 0)
    v.showNormal()
    puente = PuenteTablet(v, ServidorRemoto(), tam_fisico=(pw, ph), dpr_cliente=args.dpr)
    puente._tim.stop()

    os.makedirs(args.salida, exist_ok=True)
    for f in os.listdir(args.salida):
        if f.endswith(".png"):
            os.remove(os.path.join(args.salida, f))

    def esperar(seg: float = 0.7) -> None:
        t0 = time.monotonic()
        while time.monotonic() - t0 < seg:
            app.processEvents()
            time.sleep(0.01)

    INTERACTIVOS = (QAbstractButton, QComboBox, QAbstractSlider, QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)

    def rect_ventana(w: QWidget) -> QRect:
        return QRect(w.mapTo(v, QPoint(0, 0)), w.size())

    def visible_real(w: QWidget) -> bool:
        return w.isVisibleTo(v) and w.isVisible() and w.width() > 2 and w.height() > 2

    def en_flotante(w: QWidget) -> bool:
        x = w
        while x is not None:
            if x is getattr(v, "dock_lis", None) or x is getattr(v, "panel_avisos", None) or x is getattr(v, "aviso_emergente", None):
                return True
            x = x.parentWidget()
        return False

    def recorte_visible(w: QWidget) -> QRect:
        """Rectángulo del control visto a través de sus áreas de desplazamiento."""
        r = rect_ventana(w)
        x = w.parentWidget()
        while x is not None and x is not v:
            if isinstance(x.parentWidget(), QAbstractScrollArea) and x.parentWidget().viewport() is x:
                r = r.intersected(rect_ventana(x))
            x = x.parentWidget()
        return r

    informe: List[str] = []
    problemas_graves = 0
    avisos_toque = 0

    def auditar(nombre: str) -> None:
        nonlocal problemas_graves, avisos_toque
        esperar(0.9)
        puente._img = None
        puente._componer(True)
        img = puente._img
        img.save(os.path.join(args.salida, f"{nombre}.png"))
        todos = [w for w in v.findChildren(QWidget) if isinstance(w, INTERACTIVOS) and visible_real(w) and not en_flotante(w)]
        # Los QLineEdit internos de un spinbox/combobox no cuentan aparte.
        todos = [w for w in todos if not (isinstance(w.parentWidget(), (QAbstractSpinBox, QComboBox)))]
        peq: List[str] = []
        solapes: List[str] = []
        cortes: List[str] = []
        for w in todos:
            r = recorte_visible(w)
            if r.width() < 2 or r.height() < 2:
                continue  # fuera de la zona visible de una lista desplazable
            etiqueta = (getattr(w, "text", lambda: "")() or w.objectName() or type(w).__name__)[:28]
            if isinstance(w, QAbstractButton) and w.isCheckable() is False and w.width() < MIN_TOQUE and w.height() < MIN_TOQUE and not etiqueta.strip():
                pass
            if min(w.width(), w.height()) < MIN_TOQUE and not isinstance(w, QAbstractSlider):
                peq.append(f"{etiqueta!r} {w.width()}×{w.height()}")
            full = rect_ventana(w)
            if full.right() > lw + 1 or full.bottom() > lh + 1 or full.left() < -1 or full.top() < -1:
                cortes.append(f"{etiqueta!r} fuera de la ventana {full.getRect()}")
        for i, a in enumerate(todos):
            ra = recorte_visible(a)
            if ra.width() < 2 or ra.height() < 2:
                continue
            for b in todos[i + 1:]:
                if a.isAncestorOf(b) or b.isAncestorOf(a):
                    continue
                rb = recorte_visible(b)
                inter = ra.intersected(rb)
                if inter.width() > 3 and inter.height() > 3:
                    na = (getattr(a, "text", lambda: "")() or type(a).__name__)[:22]
                    nb = (getattr(b, "text", lambda: "")() or type(b).__name__)[:22]
                    solapes.append(f"{na!r} ∩ {nb!r} en {inter.getRect()}")
        # Etiquetas que no caben (texto elidido o cortado).
        truncadas: List[str] = []
        for w in v.findChildren(QLabel):
            if not visible_real(w) or en_flotante(w) or w.wordWrap() or not w.text() or w.pixmap():
                continue
            if "<" in w.text():
                continue
            ancho = w.fontMetrics().horizontalAdvance(w.text())
            r = recorte_visible(w)
            if ancho > w.width() + 4 and r.width() >= w.width() - 2:
                truncadas.append(f"{w.text()[:30]!r} necesita {ancho}px, tiene {w.width()}px")
        problemas_graves += len(solapes) + len(cortes)
        avisos_toque += len(peq)
        informe.append(f"### {nombre}\n- controles interactivos: {len(todos)}")
        for titulo, lista in (("Solapes", solapes), ("Cortes", cortes), (f"Objetivos < {MIN_TOQUE}px", peq), ("Texto que no cabe", truncadas)):
            if lista:
                informe.append(f"- **{titulo}** ({len(lista)}):")
                informe.extend(f"  - {x}" for x in lista[:12])
        informe.append("")
        print(f"[{nombre}] controles={len(todos)} solapes={len(solapes)} cortes={len(cortes)} pequeños={len(peq)} truncados={len(truncadas)}")

    st = v.state
    # Vistas principales
    for pagina in ("inicio", "cuerpo", "medir", "historial", "emergencia", "lis"):
        st.ir_a(pagina)
        auditar(pagina)
    # Bienestar: cada submódulo
    st.ir_a("salud_mental")
    esperar(0.5)
    for sec in list(getattr(v.vista_salud_mental, "_orden_secciones", [])):
        v.vista_salud_mental.seleccionar_seccion(sec)
        auditar(f"bienestar-{sec}")
    # Sala de control: cada panel
    st.ir_a("sala")
    esperar(0.5)
    for panel in list(getattr(v.vista_sala, "_indice_paneles", {})):
        v.vista_sala.seleccionar_panel(panel)
        auditar(f"sala-{panel}")
    # Cuerpo 3D: cada sistema
    for sistema in ("cardiovascular", "respiratorio", "neuro-ocular", "metabolico", "musculoesqueletico", "inmune-radiacion"):
        st.set_sistema(sistema)
        st.ir_a("cuerpo")
        auditar(f"cuerpo-{sistema}")
    # Panel de L.I.S. abierto y panel de avisos
    st.ir_a("inicio")
    try:
        v.dock_lis.expandir() if hasattr(v.dock_lis, "expandir") else None
    except Exception:
        pass
    esperar(0.5)
    auditar("inicio-con-dock")
    v._abrir_panel_avisos()
    auditar("avisos-abiertos")
    v.panel_avisos.hide()

    ruta = os.path.join(args.salida, "informe.md")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(f"# Auditoría tablet {lw}×{lh} lógicos ({pw}×{ph} px @ {args.dpr}×)\n\n")
        f.write(f"- Solapes/cortes (graves): **{problemas_graves}**\n- Objetivos táctiles < {MIN_TOQUE}px (avisos): **{avisos_toque}**\n\n")
        f.write("\n".join(informe))
    print(f"\nInforme: {ruta}\nGraves: {problemas_graves} · Táctiles pequeños: {avisos_toque}")
    v._cerrar_recursos()
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if problemas_graves else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
