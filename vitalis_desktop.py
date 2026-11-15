# -*- coding: utf-8 -*-
"""
vitalis_desktop.py — Aplicación Nativa de Escritorio para PC (Sin navegador web)
de V.I.T.A.L.I.S. (Vital Information Telemetry and Life-support In Space)
y su Agente Autónomo L.I.S. (Life-support In Space).

Stack 100% Nativo en Python:
  - Interfaz gráfica nativa: PySide6 (Qt6 C++) con tema oscuro monocromático
  - Motor Anatómico 3D nativo: VTK 9.7 OpenGL (128 estructuras reales de BodyParts3D)
  - Base de datos local: SQLite WAL (data/vitalis.db) con NASA OSDR OSD-575
  - Voz clonada real JARVIS: XTTS v2 en GPU (127.0.0.1:8795) + sounddevice nativo
  - Reconocimiento de voz offline: faster-whisper + sounddevice
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import socket
import subprocess
import sys
import threading

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.database import init_db
from desktop import __version__

XTTS_PORT = 8795
BACKEND_PORT = 8780
log = logging.getLogger("vitalis")


def setup_logging() -> None:
    logs_dir = os.path.join(ROOT_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.FileHandler(
        os.path.join(logs_dir, "vitalis-native.log"), encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)


def is_port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def raise_existing_window() -> bool:
    if os.name != "nt":
        return False
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _lp):
            if not user32.IsWindowVisible(hwnd):
                return True
            cls_buf = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, cls_buf, 128)
            if not cls_buf.value.startswith("Qt"):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "V.I.T.A.L.I.S." in buf.value:
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(_cb, 0)
        if found:
            user32.ShowWindow(found[0], 9)
            user32.SetForegroundWindow(found[0])
            return True
    except Exception:
        pass
    return False


def ensure_jarvis_xtts_server() -> None:
    """Optional local voice-clone server (XTTS v2).

    Not part of this repository. To use it, point VITALIS_XTTS_SERVER_SCRIPT to your own
    server script (and optionally VITALIS_XTTS_PYTHON to its interpreter). Without it the
    app speaks with edge-tts or the offline Windows SAPI voice.
    """
    script_path = os.environ.get("VITALIS_XTTS_SERVER_SCRIPT", "")
    if not script_path or not os.path.exists(script_path) or is_port_open("127.0.0.1", XTTS_PORT):
        return
    py_bin = os.environ.get("VITALIS_XTTS_PYTHON", sys.executable)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        subprocess.Popen([py_bin, script_path], cwd=ROOT_DIR, creationflags=creationflags)
    except Exception as exc:
        log.warning("Could not start the optional XTTS server: %s", exc)


def start_api_server_background() -> None:
    if is_port_open("127.0.0.1", BACKEND_PORT):
        return

    def _run() -> None:
        try:
            import uvicorn
            from backend.server import app

            uvicorn.run(app, host="127.0.0.1", port=BACKEND_PORT, log_level="warning")
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="vitalis-api").start()


def _normalizar_escala_ui(escala: object) -> str:
    txt = str(escala or "1.0").strip()
    if txt in ("1", "1.0", "1.00"):
        return "1.0"
    if txt in ("1.15", "1.3"):
        return txt
    try:
        val = min((1.0, 1.15, 1.3), key=lambda x: abs(x - float(txt)))
        return {1.0: "1.0", 1.15: "1.15", 1.3: "1.3"}[val]
    except Exception:
        return "1.0"


def aplicar_escala_entorno(escala: object, forzar: bool = False) -> str:
    """Sincroniza QT_SCALE_FACTOR y VITALIS_ESCALA_APLICADA antes de QApplication."""
    esc = _normalizar_escala_ui(escala)
    gestionado = (
        forzar
        or ("VITALIS_ESCALA_APLICADA" in os.environ)
        or ("--reinicio" in sys.argv)
    )
    if esc == "1.0":
        if gestionado:
            os.environ.pop("QT_SCALE_FACTOR", None)
    elif gestionado or "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = esc
    os.environ["VITALIS_ESCALA_APLICADA"] = esc
    return esc


def main() -> None:
    try:
        logs_dir = os.path.join(ROOT_DIR, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        if sys.stdout is None:
            sys.stdout = open(
                os.path.join(logs_dir, "vitalis-stdout.log"),
                "a",
                encoding="utf-8",
                errors="replace",
            )
        if sys.stderr is None:
            sys.stderr = open(
                os.path.join(logs_dir, "vitalis-stderr.log"),
                "a",
                encoding="utf-8",
                errors="replace",
            )
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="V.I.T.A.L.I.S. Native PC Application")
    parser.add_argument("--version", action="version", version=f"V.I.T.A.L.I.S. {__version__}")
    parser.add_argument("--test-init", action="store_true", help="Verifica carga e inicialización")
    parser.add_argument(
        "--reinicio", action="store_true", help="Lanzada desde Ajustes: espera a que cierre la anterior"
    )
    args = parser.parse_args()

    if args.reinicio:
        # La instancia que pidió el reinicio todavía tiene el mutex de instancia única.
        import time

        time.sleep(2.0)

    setup_logging()

    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ROCKET.VITALIS.NativeDesktop.1"
            )
        except Exception:
            pass
        if not args.test_init:
            mutex_name = "VITALIS_NATIVE_QT_MUTEX_2026"
            ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
            if ctypes.windll.kernel32.GetLastError() == 183:
                if raise_existing_window():
                    sys.exit(0)

    init_db()
    ensure_jarvis_xtts_server()
    start_api_server_background()

    # Tamaño del texto elegido en Ajustes: Qt sólo lo lee antes de crear la app.
    from backend.database import obtener_config_lis

    aplicar_escala_entorno(obtener_config_lis().get("escalaUI", "1.0"))

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from desktop.main_window import VentanaPrincipalVitalis, ruta_icono_app

    app = QApplication(sys.argv)
    app.setApplicationName("V.I.T.A.L.I.S.")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("NASA Space Apps · Equipo ROCKET")
    ruta_ico = ruta_icono_app()
    if os.path.exists(ruta_ico):
        app.setWindowIcon(QIcon(ruta_ico))

    ventana = VentanaPrincipalVitalis()
    ventana.showNormal()
    ventana.raise_()
    ventana.activateWindow()
    if os.name == "nt":
        try:
            ctypes.windll.user32.ShowWindow(int(ventana.winId()), 5)
            ctypes.windll.user32.SetForegroundWindow(int(ventana.winId()))
        except Exception:
            pass

    if args.test_init:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1200, ventana.close)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
