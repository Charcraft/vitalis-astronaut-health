# -*- coding: utf-8 -*-
"""
vitalis_tablet.py — V.I.T.A.L.I.S. en la tablet (pantalla remota táctil).

Arranca la MISMA aplicación de escritorio (PySide6 + VTK + SQLite + L.I.S.),
pero su ventana se renderiza a la resolución de la tablet Android y se
muestra en Chrome por USB. Touch, teclado, sonido y micrófono son los de la
tablet. No se pierde ninguna función ni cambia el diseño.

    python vitalis_tablet.py              # detecta la tablet por ADB y la conecta
    python vitalis_tablet.py --lan        # además escucha en la red local (sin USB)
    python vitalis_tablet.py --mostrar-en-pc   # deja la ventana visible en la PC
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from tablet import PUERTO  # noqa: E402

log = logging.getLogger("vitalis.tablet")
ENV_FLAGS = "VITALIS_TABLET_FLAGS"


def _escala_sistema() -> float:
    """Escala de Windows del monitor principal (1.0, 1.25, 1.5…) antes de crear Qt."""
    try:
        return max(1.0, ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0)
    except Exception:
        return 1.0


def _parsear(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="V.I.T.A.L.I.S. en tablet Android (pantalla remota táctil)")
    ap.add_argument("--lan", action="store_true", help="Escuchar también en la red local (por defecto sólo USB/localhost)")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--mostrar-en-pc", action="store_true", help="Mostrar la ventana de la app en la PC (por defecto queda invisible)")
    ap.add_argument("--sin-adb", action="store_true", help="No usar ADB (abrir http://IP:%d a mano)" % PUERTO)
    ap.add_argument("--tam", default="", help="Forzar resolución de la tablet, p. ej. 2000x1200")
    ap.add_argument("--dpr", type=float, default=0.0, help="Forzar densidad de la tablet (1.5 = 240 dpi)")
    ap.add_argument("--db", default="", help="Ruta alterna de SQLite (pruebas)")
    ap.add_argument("--test-init", action="store_true", help="Arranca, comprueba el puente y sale")
    ap.add_argument("--reinicio", action="store_true", help="Relanzada desde Ajustes")
    return ap.parse_args(argv)


def main() -> None:
    # Reinicio desde Ajustes: recupera las opciones originales.
    argv = sys.argv[1:]
    if "--reinicio" in argv and os.environ.get(ENV_FLAGS):
        argv = os.environ[ENV_FLAGS].split("\x1f") + ["--reinicio"]
    else:
        os.environ[ENV_FLAGS] = "\x1f".join(a for a in argv if a != "--reinicio")
    args = _parsear(argv)

    logs_dir = os.path.join(ROOT_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(os.path.join(logs_dir, "vitalis-tablet.log"), encoding="utf-8"), logging.StreamHandler()],
    )

    if args.reinicio:
        import time

        time.sleep(2.0)

    # --- Tablet: resolución y densidad reales (ADB) ---------------------
    from tablet import adb

    tab = None if args.sin_adb else adb.info_tablet()
    pw, ph, dpr = 2000, 1200, 1.5
    if tab:
        pw, ph, dpr = int(tab["pw"]), int(tab["ph"]), float(tab["dpr"])
        log.info("Tablet detectada: %s %dx%d @%.2fx (%s)", tab["modelo"], pw, ph, dpr, tab["serie"])
    elif not args.sin_adb:
        log.warning("No hay tablet autorizada por ADB; se usan %dx%d @%.1fx. Conéctala y acepta la depuración USB.", pw, ph, dpr)
    if args.tam and "x" in args.tam:
        pw, ph = (int(v) for v in args.tam.lower().split("x"))
    if args.dpr:
        dpr = args.dpr

    # Qt debe ver exactamente la densidad de la tablet: el texto y el 3D salen
    # nítidos, sin remuestrear. Se fija antes de crear QApplication.
    sys_scale = _escala_sistema()
    os.environ.pop("QT_SCALE_FACTOR", None)
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    os.environ["QT_SCALE_FACTOR"] = f"{dpr / sys_scale:.6f}"
    os.environ["VITALIS_ESCALA_APLICADA"] = "1.0"

    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ROCKET.VITALIS.Tablet.1")
        except Exception:
            pass

    if not args.db and os.name == "nt":
        # Misma base SQLite y mismo runtime 1 Hz: no se abren la app de escritorio y la de tablet a la vez.
        k32 = ctypes.windll.kernel32
        k32.SetLastError(0)
        k32.CreateMutexW(None, False, "VITALIS_NATIVE_QT_MUTEX_2026")
        if k32.GetLastError() == 183 and not args.reinicio:
            msg = "V.I.T.A.L.I.S. ya está abierta en la PC. Ciérrala y vuelve a lanzar la versión de tablet."
            log.error(msg)
            print(msg)
            sys.exit(2)

    if args.db:
        import backend.database as bd

        bd.DB_PATH = os.path.abspath(args.db)

    import vitalis_desktop as vd

    from backend.database import init_db

    init_db()
    if not args.db:
        vd.ensure_jarvis_xtts_server()
        vd.start_api_server_background()

    from PySide6.QtCore import QProcess, QTimer, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from desktop import __version__
    from desktop.main_window import VentanaPrincipalVitalis, ruta_icono_app

    app = QApplication(sys.argv[:1])
    app.setApplicationName("V.I.T.A.L.I.S. Tablet")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("NASA Space Apps · Equipo ROCKET")
    ico = ruta_icono_app()
    if os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))

    # «Reiniciar» desde Ajustes relanza ESTE lanzador, no el de escritorio.
    orig_detached = QProcess.startDetached

    def _detached(programa, argumentos=None, *a, **k):
        return orig_detached(sys.executable, [os.path.abspath(__file__), "--reinicio"])

    QProcess.startDetached = staticmethod(_detached)  # type: ignore[method-assign]

    from tablet import audio_bridge
    from tablet.bridge import PuenteTablet
    from tablet.server import ServidorRemoto

    servidor = ServidorRemoto(host="0.0.0.0" if args.lan else "127.0.0.1", puerto=args.puerto)
    audio_bridge.activar(servidor)

    ventana = VentanaPrincipalVitalis()
    lw, lh = max(1180, round(pw / dpr)), max(760, round(ph / dpr))
    ventana.setMinimumSize(lw, lh)
    ventana.setMaximumSize(lw, lh)
    ventana.resize(lw, lh)
    ventana.move(0, 0)
    if not args.mostrar_en_pc:
        # Qt sólo pinta (y VTK sólo renderiza) una ventana «expuesta». Por eso no se saca de la
        # pantalla: se deja invisible (opacidad ≈ 0), sin foco y transparente a los clics, de modo
        # que no tapa ni estorba la PC pero sigue viva para capturarla.
        ventana.setWindowFlag(Qt.WindowTransparentForInput, True)
        ventana.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        ventana.setWindowOpacity(0.01)
    ventana.showNormal()

    puente = PuenteTablet(ventana, servidor, tam_fisico=(pw, ph), dpr_cliente=dpr)
    servidor.iniciar()
    log.info(
        "Pantalla remota lista en http://%s:%d (ventana %dx%d lógicos, DPR Qt %.2f)",
        "0.0.0.0" if args.lan else "localhost", args.puerto, lw, lh, ventana.devicePixelRatioF(),
    )

    if tab and not args.sin_adb:
        QTimer.singleShot(600, lambda: adb.conectar_usb(str(tab["serie"]), args.puerto))

        def _abrir_si_falta() -> None:
            # Si la página ya estaba abierta en la tablet se reconecta sola: no se duplican pestañas.
            if not servidor.conectado:
                adb.abrir_pagina(str(tab["serie"]), args.puerto)

        QTimer.singleShot(7000, _abrir_si_falta)

    # Windows detiene el pintado de una ventana minimizada: se restaura sola.
    def _vigilar() -> None:
        if ventana.isMinimized():
            ventana.showNormal()

    vig = QTimer(ventana)
    vig.timeout.connect(_vigilar)
    vig.start(1500)

    if args.test_init:
        QTimer.singleShot(4000, ventana.close)

    rc = app.exec()
    servidor.detener()
    sys.exit(rc)


if __name__ == "__main__":
    main()
