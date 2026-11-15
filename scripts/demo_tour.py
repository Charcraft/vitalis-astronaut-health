# -*- coding: utf-8 -*-
"""
scripts/demo_tour.py — Scripted guided tour of V.I.T.A.L.I.S. for recording a demo video.

Opens the real software full screen on a throw-away database (your data and settings are untouched),
walks through every major function with English captions, and exits. It drives the same objects a
user would (navigation, keypad, alerts, assistant, protocols, Mission Control, Wellbeing, themes).

    python scripts/demo_tour.py                       # starts immediately, ~2 minutes
    python scripts/demo_tour.py --go-file go.txt      # waits until go.txt exists (to sync a recorder)
    python scripts/demo_tour.py --windowed            # no full screen

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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--ready-file", default="", help="written when the window is up and warmed")
    ap.add_argument("--go-file", default="", help="tour starts when this file exists")
    ap.add_argument("--done-file", default="", help="written when the tour ends")
    ap.add_argument("--fast", type=float, default=1.0, help="time scale (0.5 = twice as fast), for dry runs")
    args = ap.parse_args()

    import backend.database as bd

    tmp = tempfile.mkdtemp(prefix="vitalis-demo-")
    bd.DB_PATH = os.path.join(tmp, "demo.db")  # fresh database: seeded from the bundled OSD-575 data
    bd.init_db()

    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtGui import QFont
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

    # ---------------------------------------------------------------- captions
    caja = QLabel(v)
    caja.setWordWrap(True)
    caja.setAlignment(Qt.AlignCenter)
    caja.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    caja.setStyleSheet("background: rgba(34,38,48,0.95); color: #F2F4F8; border: 1px solid #4A5366; border-radius: 14px; padding: 14px 26px;")
    caja.setFont(QFont("Segoe UI", 21, QFont.DemiBold))
    caja.hide()
    tarjeta = QLabel(v)
    tarjeta.setWordWrap(True)
    tarjeta.setAlignment(Qt.AlignCenter)
    tarjeta.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    tarjeta.setStyleSheet("background: rgba(7,8,10,0.94); color: #F2F4F8; padding: 40px;")
    tarjeta.hide()

    def pos_capas() -> None:
        w, h = v.width(), v.height()
        caja.setGeometry(int(w * 0.07), h - 190, int(w * 0.62), 92)
        tarjeta.setGeometry(0, 0, w, h)

    def subtitulo(txt: str) -> None:
        pos_capas()
        caja.setText(txt)
        caja.show()
        caja.raise_()

    def titulo(html: str) -> None:
        pos_capas()
        tarjeta.setText(html)
        tarjeta.show()
        tarjeta.raise_()

    def quitar_titulo() -> None:
        tarjeta.hide()

    # ---------------------------------------------------------------- acciones
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

    def orbitar() -> None:
        v.visor_3d.orbitar(14, 0)

    def teclear(secuencia: str) -> None:
        for i, k in enumerate(secuencia):
            QTimer.singleShot(int(i * 450 * args.fast), seguro(lambda k=k: v.vista_medir._on_tecla(k)))

    sbar = {"id": None}

    def pedir_ayuda() -> None:
        r = crear_solicitud_ayuda(
            crew_id_solicitante="C001", destinatario="CMO_A_BORDO_C001", nivel="CRITICO",
            motivo="Oxygen saturation critically low", resumen_clinico="SpO2 below threshold; crew member reports shortness of breath.",
            protocolo_sugerido_id="respiratorio",
        )
        sbar["id"] = (r or {}).get("id")
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

    # ---------------------------------------------------------------- guion (segundos desde el inicio)
    T = [
        (0, lambda: titulo(
            "<div style='font-size:64px;font-weight:700;letter-spacing:6px'>V.I.T.A.L.I.S.</div>"
            "<div style='font-size:26px;margin-top:14px'>Vital Information Telemetry and Life-support In Space</div>"
            "<div style='font-size:22px;margin-top:26px;color:#9AA3B2'>Offline-first astronaut health monitoring · NASA Space Apps · Team ROCKET</div>")),
        (5, quitar_titulo),
        (5, vista("inicio")),
        (5.5, lambda: subtitulo("Overview · live vitals with waveforms, a heartbeat tone that follows the BPM, and a 3D body of 172 meshes")),
        (8, lambda: repetir(orbitar, 14, 400)),
        (15, vista("cuerpo")),
        (15.5, lambda: subtitulo("3D Body · six systems, organs you can touch, traffic-light status from NASA OSD-575 baselines")),
        (17, lambda: st.set_sistema("cardiovascular")),
        (20, lambda: st.set_sistema("respiratorio")),
        (23, lambda: st.set_sistema("neuro-ocular")),
        (25, lambda: v.visor_3d.cambiar_modo_vista("lateral")),
        (27, lambda: v.visor_3d.cambiar_modo_vista("capas")),
        (29, vista("medir", indicadorId="glucose")),
        (29.5, lambda: subtitulo("Measure · how to take it in microgravity, touch keypad, deterministic triage with a cited rule")),
        (32, lambda: teclear("103")),
        (35.5, lambda: v.vista_medir._registrar_lectura()),
        (40, vista("historial", paramId="glucose")),
        (40.5, lambda: subtitulo("History · each astronaut's own trajectory from real NASA flight data (L-92 to R+194)")),
        (47, lambda: get_runtime().forzar_anomalia("spo2", "CRITICO", duracion_ms=34000)),
        (47.2, vista("cuerpo")),
        (47.5, lambda: subtitulo("Red state · affected organs pulse in triage colour, a soft intermittent alarm sounds, guidance stays calm")),
        (53, lambda: v._abrir_panel_avisos()),
        (57, lambda: v.panel_avisos.hide()),
                (60.5, lambda: subtitulo("L.I.S. · on-board assistant: grounded on local data, never invents a number, controls the whole app")),
        (62, lambda: preguntar("Any anomalies?")),
        (70, lambda: preguntar("Show me the lungs")),
        (74, lambda: get_runtime().limpiar_anomalias()),
        (74, lis_replegar),
        (74.5, vista("emergencia", protocoloId="respiratorio")),
        (75, lambda: subtitulo("Emergency · step-by-step protocol, procedural animations, CPR metronome and an SBAR report to Earth")),
        (78, lambda: v.vista_emergencia._toggle_metronomo()),
        (82, pedir_ayuda),
        (86, lambda: v.vista_emergencia._toggle_metronomo()),
        (86.5, atender_ayuda),
        (88, vista("sala", panel="vivo")),
        (88.5, lambda: subtitulo("Mission Control · crew stations at 1 Hz, scenarios, events, mission log and the prioritised Earth queue")),
        (91, lambda: v.vista_sala.seleccionar_panel("escenario")),
        (94, lambda: v.vista_sala.seleccionar_panel("eventos")),
        (97, lambda: v.vista_sala.seleccionar_panel("cola")),
        (100, vista("salud_mental", seccion="bitacora")),
        (100.5, lambda: subtitulo("Wellbeing · NASA behavioral health: logbook, PVT-B reaction test, sleep, decompression, Earth link")),
        (103, lambda: v.vista_salud_mental.seleccionar_seccion("pvt")),
        (106, lambda: v.vista_salud_mental.seleccionar_seccion("descompresion")),
        (109, vista("lis")),
        (109.5, lambda: subtitulo("Settings · dark and light themes, English and Spanish, voice, alarm and assistant options")),
        (111, lambda: st.actualizar_config(temaVisual="claro")),
        (114, lambda: st.actualizar_config(temaVisual="oscuro")),
        (115.5, lambda: caja.hide()),
        (115.5, lambda: titulo(
            "<div style='font-size:46px;font-weight:700'>Measure · Compare · Decide · Act</div>"
            "<div style='font-size:26px;margin-top:22px'>26 parameters · 172-mesh 3D body · deterministic triage · 100% offline</div>"
            "<div style='font-size:24px;margin-top:22px;color:#9AA3B2'>38 automated tests · 29 views audited at touch size · MIT licence</div>"
            f"<div style='font-size:30px;margin-top:34px'>{REPO_URL}</div>"
            "<div style='font-size:18px;margin-top:26px;color:#9AA3B2'>Not a medical device · NASA OSDR OSD-575 · BodyParts3D / HRA (CC BY 4.0)</div>")),
    ]

    def lanzar() -> None:
        t0 = time.monotonic()
        print("tour: start")
        for seg, fn in T:
            QTimer.singleShot(int(seg * 1000 * args.fast), seguro(fn))
        fin = 122 * args.fast

        def terminar() -> None:
            if args.done_file:
                open(args.done_file, "w").write(str(time.monotonic() - t0))
            print("tour: done", round(time.monotonic() - t0, 1), "s")
            sys.stdout.flush()
            QTimer.singleShot(1500, lambda: os._exit(0))  # skip VTK teardown (can crash on exit)

        QTimer.singleShot(int(fin * 1000), terminar)

    def esperar_go() -> None:
        if not args.go_file or os.path.exists(args.go_file):
            lanzar()
        else:
            QTimer.singleShot(100, esperar_go)

    def listo() -> None:
        pos_capas()
        st.ir_a("inicio")
        if args.ready_file:
            open(args.ready_file, "w").write("ready")
        esperar_go()

    QTimer.singleShot(4000, listo)  # warm-up: 3D scene, runtime, first frames
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
