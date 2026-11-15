# -*- coding: utf-8 -*-
"""
Pruebas de integración de la arquitectura unificada (Back 1 + Back 2 + Vista Sala).

Cubre:
1. Catálogo Plug & Play de 26 parámetros y filtrado por entorno (`base-lunar` omite ICP).
2. Triage determinista: calidad degradada, sexo biológico para creatinina, sin límites inventados OSDR.
3. Protocolos simples por disparador (`protocolos-disparadores.json`).
4. StreamEngine 1 Hz (`SimulatedSource`, `OsdrReplaySource`, `forzar_anomalia`), CrewHub y episodios/series.
5. Cola de sincronización prioritaria A>B>C>D con hash encadenado djb2 y modo offline -> flush.
6. Rutas FastAPI nuevas (`/api/parameters`, `/api/triage`, `/api/telemetry/hub`, `/api/mediciones`,
   `/api/series`, `/api/episodios`, `/api/protocolos`, `/api/tierra`, `/api/sync/*`, `/api/export`).
7. UI PySide6 completa (`VentanaPrincipalVitalis`, `VistaSala`, `VistaMedicion` 26/25,
   `VistaHistorial` series, cambio de tema e idioma en vivo).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Importar FastAPI/Pydantic antes de PySide6 evita el hook shibokensupport sobre pydantic._migration
from fastapi.testclient import TestClient  # noqa: E402
import backend.server as server_mod  # noqa: E402

import backend.crew_hub as crew_hub_mod  # noqa: E402
import backend.database as db_mod
import backend.runtime as rt_mod
import backend.sync_tierra as sync_mod
from backend.crew_hub import CrewHub
from backend.knowledge import listar_protocolos_disp, protocolo_para, sexo_de
from backend.realtime import OsdrReplaySource, SimulatedSource, StreamEngine
from backend.registry import list_params, listar_por_entorno, validate_registry
from backend.runtime import VITALISRuntime
from backend.sync_tierra import SyncTierraManager, djb2_hash
from backend.triage import evaluar, evaluar_lectura_determinista


class _EntornoAisladoMixin:
    """Aísla SQLite, CrewHub, SyncTierra y Runtime en un directorio temporal por prueba."""

    def _montar_entorno_temporal(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="vitalis_test_")
        self._orig_db_path = db_mod.DB_PATH
        self._orig_init = db_mod._inicializado
        self._orig_hub = crew_hub_mod._hub_singleton
        self._orig_sync = sync_mod._sync_singleton
        self._orig_rt = rt_mod._runtime_singleton

        db_mod.DB_PATH = os.path.join(self._tmpdir, "vitalis_test.db")
        db_mod._inicializado = False
        db_mod.init_db()

        self._snap_path = os.path.join(self._tmpdir, "snapshot.json")
        self._lotes_path = os.path.join(self._tmpdir, "lotes.jsonl")
        self.hub = CrewHub(snapshot_path=self._snap_path)
        self.sync = SyncTierraManager(lotes_path=self._lotes_path)
        self.runtime = VITALISRuntime(hub=self.hub, sync_manager=self.sync)

        crew_hub_mod._hub_singleton = self.hub
        sync_mod._sync_singleton = self.sync
        rt_mod._runtime_singleton = self.runtime

    def _desmontar_entorno_temporal(self) -> None:
        try:
            self.runtime.stop()
        except Exception:
            pass
        db_mod.DB_PATH = self._orig_db_path
        db_mod._inicializado = self._orig_init
        crew_hub_mod._hub_singleton = self._orig_hub
        sync_mod._sync_singleton = self._orig_sync
        rt_mod._runtime_singleton = self._orig_rt
        shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestCatalogoTriageYProtocolos(unittest.TestCase):
    def test_catalogo_plug_and_play_y_entornos(self) -> None:
        validate_registry()
        todos = list_params()
        self.assertEqual(len(todos), 26)
        self.assertEqual(len(listar_por_entorno("nave")), 26)
        self.assertEqual(len(listar_por_entorno("estacion")), 26)
        lunar = listar_por_entorno("base-lunar")
        self.assertEqual(len(lunar), 25)
        self.assertNotIn("intracranial_pressure_est", {p["id"] for p in lunar})

    def test_triage_calidad_sexo_y_no_inventar_osdr(self) -> None:
        deg_nom = evaluar("heart_rate", 72, 72, "nave", calidad=0.3, sexo="M")
        self.assertEqual(deg_nom["nivel"], "NOMINAL")
        self.assertTrue(deg_nom["degradado"])

        # Calidad baja degrada una lectura CRITICA a ATENCION para evitar falsas alarmas críticas por ruido
        deg_crit = evaluar("heart_rate", 165, 72, "nave", calidad=0.3, sexo="M")
        self.assertEqual(deg_crit["nivel"], "ATENCION")
        self.assertTrue(deg_crit["degradado"])

        # Sexo biológico en creatinina: F límite 0.95 vs M límite 1.3 [POR VALIDAR]
        self.assertEqual(sexo_de("C001"), "M")
        self.assertEqual(sexo_de("C002"), "F")
        f_lim = evaluar("creatinine", 0.95, None, "nave", 1.0, sexo="F")
        f_alto = evaluar("creatinine", 1.10, None, "nave", 1.0, sexo="F")
        m_ok = evaluar("creatinine", 1.10, None, "nave", 1.0, sexo="M")
        self.assertEqual(f_lim["nivel"], "NOMINAL")
        self.assertEqual(f_alto["nivel"], "ATENCION")
        self.assertEqual(m_ok["nivel"], "NOMINAL")

        # Analito OSDR nunca inventa nivel CRITICO si el dataset no lo fija
        glu_ext = evaluar("glucose", 250.0, 90.0, "nave", 1.0, sexo="M")
        self.assertEqual(glu_ext["nivel"], "ATENCION")

        # Parámetro continuo con regla crítica sí escala a CRITICO y mapea sistema visual VTK
        hr_crit = evaluar_lectura_determinista("C001", "heart_rate", 165.0)
        self.assertEqual(hr_crit["nivel"], "CRITICO")
        self.assertEqual(hr_crit["sistema"], "cardiovascular")
        self.assertEqual(hr_crit["protocoloSugerido"]["id"], "emergencia-cardiorrespiratoria")

        # Alias heredado presion arterial y temperatura
        bp = evaluar_lectura_determinista("C001", "blood_pressure", 165.0)
        self.assertIn(bp["nivel"], ("ATENCION", "CRITICO"))
        tmp = evaluar_lectura_determinista("C001", "body_temp", 37.0)
        self.assertEqual(tmp["nivel"], "NOMINAL")

    def test_protocolos_por_disparador(self) -> None:
        self.assertEqual(len(listar_protocolos_disp()), 4)
        self.assertEqual(protocolo_para("heart_rate", "CRITICO")["id"], "emergencia-cardiorrespiratoria")
        self.assertEqual(protocolo_para("cabin_co2", "CRITICO")["id"], "hipercapnia-cabina")
        self.assertEqual(protocolo_para("radiation_dose", "CRITICO")["id"], "radiacion-acumulada")
        self.assertEqual(protocolo_para("glucose", "ATENCION")["id"], "alteracion-metabolica")


class TestRuntimeHubYSync(_EntornoAisladoMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._montar_entorno_temporal()

    def tearDown(self) -> None:
        self._desmontar_entorno_temporal()

    def test_stream_engine_anomalias_y_entorno(self) -> None:
        motor = StreamEngine("C003", SimulatedSource("C003"), entorno="base-lunar")
        frame = motor.tick()
        self.assertNotIn("intracranial_pressure_est", frame["lecturas"])

        motor.set_entorno("nave")
        motor.forzar_anomalia("spo2", "CRITICO", duracion_ms=10_000)
        frame_crit = motor.tick()
        self.assertEqual(frame_crit["lecturas"]["spo2"]["nivel"], "CRITICO")
        self.assertIn("thorax_lungs", frame_crit["estadoNodos3D"])

        motor.limpiar_anomalia("spo2")
        frame_rec = motor.tick()
        self.assertNotEqual(frame_rec["lecturas"]["spo2"]["nivel"], "CRITICO")

    def test_osdr_replay_source_progresa(self) -> None:
        reloj = [1_000_000]
        src = OsdrReplaySource(
            crew_id="C003",
            duracion_total_ms=7_000,
            solo_osdr=True,
            ahora_fn=lambda: reloj[0],
        )
        src.start()
        self.assertEqual(src.get_timepoint_actual(), "R+1")
        reloj[0] += 6_500
        src.leer(reloj[0])
        self.assertEqual(src.get_timepoint_actual(), "R+194")

    def test_runtime_episodios_series_y_aislamiento_hub(self) -> None:
        eventos_sse = []
        unsub = self.hub.suscribir(eventos_sse.append)
        try:
            self.runtime.forzar_anomalia("heart_rate", "CRITICO", crew_id="C001", duracion_ms=15_000)
            abiertos = db_mod.listar_episodios("C001", solo_abiertos=True)
            self.assertTrue(any(e["parametroId"] == "heart_rate" for e in abiertos))
            self.assertTrue(any(e["tipo"] == "alerta" for e in eventos_sse))

            series_1m = db_mod.listar_series("C001", "heart_rate", resolucion="1min")
            self.assertGreaterEqual(len(series_1m), 1)

            self.runtime.limpiar_anomalias("C001")
            abiertos_despues = [
                e for e in db_mod.listar_episodios("C001", solo_abiertos=True)
                if e["parametroId"] == "heart_rate"
            ]
            self.assertEqual(abiertos_despues, [])

            self.hub.set_estacion_aislada("C002", True)
            snap = {s["crewId"]: s for s in self.hub.snapshot()}
            self.assertEqual(snap["C002"]["estadoEnlace"], "sin-enlace")
            self.assertTrue(os.path.exists(self._snap_path))
        finally:
            unsub()

    def test_sync_cola_prioridad_hash_y_offline(self) -> None:
        self.assertEqual(djb2_hash("vitalis"), djb2_hash("vitalis"))
        self.sync.set_estado_red("offline")

        # Encolar en orden inverso D -> C -> A
        bid = db_mod.registrar_bitacora("Nota de prueba", "CMO", "C001")
        self.sync.encolar_bitacora(bid)
        m_c = db_mod.guardar_medicion_sensor("C001", "glucose", 92.0, "mg/dL", "NOMINAL")
        self.sync.encolar_medicion(int(m_c["id"]), "NOMINAL")
        ev_id = db_mod.registrar_evento_emergencia("C001", 1_700_000_000_000, "CRITICO", "spo2=82%")
        self.sync.encolar_evento(ev_id, "CRITICO")

        res_off = self.sync.flush_cola()
        self.assertEqual(res_off["procesados"], 0)
        self.assertEqual(self.sync.stats()["cola"]["pendientes"], 3)

        # Al reconectar online VITALISRuntime vacía automáticamente la cola en orden A > C > D
        self.sync.set_estado_red("online")
        self.sync.flush_cola()
        self.assertEqual(self.sync.stats()["cola"]["pendientes"], 0)

        lineas = Path(self._lotes_path).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lineas), 3)
        import json as _json
        lotes_rec = [_json.loads(l) for l in lineas]
        prios = [l["prioridad"] for l in lotes_rec]
        self.assertEqual(prios, ["A", "C", "D"])
        # Nuevo lote encadenado apunta a un hash ya confirmado en Tierra
        b_sig = db_mod.registrar_bitacora("Seguimiento confirmado", "CMO", "C001")
        self.sync.encolar_bitacora(b_sig)
        self.sync.flush_cola()
        lineas2 = Path(self._lotes_path).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lineas2), 4)
        self.assertIn(_json.loads(lineas2[-1])["hashPrevio"], {l["hash"] for l in lotes_rec})

        respaldo = db_mod.exportar_respaldo_completo("C001")
        self.assertIn("mediciones", respaldo)
        self.assertIn("episodios", respaldo)
        self.assertIn("bitacora", respaldo)


class TestFastAPIEndpoints(_EntornoAisladoMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._montar_entorno_temporal()
        self.server_mod = server_mod
        self.client = TestClient(server_mod.app)

    def tearDown(self) -> None:
        self._desmontar_entorno_temporal()

    def test_endpoints_nuevos_y_compat(self) -> None:
        r_p = self.client.get("/api/parameters?entorno=base-lunar")
        self.assertEqual(r_p.status_code, 200)
        self.assertEqual(r_p.json()["total"], 25)

        r_t = self.client.post("/api/triage", json={"crewId": "C002", "indicadorId": "creatinine", "valor": 1.10})
        self.assertEqual(r_t.status_code, 200)
        self.assertEqual(r_t.json()["nivel"], "ATENCION")

        with patch.object(sync_mod, "TIERRA_LOTES_FILE", self._lotes_path):
            r_m = self.client.post("/api/mediciones", json={"crewId": "C001", "parametroId": "glucose", "valor": 95})
            self.assertEqual(r_m.status_code, 200)
            self.assertTrue(r_m.json()["ok"])

        r_hub = self.client.get("/api/telemetry/hub")
        self.assertEqual(r_hub.status_code, 200)
        self.assertEqual(len(r_hub.json()["tripulantes"]), 4)

        r_proto = self.client.get("/api/protocolos?parametroId=cabin_co2&nivel=CRITICO")
        self.assertEqual(r_proto.status_code, 200)
        self.assertEqual(r_proto.json()["protocolos"][0]["id"], "hipercapnia-cabina")

        r_exp = self.client.get("/api/export?crewId=C001")
        self.assertEqual(r_exp.status_code, 200)
        self.assertGreaterEqual(len(r_exp.json()["mediciones"]), 1)


class TestDesktopIntegracionUI(_EntornoAisladoMixin, unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "windows")
        self._montar_entorno_temporal()

    def tearDown(self) -> None:
        self._desmontar_entorno_temporal()

    def test_ventana_sala_entorno_tema_e_idioma(self) -> None:
        import time as _time
        from PySide6.QtWidgets import QApplication
        from desktop.main_window import VentanaPrincipalVitalis

        app = QApplication.instance() or QApplication([])
        win = VentanaPrincipalVitalis()
        try:
            self.assertIn("sala", win.mapa_vistas)
            self.assertIn("sala", win.botones_nav)

            win.state.ir_a("sala")
            app.processEvents()

            # Cambiar a base-lunar debe actualizar Medición de 26 -> 25 parámetros
            self.assertEqual(win.vista_medir.combo_ind.count(), 26)
            win.vista_sala._on_entorno_elegido("base-lunar")
            app.processEvents()
            self.assertEqual(win.state.entorno, "base-lunar")
            self.assertEqual(win.vista_medir.combo_ind.count(), 25)

            # Historial soporta alternar a series 1min
            win.state.ir_a("historial")
            win.vista_historial._on_modo_serie("1min")
            app.processEvents()
            self.assertGreaterEqual(win.vista_historial.tabla.rowCount(), 25)

            # Inyección de anomalía en vivo refleja en BotonAvisos / VistaSala
            win.runtime.forzar_anomalia("spo2", "CRITICO", crew_id=win.state.crew_id, duracion_ms=10_000)
            win._on_tick_vivo()
            app.processEvents()
            self.assertTrue(any(a["indicadorId"] == "spo2" for a in win._avisos))

            # Cambio de tema e idioma en caliente no rompe VistaSala
            win.aplicar_tema("claro")
            win.aplicar_tema("oscuro")
            win.state.actualizar_config(idioma="es")
            _time.sleep(0.05)
            app.processEvents()
            win.state.actualizar_config(idioma="en")
            _time.sleep(0.05)
            app.processEvents()
            self.assertIn("sala", win.mapa_vistas)
        finally:
            win.close()
            app.processEvents()

    def test_alerta_amarilla_proactiva_lis_y_deduplicacion(self) -> None:
        from PySide6.QtWidgets import QApplication
        from desktop.i18n import fijar_idioma
        from desktop.main_window import VentanaPrincipalVitalis

        fijar_idioma("es", notificar=False)
        app = QApplication.instance() or QApplication([])
        win = VentanaPrincipalVitalis()
        try:
            win.state.actualizar_config(idioma="es", vozActiva=True, mostrarAvisosEmergentes=True)
            win.state.set_crew("C001")
            win.state.set_timepoint("L-92")
            app.processEvents()

            with patch.object(win.motor_voz, "hablar") as mock_hablar:
                # Limpiar baseline inicial y forzar estado amarillo en SpO2
                win._ultimo_anuncio_voz = ""
                win.dock_lis._ultimo_aviso_proactivo_firma = ""
                win.runtime.forzar_anomalia(
                    "spo2", "ATENCION", crew_id=win.state.crew_id, duracion_ms=15_000
                )
                win._on_tick_vivo()
                app.processEvents()

                self.assertEqual(win.dock_lis._nivel_actual, "ATENCION")
                self.assertEqual(win.dock_lis.rostro.expresion, "ATENCION")
                burbuja_txt = win.dock_lis.lbl_burbuja.text()
                self.assertIn("Aviso preventivo", burbuja_txt)
                self.assertIn("Para ayudar a que mejore", burbuja_txt)
                self.assertIn("respiraciones", burbuja_txt.lower())
                self.assertNotIn("Abrir protocolo", [a.get("etiqueta") for a in win.dock_lis._ultimas_acciones])

                self.assertEqual(mock_hablar.call_count, 1)
                voz_txt = mock_hablar.call_args.args[0]
                self.assertIn("sin alarma crítica", voz_txt.lower())
                self.assertIn("respiraciones", voz_txt.lower())

                # Segundo tick a 1 Hz con el mismo estado amarillo: NO debe repetir voz
                win._on_tick_vivo()
                app.processEvents()
                self.assertEqual(mock_hablar.call_count, 1)
        finally:
            win.close()
            app.processEvents()


class TestLISAlertaAmarillaProactiva(_EntornoAisladoMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._montar_entorno_temporal()
        from desktop.i18n import fijar_idioma
        fijar_idioma("es", notificar=False)

    def tearDown(self) -> None:
        self._desmontar_entorno_temporal()

    def test_indicaciones_mejora_y_respuesta_calmada(self) -> None:
        from backend.lis_agent import (
            construir_alerta_proactiva_lis,
            generar_respuesta_determinista,
        )
        from backend.triage import evaluar_lectura_determinista, indicacion_mejora_para
        from desktop.i18n import fijar_idioma

        ev_hr = evaluar_lectura_determinista("C001", "heart_rate", 104.0)
        self.assertEqual(ev_hr["nivel"], "ATENCION")
        self.assertEqual(ev_hr["accionSugerida"], indicacion_mejora_para("heart_rate", "ATENCION_ALTO"))
        self.assertIn("descansa", ev_hr["accionSugerida"].lower())
        self.assertIn("repite", ev_hr["accionSugerida"].lower())

        pend_amarillo = [
            {
                "indicadorId": "cabin_co2",
                "titulo": "CO2 de cabina por encima del rango",
                "valor": 4.2,
                "unidad": "mmHg",
                "nivel": "ATENCION",
                "desvio": 40.0,
                "sistema": "respiratorio",
                "origen": "vivo",
                "reglaDisparada": "ATENCION_ALTO",
                "accion": indicacion_mejora_para("cabin_co2", "ATENCION_ALTO"),
            }
        ]
        alerta = construir_alerta_proactiva_lis(pend_amarillo, "C002", personalidad="jarvis-cordial")
        self.assertEqual(alerta["nivel"], "ATENCION")
        self.assertFalse(alerta["solicitoAyudaAutomatica"])
        self.assertIn("no es una situación crítica", alerta["texto"].lower())
        self.assertIn("ventiladores", alerta["texto"].lower())
        self.assertIn("sin alarma crítica", alerta["textoVoz"].lower())

        # También verificar traducción al inglés en estado amarillo
        fijar_idioma("en", notificar=False)
        pend_en = [dict(pend_amarillo[0], accion=indicacion_mejora_para("cabin_co2", "ATENCION_ALTO"))]
        alerta_en = construir_alerta_proactiva_lis(pend_en, "C002", personalidad="jarvis-cordial")
        self.assertEqual(alerta_en["nivel"], "ATENCION")
        self.assertIn("preventive notice", alerta_en["texto"].lower())
        self.assertIn("not a critical emergency", alerta_en["texto"].lower())
        self.assertIn("airflow", alerta_en["texto"].lower())
        fijar_idioma("es", notificar=False)

        # Guardar medición amarilla local y verificar respuestas deterministas de L.I.S.
        db_mod.guardar_medicion_local("C001", "glucose", 62.0, "mg/dL", "ATENCION", "[L-92] Control")
        resp_est = generar_respuesta_determinista("estado actual", crew_id="C001", timepoint="L-92")
        self.assertEqual(resp_est["nivelAlerta"], "ATENCION")
        self.assertIn("aviso preventivo", resp_est["texto"].lower())
        self.assertIn("burbujas", resp_est["texto"].lower())

        resp_av = generar_respuesta_determinista("qué alertas tengo", crew_id="C001", timepoint="L-92")
        self.assertEqual(resp_av["nivelAlerta"], "ATENCION")
        self.assertIn("no es una urgencia crítica", resp_av["texto"].lower())

    def test_alarma_intermitente_modo_emergencia_rojo(self) -> None:
        import numpy as np
        from PySide6.QtWidgets import QApplication
        from desktop.i18n import fijar_idioma
        from desktop.main_window import VentanaPrincipalVitalis
        from desktop.voice_engine import (
            MotorVozNativo,
            construir_pulso_alarma_emergencia,
        )

        # 1) Onda acústica suave sin estridencias ni clics de arranque/cierre
        pulso = construir_pulso_alarma_emergencia(22050)
        self.assertEqual(pulso.dtype, np.float32)
        self.assertGreater(len(pulso), 8000)
        self.assertLessEqual(float(np.max(np.abs(pulso))), 0.25)
        self.assertGreater(float(np.sqrt(np.mean(pulso * pulso))), 0.02)
        self.assertLess(abs(float(pulso[0])), 1e-4)
        self.assertLess(abs(float(pulso[-1])), 1e-4)

        # 2) No se superpone cuando L.I.S. habla o escucha por micrófono
        motor = MotorVozNativo()
        motor._hablando = True
        self.assertFalse(motor.reproducir_pulso_alarma_emergencia())
        motor._hablando = False
        motor._escuchando = True
        self.assertFalse(motor.reproducir_pulso_alarma_emergencia())
        motor._escuchando = False

        # 3) Activación automática en estado rojo, intermitencia, silencio y SBAR
        fijar_idioma("es", notificar=False)
        app = QApplication.instance() or QApplication([])
        win = VentanaPrincipalVitalis()
        try:
            win.state.actualizar_config(
                idioma="es", vozActiva=False, alarmaEmergenciaSonora=True
            )
            win.state.set_crew("C001")
            win.state.set_timepoint("L-92")
            app.processEvents()

            self.assertFalse(win._alarma_roja_activa)
            self.assertFalse(win._timer_alarma.isActive())
            self.assertFalse(win.state.alarma_roja_presente)

            with patch.object(
                win.motor_voz, "reproducir_pulso_alarma_emergencia", return_value=True
            ) as mock_pulso:
                win.runtime.forzar_anomalia(
                    "spo2", "CRITICO", crew_id="C001", duracion_ms=15_000
                )
                win._on_tick_vivo()
                app.processEvents()

                self.assertTrue(win._alarma_roja_activa)
                self.assertTrue(win._timer_alarma.isActive())
                self.assertTrue(win.state.alarma_emergencia_sonando)
                self.assertIn("Silenciar", win.btn_alarma_roja.text())
                self.assertGreaterEqual(mock_pulso.call_count, 1)

                # Segundo pulso intermitente del temporizador
                antes = mock_pulso.call_count
                win._tick_alarma_emergencia()
                self.assertEqual(mock_pulso.call_count, antes + 1)

                # Silenciar para el episodio actual detiene timer pero mantiene estado rojo
                win._alternar_silencio_alarma()
                self.assertFalse(win._alarma_roja_activa)
                self.assertFalse(win._timer_alarma.isActive())
                self.assertTrue(win.state.alarma_roja_presente)
                self.assertIn("silenciada", win.btn_alarma_roja.text().lower())

                # Nueva emergencia SBAR reactiva la alarma sin requerir reactivación manual
                db_mod.crear_solicitud_ayuda(
                    crew_id_solicitante="C001",
                    destinatario="CMO_A_BORDO_C001",
                    nivel="CRITICO",
                    motivo="Prueba alarma SBAR",
                    resumen_clinico="SpO2 crítico",
                    protocolo_sugerido_id="respiratorio",
                )
                win._refrescar_banner_sos()
                self.assertTrue(win._alarma_roja_activa)
                self.assertTrue(win._timer_alarma.isActive())

                # Ajustes de alarma en Configuraciones: tono, intervalo, volumen, SBAR y prueba
                for tono_id in ("doble-suave", "pulso-unico", "acorde-tibio"):
                    onda_t = construir_pulso_alarma_emergencia(
                        22050, volumen=0.85, tono=tono_id
                    )
                    self.assertLessEqual(float(np.max(np.abs(onda_t))), 0.25)
                    self.assertLess(abs(float(onda_t[0])), 1e-4)
                    self.assertLess(abs(float(onda_t[-1])), 1e-4)

                win.vista_lis.chips_intervalo_alarma.botones["4500"].click()
                win.vista_lis.chips_tono_alarma.botones["acorde-tibio"].click()
                win.vista_lis.slider_vol_alarma.setValue(45)
                win.vista_lis._guardar_vol_alarma_debounced()
                app.processEvents()
                self.assertEqual(win._timer_alarma.interval(), 4500)
                self.assertEqual(win.state.config["alarmaEmergenciaTono"], "acorde-tibio")
                self.assertAlmostEqual(
                    float(win.state.config["alarmaEmergenciaVolumen"]), 0.45, places=2
                )

                ant_cfg = mock_pulso.call_count
                win._tick_alarma_emergencia()
                self.assertEqual(mock_pulso.call_count, ant_cfg + 1)
                self.assertEqual(
                    mock_pulso.call_args.kwargs.get("tono"), "acorde-tibio"
                )
                self.assertAlmostEqual(
                    float(mock_pulso.call_args.kwargs.get("volumen", 0.0)),
                    0.45,
                    places=2,
                )

                # Botón de prueba en Ajustes respeta los parámetros configurados
                ant_test = mock_pulso.call_count
                win.vista_lis.btn_probar_alarma.click()
                self.assertEqual(mock_pulso.call_count, ant_test + 1)

                # Excluir alertas SBAR detiene la alarma si no hay alertas críticas activas
                win._avisos = []
                win.state.actualizar_config(alarmaEmergenciaIncluirSbar=False)
                app.processEvents()
                self.assertFalse(win._alarma_roja_activa)
                win.state.actualizar_config(alarmaEmergenciaIncluirSbar=True)
                app.processEvents()
                self.assertTrue(win._alarma_roja_activa)

                # Desactivar por ajuste detiene inmediatamente y actualiza Ajustes + Emergencia
                win.state.actualizar_config(alarmaEmergenciaSonora=False)
                app.processEvents()
                self.assertFalse(win._alarma_roja_activa)
                self.assertFalse(win._timer_alarma.isActive())
                self.assertFalse(win.vista_lis.sw_alarma_sonora.isChecked())
                self.assertIn("Desactivada", win.vista_emergencia.lbl_alarma_em.text())

                # Restaurar ajustes por defecto restablece los controles de alarma
                win.vista_lis._restaurar()
                app.processEvents()
                self.assertTrue(win.vista_lis.sw_alarma_sonora.isChecked())
                self.assertEqual(win._timer_alarma.interval(), 2800)
                self.assertAlmostEqual(
                    float(win.state.config["alarmaEmergenciaVolumen"]), 0.70, places=2
                )
                win.state.actualizar_config(alarmaEmergenciaSonora=False)
                app.processEvents()
        finally:
            win.close()
            app.processEvents()

    def test_estado_critico_preserva_voz_configurada(self) -> None:
        import asyncio
        from unittest.mock import MagicMock, patch
        from PySide6.QtWidgets import QApplication
        from backend.lis_agent import (
            construir_alerta_proactiva_lis,
            detectar_idioma_texto,
            sintetizar_voz_lis,
        )
        from desktop.i18n import fijar_idioma
        from desktop.main_window import VentanaPrincipalVitalis

        app = QApplication.instance() or QApplication([])

        # 1) Modo inglés con voz configurada (Guy / Aria): CRITICO no debe cambiar a voz española
        fijar_idioma("en", notificar=False)
        win = VentanaPrincipalVitalis()
        try:
            win.state.set_crew("C001")
            win.state.set_timepoint("L-92")
            win.state.actualizar_config(
                idioma="en",
                vozId="en-US-GuyNeural",
                vozActiva=True,
                alarmaEmergenciaSonora=False,
            )
            app.processEvents()

            with patch.object(win.motor_voz, "hablar") as mock_hablar:
                for idx, (pid, voz_esperada) in enumerate(
                    (
                        ("heart_rate", "en-US-GuyNeural"),
                        ("spo2", "en-US-AriaNeural"),
                    )
                ):
                    if win.state.config.get("vozId") != voz_esperada:
                        win.state.actualizar_config(vozId=voz_esperada)
                        app.processEvents()
                    win._ultimo_anuncio_voz = ""
                    win.dock_lis._ultimo_aviso_proactivo_firma = ""
                    win.runtime.limpiar_anomalias(win.state.crew_id)
                    win.runtime.forzar_anomalia(
                        pid, "CRITICO", crew_id=win.state.crew_id, duracion_ms=15_000
                    )
                    win._on_tick_vivo()
                    app.processEvents()

                    self.assertGreaterEqual(mock_hablar.call_count, idx + 1)
                    kwargs = mock_hablar.call_args.kwargs
                    args = mock_hablar.call_args.args
                    texto_voz = args[0]
                    self.assertEqual(kwargs.get("voz_id"), voz_esperada)
                    self.assertEqual(kwargs.get("lang"), "en")
                    self.assertNotIn("Notificar al Oficial", texto_voz)
                    self.assertIn("Crew Medical Officer", texto_voz)
                    self.assertEqual(detectar_idioma_texto(texto_voz, defecto="en"), "en")

                    # Verifica además qué voz neural exacta recibe edge_tts en sintetizar_voz_lis
                    mock_comm = MagicMock()

                    async def _fake_stream():
                        yield {"type": "audio", "data": b"X" * 320}

                    mock_comm.return_value.stream = _fake_stream
                    with patch("edge_tts.Communicate", mock_comm):
                        audio, _mime, eng = asyncio.run(
                            sintetizar_voz_lis(
                                texto_voz,
                                voz_id=kwargs.get("voz_id"),
                                rate=float(kwargs.get("velocidad", 1.04)),
                                lang=kwargs.get("lang"),
                            )
                        )
                    self.assertEqual(eng, "edge-neural-fallback")
                    self.assertGreater(len(audio), 200)
                    self.assertEqual(mock_comm.call_args.kwargs.get("voice"), voz_esperada)

            # 2) Cambio de idioma es -> en conserva equivalente femenino (Dalia -> Aria)
            win.state.actualizar_config(idioma="es", vozId="es-MX-DaliaNeural")
            app.processEvents()
            win.state.actualizar_config(idioma="en")
            app.processEvents()
            self.assertEqual(win.state.config.get("vozId"), "en-US-AriaNeural")

            # 3) Modo español con voz configurada (Dalia / Álvaro) también preserva la voz en CRITICO
            win.state.actualizar_config(idioma="es", vozId="es-MX-DaliaNeural")
            app.processEvents()
            win.runtime.limpiar_anomalias(win.state.crew_id)
            win.runtime.forzar_anomalia("heart_rate", "CRITICO", crew_id=win.state.crew_id, duracion_ms=15_000)
            win._ultimo_anuncio_voz = ""
            win.dock_lis._ultimo_aviso_proactivo_firma = ""
            with patch.object(win.motor_voz, "hablar") as mock_hablar_es:
                win._on_tick_vivo()
                app.processEvents()
                self.assertEqual(mock_hablar_es.call_count, 1)
                self.assertEqual(mock_hablar_es.call_args.kwargs.get("voz_id"), "es-MX-DaliaNeural")
                self.assertEqual(mock_hablar_es.call_args.kwargs.get("lang"), "es")

            # Metadata de idioma consistente en alerta proactiva
            al_meta = construir_alerta_proactiva_lis(
                [p for p in win._avisos if p["nivel"] == "CRITICO"], "C001"
            )
            self.assertEqual(al_meta.get("lang"), "es")
        finally:
            win.runtime.limpiar_anomalias("C001")
            win.close()
            app.processEvents()


class TestVistasBaseDatosCompletas(_EntornoAisladoMixin, unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "windows")
        self._montar_entorno_temporal()

    def tearDown(self) -> None:
        self._desmontar_entorno_temporal()

    def test_cinco_vistas_faltantes_base_datos(self) -> None:
        from PySide6.QtWidgets import QApplication
        from desktop.i18n import fijar_idioma
        from desktop.main_window import VentanaPrincipalVitalis

        fijar_idioma("es", notificar=False)
        app = QApplication.instance() or QApplication([])
        win = VentanaPrincipalVitalis()
        try:
            win.state.actualizar_config(
                idioma="es",
                vozActiva=False,
                alarmaEmergenciaSonora=False,
                mostrarAvisosEmergentes=False,
            )
            win.state.set_crew("C003")
            app.processEvents()

            # 1) Bitácora de misión (mission_log) + reconciliación al sincronizar
            win.state.ir_a("sala", panel="bitacora")
            win.vista_sala.panel_bitacora.txt_nota.setText("Revisión orbital nominal C003")
            win.vista_sala.panel_bitacora._guardar_entrada()
            app.processEvents()
            filas_bit = db_mod.listar_bitacora(10, "C003")
            self.assertEqual(len(filas_bit), 1)
            self.assertIn("Revisión orbital nominal C003", filas_bit[0]["texto"])

            # 2) Cola y Tierra (sync_queue + lotes.jsonl)
            win.vista_sala.seleccionar_panel("cola")
            win.vista_sala.panel_cola._forzar_flush()
            app.processEvents()
            self.assertGreaterEqual(win.vista_sala.panel_cola.tabla_cola.rowCount(), 1)
            self.assertGreaterEqual(win.vista_sala.panel_cola.tabla_tierra.rowCount(), 1)
            self.assertTrue(db_mod.listar_bitacora(10, "C003")[0]["sincronizadoTierra"])

            # 3) Eventos de emergencia, episodios completos y bandeja SBAR
            db_mod.registrar_evento_emergencia("C003", 1_700_000_000_000, "CRITICO", "spo2=82%")
            db_mod.abrir_episodio("C003", "spo2", "CRITICO", 1_700_000_000_000)
            req = db_mod.crear_solicitud_ayuda(
                "C003", "CMO_A_BORDO_C001", "CRITICO", "Desaturación sostenida", "SpO2 82%", "respiratorio"
            )
            win.state.ayudaCambiada.emit()
            app.processEvents()
            self.assertFalse(win.banner_sos.isHidden())
            self.assertIn(req["hash"], win.lbl_sos_banner.text())

            win.vista_sala.seleccionar_panel("eventos")
            app.processEvents()
            self.assertGreaterEqual(win.vista_sala.panel_eventos.tabla_eventos.rowCount(), 1)
            self.assertGreaterEqual(win.vista_sala.panel_eventos.tabla_episodios.rowCount(), 1)

            win.vista_sala.panel_eventos._atender_sbar(int(req["id"]))
            app.processEvents()
            self.assertTrue(win.banner_sos.isHidden())
            self.assertEqual(db_mod.listar_solicitudes_ayuda(solo_activas=True), [])

            # 4) Medir con nota clínica -> Historial manuales + En vivo 15 min (1 Hz)
            win.state.ir_a("medir", indicadorId="heart_rate")
            win.vista_medir._texto_valor = "84"
            win.vista_medir._valor_precargado = False
            win.vista_medir.txt_nota_med.setText("Post-ejercicio cicloergómetro")
            win.vista_medir._registrar_lectura()
            app.processEvents()

            db_mod.guardar_medicion_sensor("C003", "heart_rate", 84.0, "lpm", "NOMINAL")
            db_mod.guardar_medicion_sensor("C003", "heart_rate", 86.0, "lpm", "NOMINAL")

            win.state.ir_a("historial")
            win.vista_historial._on_modo_serie("manuales")
            app.processEvents()
            self.assertGreaterEqual(win.vista_historial.tabla.rowCount(), 1)
            self.assertIn("Post-ejercicio", win.vista_historial.lbl_rango.text())

            win.vista_historial._on_modo_serie("vivo")
            app.processEvents()
            self.assertGreaterEqual(win.vista_historial.tabla.rowCount(), 25)

            # 5) Ajustes: alias preferido y todas las notas con categoría (sin tope de 4)
            notas_antes = len(db_mod.obtener_memoria_astronauta("C003")["notasRecordadas"])
            win.state.ir_a("lis")
            win.vista_lis.txt_alias_mem.setText("Comandante Vega")
            win.vista_lis._guardar_alias_memoria()
            for idx in range(6):
                win.vista_lis._cat_nota_mem = "preferencia" if idx % 2 == 0 else "antecedente"
                win.vista_lis.txt_nota_mem.setText(f"Nota memoria {idx + 1}")
                win.vista_lis._guardar_nota_memoria()
            app.processEvents()

            mem = db_mod.obtener_memoria_astronauta("C003")
            self.assertEqual(mem["aliasPreferido"], "Comandante Vega")
            self.assertEqual(len(mem["notasRecordadas"]), notas_antes + 6)
            self.assertGreater(len(mem["notasRecordadas"]), 4)
            self.assertEqual(win.vista_lis.vbox_notas_mem.count(), len(mem["notasRecordadas"]))
            textos_mem = [
                win.vista_lis.vbox_notas_mem.itemAt(i).widget().text()
                for i in range(win.vista_lis.vbox_notas_mem.count())
            ]
            self.assertTrue(any("Preferencia" in txt and "Nota memoria 1" in txt for txt in textos_mem))
            self.assertTrue(any("Antecedente" in txt and "Nota memoria 6" in txt for txt in textos_mem))
        finally:
            win.close()
            app.processEvents()


class TestMonitorOverviewTiempoReal(_EntornoAisladoMixin, unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "windows")
        self._montar_entorno_temporal()

    def tearDown(self) -> None:
        self._desmontar_entorno_temporal()

    def test_sintesis_audio_hospitalario_bpm_y_spo2(self) -> None:
        import numpy as np
        from desktop.voice_engine import (
            construir_pulso_latido_monitor,
            intervalo_latido_ms,
        )

        self.assertLess(intervalo_latido_ms(160), intervalo_latido_ms(100))
        self.assertLess(intervalo_latido_ms(100), intervalo_latido_ms(60))

        pulso_norm = construir_pulso_latido_monitor(22050, spo2=99.0, bpm=64.0, volumen=0.35, nivel="NOMINAL")
        pulso_hipo = construir_pulso_latido_monitor(22050, spo2=84.0, bpm=165.0, volumen=0.35, nivel="CRITICO")
        self.assertGreater(len(pulso_norm), 0)
        self.assertGreater(len(pulso_hipo), 0)
        self.assertTrue(np.all(np.isfinite(pulso_norm)))
        self.assertTrue(np.all(np.isfinite(pulso_hipo)))
        self.assertLess(len(pulso_hipo), len(pulso_norm))

        def _freq_dom(pcm: np.ndarray) -> float:
            freqs = np.fft.rfftfreq(len(pcm), d=1.0 / 22050.0)
            mags = np.abs(np.fft.rfft(pcm))
            return float(freqs[int(np.argmax(mags))])

        self.assertGreater(_freq_dom(pulso_norm), _freq_dom(pulso_hipo))

    def test_overview_graficas_fondo_y_cadencia_sonora_aceleran_con_bpm(self) -> None:
        from PySide6.QtWidgets import QApplication
        from desktop.i18n import fijar_idioma
        from desktop.main_window import VentanaPrincipalVitalis
        from desktop.voice_engine import intervalo_latido_ms

        fijar_idioma("es", notificar=False)
        app = QApplication.instance() or QApplication([])
        win = VentanaPrincipalVitalis()
        try:
            win.state.actualizar_config(
                idioma="es",
                vozActiva=False,
                alarmaEmergenciaSonora=False,
                mostrarAvisosEmergentes=False,
                sonidoMonitorOverview=True,
                volumenMonitorOverview=0.35,
            )
            win.state.set_crew("C003")
            app.processEvents()
            app.processEvents()

            vo = win.vista_inicio
            self.assertIs(vo.motor_voz, win.motor_voz)
            vo._tick_telemetria(forzar=True)
            app.processEvents()

            # Gráficas de fondo conectadas a parámetros numéricos (izquierda y cabina)
            self.assertGreaterEqual(len(vo.ind_fc._serie_viva), 1)
            self.assertGreaterEqual(len(vo.ind_spo2._serie_viva), 1)
            self.assertGreaterEqual(len(vo.ind_pa._serie_viva), 1)
            self.assertGreaterEqual(len(vo.ind_temp._serie_viva), 1)
            self.assertEqual(len(vo.ind_fc._onda_muestras), 180)
            self.assertGreaterEqual(len(vo._mon_rad._serie_viva), 1)
            self.assertGreaterEqual(len(vo._mon_co2._serie_viva), 1)
            self.assertGreaterEqual(len(vo._mon_rr._serie_viva), 1)
            self.assertGreaterEqual(len(vo._mon_icp._serie_viva), 1)

            # Pintado real de fondo sin errores en ambos temas
            vo.ind_fc.grab()
            vo._mon_rr.grab()
            win.state.actualizar_config(temaVisual="claro")
            app.processEvents()
            vo.ind_fc.grab()
            win.state.actualizar_config(temaVisual="oscuro")
            app.processEvents()

            with patch.object(win.motor_voz, "reproducir_latido_monitor", return_value=True) as mock_latido:
                bpm_inicial = vo._bpm_vivo
                for _ in range(90):  # 3.0 s simulados a 30 FPS
                    vo._avanzar_monitor_dt(1.0 / 30.0)
                latidos_normales = mock_latido.call_count
                self.assertGreaterEqual(latidos_normales, 2)

                # Inyectar taquicardia CRITICA (>110 lpm) y comprobar aceleración visual + acústica
                win.runtime.limpiar_anomalias("C003")
                win.runtime.forzar_anomalia("heart_rate", "CRITICO", crew_id="C003", duracion_ms=20_000)
                app.processEvents()
                vo._tick_telemetria(forzar=True)
                app.processEvents()

                self.assertGreater(vo._bpm_vivo, bpm_inicial + 30.0)
                self.assertEqual(vo.ind_fc._nivel, "CRITICO")
                self.assertEqual(vo._nivel_fc_vivo, "CRITICO")
                self.assertFalse(hasattr(vo, "btn_monitor_audio"))
                self.assertFalse(hasattr(vo, "fila_mon_hdr"))
                self.assertIn(str(int(round(vo._bpm_vivo))), vo.ind_fc.lbl_valor.text())

                mock_latido.reset_mock()
                for _ in range(90):  # otros 3.0 s a bpm elevado
                    vo._avanzar_monitor_dt(1.0 / 30.0)
                latidos_rapidos = mock_latido.call_count
                self.assertGreater(latidos_rapidos, latidos_normales)
                self.assertEqual(mock_latido.call_args.kwargs.get("nivel"), "CRITICO")

            # Silenciar desde Ajustes actualiza sonido_monitor_activo y bloquea pulsos nuevos
            self.assertTrue(vo.sonido_monitor_activo())
            win.vista_lis.sw_monitor_overview.setChecked(False)
            app.processEvents()
            self.assertFalse(win.state.config.get("sonidoMonitorOverview"))
            self.assertFalse(vo.sonido_monitor_activo())
        finally:
            win.runtime.limpiar_anomalias("C003")
            win.close()
            app.processEvents()


class TestNavegacionYTactilUX(_EntornoAisladoMixin, unittest.TestCase):
    """Comprueba navegación directa, icono de Ajustes, Mission Control en 5 pasos y objetivos táctiles."""

    def setUp(self) -> None:
        self._montar_entorno_temporal()

    def tearDown(self) -> None:
        self._desmontar_entorno_temporal()

    def test_arranque_emite_avisos_y_voz_lis(self) -> None:
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from desktop import i18n
        from desktop.main_window import VentanaPrincipalVitalis
        from desktop.voice_engine import MotorVozNativo

        llamadas_voz = []

        def _fake_hablar(_self, texto, voz_id="jarvis-clone-latam", velocidad=1.04, lang=None):
            llamadas_voz.append((str(texto), str(voz_id), float(velocidad), lang))

        app = QApplication.instance() or QApplication([])
        with patch.object(MotorVozNativo, "hablar", new=_fake_hablar):
            win = VentanaPrincipalVitalis()
            try:
                win.showNormal()
                QTest.qWait(80)
                app.processEvents()
                self.assertTrue(bool(win.state.config.get("vozActiva", True)))
                self.assertTrue(bool(win.state.config.get("mostrarAvisosEmergentes", True)))
                self.assertTrue(win.aviso_emergente.isVisible())
                self.assertGreaterEqual(
                    win.aviso_emergente.y(), win.barra_nav.geometry().bottom()
                )
                self.assertLess(win.aviso_emergente.y(), 200)
                self.assertGreaterEqual(len(llamadas_voz), 1)
                self.assertTrue(bool(win.dock_lis.lbl_burbuja.text().strip()))
                self.assertIn(win.dock_lis._nivel_actual, ("ATENCION", "CRITICO"))

                llamadas_voz.clear()
                win.dock_lis._mostrar_respuesta(
                    {
                        "crewId": win.state.crew_id,
                        "emisor": "asistente",
                        "texto": "Sistemas nominales, señor.",
                        "nivelAlerta": "NOMINAL",
                    }
                )
                self.assertEqual(len(llamadas_voz), 1)
                self.assertEqual(llamadas_voz[0][3], i18n.idioma())
            finally:
                win.close()

    def test_navegacion_directa_ajustes_icono_y_sala_flujo(self) -> None:
        from PySide6.QtWidgets import QApplication
        from desktop.i18n import fijar_idioma
        from desktop.main_window import VentanaPrincipalVitalis

        fijar_idioma("es", notificar=False)
        app = QApplication.instance() or QApplication([])
        win = VentanaPrincipalVitalis()
        try:
            win.state.actualizar_config(
                idioma="es",
                temaVisual="oscuro",
                vozActiva=False,
                alarmaEmergenciaSonora=False,
                mostrarAvisosEmergentes=False,
            )
            app.processEvents()
            vo = win.vista_inicio
            self.assertFalse(hasattr(vo, "btn_monitor_audio"))

            # Botón de Ajustes solo por ícono táctil
            btn_aj = win.botones_nav["lis"]
            self.assertEqual(btn_aj.objectName(), "navIcono")
            self.assertEqual(btn_aj.text(), "")
            self.assertFalse(btn_aj.icon().isNull())
            self.assertGreaterEqual(btn_aj.minimumHeight(), 52)
            self.assertGreaterEqual(btn_aj.minimumWidth(), 52)
            btn_aj.click()
            app.processEvents()
            self.assertEqual(win.state.pagina, "lis")

            # Marca en barra superior regresa a Overview
            win.btn_marca.click()
            app.processEvents()
            self.assertEqual(win.state.pagina, "inicio")

            # Tocar Heart Rate o CO2 salta directo a Historial en modo vivo
            vo.ind_fc.pulsado.emit()
            app.processEvents()
            self.assertEqual(win.state.pagina, "historial")
            self.assertEqual(win.vista_historial._seleccion, "heart_rate")
            self.assertEqual(win.vista_historial._modo_serie, "vivo")

            win.btn_marca.click()
            app.processEvents()
            vo._mon_co2.pulsado.emit()
            app.processEvents()
            self.assertEqual(win.state.pagina, "historial")
            self.assertEqual(win.vista_historial._seleccion, "cabin_co2")
            self.assertEqual(win.vista_historial._modo_serie, "vivo")

            # Botones de historial en card_foco y Cuerpo 3D
            win.vista_cuerpo.btn_hist_3d.click()
            app.processEvents()
            self.assertEqual(win.state.pagina, "historial")

            # Mission Control en 5 pasos táctiles claros
            win.state.ir_a("sala")
            app.processEvents()
            vs = win.vista_sala
            self.assertEqual(list(vs.botones_flujo.keys()), ["vivo", "escenario", "eventos", "bitacora", "cola"])
            for btn in vs.botones_flujo.values():
                self.assertGreaterEqual(btn.minimumHeight(), 52)

            for ui_crew in vs._crew_cards.values():
                self.assertGreaterEqual(ui_crew["btn_ver"].minimumHeight(), 52)
                self.assertGreaterEqual(ui_crew["btn_aislar"].minimumHeight(), 52)

            for ui_tel in vs._tele_cards.values():
                self.assertGreaterEqual(ui_tel["lbl_regla"].font().pixelSize(), 14)

            vs.seleccionar_panel("escenario")
            app.processEvents()
            desc_esc = vs.lbl_flujo_desc.text()
            self.assertTrue(len(desc_esc) > 10)
            vs._on_entorno_elegido("base-lunar")
            app.processEvents()
            self.assertIn("Base lunar", vs.lbl_resumen_entorno.text())

            vs.seleccionar_panel("cola")
            app.processEvents()
            self.assertGreaterEqual(vs.panel_cola.tabla_cola.verticalHeader().defaultSectionSize(), 52)
            self.assertGreaterEqual(win.dock_lis.btn_callar.minimumHeight(), 48)

            # Cambio a EN y tema claro conserva icono sin texto en Ajustes
            win.state.actualizar_config(idioma="en", temaVisual="claro")
            app.processEvents()
            self.assertEqual(win.botones_nav["lis"].text(), "")
            self.assertFalse(win.botones_nav["lis"].icon().isNull())
        finally:
            win.close()
            app.processEvents()


class TestBienestarSaludMental(_EntornoAisladoMixin, unittest.TestCase):
    """Verifica integración completa del módulo BHP de salud emocional/mental y conducta."""

    def setUp(self) -> None:
        self._montar_entorno_temporal()

    def tearDown(self) -> None:
        self._desmontar_entorno_temporal()

    def test_db_triage_y_lis_salud_mental(self) -> None:
        from backend.lis_agent import generar_respuesta_determinista
        from backend.triage import evaluar_salud_mental_determinista
        from desktop.i18n import fijar_idioma

        fijar_idioma("es", notificar=False)

        # 1) Persistencia SQLite + gamificación + respaldo completo
        ev = db_mod.guardar_evaluacion_mental(
            crew_id="C001",
            timepoint="L-92",
            horas_sueno=7.2,
            nivel_estres=2,
            animo=4,
            fatiga=2,
            aislamiento=1,
            pvt_latencia_ms=285.0,
            pvt_lapsus=0,
            nivel_triage="verde",
            notas="[Hábitat] Prueba integral de bitácora confidencial",
        )
        self.assertEqual(ev["crewId"], "C001")
        lista = db_mod.obtener_evaluaciones_mentales("C001", limit=5)
        self.assertGreaterEqual(len(lista), 1)
        self.assertAlmostEqual(float(lista[0]["pvtLatenciaMs"]), 285.0, places=1)

        gam0 = db_mod.obtener_estado_gamificacion("C001")
        self.assertEqual(len(gam0["misiones"]), len(db_mod.MISIONES_DEFECTO))
        self.assertEqual(len(gam0["insignias"]), len(db_mod.INSIGNIAS_DEFECTO))

        gam1 = db_mod.marcar_mision_gamificacion("C001", "hidratacion", True)
        self.assertEqual(gam1["score"], 15)
        db_mod.desbloquear_insignia("C001", "biofilia")
        gam2 = db_mod.obtener_estado_gamificacion("C001")
        bio = next(i for i in gam2["insignias"] if i["id"] == "biofilia")
        self.assertTrue(bio["desbloqueada"])

        respaldo = db_mod.exportar_respaldo_completo()
        self.assertIn("evaluacionesMentales", respaldo)
        self.assertGreaterEqual(len(respaldo["evaluacionesMentales"]), 1)

        # 2) Triage determinista BHP (verde, amarillo, rojo)
        tv = evaluar_salud_mental_determinista(horas_sueno=7.2, pvt_latencia_ms=290, pvt_lapsus=0, estres_score=3, aislamiento_score=2)
        self.assertEqual(tv["nivel"], "verde")
        ta = evaluar_salud_mental_determinista(horas_sueno=5.8, pvt_latencia_ms=390, pvt_lapsus=1, estres_score=6, aislamiento_score=4)
        self.assertEqual(ta["nivel"], "amarillo")
        self.assertIn("POR VALIDAR", ta["accion"])
        tr_rojo = evaluar_salud_mental_determinista(horas_sueno=4.2, pvt_latencia_ms=480, pvt_lapsus=3, estres_score=9, aislamiento_score=8)
        self.assertEqual(tr_rojo["nivel"], "rojo")
        self.assertIn("POR VALIDAR", tr_rojo["accion"])

        # 3) Agente L.I.S. para consultas emocionales/conductuales
        resp_es = generar_respuesta_determinista("cómo está mi salud mental y estrés", crew_id="C001", timepoint="L-92")
        self.assertEqual(resp_es["modoVerificacion"], "DETERMINISTA_ESTRICTO")
        self.assertEqual(resp_es["accionesControl"], [{"tipo": "NAVEGACION", "valor": "salud_mental"}])
        self.assertIn("C001", resp_es["texto"])

        fijar_idioma("en", notificar=False)
        resp_en = generar_respuesta_determinista("check my mental health and sleep", crew_id="C001", timepoint="L-92")
        self.assertEqual(resp_en["accionesControl"], [{"tipo": "NAVEGACION", "valor": "salud_mental"}])
        self.assertIn("readiness", resp_en["texto"].lower())
        fijar_idioma("es", notificar=False)

    def test_ui_bienestar_navegacion_temas_idiomas_y_cabecera_1180(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from desktop.i18n import fijar_idioma
        from desktop.main_window import VentanaPrincipalVitalis
        from desktop.state import PAGINAS

        self.assertIn("salud_mental", PAGINAS)
        fijar_idioma("es", notificar=False)
        app = QApplication.instance() or QApplication([])
        win = VentanaPrincipalVitalis()
        win.setAttribute(Qt.WA_ShowWithoutActivating, True)
        cfg_orig = dict(win.state.config)
        try:
            win.state.actualizar_config(
                idioma="es",
                temaVisual="oscuro",
                vozActiva=False,
                alarmaEmergenciaSonora=False,
                mostrarAvisosEmergentes=False,
                mostrarAsistente=False,
            )
            win.resize(1180, 760)
            win.show()
            app.processEvents()

            # Soundscape files are optional (not shipped: provenance unverified). When absent the
            # player falls back to synthesised noise, so the player must still exist for all three.
            v = win.vista_salud_mental
            self.assertEqual(set(v.biofilia._archivos), {"lluvia", "bosque", "oceano"})

            # Navegar con sub-sección y recorrer las 8 secciones
            win.state.ir_a("salud_mental", seccion="descompresion")
            app.processEvents()
            self.assertEqual(win.state.pagina, "salud_mental")
            self.assertTrue(win.botones_nav["salud_mental"].isChecked())
            self.assertEqual(v._seccion_actual, "descompresion")

            for sec in ("bitacora", "rutina", "pvt", "cognicion", "sueno", "insignias", "descompresion", "dsn"):
                v.seleccionar_seccion(sec)
                app.processEvents()
                self.assertEqual(v._seccion_actual, sec)
                self.assertGreaterEqual(v.btns_secciones[sec].minimumHeight(), 44)

            # Archivar una entrada de bitácora desde UI
            v.seleccionar_seccion("bitacora")
            v.txt_bitacora.setPlainText("Adaptación nominal en cabina durante turno nocturno.")
            v._guardar_bitacora()
            app.processEvents()
            evs = db_mod.obtener_evaluaciones_mentales(win.state.crew_id, limit=5)
            self.assertTrue(any("Adaptación nominal" in (e.get("notas") or "") for e in evs))

            # Cambio en vivo a EN + tema claro a 1180x760 sin desborde ni recorte en barra superior
            win.state.actualizar_config(idioma="en", temaVisual="claro")
            app.processEvents()
            win.state.ir_a("salud_mental", seccion="bitacora")
            app.processEvents()
            for clave, btn in win.botones_nav.items():
                self.assertLessEqual(
                    btn.sizeHint().width() - btn.width(),
                    2,
                    f"Botón nav '{clave}' ({btn.text()!r}) recortado en 1180px: w={btn.width()} hint={btn.sizeHint().width()}",
                )

            # Al salir de Bienestar detiene recursos activos sin afectar otros subsistemas
            with patch.object(win.vista_salud_mental, "detener_recursos") as mock_stop:
                win.state.ir_a("inicio")
                app.processEvents()
                self.assertGreaterEqual(mock_stop.call_count, 1)
        finally:
            win.state.actualizar_config(
                idioma=cfg_orig.get("idioma", "es"),
                temaVisual=cfg_orig.get("temaVisual", "oscuro"),
                mostrarAsistente=cfg_orig.get("mostrarAsistente", True),
                vozActiva=cfg_orig.get("vozActiva", True),
                alarmaEmergenciaSonora=cfg_orig.get("alarmaEmergenciaSonora", True),
                mostrarAvisosEmergentes=cfg_orig.get("mostrarAvisosEmergentes", True),
            )
            win.close()
            app.processEvents()


class TestPersistenciaConfigEIcono(_EntornoAisladoMixin, unittest.TestCase):
    """Verifica persistencia completa de Ajustes tras reinicio e icono multi-resolución."""

    def setUp(self) -> None:
        self._montar_entorno_temporal()
        self._env_orig = {
            k: os.environ.get(k)
            for k in ("QT_SCALE_FACTOR", "VITALIS_ESCALA_APLICADA")
        }

    def tearDown(self) -> None:
        for k, val in self._env_orig.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val
        self._desmontar_entorno_temporal()

    def test_persistencia_ajustes_debounced_apikey_escala_y_restaurar(self) -> None:
        from PySide6.QtWidgets import QApplication
        import vitalis_desktop as app_entry
        from desktop.i18n import fijar_idioma
        from desktop.main_window import VentanaPrincipalVitalis
        from desktop.state import AppState

        app_entry.aplicar_escala_entorno("1.0", forzar=True)
        fijar_idioma("es", notificar=False)
        app = QApplication.instance() or QApplication([])
        win = VentanaPrincipalVitalis()
        try:
            win.state.actualizar_config(
                idioma="es",
                vozId="jarvis-clone-latam",
                vozActiva=False,
                alarmaEmergenciaSonora=False,
                mostrarAvisosEmergentes=False,
                mostrarAsistente=False,
            )
            win.state.ir_a("lis")
            app.processEvents()

            # 1) Voz JARVIS XTTS persiste al alternar ES -> EN -> ES
            win.state.actualizar_config(idioma="en")
            app.processEvents()
            self.assertEqual(win.state.config["vozId"], "jarvis-clone-latam")
            win.state.actualizar_config(idioma="es")
            app.processEvents()
            self.assertEqual(win.state.config["vozId"], "jarvis-clone-latam")

            # 2) L.I.S. escribe escalaUI (no clave huérfana escalaFuente) y btn_reiniciar persiste visible
            res_escala = win.dock_lis._aplicar_config_accion("escalaFuente", "1.15")
            self.assertIsNotNone(res_escala)
            app.processEvents()
            self.assertEqual(db_mod.obtener_config_lis()["escalaUI"], "1.15")
            self.assertFalse(win.vista_lis.btn_reiniciar.isHidden())

            # Al reconstruir por cambio de idioma, btn_reiniciar sigue visible mientras no se reinicie
            win.state.actualizar_config(idioma="en")
            app.processEvents()
            self.assertFalse(win.vista_lis.btn_reiniciar.isHidden())

            # 3) Sliders con debounce + API key + Ollama sin espera de 250ms se vuelcan al cerrar
            v = win.vista_lis
            v.slider_vel.setValue(118)
            v.slider_vol_alarma.setValue(85)
            v.slider_vol_monitor.setValue(60)
            v.txt_apikey.setText("sk-test-persistencia-1234")
            v.txt_ollama_url.setText("http://127.0.0.1:11435")
            v.combo_ollama_mod.setCurrentText("llama3.2:3b")
            win.close()
            app.processEvents()

            # Simula nuevo arranque cargando AppState limpio desde SQLite
            estado_reinicio = AppState()
            cfg = estado_reinicio.config
            self.assertEqual(cfg["escalaUI"], "1.15")
            self.assertEqual(cfg["vozId"], "jarvis-clone-latam")
            self.assertAlmostEqual(float(cfg["velocidadVoz"]), 1.18, places=2)
            self.assertAlmostEqual(float(cfg["alarmaEmergenciaVolumen"]), 0.85, places=2)
            self.assertAlmostEqual(float(cfg["volumenMonitorOverview"]), 0.60, places=2)
            self.assertEqual(cfg["cloudApiKey"], "sk-test-persistencia-1234")
            self.assertEqual(cfg["llmEndpointLocal"], "http://127.0.0.1:11435")
            self.assertEqual(cfg["llmModeloLocal"], "llama3.2:3b")

            # 4) Escala de entorno al reiniciar: 1.15 fija QT_SCALE_FACTOR y volver a 1.0 la limpia
            self.assertEqual(app_entry.aplicar_escala_entorno("1.15"), "1.15")
            self.assertEqual(os.environ.get("QT_SCALE_FACTOR"), "1.15")
            self.assertEqual(os.environ.get("VITALIS_ESCALA_APLICADA"), "1.15")
            self.assertEqual(app_entry.aplicar_escala_entorno("1.0"), "1.0")
            self.assertNotIn("QT_SCALE_FACTOR", os.environ)
            self.assertEqual(os.environ.get("VITALIS_ESCALA_APLICADA"), "1.0")

            # 5) Restaurar valores de fábrica sincroniza AppState en memoria + señales + SQLite
            eventos_restaurar = []
            estado_reinicio.crewChanged.connect(lambda v: eventos_restaurar.append(("crew", v)))
            estado_reinicio.entornoCambiado.connect(lambda v: eventos_restaurar.append(("entorno", v)))
            estado_reinicio.enlaceTierraCambiado.connect(lambda v: eventos_restaurar.append(("enlace", v)))
            estado_reinicio.set_crew("C001")
            estado_reinicio.set_timepoint("L-10")
            estado_reinicio.set_entorno("base-lunar")
            estado_reinicio.set_modo_telemetria("sensores")
            estado_reinicio.set_enlace_tierra(False)
            eventos_restaurar.clear()
            estado_reinicio.restaurar_config()
            self.assertEqual(estado_reinicio.crew_id, db_mod.CONFIG_LIS_DEFECTO["crewId"])
            self.assertEqual(estado_reinicio.timepoint, db_mod.CONFIG_LIS_DEFECTO["timepoint"])
            self.assertEqual(estado_reinicio.entorno, "nave")
            self.assertEqual(estado_reinicio.modo_telemetria, "simulado")
            self.assertTrue(estado_reinicio.enlace_tierra_online)
            self.assertIn(("crew", db_mod.CONFIG_LIS_DEFECTO["crewId"]), eventos_restaurar)
            self.assertIn(("entorno", "nave"), eventos_restaurar)
            self.assertIn(("enlace", True), eventos_restaurar)
        finally:
            win.close()
            app.processEvents()

    def test_icono_programa_multiresolucion_y_ventana(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
        from desktop.main_window import ICON_FALLBACK_PATH, ICON_PATH, VentanaPrincipalVitalis, ruta_icono_app

        self.assertTrue(os.path.exists(ICON_PATH), f"Falta icono principal: {ICON_PATH}")
        self.assertTrue(os.path.exists(ICON_FALLBACK_PATH), f"Falta icono marca: {ICON_FALLBACK_PATH}")
        self.assertEqual(ruta_icono_app(), ICON_PATH)

        app = QApplication.instance() or QApplication([])
        ico = QIcon(ICON_PATH)
        self.assertFalse(ico.isNull())
        tamanos = {(s.width(), s.height()) for s in ico.availableSizes()}
        for req in ((16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (256, 256)):
            self.assertIn(req, tamanos, f"Falta tamaño {req} en {ICON_PATH}: {sorted(tamanos)}")

        win = VentanaPrincipalVitalis()
        win.setAttribute(Qt.WA_ShowWithoutActivating, True)
        try:
            win.state.actualizar_config(
                vozActiva=False,
                alarmaEmergenciaSonora=False,
                mostrarAvisosEmergentes=False,
                mostrarAsistente=False,
            )
            self.assertFalse(win.windowIcon().isNull())
            win.show()
            app.processEvents()
            if sys.platform == "win32":
                self.assertEqual(len(win._hicons_so), 2)
        finally:
            win.close()
            app.processEvents()
            self.assertEqual(win._hicons_so, [])


if __name__ == "__main__":
    unittest.main()
