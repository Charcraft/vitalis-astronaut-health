# -*- coding: utf-8 -*-
"""
scripts/demo_tour.py — Scripted guided tour of V.I.T.A.L.I.S. for recording a demo video.

Opens the real software full screen (light theme, no captions) on a throw-away database — your data
and settings are untouched — and walks through: the live Overview, the 3D body (all six systems,
ten organs, camera modes), guided measurement, and how the system reacts to a problem (yellow
warning → red alert with alarm, organ highlighting, alert panel, suggested protocol, emergency
protocols and ALSP animations, SBAR to Earth, Mission Control) before returning to normal.

    python scripts/demo_tour.py                       # starts immediately, exactly 2 minutes
    python scripts/demo_tour.py --go-file go.txt      # waits until go.txt exists (to sync a recorder)
    python scripts/demo_tour.py --windowed --fast 0.3 # quick dry run

Audio (BPM tone, alarm, L.I.S. voice) plays normally, so a desktop-audio capture records it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

REPO_URL = "github.com/Charcraft/vitalis-astronaut-health"
DURACION = 120  # seconds (exactly two minutes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--ready-file", default="", help="written when the window is up and warmed")
    ap.add_argument("--go-file", default="", help="tour starts when this file exists")
    ap.add_argument("--done-file", default="", help="written when the tour ends")
    ap.add_argument("--fast", type=float, default=1.0, help="time scale (0.3 = ~3x faster), for dry runs")
    args = ap.parse_args()

    import backend.database as bd

    tmp = tempfile.mkdtemp(prefix="vitalis-demo-")
    bd.DB_PATH = os.path.join(tmp, "demo.db")  # fresh database: seeded from the bundled OSD-575 data
    bd.init_db()

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QLabel

    from backend.database import atender_solicitud_ayuda, crear_solicitud_ayuda, listar_solicitudes_ayuda
    from backend.runtime import get_runtime
    from desktop.main_window import VentanaPrincipalVitalis

    app = QApplication(sys.argv[:1])
    v = VentanaPrincipalVitalis()
    if args.windowed:
        v.resize(1460, 900)
        v.show()
    else:
        v.showFullScreen()
    st = v.state
    st.actualizar_config(temaVisual="claro")

    # Title / closing cards (the only text overlays; no subtitles)
    tarjeta = QLabel(v)
    tarjeta.setWordWrap(True)
    tarjeta.setAlignment(Qt.AlignCenter)
    tarjeta.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    tarjeta.setStyleSheet("background: rgba(255,255,255,0.97); color: #0B0D10; padding: 40px;")
    tarjeta.hide()

    def titulo(html: str) -> None:
        tarjeta.setGeometry(0, 0, v.width(), v.height())
        tarjeta.setText(html)
        tarjeta.show()
        tarjeta.raise_()

    def quitar_titulo() -> None:
        tarjeta.hide()

    def seguro(fn):
        def _w():
            try:
                fn()
            except Exception as exc:  # the tour never stops because of one step
                print("paso fallido:", getattr(fn, "__name__", fn), exc, file=sys.stderr)
        return _w

    def repetir(fn, veces: int, cada_ms: int) -> None:
        for i in range(veces):
            QTimer.singleShot(int(i * cada_ms * args.fast), seguro(fn))

    def orbitar(dx: float = 14, n: int = 10, cada: int = 400):
        return lambda: repetir(lambda: v.visor_3d.orbitar(dx, 0), n, cada)

    def teclear(secuencia: str) -> None:
        for i, k in enumerate(secuencia):
            QTimer.singleShot(int(i * 450 * args.fast), seguro(lambda k=k: v.vista_medir._on_tecla(k)))

    def pedir_ayuda() -> None:
        crear_solicitud_ayuda(
            crew_id_solicitante="C003", destinatario="CMO_A_BORDO_C001", nivel="CRITICO",
            motivo="Oxygen saturation critically low",
            resumen_clinico="SpO2 below threshold; crew member reports shortness of breath.",
            protocolo_sugerido_id="respiratorio",
        )
        st.ayudaCambiada.emit()

    def atender_ayuda() -> None:
        for s in listar_solicitudes_ayuda(solo_activas=True):
            atender_solicitud_ayuda(int(s["id"]))
        st.ayudaCambiada.emit()

    def preguntar(texto: str) -> None:
        d = v.dock_lis
        if getattr(d, "_minimizado", False):
            d._toggle_minimizado()
        if not getattr(d, "_expandido", False):
            d._toggle_expandido()
        d.txt_input.setText(texto)
        d._enviar_consulta()

    def lis_replegar() -> None:
        d = v.dock_lis
        if getattr(d, "_expandido", False):
            d._toggle_expandido()
        if not getattr(d, "_minimizado", False):
            d._toggle_minimizado()

    def vista(p: str, **kw):
        return lambda: st.ir_a(p, **kw)

    def organo(nombre: str):
        return lambda: v._on_control_visor_3d("organo", nombre)

    def paso(i: int):
        return lambda: v.vista_emergencia._mostrar_paso(i)

    def equipo(eid: str):
        return lambda: v.vista_emergencia._seleccionar_equipo_anim(eid)

    def proto(pid: str):
        return lambda: st.ir_a("emergencia", protocoloId=pid)

    def metro():
        return lambda: v.vista_emergencia._toggle_metronomo()

    T: list = []

    def at(t: float, fn) -> None:
        T.append((t, fn))

    # ------------------------------------------------------------- 0:00 title + Overview
    at(0, lambda: titulo(
        "<div style='font-size:64px;font-weight:700;letter-spacing:6px'>V.I.T.A.L.I.S.</div>"
        "<div style='font-size:26px;margin-top:14px'>Vital Information Telemetry and Life-support In Space</div>"
        "<div style='font-size:22px;margin-top:26px;color:#5B6472'>Offline-first astronaut health monitoring</div>"))
    at(3, quitar_titulo)
    at(3, vista("inicio"))
    at(3.5, orbitar(12, 11, 420))

    # ------------------------------------------------------------- 3D body: systems, organs, camera
    at(8, vista("cuerpo"))
    sistemas = ["cardiovascular", "respiratorio", "neuro-ocular", "metabolico", "musculoesqueletico", "inmune-radiacion"]
    for i, s in enumerate(sistemas):
        at(8.3 + i * 2.2, (lambda s=s: st.set_sistema(s)))
        at(9.0 + i * 2.2, orbitar(10, 3, 330))
    organos = ["corazon", "pulmones", "higado", "riñones", "cerebro", "ojos", "estomago", "pancreas", "intestino", "huesos"]
    for i, o in enumerate(organos):
        at(21.5 + i * 1.3, organo(o))
    at(34.5, lambda: v.visor_3d.cambiar_modo_vista("lateral"))
    at(36, lambda: v.visor_3d.cambiar_modo_vista("capas"))
    at(37, lambda: repetir(lambda: v.visor_3d._zoom(1.12), 3, 250))

    # ------------------------------------------------------------- guided measurement
    at(38.5, vista("medir", indicadorId="glucose"))
    at(39.5, lambda: teclear("103"))
    at(42.5, lambda: v.vista_medir._registrar_lectura())

    # ------------------------------------------------------------- the system reacts to a problem
    at(46, vista("cuerpo"))
    at(46.2, lambda: st.set_sistema("cardiovascular"))
    at(47, lambda: get_runtime().forzar_anomalia("heart_rate", "ATENCION", duracion_ms=120000))   # yellow
    at(50, lambda: v._abrir_panel_avisos())
    at(53, lambda: v.panel_avisos.hide())
    at(54, lambda: get_runtime().forzar_anomalia("spo2", "CRITICO", duracion_ms=120000))          # red
    at(55, lambda: st.set_sistema("respiratorio"))
    at(60, lambda: v._abrir_panel_avisos())
    at(65, lambda: v._protocolo_desde_aviso("respiratorio"))

    # ------------------------------------------------------------- emergency protocols
    at(66, paso(0))
    at(69, paso(1))
    at(72, pedir_ayuda)                                    # SBAR to Earth
    at(74, proto("cardiovascular"))
    at(74.5, paso(0))
    at(76.5, metro())
    at(78, paso(1))
    at(81, metro())
    at(82, proto("neurologico"))
    at(82.5, paso(0))
    at(85, paso(1))
    at(87, proto("trauma"))
    at(87.5, paso(0))
    at(90, paso(1))
    at(92, equipo("dea"))
    at(94.5, equipo("iv"))
    at(97, equipo("via-aerea"))
    at(99.5, equipo("farmacos"))

    # ------------------------------------------------------------- assistant + Mission Control
    at(102, vista("cuerpo"))
    at(102.5, lambda: preguntar("Any anomalies?"))
    at(108, lis_replegar)
    at(108.2, vista("sala", panel="eventos"))
    at(110.2, lambda: v.vista_sala.seleccionar_panel("cola"))

    # ------------------------------------------------------------- back to normal + closing
    at(112, lambda: get_runtime().limpiar_anomalias())
    at(112, atender_ayuda)
    at(112.3, vista("salud_mental", seccion="pvt"))
    at(115, lambda: titulo(
        "<div style='font-size:46px;font-weight:700'>Measure · Compare · Decide · Act</div>"
        "<div style='font-size:26px;margin-top:22px'>26 parameters · 172-mesh 3D body · deterministic triage · 100% offline</div>"
        "<div style='font-size:24px;margin-top:22px;color:#5B6472'>38 automated tests · 29 views audited at touch size · MIT licence</div>"
        f"<div style='font-size:30px;margin-top:34px'>{REPO_URL}</div>"
        "<div style='font-size:18px;margin-top:26px;color:#5B6472'>Not a medical device · NASA OSDR OSD-575 · BodyParts3D / HRA (CC BY 4.0)</div>"))

    def lanzar() -> None:
        t0 = time.monotonic()
        print("tour: start")
        for seg, fn in T:
            QTimer.singleShot(int(seg * 1000 * args.fast), seguro(fn))

        def terminar() -> None:
            if args.done_file:
                open(args.done_file, "w").write(str(time.monotonic() - t0))
            print("tour: done", round(time.monotonic() - t0, 1), "s")
            sys.stdout.flush()
            QTimer.singleShot(1500, lambda: os._exit(0))  # skip VTK teardown (can crash on exit)

        QTimer.singleShot(int(DURACION * 1000 * args.fast), terminar)

    def esperar_go() -> None:
        if not args.go_file or os.path.exists(args.go_file):
            lanzar()
        else:
            QTimer.singleShot(100, esperar_go)

    def listo() -> None:
        st.ir_a("inicio")
        if args.ready_file:
            open(args.ready_file, "w").write("ready")
        esperar_go()

    QTimer.singleShot(5000, listo)  # warm-up: theme, 3D scene, runtime, first frames
    rc = app.exec()
    try:
        v._cerrar_recursos()
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)
    sys.stdout.flush()
    os._exit(rc)


if __name__ == "__main__":
    main()
