# -*- coding: utf-8 -*-
"""
tests/test_tablet.py — Pruebas del puente de tablet (touch, texto, audio, protocolo).

Se ejecutan sin tablet y sin GPU: Qt en modo `offscreen` y un servidor falso.
    python -m unittest tests/test_tablet.py -v
"""

from __future__ import annotations

import os
import struct
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
from PySide6.QtWidgets import (
    QApplication, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from tablet import audio_bridge
from tablet.bridge import PuenteTablet
from tablet.server import MSG_AUDIO, MSG_AUDIO_STOP, PROTOCOLO, ServidorRemoto

_app = QApplication.instance() or QApplication([])


class _ServidorFalso:
    """Lo mínimo que usan el puente y el audio."""

    def __init__(self) -> None:
        self.conectado = True
        self.pendientes = 0
        self.ultimo_ack = 0.0
        self.latencia_ms = 0.0
        self.enviados_bytes: list[bytes] = []
        self.enviados_json: list[dict] = []
        self.al_mensaje = lambda m: None
        self.al_mic = lambda b: None
        self.al_conectar = lambda: None
        self.al_desconectar = lambda: None

    def enviar_bytes(self, datos: bytes, contar_ack=None) -> None:
        self.enviados_bytes.append(datos)

    def enviar_json(self, o: dict) -> None:
        self.enviados_json.append(o)


def _pump(seg: float = 0.05) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < seg:
        _app.processEvents()
        time.sleep(0.005)


class PuenteTactilTest(unittest.TestCase):
    def setUp(self) -> None:
        self.v = QWidget()
        self.v.resize(800, 600)
        lay = QVBoxLayout(self.v)
        self.clics = 0
        self.btn = QPushButton("Pulsar")
        self.btn.setFixedHeight(60)
        self.btn.clicked.connect(self._clic)
        lay.addWidget(self.btn)
        # Lista desplazable con un botón al principio de contenido alto.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        cont = QWidget()
        cl = QVBoxLayout(cont)
        self.clics_lista = 0
        self.btn_lista = QPushButton("En lista")
        self.btn_lista.setFixedHeight(60)
        self.btn_lista.clicked.connect(lambda: setattr(self, "clics_lista", self.clics_lista + 1))
        cl.addWidget(self.btn_lista)
        for i in range(40):
            f = QPushButton(f"fila {i}")
            f.setFixedHeight(60)
            cl.addWidget(f)
        self.scroll.setWidget(cont)
        lay.addWidget(self.scroll, 1)
        self.campo = QLineEdit()
        lay.addWidget(self.campo)
        self.nota = QPlainTextEdit()
        lay.addWidget(self.nota)
        self.v.show()
        _pump(0.15)
        self.srv = _ServidorFalso()
        self.puente = PuenteTablet(self.v, self.srv, minimo_logico=(100, 100))
        self.puente._tim.stop()
        self.puente._tim_ime.stop()

    def tearDown(self) -> None:
        self.puente._tim_fling.stop()
        self.v.close()

    def _clic(self) -> None:
        self.clics += 1

    def _norm(self, w: QWidget, dx: float = 0.5, dy: float = 0.5) -> tuple[float, float]:
        p = w.mapTo(self.v, w.rect().topLeft())
        return (p.x() + w.width() * dx) / self.v.width(), (p.y() + w.height() * dy) / self.v.height()

    def _ptr(self, fase: str, w: QWidget, pid: int = 1, dx: float = 0.5, dy: float = 0.5) -> None:
        x, y = self._norm(w, dx, dy)
        self.puente._on_mensaje({"t": "ptr", "ph": fase, "id": pid, "x": x, "y": y})
        _pump(0.01)

    def test_toque_pulsa_un_boton(self) -> None:
        self._ptr("down", self.btn)
        self._ptr("up", self.btn)
        self.assertEqual(self.clics, 1)

    def test_arrastre_fuera_del_boton_no_pulsa(self) -> None:
        self._ptr("down", self.btn)
        x, y = self._norm(self.scroll)
        self.puente._on_mensaje({"t": "ptr", "ph": "move", "id": 1, "x": x, "y": y})
        self.puente._on_mensaje({"t": "ptr", "ph": "up", "id": 1, "x": x, "y": y})
        self.assertEqual(self.clics, 0)

    def test_arrastre_en_lista_desplaza_y_no_pulsa(self) -> None:
        sb = self.scroll.verticalScrollBar()
        self.assertEqual(sb.value(), 0)
        x, y = self._norm(self.btn_lista)
        alto = self.v.height()
        self.puente._on_mensaje({"t": "ptr", "ph": "down", "id": 1, "x": x, "y": y})
        for k in range(1, 8):
            self.puente._on_mensaje({"t": "ptr", "ph": "move", "id": 1, "x": x, "y": y - k * 20 / alto})
        self.puente._on_mensaje({"t": "ptr", "ph": "up", "id": 1, "x": x, "y": y - 140 / alto})
        self.assertGreater(sb.value(), 80)
        self.assertEqual(self.clics_lista, 0, "un arrastre no debe contar como toque")

    def test_toque_corto_en_lista_pulsa(self) -> None:
        self.scroll.verticalScrollBar().setValue(0)
        self._ptr("down", self.btn_lista)
        self._ptr("up", self.btn_lista)
        self.assertEqual(self.clics_lista, 1)

    def test_texto_desde_teclado_android(self) -> None:
        self.campo.setFocus()
        _pump(0.02)
        self.puente._on_mensaje({"t": "text", "s": 0, "d": 0, "i": "hola"})
        self.assertEqual(self.campo.text(), "hola")
        # Sustituir «ol» por «OL»: (inicio 1, borrar 2, insertar 2)
        self.puente._on_mensaje({"t": "text", "s": 1, "d": 2, "i": "OL"})
        self.assertEqual(self.campo.text(), "hOLa")
        self.puente._on_mensaje({"t": "text", "s": 4, "d": 0, "i": "!"})
        self.assertEqual(self.campo.text(), "hOLa!")

    def test_texto_multilinea(self) -> None:
        self.nota.setFocus()
        _pump(0.02)
        self.puente._on_mensaje({"t": "text", "s": 0, "d": 0, "i": "uno\ndos"})
        self.assertEqual(self.nota.toPlainText(), "uno\ndos")
        self.puente._on_mensaje({"t": "text", "s": 3, "d": 1, "i": " "})
        self.assertEqual(self.nota.toPlainText(), "uno dos")

    def test_enter_dispara_returnpressed(self) -> None:
        enviados: list[str] = []
        self.campo.returnPressed.connect(lambda: enviados.append(self.campo.text()))
        self.campo.setFocus()
        _pump(0.02)
        self.puente._on_mensaje({"t": "text", "s": 0, "d": 0, "i": "ok"})
        self.puente._on_mensaje({"t": "key", "k": "Enter"})
        self.assertEqual(enviados, ["ok"])

    def test_tocar_un_campo_le_da_foco_y_avisa_al_teclado(self) -> None:
        self._ptr("down", self.campo)
        self._ptr("up", self.campo)
        self.assertTrue(self.v.focusWidget() is self.campo)
        self.puente._sincronizar_ime()
        ime = [m for m in self.srv.enviados_json if m.get("t") == "ime" and m.get("on")]
        self.assertTrue(ime, "debe pedir el teclado de Android")
        self.assertFalse(ime[-1]["multi"])

    def test_repintado_parcial_equivale_al_completo(self) -> None:
        """Repintar sólo lo sucio debe dar exactamente la misma imagen que repintar todo."""
        self.puente._on_mensaje({"t": "hello", "pw": 800, "ph": 600, "dpr": 1.0, "cw": 800, "ch": 600})
        self.puente._componer(True)
        _pump(0.1)
        self.puente._sucio = type(self.puente._sucio)()  # descarta lo pendiente
        self.btn.setText("Texto distinto y bastante más largo")
        self.campo.setText("cambio")
        _pump(0.15)
        self.assertFalse(self.puente._sucio.isEmpty(), "los repintados deben registrarse como sucios")
        bb = self.puente._componer(False)
        self.assertIsNotNone(bb)
        self.assertLess(bb.width() * bb.height(), 800 * 600, "no debe repintar toda la ventana")
        parcial = self.puente._img.copy()
        self.puente._img = None
        self.puente._componer(True)
        self.assertTrue(parcial == self.puente._img, "el parcial debe coincidir píxel a píxel con el completo")

    def test_composicion_y_codificacion_de_la_captura(self) -> None:
        self.puente._on_mensaje({"t": "hello", "pw": 800, "ph": 600, "dpr": 1.0, "cw": 800, "ch": 600})
        self.puente._componer(True)
        img = self.puente._img
        self.assertEqual((img.width(), img.height()), (800, 600))
        jpeg = self.puente._codificar(img)
        self.assertEqual(jpeg[:2], b"\xff\xd8", "debe ser un JPEG válido")


class AudioTabletTest(unittest.TestCase):
    def setUp(self) -> None:
        import sounddevice as sd

        self.sd = sd
        self.srv = _ServidorFalso()
        audio_bridge.activar(self.srv)

    def tearDown(self) -> None:
        audio_bridge.desactivar()

    def test_output_stream_envia_pcm_y_marca_ritmo(self) -> None:
        with self.sd.OutputStream(samplerate=22050, channels=1, dtype="float32") as st:
            t0 = time.monotonic()
            st.write(np.full((2205, 1), 0.5, dtype=np.float32))  # 0.1 s
            self.assertLess(time.monotonic() - t0, 0.5)
        tipo, _sid, sr, ch = struct.unpack("<BHIB", self.srv.enviados_bytes[0][:8])
        self.assertEqual((tipo, sr, ch), (MSG_AUDIO, 22050, 1))
        pcm = np.frombuffer(self.srv.enviados_bytes[0][8:], dtype="<i2")
        self.assertEqual(len(pcm), 2205)
        self.assertAlmostEqual(pcm[0] / 32767.0, 0.5, places=2)

    def test_play_stop_wait(self) -> None:
        self.sd.play(np.zeros(2205, dtype=np.float32), 22050)
        self.assertEqual(self.srv.enviados_bytes[-1][0], MSG_AUDIO)
        self.sd.stop()
        self.assertEqual(self.srv.enviados_bytes[-1][0], MSG_AUDIO_STOP)
        t0 = time.monotonic()
        self.sd.wait()
        self.assertLess(time.monotonic() - t0, 0.2)

    def test_microfono_entrega_bloques_float32(self) -> None:
        bloques: list[np.ndarray] = []
        with self.sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=800,
                                 callback=lambda d, n, t, s: bloques.append(d)):
            self.assertTrue(any(m.get("t") == "mic" and m.get("on") for m in self.srv.enviados_json))
            pcm = (np.sin(np.linspace(0, 30, 1600)) * 12000).astype("<i2").tobytes()
            self.srv.al_mic(pcm)
        self.assertEqual(len(bloques), 2)
        self.assertEqual(bloques[0].shape, (800, 1))
        self.assertEqual(bloques[0].dtype, np.float32)
        self.assertTrue(any(m.get("t") == "mic" and not m.get("on") for m in self.srv.enviados_json))

    def test_consultas_de_dispositivo(self) -> None:
        self.sd.check_input_settings(samplerate=16000, channels=1, dtype="float32")
        info = self.sd.query_devices(kind="input")
        self.assertEqual(int(info["default_samplerate"]), 16000)


class ProtocoloServidorTest(unittest.TestCase):
    def test_rechaza_clientes_de_version_antigua_y_acepta_el_actual(self) -> None:
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        srv = ServidorRemoto()
        conectados: list[bool] = []
        srv.al_conectar = lambda: conectados.append(True)
        recibidos: list[dict] = []
        srv.al_mensaje = recibidos.append
        with TestClient(srv.app) as c:
            with self.assertRaises(WebSocketDisconnect) as cm:
                with c.websocket_connect("/ws") as viejo:
                    viejo.receive_text()
            self.assertEqual(cm.exception.code, 4001)
            with c.websocket_connect(f"/ws?v={PROTOCOLO}") as ws:
                ws.send_json({"t": "hello", "pw": 2000, "ph": 1200})
                ws.send_json({"t": "ack", "n": 1})
                time.sleep(0.2)
        self.assertEqual(conectados, [True])
        self.assertEqual(recibidos[0]["t"], "hello")
        self.assertTrue(all(m.get("t") != "ack" for m in recibidos), "los ack no llegan al puente")

    def test_pagina_servida(self) -> None:
        from starlette.testclient import TestClient

        c = TestClient(ServidorRemoto().app)
        r = c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("V.I.T.A.L.I.S.", r.text)
        self.assertEqual(c.get("/manifest.webmanifest").status_code, 200)


if __name__ == "__main__":
    unittest.main()
