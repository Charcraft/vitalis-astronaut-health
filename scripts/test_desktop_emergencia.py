# -*- coding: utf-8 -*-
"""Prueba de integración de la animación ALSP en VistaEmergencia (PySide6)."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.database import init_db  # noqa: E402

init_db()

from PySide6.QtWidgets import QApplication  # noqa: E402

from desktop import theme as t  # noqa: E402
from desktop.state import AppState  # noqa: E402
from desktop.views import VistaEmergencia  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(t.QSS)
    vista = VistaEmergencia(AppState())
    vista.resize(1460, 800)
    vista.show()
    for _ in range(3):
        app.processEvents()

    out_dir = os.path.join(ROOT, "logs")
    os.makedirs(out_dir, exist_ok=True)

    for pid in ("cardiovascular", "respiratorio", "trauma", "neurologico"):
        vista.seleccionar_protocolo(pid)
        app.processEvents()
        estados = []
        for i in range(len(vista._botones_pasos)):
            vista._mostrar_paso(i)
            app.processEvents()
            estados.append(
                f"{i + 1}:{vista.anim.equipo_id}/{vista.anim.acto + 1}"
                if vista.anim.isVisible()
                else f"{i + 1}:sin-animacion"
            )
        print(pid, "->", ", ".join(estados))

    vista.seleccionar_protocolo("cardiovascular")
    vista._mostrar_paso(2)
    for _ in range(3):
        app.processEvents()
    path = os.path.join(out_dir, "emergencia_desktop.png")
    vista.grab().save(path)
    print("captura:", path)

    vista.resize(1180, 760)
    for _ in range(4):
        app.processEvents()
    path_small = os.path.join(out_dir, "emergencia_desktop_1180.png")
    vista.grab().save(path_small)
    print("captura pequeña:", path_small)

    from PySide6.QtTest import QTest

    img1 = vista.anim.grab().toImage()
    QTest.qWait(700)
    img2 = vista.anim.grab().toImage()
    print("animacion_cambia:", img1 != img2)
    vista.close()


if __name__ == "__main__":
    main()
