# -*- coding: utf-8 -*-
"""
desktop/salud_mental.py — Vista Nativa de Bienestar Emocional y Conducta (NASA BHP).

Integra de forma coherente al sistema visual dual y táctil de V.I.T.A.L.I.S.:
  - Sub-navegación superior en rejilla táctil 4x2 (`#subnavFlujo` + `#flujoBanner`)
    compatible con resoluciones 1180x760 y 1460x920 sin desbordes ni dependencia del pie
  - Soporte completo para temas claro/oscuro (`aplicar_tema`) e idioma `ES`/`EN` (`tr`)
  - 8 módulos: Bitácora, Rutina, Test PVT-B, Cognición (Stroop), Sueño, Insignias,
    Descompresión (Box Breathing 4-4-4-4 + Biofilia WAV) y Enlace DSN asíncrono
"""

from __future__ import annotations

import os
import random
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from backend.database import (
    desbloquear_insignia,
    get_cabina_dataset,
    guardar_evaluacion_mental,
    marcar_mision_gamificacion,
    obtener_estado_gamificacion,
    obtener_evaluaciones_mentales,
    obtener_memoria_astronauta,
)
from backend.triage import evaluar_salud_mental_determinista
from desktop import theme as t
from desktop.i18n import tr
from desktop.state import AppState
from desktop.widgets import (
    FilaIndicador,
    GraficaTendencia,
    Tarjeta,
    boton,
    divisor,
    etiqueta,
    etiqueta_mono,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INFO_ASTRONAUTAS: Dict[str, Dict[str, str]] = {
    "C001": {
        "nombre_corto": "Marcus",
        "nombre_completo": "Dr. Marcus Vance",
        "rol": "Oficial Médico de Tripulación (CMO)",
        "mision": "Comandancia médica · Expedición VITALIS-I",
    },
    "C002": {
        "nombre_corto": "Elena",
        "nombre_completo": "Dra. Elena Rostova",
        "rol": "Piloto de Misión",
        "mision": "Pilotaje orbital · Expedición VITALIS-I",
    },
    "C003": {
        "nombre_corto": "Kenji",
        "nombre_completo": "Ing. Kenji Sato",
        "rol": "Especialista de Misión",
        "mision": "Sistemas de cabina y soporte vital · Expedición VITALIS-I",
    },
    "C004": {
        "nombre_corto": "Sarah",
        "nombre_completo": "Cmdte. Sarah Connor",
        "rol": "Comandante de Misión",
        "mision": "Comando general de vuelo · Expedición VITALIS-I",
    },
}

SECCIONES_BHP: List[tuple[str, str, str, str]] = [
    ("bitacora", "Bitácora", "Registro emocional y notas privadas de adaptación en cabina.", "Archivar entrada"),
    ("rutina", "Rutina", "Micro-acciones operativas diarias que alimentan el índice de preparación.", "Iniciar prueba PVT-B"),
    ("pvt", "PVT-B", "Prueba psicomotora de reflejos de 3 rondas y conteo de lapsus > 500 ms.", "Iniciar prueba"),
    ("cognicion", "Cognición", "Batería tipo Stroop para atención ejecutiva y flexibilidad mental.", "Iniciar batería"),
    ("sueno", "Sueño", "Serie circadiana, espectro lumínico y temporizador de siesta NASA Ames.", "Alternar espectro"),
    ("insignias", "Insignias", "Logros operativos asociados a descanso, vigilancia y biofilia.", "Ver protocolo HRP"),
    ("descompresion", "Descompresión", "Respiración guiada 4-4-4-4 y paisajes sonoros terrestres en bucle.", "Iniciar respiración 4x4"),
    ("dsn", "Enlace DSN", "Cápsula afectiva asíncrona y búfer cifrado de retorno hacia Tierra [SUPUESTO].", "Grabar cápsula DSN"),
]


class _SegmentoShim:
    """Mantiene compatibilidad con `.barra_segmentos.marcar(clave)`."""

    def __init__(self, padre: "VistaSaludMental") -> None:
        self._padre = padre

    def marcar(self, clave_o_nombre: str) -> None:
        self._padre._marcar_seccion_ui(clave_o_nombre)


def _colores_animo() -> Dict[str, tuple[str, str, str, str]]:
    osc = t.es_oscuro()
    return {
        "optimo": ("Enfocado", t.NORMAL, t.INSIGNIA_OK_BG, t.INSIGNIA_OK_BORDE),
        "nominal": ("Nominal", t.TEXTO, t.FONDO, t.BORDE_SUAVE),
        "fatiga": ("Fatiga", t.ATENCION, t.CAJA_FALLO_BG, t.CAJA_FALLO_BORDE),
        "tension": ("Tensión", t.ALERTA, t.PELIGRO_BG, t.PELIGRO_BORDE),
        "aislamiento": (
            "Aislamiento",
            "#C4B5FD" if osc else "#6D28D9",
            "#24163A" if osc else "#F3E8FF",
            "#6D28D9" if osc else "#C4B5FD",
        ),
    }


def _colores_stroop() -> List[tuple[str, str, str]]:
    osc = t.es_oscuro()
    return [
        ("rojo", "Rojo", "#FF6B70" if osc else "#DC2626"),
        ("verde", "Verde", "#38D9A9" if osc else "#059669"),
        ("azul", "Azul", "#7CE8FF" if osc else "#0284C7"),
        ("ámbar", "Ámbar", "#F2D49B" if osc else "#B45309"),
    ]


def _estilo_scroll() -> str:
    return (
        "QScrollArea { background: transparent; border: none; }"
        f"QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}"
        f"QScrollBar::handle:vertical {{ background: {t.SCROLL_HANDLE}; min-height: 24px; border-radius: 3px; }}"
        f"QScrollBar::handle:vertical:hover {{ background: {t.BORDE_SUAVE}; }}"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
    )


class ReproductorBiofilia:
    """Reproductor no bloqueante de paisajes sonoros en WAV o ruido rosa sintético."""

    def __init__(self) -> None:
        self._activo = False
        self._hilo: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._tipo = "lluvia"
        self._archivos = {
            "lluvia": os.path.join(ROOT_DIR, "desktop", "assets", "audio", "lluvia.wav"),
            "bosque": os.path.join(ROOT_DIR, "desktop", "assets", "audio", "bosque.wav"),
            "oceano": os.path.join(ROOT_DIR, "desktop", "assets", "audio", "oceano.wav"),
        }

    @property
    def activo(self) -> bool:
        return self._activo

    def iniciar(self, tipo: str = "lluvia") -> None:
        self.detener()
        self._tipo = tipo
        self._stop_event.clear()
        self._activo = True

        def _worker() -> None:
            ruta = self._archivos.get(self._tipo)
            if ruta and os.path.exists(ruta):
                try:
                    data, sr = sf.read(ruta, dtype="float32")
                    data = data * 0.72
                    bloque = 4096
                    pos = 0
                    total = len(data)
                    canales = 1 if data.ndim == 1 else data.shape[1]
                    with sd.OutputStream(samplerate=sr, channels=canales, dtype="float32") as stream:
                        while not self._stop_event.is_set() and total > 0:
                            fin = min(pos + bloque, total)
                            stream.write(data[pos:fin])
                            pos = 0 if fin >= total else fin
                except Exception:
                    pass
                finally:
                    self._activo = False
            else:
                sr = 22050
                n_samples = sr
                try:
                    with sd.OutputStream(samplerate=sr, channels=1, dtype="float32") as stream:
                        while not self._stop_event.is_set():
                            white = np.random.randn(n_samples).astype(np.float32) * 0.04
                            pink = np.cumsum(white) * 0.012
                            pink -= np.mean(pink)
                            stream.write(np.clip(pink * 0.45, -0.25, 0.25))
                except Exception:
                    pass
                finally:
                    self._activo = False

        self._hilo = threading.Thread(target=_worker, daemon=True, name="lis-biofilia")
        self._hilo.start()

    def detener(self) -> None:
        self._stop_event.set()
        self._activo = False
        if self._hilo and self._hilo.is_alive():
            self._hilo.join(timeout=0.35)
        self._hilo = None


class OrbeRespiracion(QWidget):
    """Guía visual vectorial para ciclo Box Breathing (4-4-4-4)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(188, 188)
        self._fase_texto = tr("Listo")
        self._segundo_texto = "4s"
        self._progreso = 0.48
        self._color_orbe = QColor(t.TEXTO_SUAVE)

    def actualizar(self, texto: str, seg_txt: str, progreso: float, color_hex: str) -> None:
        self._fase_texto = tr(texto)
        self._segundo_texto = seg_txt
        self._progreso = max(0.46, min(1.0, progreso))
        self._color_orbe = QColor(color_hex)
        self.update()

    def aplicar_tema(self) -> None:
        self._color_orbe = QColor(t.TEXTO_SUAVE)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        max_r = min(w, h) / 2.0 - 16.0
        r = max_r * self._progreso

        p.setPen(QPen(QColor(t.BORDE_SUAVE), 1.3, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), max_r, max_r)

        c = self._color_orbe
        p.setPen(QPen(c, 2.2))
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 28 if t.es_oscuro() else 20))
        p.drawEllipse(QPointF(cx, cy), r, r)

        p.setPen(QColor(t.TEXTO))
        p.setFont(QFont(t.FUENTE, 14, QFont.Bold))
        p.drawText(QRectF(cx - max_r, cy - 22, max_r * 2, 26), Qt.AlignCenter, self._fase_texto)

        p.setPen(QColor(t.SECUNDARIO))
        p.setFont(QFont(t.FUENTE_MONO, 14))
        p.drawText(QRectF(cx - max_r, cy + 6, max_r * 2, 24), Qt.AlignCenter, self._segundo_texto)
        p.end()


class VistaSaludMental(QWidget):
    """Vista de Bienestar Emocional y Conducta (NASA BHP) adaptada al diseño V.I.T.A.L.I.S."""

    def __init__(self, state: AppState, motor_voz: Optional[Any] = None) -> None:
        super().__init__()
        self.state = state
        self.motor_voz = motor_voz
        self.biofilia = ReproductorBiofilia()
        self.barra_segmentos = _SegmentoShim(self)

        # Estado PVT-B
        self._pvt_estado = "inactivo"
        self._pvt_intentos: List[float] = []
        self._pvt_lapsus = 0
        self._pvt_ts_inicio = 0.0
        self._pvt_timer = QTimer(self)
        self._pvt_timer.timeout.connect(self._on_pvt_disparo)
        self._pvt_anim_timer = QTimer(self)
        self._pvt_anim_timer.setInterval(16)
        self._pvt_anim_timer.timeout.connect(self._on_pvt_tick)

        # Estado Box Breathing
        self._resp_activo = False
        self._resp_tiempo = 0.0
        self._resp_mision_concedida = False
        self._resp_timer = QTimer(self)
        self._resp_timer.setInterval(60)
        self._resp_timer.timeout.connect(self._on_respiracion_tick)

        # Estado Siesta Táctica (NASA Ames)
        self._siesta_activa = False
        self._siesta_segundos = 26 * 60
        self._luz_reposo = False
        self._siesta_timer = QTimer(self)
        self._siesta_timer.setInterval(1000)
        self._siesta_timer.timeout.connect(self._on_siesta_tick)

        # Estado Stroop
        self._stroop_activo = False
        self._stroop_ronda = 0
        self._stroop_aciertos = 0
        self._stroop_tiempos: List[float] = []
        self._stroop_t0 = 0.0
        self._stroop_color_correcto = ""

        # Estado DSN
        self._dsn_segundos_ventana = 2 * 3600 + 34 * 60 + 18
        self._dsn_timer = QTimer(self)
        self._dsn_timer.setInterval(1000)
        self._dsn_timer.timeout.connect(self._on_dsn_segundo_tick)
        self._dsn_timer.start()

        self._dsn_audio_reproduciendo = False
        self._dsn_audio_segundos = 0
        self._dsn_audio_timer = QTimer(self)
        self._dsn_audio_timer.setInterval(500)
        self._dsn_audio_timer.timeout.connect(self._on_dsn_audio_tick)

        self._dsn_grabando = False
        self._dsn_grabacion_segundos = 0.0
        self._dsn_rec_timer = QTimer(self)
        self._dsn_rec_timer.setInterval(150)
        self._dsn_rec_timer.timeout.connect(self._on_dsn_rec_tick)

        self._dsn_paquetes_encolados: List[Dict[str, Any]] = []
        self._seccion_actual = "bitacora"
        self._triage_actual: Dict[str, Any] = {}
        self._frames_stroop_pal: List[QFrame] = []
        self._frames_dsn_cajas: List[QFrame] = []
        self._frames_dsn_enviados: List[QFrame] = []

        self._construir_ui()
        self.aplicar_tema()
        self.refrescar()

        self.state.crewChanged.connect(lambda *_: self.refrescar())
        self.state.timepointChanged.connect(lambda *_: self.refrescar())

    def detener_recursos(self) -> None:
        """Detiene temporizadores y flujo de audio biofílico al reconstruir o cerrar."""
        for tm in (
            self._pvt_timer,
            self._pvt_anim_timer,
            self._resp_timer,
            self._siesta_timer,
            self._dsn_timer,
            self._dsn_audio_timer,
            self._dsn_rec_timer,
        ):
            if tm.isActive():
                tm.stop()
        self._resp_activo = False
        self._dsn_audio_reproduciendo = False
        self._dsn_grabando = False
        self.biofilia.detener()

    def _info_tripulante(self, crew_id: str) -> Dict[str, str]:
        base = INFO_ASTRONAUTAS.get(
            crew_id,
            {
                "nombre_corto": crew_id,
                "nombre_completo": crew_id,
                "rol": "Tripulante",
                "mision": "Expedición VITALIS-I",
            },
        )
        mem = obtener_memoria_astronauta(crew_id) or {}
        alias = str(mem.get("alias") or "").strip()
        nombre_corto = alias or base["nombre_corto"]
        return {
            "nombre_corto": nombre_corto,
            "nombre_completo": alias or base["nombre_completo"],
            "rol": tr(base["rol"]),
            "mision": tr(base["mision"]),
            "saludo": tr("Hola, {nombre}", nombre=nombre_corto),
        }

    # ------------------------------------------------------------------ UI
    def _construir_ui(self) -> None:
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(18)

        # --- COLUMNA IZQUIERDA (Scrollable, 296 px) ---
        scroll_izq = QScrollArea()
        scroll_izq.setWidgetResizable(True)
        scroll_izq.setFrameShape(QFrame.NoFrame)
        scroll_izq.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_izq.setFixedWidth(296)
        self._scroll_izq = scroll_izq

        w_izq = QWidget()
        col_izq = QVBoxLayout(w_izq)
        col_izq.setContentsMargins(0, 0, 6, 0)
        col_izq.setSpacing(4)

        self.lbl_saludo_tripulante = QLabel(tr("Bienestar operativo"))
        col_izq.addWidget(self.lbl_saludo_tripulante)

        self.lbl_estado = QLabel(tr("Vigilancia nominal"))
        self.lbl_estado.setObjectName("titulo")
        self.lbl_estado.setWordWrap(True)
        col_izq.addWidget(self.lbl_estado)

        self.lbl_sub = etiqueta(tr("Evaluación emocional y ritmo circadiano"), t.T_PEQUENO, "SECUNDARIO", wrap=True)
        col_izq.addWidget(self.lbl_sub)
        col_izq.addSpacing(8)
        col_izq.addWidget(divisor())

        self.ind_pvt = FilaIndicador(tr("Vigilancia (PVT-B)"), tr("ms"))
        self.ind_sueno = FilaIndicador(tr("Descanso circadiano"), tr("h"))
        self.ind_frs = FilaIndicador(tr("Preparación de vuelo"), "%")
        self.ind_racha = FilaIndicador(tr("Racha de misión"), tr("días"))

        for fila in (self.ind_pvt, self.ind_sueno, self.ind_frs, self.ind_racha):
            col_izq.addWidget(fila)
            col_izq.addWidget(divisor())

        col_izq.addStretch(1)
        scroll_izq.setWidget(w_izq)
        raiz.addWidget(scroll_izq)

        # --- COLUMNA CENTRAL: Barra 4x2 + Banner explicativo + Stack ---
        col_centro = QVBoxLayout()
        col_centro.setSpacing(12)

        cab_nav = Tarjeta(margen=12, espacio=8)
        grid_nav = QGridLayout()
        grid_nav.setSpacing(6)
        self.grupo_secciones = QButtonGroup(self)
        self.grupo_secciones.setExclusive(True)
        self.btns_secciones: Dict[str, QPushButton] = {}
        for i, (clave, titulo_sec, _desc, _cta) in enumerate(SECCIONES_BHP):
            btn = QPushButton(tr(titulo_sec))
            btn.setObjectName("subnavFlujo")
            btn.setCheckable(True)
            btn.setMinimumHeight(44)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, c=clave: self.seleccionar_seccion(c))
            self.grupo_secciones.addButton(btn)
            self.btns_secciones[clave] = btn
            grid_nav.addWidget(btn, i // 4, i % 4)
        self.btns_secciones["bitacora"].setChecked(True)
        cab_nav.capa.addLayout(grid_nav)

        self.banner_flujo = QFrame()
        self.banner_flujo.setObjectName("flujoBanner")
        hb = QHBoxLayout(self.banner_flujo)
        hb.setContentsMargins(12, 8, 12, 8)
        self.lbl_flujo_desc = etiqueta(tr(SECCIONES_BHP[0][2]), t.T_PEQUENO, "TEXTO_SUAVE", wrap=True)
        hb.addWidget(self.lbl_flujo_desc, 1)
        cab_nav.capa.addWidget(self.banner_flujo)
        col_centro.addWidget(cab_nav)

        self.stack_secciones = QStackedWidget()
        self.sec_bitacora = self._crear_seccion_bitacora()
        self.sec_rutina = self._crear_seccion_rutina()
        self.sec_pvt = self._crear_seccion_pvt()
        self.sec_cognicion = self._crear_seccion_cognicion()
        self.sec_sueno = self._crear_seccion_sueno()
        self.sec_insignias = self._crear_seccion_insignias()
        self.sec_descompresion = self._crear_seccion_descompresion()
        self.sec_dsn = self._crear_seccion_enlace_dsn()

        self._orden_secciones = [
            "bitacora", "rutina", "pvt", "cognicion",
            "sueno", "insignias", "descompresion", "dsn",
        ]
        for w in (
            self.sec_bitacora,
            self.sec_rutina,
            self.sec_pvt,
            self.sec_cognicion,
            self.sec_sueno,
            self.sec_insignias,
            self.sec_descompresion,
            self.sec_dsn,
        ):
            self.stack_secciones.addWidget(w)
        col_centro.addWidget(self.stack_secciones, 1)

        w_centro = QWidget()
        w_centro.setLayout(col_centro)
        raiz.addWidget(w_centro, 1)

        # --- COLUMNA DERECHA (Scrollable, 310 px) ---
        scroll_der = QScrollArea()
        scroll_der.setWidgetResizable(True)
        scroll_der.setFrameShape(QFrame.NoFrame)
        scroll_der.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_der.setFixedWidth(310)
        self._scroll_der = scroll_der

        w_der = QWidget()
        col_der = QVBoxLayout(w_der)
        col_der.setContentsMargins(0, 0, 6, 0)
        col_der.setSpacing(12)

        self.card_foco = Tarjeta(margen=16, espacio=10)
        self.lbl_foco_tag = etiqueta_mono(tr("Dictamen operativo · NASA BHP"))
        self.card_foco.capa.addWidget(self.lbl_foco_tag)

        self.lbl_foco_titulo = etiqueta(tr("Apto para operaciones críticas"), t.T_DESTACADO, "TEXTO", peso=600, wrap=True)
        self.card_foco.capa.addWidget(self.lbl_foco_titulo)

        self.lbl_foco_desc = etiqueta(
            tr("Vigilancia psicomotora y ciclo circadiano dentro de los márgenes esperados."),
            t.T_CUERPO,
            "SECUNDARIO",
            wrap=True,
        )
        self.card_foco.capa.addWidget(self.lbl_foco_desc)

        self.lbl_foco_protocolo = etiqueta(
            tr("Regla de vuelo: Nominal para EVA y maniobras orbitales [POR VALIDAR]."),
            t.T_PEQUENO,
            "TERCIARIO",
            wrap=True,
        )
        self.card_foco.capa.addWidget(self.lbl_foco_protocolo)

        self.btn_accion_foco = boton(tr("Archivar entrada"), estilo="primario", al_pulsar=self._guardar_bitacora)
        self.btn_accion_foco.setMinimumHeight(t.ALTO_TOQUE)
        self.card_foco.capa.addWidget(self.btn_accion_foco)
        col_der.addWidget(self.card_foco)

        self.card_hrp = Tarjeta(margen=16, espacio=8)
        self.card_hrp.capa.addWidget(etiqueta_mono(tr("Peligro HRP #2 · Confinamiento")))
        self.lbl_hrp_criterio = etiqueta(
            tr("Criterio de escalada [POR VALIDAR]: PVT > 450 ms o sueño < 5.0 h restringe EVA."),
            t.T_PEQUENO,
            "SECUNDARIO",
            wrap=True,
        )
        self.card_hrp.capa.addWidget(self.lbl_hrp_criterio)
        self.lbl_hrp_cmo = etiqueta(
            tr("Oficial Médico (CMO): C001 · Seguimiento confidencial."),
            t.T_PEQUENO,
            "TERCIARIO",
            wrap=True,
        )
        self.card_hrp.capa.addWidget(self.lbl_hrp_cmo)
        col_der.addWidget(self.card_hrp)

        self.card_enlace = Tarjeta(margen=16, espacio=8)
        self.card_enlace.capa.addWidget(etiqueta_mono(tr("Enlace Tierra · Retardo Marte [SUPUESTO]")))
        for k_txt, v_txt, v_rol in (
            ("Retardo unidireccional:", "14m 20s", "TEXTO"),
            ("Cohesión de equipo:", "94% · Nominal", "NORMAL"),
            ("Soporte en cabina:", "Autónomo L.I.S.", "ATENCION"),
        ):
            h_f = QHBoxLayout()
            h_f.addWidget(etiqueta(tr(k_txt), t.T_PEQUENO, "SECUNDARIO", wrap=True))
            h_f.addStretch(1)
            h_f.addWidget(etiqueta(tr(v_txt), t.T_PEQUENO, v_rol, peso=600, mono=True))
            self.card_enlace.capa.addLayout(h_f)

        self.btn_abrir_dsn_der = boton(tr("Abrir enlace DSN"), al_pulsar=lambda: self.seleccionar_seccion("dsn"))
        self.btn_abrir_dsn_der.setMinimumHeight(48)
        self.card_enlace.capa.addWidget(self.btn_abrir_dsn_der)
        col_der.addWidget(self.card_enlace)

        col_der.addStretch(1)
        scroll_der.setWidget(w_der)
        raiz.addWidget(scroll_der)

    # ------------------------------------------------------------------ 1. Bitácora
    def _crear_seccion_bitacora(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_bitacora = scroll

        w_main = QWidget()
        v_main = QVBoxLayout(w_main)
        v_main.setContentsMargins(0, 0, 6, 0)
        v_main.setSpacing(12)

        card_header = Tarjeta(margen=16, espacio=8)
        h_top = QHBoxLayout()
        h_top.addWidget(etiqueta_mono(tr("CUADERNO DE BITÁCORA · CONFIDENCIAL")))
        h_top.addStretch(1)
        self.lbl_priv = QLabel(tr("USO INTERNO CMO"))
        self.lbl_priv.setAlignment(Qt.AlignCenter)
        h_top.addWidget(self.lbl_priv)
        card_header.capa.addLayout(h_top)

        self.lbl_bitacora_saludo = QLabel(tr("Hola, Tripulante"))
        self.lbl_bitacora_saludo.setWordWrap(True)
        card_header.capa.addWidget(self.lbl_bitacora_saludo)

        self.lbl_bitacora_sub = etiqueta(
            tr("Registro emocional y de adaptación en cabina."),
            t.T_CUERPO,
            "SECUNDARIO",
            wrap=True,
        )
        card_header.capa.addWidget(self.lbl_bitacora_sub)

        h_meta = QHBoxLayout()
        h_meta.setSpacing(10)
        self.lbl_res_val = etiqueta_mono(tr("Resiliencia: 94%"))
        self.lbl_cohesion_val = etiqueta_mono(tr("Cohesión: 96%"))
        self.lbl_pvt_status_val = etiqueta_mono(tr("PVT: –"))
        h_meta.addWidget(self.lbl_res_val)
        h_meta.addWidget(etiqueta("·", t.T_PEQUENO, "TERCIARIO"))
        h_meta.addWidget(self.lbl_cohesion_val)
        h_meta.addWidget(etiqueta("·", t.T_PEQUENO, "TERCIARIO"))
        h_meta.addWidget(self.lbl_pvt_status_val)
        h_meta.addStretch(1)
        card_header.capa.addLayout(h_meta)
        v_main.addWidget(card_header)

        h_tabs = QHBoxLayout()
        h_tabs.setSpacing(10)
        self.btn_tab_bitacora_form = QPushButton(tr("Nueva entrada"))
        self.btn_tab_bitacora_form.setCursor(Qt.PointingHandCursor)
        self.btn_tab_bitacora_form.setMinimumHeight(48)
        self.btn_tab_bitacora_form.clicked.connect(lambda: self._cambiar_tab_bitacora(0))
        h_tabs.addWidget(self.btn_tab_bitacora_form, 1)

        self.btn_tab_bitacora_hist = QPushButton(tr("Registros anteriores"))
        self.btn_tab_bitacora_hist.setCursor(Qt.PointingHandCursor)
        self.btn_tab_bitacora_hist.setMinimumHeight(48)
        self.btn_tab_bitacora_hist.clicked.connect(lambda: self._cambiar_tab_bitacora(1))
        h_tabs.addWidget(self.btn_tab_bitacora_hist, 1)
        v_main.addLayout(h_tabs)

        self.stack_bitacora = QStackedWidget()

        # Página 0: nueva entrada
        w_p0 = QWidget()
        v_p0 = QVBoxLayout(w_p0)
        v_p0.setContentsMargins(0, 0, 0, 0)
        card_hoja = Tarjeta(margen=18, espacio=12)

        card_hoja.capa.addWidget(etiqueta(tr("Ámbito de la entrada"), t.T_PEQUENO, "ETIQUETA", peso=600))
        grid_amb = QGridLayout()
        grid_amb.setSpacing(8)
        self.btn_cat_grupo = QButtonGroup(self)
        self.btn_cat_grupo.setExclusive(True)
        self.btns_cat: Dict[str, QPushButton] = {}
        self._categoria_bitacora_activa = "Cabina"
        categorias = [
            ("Cabina", "Hábitat"),
            ("Operaciones", "Operaciones"),
            ("Equipo", "Tripulación"),
            ("Tierra", "Tierra"),
            ("Descanso", "Descanso"),
        ]
        for i, (key, nom) in enumerate(categorias):
            b = QPushButton(tr(nom))
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setMinimumHeight(44)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._seleccionar_categoria_bitacora(k))
            self.btn_cat_grupo.addButton(b)
            self.btns_cat[key] = b
            grid_amb.addWidget(b, i // 3, i % 3)
        self.btns_cat["Cabina"].setChecked(True)
        card_hoja.capa.addLayout(grid_amb)

        card_hoja.capa.addWidget(etiqueta(tr("Estado emocional percibido"), t.T_PEQUENO, "ETIQUETA", peso=600))
        grid_ton = QGridLayout()
        grid_ton.setSpacing(8)
        self.btn_animo_grupo = QButtonGroup(self)
        self.btn_animo_grupo.setExclusive(True)
        self.btns_animo: Dict[str, QPushButton] = {}
        for i, (key, (nom, _col, _bg, _bdr)) in enumerate(_colores_animo().items()):
            b = QPushButton(tr(nom))
            b.setCheckable(True)
            b.setMinimumHeight(44)
            b.setCursor(Qt.PointingHandCursor)
            self.btn_animo_grupo.addButton(b)
            self.btns_animo[key] = b
            grid_ton.addWidget(b, i // 3, i % 3)
        self.btns_animo["nominal"].setChecked(True)
        card_hoja.capa.addLayout(grid_ton)

        self.txt_bitacora = QTextEdit()
        self.txt_bitacora.setPlaceholderText(
            tr("Documenta eventos en cabina, estado de ánimo, descanso o notas confidenciales...")
        )
        self.txt_bitacora.setMinimumHeight(140)
        card_hoja.capa.addWidget(self.txt_bitacora)

        h_foot = QHBoxLayout()
        self.lbl_bitacora_status = etiqueta(tr("Listo para archivar registro confidencial."), t.T_PEQUENO, "SECUNDARIO", wrap=True)
        h_foot.addWidget(self.lbl_bitacora_status, 1)
        self.btn_guardar_bitacora = boton(tr("Archivar entrada"), estilo="primario", al_pulsar=self._guardar_bitacora)
        self.btn_guardar_bitacora.setMinimumHeight(t.ALTO_TOQUE)
        h_foot.addWidget(self.btn_guardar_bitacora)
        card_hoja.capa.addLayout(h_foot)

        v_p0.addWidget(card_hoja)
        v_p0.addStretch(1)
        self.stack_bitacora.addWidget(w_p0)

        # Página 1: historial
        w_p1 = QWidget()
        v_p1 = QVBoxLayout(w_p1)
        v_p1.setContentsMargins(0, 0, 0, 0)
        card_hist = Tarjeta(margen=18, espacio=12)

        h_ht = QHBoxLayout()
        h_ht.addWidget(etiqueta_mono(tr("REGISTROS ARCHIVADOS")))
        h_ht.addStretch(1)
        self.lbl_hist_count = etiqueta_mono(tr("{n} registros", n=0))
        h_ht.addWidget(self.lbl_hist_count)
        card_hist.capa.addLayout(h_ht)

        grid_flt = QGridLayout()
        grid_flt.setSpacing(6)
        self.btn_filtro_grupo = QButtonGroup(self)
        self.btn_filtro_grupo.setExclusive(True)
        self.btns_filtro: Dict[str, QPushButton] = {}
        self._filtro_bitacora_activo = "Todos"
        filtros = ["Todos", "Hábitat", "Operaciones", "Tripulación", "Tierra", "Descanso"]
        for i, f_nom in enumerate(filtros):
            b_f = QPushButton(tr(f_nom))
            b_f.setObjectName("chip")
            b_f.setCheckable(True)
            b_f.setMinimumHeight(44)
            b_f.setCursor(Qt.PointingHandCursor)
            b_f.clicked.connect(lambda _=False, fn=f_nom: self._filtrar_timeline_bitacora(fn))
            self.btn_filtro_grupo.addButton(b_f)
            self.btns_filtro[f_nom] = b_f
            grid_flt.addWidget(b_f, i // 3, i % 3)
        self.btns_filtro["Todos"].setChecked(True)
        card_hist.capa.addLayout(grid_flt)

        self.contenedor_timeline = QVBoxLayout()
        self.contenedor_timeline.setSpacing(10)
        card_hist.capa.addLayout(self.contenedor_timeline)
        v_p1.addWidget(card_hist)
        v_p1.addStretch(1)
        self.stack_bitacora.addWidget(w_p1)

        v_main.addWidget(self.stack_bitacora, 1)
        self._tab_bitacora_idx = 0
        scroll.setWidget(w_main)
        return scroll

    # ------------------------------------------------------------------ 2. Rutina
    def _crear_seccion_rutina(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_rutina = scroll

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 6, 0)
        card = Tarjeta(margen=18, espacio=12)
        card.capa.addWidget(etiqueta_mono(tr("Rutina de misión · Preparación de vuelo")))
        card.capa.addWidget(
            etiqueta(
                tr("Micro-acciones diarias que sostienen el bienestar y la aptitud operativa."),
                t.T_PEQUENO,
                "SECUNDARIO",
                wrap=True,
            )
        )

        self.filas_misiones: Dict[str, QFrame] = {}
        self.badges_misiones: Dict[str, QLabel] = {}
        self.botones_accion_misiones: Dict[str, QPushButton] = {}

        misiones_def = [
            ("pvt", "Prueba de vigilancia psicomotora (PVT-B)", "+25 pts", "Completar test PVT-B o batería Stroop.", "Ir al test"),
            ("ejercicio", "Ejercicio resistivo y cardiovascular ARED", "+30 pts", "Sesión diaria para mitigar pérdida ósea.", "Registrar"),
            ("hidratacion", "Hidratación de 2.5 L en microgravedad", "+15 pts", "Compensa redistribución de fluidos.", "Registrar"),
            ("descompresion", "Descompresión y biofilia terrestre", "+20 pts", "Respiración 4-4-4-4, audio ambiental o bitácora.", "Abrir"),
            ("luz_circadiana", "Ajuste circadiano o siesta táctica", "+10 pts", "Luz de litera o siesta NASA Ames de 26 min.", "Abrir"),
        ]

        for m_id, texto, pts, subtexto, btn_txt in misiones_def:
            f = QFrame()
            f.setObjectName("filaMision")
            hf = QHBoxLayout(f)
            hf.setContentsMargins(14, 12, 14, 12)
            hf.setSpacing(10)

            v_txt = QVBoxLayout()
            v_txt.setSpacing(2)
            v_txt.addWidget(etiqueta(tr(texto), t.T_CUERPO, "TEXTO", peso=600, wrap=True))
            v_txt.addWidget(etiqueta(tr(subtexto), t.T_PEQUENO, "SECUNDARIO", wrap=True))
            hf.addLayout(v_txt, 1)

            hf.addWidget(etiqueta(tr(pts), t.T_PEQUENO, "ETIQUETA", mono=True))

            btn_act = boton(tr(btn_txt), al_pulsar=lambda mid=m_id: self._ejecutar_accion_mision(mid))
            btn_act.setMinimumHeight(48)
            self.botones_accion_misiones[m_id] = btn_act
            hf.addWidget(btn_act)

            lbl_badge = QLabel(tr("Completada"))
            lbl_badge.setMinimumHeight(44)
            lbl_badge.setAlignment(Qt.AlignCenter)
            lbl_badge.setVisible(False)
            self.badges_misiones[m_id] = lbl_badge
            hf.addWidget(lbl_badge)

            f.setCursor(Qt.PointingHandCursor)
            f.mousePressEvent = lambda _e, mid=m_id: self._enfocar_mision(mid)
            self.filas_misiones[m_id] = f
            card.capa.addWidget(f)

        v.addWidget(card)
        v.addStretch(1)
        scroll.setWidget(w)
        return scroll

    # ------------------------------------------------------------------ 3. PVT-B
    def _crear_seccion_pvt(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        card = Tarjeta(margen=18, espacio=12)
        card.capa.addWidget(etiqueta_mono(tr("Test psicomotor PVT-B · Vigilancia")))
        card.capa.addWidget(
            etiqueta(
                tr("Mide la latencia de respuesta neurocognitiva y lapsus de atención (> 500 ms) [POR VALIDAR]."),
                t.T_PEQUENO,
                "SECUNDARIO",
                wrap=True,
            )
        )

        self.frame_pvt_pantalla = QFrame()
        self.frame_pvt_pantalla.setObjectName("panelMental")
        self.frame_pvt_pantalla.setMinimumHeight(175)
        v_disp = QVBoxLayout(self.frame_pvt_pantalla)
        v_disp.setAlignment(Qt.AlignCenter)
        v_disp.setSpacing(6)

        self.lbl_pvt_ms = QLabel("000 ms")
        self.lbl_pvt_ms.setFont(QFont(t.FUENTE_MONO, 52, QFont.Light))
        self.lbl_pvt_ms.setAlignment(Qt.AlignCenter)
        v_disp.addWidget(self.lbl_pvt_ms)

        self.lbl_pvt_estado_sub = etiqueta(tr("Pulsa 'Iniciar prueba' para comenzar 3 rondas"), t.T_CUERPO, "SECUNDARIO", wrap=True)
        self.lbl_pvt_estado_sub.setAlignment(Qt.AlignCenter)
        v_disp.addWidget(self.lbl_pvt_estado_sub)
        card.capa.addWidget(self.frame_pvt_pantalla)

        h_btns = QHBoxLayout()
        h_btns.setSpacing(12)
        self.btn_iniciar_pvt = boton(tr("Iniciar prueba"), estilo="primario", al_pulsar=self._iniciar_test_pvt)
        self.btn_iniciar_pvt.setMinimumHeight(60)
        h_btns.addWidget(self.btn_iniciar_pvt, 1)

        self.btn_responder_pvt = boton(tr("Responder ahora"), estilo="primario", al_pulsar=self._reaccionar_pvt)
        self.btn_responder_pvt.setMinimumHeight(60)
        self.btn_responder_pvt.setEnabled(False)
        h_btns.addWidget(self.btn_responder_pvt, 2)
        card.capa.addLayout(h_btns)

        v.addWidget(card)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ 4. Cognición (Stroop)
    def _crear_seccion_cognicion(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        card = Tarjeta(margen=18, espacio=12)
        card.capa.addWidget(etiqueta_mono(tr("Batería cognitiva · NASA / UPenn Cognition")))
        card.capa.addWidget(
            etiqueta(
                tr("Test de conflicto Stroop: selecciona el COLOR de la tinta, no lo que dice la palabra."),
                t.T_PEQUENO,
                "SECUNDARIO",
                wrap=True,
            )
        )

        self.frame_stroop = QFrame()
        self.frame_stroop.setObjectName("panelMental")
        self.frame_stroop.setMinimumHeight(140)
        v_str = QVBoxLayout(self.frame_stroop)
        v_str.setContentsMargins(14, 14, 14, 14)
        v_str.setAlignment(Qt.AlignCenter)
        v_str.setSpacing(6)

        self.lbl_stroop_ronda = etiqueta(tr("Ronda pendiente de inicio"), t.T_PEQUENO, "ETIQUETA", mono=True, wrap=True)
        self.lbl_stroop_ronda.setAlignment(Qt.AlignCenter)
        v_str.addWidget(self.lbl_stroop_ronda)

        self.lbl_stroop_palabra = QLabel(tr("LISTO"))
        self.lbl_stroop_palabra.setFont(QFont(t.FUENTE, 34, QFont.Bold))
        self.lbl_stroop_palabra.setMinimumHeight(56)
        self.lbl_stroop_palabra.setAlignment(Qt.AlignCenter)
        v_str.addWidget(self.lbl_stroop_palabra)
        card.capa.addWidget(self.frame_stroop)

        grid_col = QGridLayout()
        grid_col.setSpacing(10)
        self.btns_stroop_colores: Dict[str, QPushButton] = {}
        for idx, (cid, nom, _hex) in enumerate(_colores_stroop()):
            b = QPushButton(tr(nom))
            b.setMinimumHeight(54)
            b.setEnabled(False)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=cid: self._responder_stroop(c))
            self.btns_stroop_colores[cid] = b
            grid_col.addWidget(b, idx // 2, idx % 2)
        card.capa.addLayout(grid_col)

        h_act = QHBoxLayout()
        self.lbl_stroop_feedback = etiqueta(tr("Batería lista (3 rondas)"), t.T_PEQUENO, "SECUNDARIO", wrap=True)
        h_act.addWidget(self.lbl_stroop_feedback, 1)
        self.btn_iniciar_stroop = boton(tr("Iniciar batería"), estilo="primario", al_pulsar=self._iniciar_test_stroop)
        self.btn_iniciar_stroop.setMinimumHeight(t.ALTO_TOQUE)
        h_act.addWidget(self.btn_iniciar_stroop)
        card.capa.addLayout(h_act)

        v.addWidget(card)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ 5. Sueño
    def _crear_seccion_sueno(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_sueno = scroll

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 6, 0)
        card = Tarjeta(margen=18, espacio=12)
        card.capa.addWidget(etiqueta_mono(tr("Ritmo circadiano · Serie de descanso")))
        card.capa.addWidget(
            etiqueta(
                tr("Horas de sueño frente a la línea base pre-vuelo [SUPUESTO]."),
                t.T_PEQUENO,
                "SECUNDARIO",
                wrap=True,
            )
        )

        self.grafica_sueno = GraficaTendencia(alto=130)
        card.capa.addWidget(self.grafica_sueno)
        card.capa.addWidget(divisor())

        h_luz = QHBoxLayout()
        h_luz.setSpacing(12)
        v_luz = QVBoxLayout()
        v_luz.addWidget(etiqueta(tr("Iluminación espectral de cabina"), t.T_DESTACADO, "TEXTO", peso=600, wrap=True))
        v_luz.addWidget(etiqueta(tr("Azul 460 nm vigilia · Ámbar 600 nm descanso"), t.T_PEQUENO, "SECUNDARIO", wrap=True))
        h_luz.addLayout(v_luz, 1)
        self.btn_luz = boton(tr("Modo vigilia"), estilo="primario", al_pulsar=self._alternar_luz)
        self.btn_luz.setMinimumHeight(t.ALTO_TOQUE)
        h_luz.addWidget(self.btn_luz)
        card.capa.addLayout(h_luz)
        card.capa.addWidget(divisor())

        h_siesta = QHBoxLayout()
        h_siesta.setSpacing(12)
        v_s = QVBoxLayout()
        v_s.addWidget(etiqueta(tr("Siesta táctica · NASA Ames (26 min)"), t.T_DESTACADO, "TEXTO", peso=600, wrap=True))
        self.lbl_siesta_estado = etiqueta(tr("En espera · Cabina lista (26:00 min)"), t.T_PEQUENO, "ETIQUETA", mono=True, wrap=True)
        v_s.addWidget(self.lbl_siesta_estado)
        h_siesta.addLayout(v_s, 1)

        v_sb = QVBoxLayout()
        v_sb.setSpacing(8)
        self.btn_siesta = boton(tr("Iniciar siesta (26m)"), estilo="primario", al_pulsar=self._toggle_siesta)
        self.btn_siesta.setMinimumHeight(t.ALTO_TOQUE)
        v_sb.addWidget(self.btn_siesta)
        self.btn_siesta_simular = boton(tr("Concluir siesta (+10 pts)"), al_pulsar=self._completar_siesta)
        self.btn_siesta_simular.setMinimumHeight(48)
        self.btn_siesta_simular.setVisible(False)
        v_sb.addWidget(self.btn_siesta_simular)
        h_siesta.addLayout(v_sb)
        card.capa.addLayout(h_siesta)

        v.addWidget(card)
        v.addStretch(1)
        scroll.setWidget(w)
        return scroll

    # ------------------------------------------------------------------ 6. Insignias
    def _crear_seccion_insignias(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_insignias = scroll

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 6, 0)
        card = Tarjeta(margen=18, espacio=12)
        card.capa.addWidget(etiqueta_mono(tr("Vitrina de logros · Rendimiento de vuelo")))
        card.capa.addWidget(
            etiqueta(
                tr("Toca una insignia para ver su criterio operativo."),
                t.T_PEQUENO,
                "SECUNDARIO",
                wrap=True,
            )
        )

        self.cards_insignias: Dict[str, QFrame] = {}
        self.badges_insignias: Dict[str, QLabel] = {}
        ins_meta = [
            ("mercurio", "Reflejos de Mercurio", "PVT < 300 ms [POR VALIDAR]",
             "Latencia media inferior a 300 ms y 0 lapsus en test de vigilancia.",
             "Reacción rápida en acoplamiento y despresurización."),
            ("centinela", "Centinela Circadiano", "Sueño > 6.5 h [POR VALIDAR]",
             "Sostener descanso nominal o ajustar iluminación/siesta táctica.",
             "Mitiga desincronización circadiana en vuelo."),
            ("biofilia", "Conexión Terrestre", "Biofilia 0G",
             "Completar sesión de respiración 4-4-4-4 o audio biofílico.",
             "Mitiga sobrecarga acústica de cabina y aislamiento."),
            ("marte", "Listo para Marte", "100% Rutina",
             "Completar todas las misiones diarias de bienestar.",
             "Indicador integrado de preparación del día [SUPUESTO]."),
        ]
        grid = QGridLayout()
        grid.setSpacing(10)
        for idx, (iid, nombre, tag, objetivo, relevancia) in enumerate(ins_meta):
            f = QFrame()
            f.setObjectName("celdaTactil")
            v_ins = QVBoxLayout(f)
            v_ins.setContentsMargins(14, 14, 14, 14)
            v_ins.setSpacing(6)
            h_top = QHBoxLayout()
            h_top.addWidget(etiqueta(tr(nombre), t.T_CUERPO, "TEXTO", peso=600, wrap=True), 1)
            badge = QLabel(tr("Pendiente"))
            badge.setAlignment(Qt.AlignCenter)
            h_top.addWidget(badge)
            v_ins.addLayout(h_top)
            v_ins.addWidget(etiqueta(tr(tag), t.T_PEQUENO, "ETIQUETA", mono=True, wrap=True))
            v_ins.addWidget(etiqueta(tr(objetivo), t.T_PEQUENO, "SECUNDARIO", wrap=True))
            f.setCursor(Qt.PointingHandCursor)
            f.mousePressEvent = lambda _e, k=iid, n=nombre, r=relevancia, o=objetivo: self._on_insignia_seleccionada(k, n, r, o)
            self.cards_insignias[iid] = f
            self.badges_insignias[iid] = badge
            grid.addWidget(f, idx // 2, idx % 2)
        card.capa.addLayout(grid)
        v.addWidget(card)
        v.addStretch(1)
        scroll.setWidget(w)
        return scroll

    # ------------------------------------------------------------------ 7. Descompresión & Biofilia
    def _crear_seccion_descompresion(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_descompresion = scroll

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(12)

        card = Tarjeta(margen=18, espacio=12)
        card.capa.addWidget(etiqueta_mono(tr("Descompresión autonómica · Biofilia 0G")))
        card.capa.addWidget(
            etiqueta(
                tr("Respiración guiada Box Breathing (4-4-4-4) y paisaje sonoro terrestre continuo."),
                t.T_PEQUENO,
                "SECUNDARIO",
                wrap=True,
            )
        )

        v_orbe = QVBoxLayout()
        v_orbe.setAlignment(Qt.AlignCenter)
        v_orbe.setSpacing(10)
        self.orbe_resp = OrbeRespiracion()
        v_orbe.addWidget(self.orbe_resp, 0, Qt.AlignCenter)
        self.btn_resp = boton(tr("Iniciar respiración 4x4"), estilo="primario", al_pulsar=self._toggle_respiracion)
        self.btn_resp.setMinimumHeight(t.ALTO_TOQUE)
        v_orbe.addWidget(self.btn_resp)
        card.capa.addLayout(v_orbe)

        card.capa.addWidget(divisor())

        card.capa.addWidget(etiqueta(tr("Audio biofílico terrestre"), t.T_DESTACADO, "TEXTO", peso=600, wrap=True))
        card.capa.addWidget(
            etiqueta(
                tr("Paisajes acústicos reales en bucle para mitigar el ruido continuo de cabina."),
                t.T_PEQUENO,
                "SECUNDARIO",
                wrap=True,
            )
        )
        h_tipos = QHBoxLayout()
        h_tipos.setSpacing(8)
        self.btn_lluvia = QPushButton(tr("Lluvia"))
        self.btn_bosque = QPushButton(tr("Bosque"))
        self.btn_oceano = QPushButton(tr("Océano"))
        for b, tipo in ((self.btn_lluvia, "lluvia"), (self.btn_bosque, "bosque"), (self.btn_oceano, "oceano")):
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setMinimumHeight(48)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, tp=tipo: self._cambiar_audio(tp))
            h_tipos.addWidget(b, 1)
        self.btn_lluvia.setChecked(True)
        card.capa.addLayout(h_tipos)

        self.btn_play_audio = boton(tr("Reproducir sonido"), al_pulsar=self._toggle_audio)
        self.btn_play_audio.setMinimumHeight(t.ALTO_TOQUE)
        card.capa.addWidget(self.btn_play_audio)

        v.addWidget(card)
        v.addStretch(1)
        scroll.setWidget(w)
        return scroll

    # ------------------------------------------------------------------ 8. Enlace DSN
    def _crear_seccion_enlace_dsn(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_dsn = scroll

        w_main = QWidget()
        v_main = QVBoxLayout(w_main)
        v_main.setContentsMargins(0, 0, 6, 0)
        v_main.setSpacing(12)

        # 1. Red DSN [SUPUESTO]
        card_dsn = Tarjeta(margen=16, espacio=10)
        h_top = QHBoxLayout()
        h_top.addWidget(etiqueta_mono(tr("RED DE ESPACIO PROFUNDO (DSN) · SIMULACIÓN [SUPUESTO]")), 1)
        self.lbl_dsn_badge_estado = QLabel(tr("BÚFER LOCAL"))
        self.lbl_dsn_badge_estado.setAlignment(Qt.AlignCenter)
        h_top.addWidget(self.lbl_dsn_badge_estado)
        card_dsn.capa.addLayout(h_top)

        grid_m = QGridLayout()
        grid_m.setSpacing(8)
        self.labels_dsn_telemetria: Dict[str, QLabel] = {}
        for i, (tit, val, rol) in enumerate((
            ("Estación:", "Madrid DSS-63", "TEXTO"),
            ("Retardo ida:", "14m 20s", "ATENCION"),
            ("Próximo pase:", "02h 34m 18s", "NORMAL"),
            ("Búfer:", "1 recibido · 0 en cola", "TEXTO"),
        )):
            f_m = QFrame()
            f_m.setObjectName("cajaDsn")
            self._frames_dsn_cajas.append(f_m)
            vm = QVBoxLayout(f_m)
            vm.setContentsMargins(10, 8, 10, 8)
            vm.addWidget(etiqueta(tr(tit), t.T_PEQUENO, "TERCIARIO"))
            lv = etiqueta(tr(val), t.T_PEQUENO, rol, peso=700, mono=True)
            vm.addWidget(lv)
            self.labels_dsn_telemetria[tit] = lv
            grid_m.addWidget(f_m, i // 2, i % 2)
        card_dsn.capa.addLayout(grid_m)
        v_main.addWidget(card_dsn)

        # 2. Cápsula entrante
        card_rec = Tarjeta(margen=16, espacio=10)
        card_rec.capa.addWidget(etiqueta_mono(tr("CÁPSULA PERSONAL ENTRANTE · CANAL CONFIDENCIAL")))
        self.lbl_dsn_mensaje_sub = etiqueta(
            tr("Mensaje familiar sincronizado desde Houston [SUPUESTO]."),
            t.T_PEQUENO,
            "SECUNDARIO",
            wrap=True,
        )
        card_rec.capa.addWidget(self.lbl_dsn_mensaje_sub)

        self.f_player_dsn = QFrame()
        self.f_player_dsn.setObjectName("panelMental")
        v_pl = QVBoxLayout(self.f_player_dsn)
        v_pl.setContentsMargins(12, 12, 12, 12)
        v_pl.setSpacing(8)
        h_pt = QHBoxLayout()
        self.lbl_dsn_audio_tit = etiqueta(tr("Mensaje de voz familiar"), t.T_CUERPO, "TEXTO", peso=600)
        h_pt.addWidget(self.lbl_dsn_audio_tit, 1)
        self.lbl_dsn_audio_tiempo = etiqueta_mono("00:00 / 01:45")
        h_pt.addWidget(self.lbl_dsn_audio_tiempo)
        v_pl.addLayout(h_pt)

        self.prog_dsn_audio = QProgressBar()
        self.prog_dsn_audio.setRange(0, 105)
        self.prog_dsn_audio.setValue(0)
        self.prog_dsn_audio.setTextVisible(False)
        self.prog_dsn_audio.setFixedHeight(8)
        v_pl.addWidget(self.prog_dsn_audio)

        h_pb = QHBoxLayout()
        self.btn_dsn_audio_play = boton(tr("Reproducir mensaje"), estilo="primario", al_pulsar=self._toggle_dsn_audio)
        self.btn_dsn_audio_play.setMinimumHeight(48)
        h_pb.addWidget(self.btn_dsn_audio_play)
        self.btn_dsn_audio_stop = boton(tr("Detener"), al_pulsar=self._stop_dsn_audio)
        self.btn_dsn_audio_stop.setMinimumHeight(48)
        h_pb.addWidget(self.btn_dsn_audio_stop)
        h_pb.addStretch(1)
        v_pl.addLayout(h_pb)
        card_rec.capa.addWidget(self.f_player_dsn)

        self.lbl_dsn_transcripcion = etiqueta(
            tr("«Te dejamos este mensaje antes de salir. Todos en casa estamos bien y muy orgullosos de ti. Mantente firme en la estación.»"),
            t.T_PEQUENO,
            "TEXTO_SUAVE",
            wrap=True,
        )
        card_rec.capa.addWidget(self.lbl_dsn_transcripcion)
        v_main.addWidget(card_rec)

        # 3. Grabador de retorno
        card_grab = Tarjeta(margen=16, espacio=10)
        card_grab.capa.addWidget(etiqueta_mono(tr("CÁPSULA DE RETORNO A TIERRA · BORRADOR LOCAL")))

        h_dest = QHBoxLayout()
        h_dest.setSpacing(6)
        self.btn_dsn_dest_grupo = QButtonGroup(self)
        self.btn_dsn_dest_grupo.setExclusive(True)
        self.btns_dsn_dest: Dict[str, QPushButton] = {}
        for key, nom, chk in (
            ("familia", "Familia", True),
            ("capcom", "Capcom", False),
            ("bhp", "Soporte BHP", False),
        ):
            b = QPushButton(tr(nom))
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(chk)
            b.setMinimumHeight(44)
            b.setCursor(Qt.PointingHandCursor)
            self.btn_dsn_dest_grupo.addButton(b)
            self.btns_dsn_dest[key] = b
            h_dest.addWidget(b)
        h_dest.addStretch(1)
        card_grab.capa.addLayout(h_dest)

        self.f_rec_box = QFrame()
        self.f_rec_box.setObjectName("panelMental")
        v_rb = QVBoxLayout(self.f_rec_box)
        v_rb.setContentsMargins(12, 12, 12, 12)
        v_rb.setSpacing(8)

        h_rstat = QHBoxLayout()
        self.lbl_dsn_rec_tiempo = QLabel("00:00")
        self.lbl_dsn_rec_tiempo.setFont(QFont(t.FUENTE_MONO, 24, QFont.Bold))
        h_rstat.addWidget(self.lbl_dsn_rec_tiempo)
        v_rt = QVBoxLayout()
        self.lbl_dsn_rec_status = etiqueta(tr("Listo para captura de nota de voz [SIMULACIÓN]."), t.T_PEQUENO, "SECUNDARIO", wrap=True)
        v_rt.addWidget(self.lbl_dsn_rec_status)
        h_rstat.addLayout(v_rt, 1)

        h_vu = QHBoxLayout()
        h_vu.setSpacing(3)
        self.dsn_vu_leds: List[QFrame] = []
        for _ in range(10):
            led = QFrame()
            led.setFixedSize(7, 22)
            h_vu.addWidget(led)
            self.dsn_vu_leds.append(led)
        h_rstat.addLayout(h_vu)
        v_rb.addLayout(h_rstat)

        h_rbtns = QHBoxLayout()
        self.btn_dsn_rec_toggle = boton(tr("Iniciar grabación"), al_pulsar=self._toggle_dsn_rec)
        self.btn_dsn_rec_toggle.setMinimumHeight(48)
        h_rbtns.addWidget(self.btn_dsn_rec_toggle)
        self.btn_dsn_rec_reset = boton(tr("Descartar"), al_pulsar=self._reset_dsn_rec)
        self.btn_dsn_rec_reset.setMinimumHeight(48)
        self.btn_dsn_rec_reset.setEnabled(False)
        h_rbtns.addWidget(self.btn_dsn_rec_reset)
        h_rbtns.addStretch(1)
        v_rb.addLayout(h_rbtns)
        card_grab.capa.addWidget(self.f_rec_box)

        self.txt_dsn_nota = QTextEdit()
        self.txt_dsn_nota.setPlaceholderText(tr("Nota escrita opcional para adjuntar a la cápsula de retorno..."))
        self.txt_dsn_nota.setFixedHeight(68)
        card_grab.capa.addWidget(self.txt_dsn_nota)

        h_enc = QHBoxLayout()
        self.lbl_dsn_encolar_status = etiqueta(tr("En espera de captura o nota."), t.T_PEQUENO, "SECUNDARIO", wrap=True)
        h_enc.addWidget(self.lbl_dsn_encolar_status, 1)
        self.btn_dsn_encolar = boton(tr("Encolar cápsula"), estilo="primario", al_pulsar=self._encolar_paquete_dsn)
        self.btn_dsn_encolar.setMinimumHeight(t.ALTO_TOQUE)
        self.btn_dsn_encolar.setEnabled(False)
        h_enc.addWidget(self.btn_dsn_encolar)
        card_grab.capa.addLayout(h_enc)
        v_main.addWidget(card_grab)

        card_cola = Tarjeta(margen=16, espacio=10)
        h_ct = QHBoxLayout()
        h_ct.addWidget(etiqueta_mono(tr("BÚFER DE TRANSMISIÓN DSN")))
        h_ct.addStretch(1)
        self.lbl_dsn_cola_count = etiqueta_mono(tr("{n} en cola", n=0))
        h_ct.addWidget(self.lbl_dsn_cola_count)
        card_cola.capa.addLayout(h_ct)
        self.contenedor_dsn_cola = QVBoxLayout()
        self.contenedor_dsn_cola.setSpacing(6)
        card_cola.capa.addLayout(self.contenedor_dsn_cola)
        v_main.addWidget(card_cola)

        v_main.addStretch(1)
        scroll.setWidget(w_main)
        return scroll

    # ------------------------------------------------------------------ Tema
    def aplicar_tema(self) -> None:
        self.lbl_saludo_tripulante.setStyleSheet(
            f"color: {t.NORMAL}; font-size: {t.T_DESTACADO}px; font-weight: 700;"
        )
        self.lbl_bitacora_saludo.setStyleSheet(
            f"color: {t.NORMAL}; font-size: 20px; font-weight: 700;"
        )
        self.lbl_priv.setStyleSheet(
            f"background: {t.FONDO}; border: 1px solid {t.BORDE}; border-radius: 6px;"
            f"padding: 4px 10px; font-size: {t.T_PEQUENO}px; color: {t.NORMAL};"
            f"font-family: {t.FUENTE_MONO}; font-weight: 600;"
        )
        self.lbl_dsn_badge_estado.setStyleSheet(
            f"font-size: {t.T_PEQUENO}px; font-weight: 700; color: {t.NORMAL};"
            f"background: {t.INSIGNIA_OK_BG}; border: 1px solid {t.INSIGNIA_OK_BORDE};"
            f"border-radius: 6px; padding: 4px 10px; font-family: {t.FUENTE_MONO};"
        )
        css_scroll = _estilo_scroll()
        for attr in (
            "_scroll_izq", "_scroll_der", "_scroll_bitacora", "_scroll_rutina",
            "_scroll_sueno", "_scroll_insignias", "_scroll_descompresion", "_scroll_dsn",
        ):
            sc = getattr(self, attr, None)
            if sc is not None:
                sc.setStyleSheet(css_scroll)

        box_css = f"QFrame#panelMental {{ background: {t.FONDO}; border: 1px solid {t.BORDE}; border-radius: 14px; }}"
        self.frame_pvt_pantalla.setStyleSheet(box_css)
        self.frame_stroop.setStyleSheet(box_css)
        self.f_player_dsn.setStyleSheet(box_css)
        self.f_rec_box.setStyleSheet(box_css)
        for fm in self._frames_dsn_cajas:
            fm.setStyleSheet(
                f"QFrame#cajaDsn {{ background: {t.FONDO}; border: 1px solid {t.BORDE}; border-radius: 8px; }}"
            )
        for fp in self._frames_dsn_enviados:
            fp.setStyleSheet(
                f"QFrame#cajaDsnEnv {{ background: {t.INSIGNIA_OK_BG}; border: 1px solid {t.INSIGNIA_OK_BORDE}; border-radius: 8px; }}"
            )

        edit_css = (
            f"QTextEdit {{ background: {t.FONDO}; border: 1px solid {t.BORDE}; border-radius: 10px;"
            f" color: {t.TEXTO}; padding: 12px 14px; font-size: {t.T_CUERPO}px; }}"
            f"QTextEdit:focus {{ border-color: {t.NORMAL}; }}"
        )
        self.txt_bitacora.setStyleSheet(edit_css)
        self.txt_dsn_nota.setStyleSheet(edit_css)

        for key, (nom, col_txt, bg_chk, bdr_chk) in _colores_animo().items():
            b = self.btns_animo.get(key)
            if b is not None:
                b.setStyleSheet(
                    f"QPushButton {{ background: {t.FONDO}; border: 1px solid {t.BORDE}; border-radius: 10px;"
                    f" padding: 6px 12px; color: {t.TEXTO_SUAVE}; font-size: {t.T_PEQUENO}px; }}"
                    f"QPushButton:hover {{ border-color: {t.TEXTO}; color: {t.TEXTO}; }}"
                    f"QPushButton:checked {{ background: {bg_chk}; border: 1.5px solid {bdr_chk}; color: {col_txt}; font-weight: 600; }}"
                )
        for cid, _nom, hex_col in _colores_stroop():
            b = self.btns_stroop_colores.get(cid)
            if b is not None:
                b.setStyleSheet(
                    f"QPushButton {{ background: {t.FONDO}; border: 1.5px solid {hex_col}; border-radius: 12px;"
                    f" color: {hex_col}; font-size: {t.T_CUERPO}px; font-weight: 600; }}"
                    f"QPushButton:hover {{ background: {t.HOVER}; }}"
                    f"QPushButton:disabled {{ border-color: {t.BORDE}; color: {t.TERCIARIO}; }}"
                )
        self.prog_dsn_audio.setStyleSheet(
            f"QProgressBar {{ background: {t.BORDE}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {t.NORMAL}; border-radius: 4px; }}"
        )
        self.lbl_dsn_rec_tiempo.setStyleSheet(f"color: {t.NORMAL};")
        self.lbl_pvt_ms.setStyleSheet(f"color: {t.NORMAL};")
        self.orbe_resp.aplicar_tema()
        self._cambiar_tab_bitacora(getattr(self, "_tab_bitacora_idx", 0))
        self.refrescar()

    # ------------------------------------------------------------------ Navegación interna
    def _marcar_seccion_ui(self, clave_o_nombre: str) -> None:
        busq = clave_o_nombre.strip().lower()
        target = "bitacora"
        for clave, titulo, _d, _c in SECCIONES_BHP:
            if busq in (clave.lower(), titulo.lower(), tr(titulo).lower()):
                target = clave
                break
        if target in self.btns_secciones:
            self.btns_secciones[target].setChecked(True)
        self._aplicar_seccion(target)

    def seleccionar_seccion(self, clave: str) -> None:
        if clave in self.btns_secciones:
            self.btns_secciones[clave].setChecked(True)
        self._aplicar_seccion(clave)

    def _aplicar_seccion(self, clave: str) -> None:
        if clave not in self._orden_secciones:
            return
        self._seccion_actual = clave
        idx = self._orden_secciones.index(clave)
        self.stack_secciones.setCurrentIndex(idx)
        for c, _t, desc, cta in SECCIONES_BHP:
            if c == clave:
                self.lbl_flujo_desc.setText(tr(desc))
                self.btn_accion_foco.setText(tr(cta))
                break
        try:
            self.btn_accion_foco.clicked.disconnect()
        except Exception:
            pass
        acciones = {
            "bitacora": self._guardar_bitacora,
            "rutina": lambda: self.seleccionar_seccion("pvt"),
            "pvt": self._iniciar_test_pvt,
            "cognicion": self._iniciar_test_stroop,
            "sueno": self._alternar_luz,
            "insignias": lambda: self.seleccionar_seccion("rutina"),
            "descompresion": self._toggle_respiracion,
            "dsn": self._toggle_dsn_rec,
        }
        self.btn_accion_foco.clicked.connect(acciones[clave])
        if self._triage_actual:
            self._aplicar_triage(self._triage_actual)

    # ------------------------------------------------------------------ Refresco
    def refrescar(self) -> None:
        crew_id = self.state.crew_id
        info = self._info_tripulante(crew_id)

        self.lbl_saludo_tripulante.setText(info["saludo"])
        self.lbl_sub.setText(f"{info['nombre_completo']} · {info['rol']}")
        self.lbl_bitacora_saludo.setText(info["saludo"])
        self.lbl_bitacora_sub.setText(f"{info['nombre_completo']} · {info['mision']}")
        self.lbl_dsn_audio_tit.setText(
            tr("Mensaje familiar para {nombre} ({tp})", nombre=info["nombre_corto"], tp=self.state.timepoint)
        )

        estado_gam = obtener_estado_gamificacion(crew_id)
        racha = int(estado_gam.get("rachaDias", 12) or 12)
        score = int(estado_gam.get("score", 0) or 0)

        self.lbl_res_val.setText(tr("Resiliencia: {n}%", n=min(99, max(88, int(86 + score * 0.12)))))
        self.lbl_cohesion_val.setText(tr("Cohesión: {n}%", n=96))
        self.lbl_pvt_status_val.setText(
            tr("PVT: {ms} ms", ms=int(self._pvt_intentos[-1])) if self._pvt_intentos else tr("PVT: –")
        )

        self._recargar_timeline_bitacora()

        cabina_data = get_cabina_dataset()
        tripulante = cabina_data.get("tripulantes", {}).get(crew_id, {})
        horas_s = float(tripulante.get("horasSueno", 6.8) or 6.8)
        base_s = float(tripulante.get("baseHorasSueno", 7.2) or 7.2)

        pvt_val = int(self._pvt_intentos[-1]) if self._pvt_intentos else "–"
        self.ind_pvt.actualizar(pvt_val, tr("objetivo < 355 ms"), insignia=(isinstance(pvt_val, int) and pvt_val < 355))
        self.ind_sueno.actualizar(f"{horas_s:.1f}", tr("base {b:.1f}", b=base_s), insignia=(horas_s >= 6.5))
        self.ind_frs.actualizar(f"{score}", tr("meta 100"), insignia=(score >= 80))
        self.ind_racha.actualizar(f"{racha}", tr("nominal"), insignia=(racha >= 7))

        triage_res = evaluar_salud_mental_determinista(
            horas_sueno=horas_s,
            pvt_latencia_ms=self._pvt_intentos[-1] if self._pvt_intentos else 0.0,
            pvt_lapsus=self._pvt_lapsus,
        )
        self._triage_actual = triage_res
        self._aplicar_triage(triage_res)

        for m in estado_gam.get("misiones", []):
            mid = m.get("id")
            comp = bool(m.get("completada", False))
            btn_act = self.botones_accion_misiones.get(mid)
            lbl_badge = self.badges_misiones.get(mid)
            fila = self.filas_misiones.get(mid)
            if btn_act and lbl_badge and fila:
                btn_act.setVisible(not comp)
                lbl_badge.setVisible(comp)
                if comp:
                    lbl_badge.setStyleSheet(
                        f"font-size: {t.T_PEQUENO}px; font-weight: 600; color: {t.NORMAL};"
                        f"background: {t.INSIGNIA_OK_BG}; border: 1px solid {t.INSIGNIA_OK_BORDE};"
                        f"border-radius: 10px; padding: 6px 14px;"
                    )
                    fila.setStyleSheet(
                        f"QFrame#filaMision {{ background: {t.INSIGNIA_OK_BG}; border: 1px solid {t.INSIGNIA_OK_BORDE}; border-radius: 12px; }}"
                    )
                else:
                    fila.setStyleSheet(
                        f"QFrame#filaMision {{ background: {t.FONDO}; border: 1px solid {t.BORDE}; border-radius: 12px; }}"
                    )

        for ins in estado_gam.get("insignias", []):
            iid = ins.get("id")
            desb = bool(ins.get("desbloqueada", False))
            card = self.cards_insignias.get(iid)
            badge = self.badges_insignias.get(iid)
            if card and badge:
                if desb:
                    card.setStyleSheet(
                        f"QFrame#celdaTactil {{ background: {t.INSIGNIA_OK_BG}; border: 1.5px solid {t.INSIGNIA_OK_BORDE}; border-radius: 14px; }}"
                    )
                    badge.setText(tr("Desbloqueada"))
                    badge.setStyleSheet(
                        f"font-size: {t.T_PEQUENO}px; font-weight: 600; color: {t.NORMAL};"
                        f"background: {t.INSIGNIA_OK_BG}; border: 1px solid {t.INSIGNIA_OK_BORDE};"
                        f"border-radius: 8px; padding: 4px 10px;"
                    )
                else:
                    card.setStyleSheet(
                        f"QFrame#celdaTactil {{ background: {t.FONDO}; border: 1px solid {t.BORDE}; border-radius: 14px; }}"
                    )
                    badge.setText(tr("Pendiente"))
                    badge.setStyleSheet(
                        f"font-size: {t.T_PEQUENO}px; color: {t.TERCIARIO};"
                        f"border: 1px solid {t.BORDE}; border-radius: 8px; padding: 4px 10px;"
                    )

        serie_sueno = [
            {"timepoint": "L-92", "valor": base_s + 0.2},
            {"timepoint": "L-44", "valor": base_s},
            {"timepoint": "L-3", "valor": base_s - 0.4},
            {"timepoint": "R+1", "valor": horas_s - 0.8},
            {"timepoint": "R+45", "valor": horas_s - 0.2},
            {"timepoint": "R+82", "valor": horas_s},
            {"timepoint": "R+194", "valor": horas_s},
        ]
        self.grafica_sueno.cargar(serie_sueno, rango_min=5.0, rango_max=9.0, activo=self.state.timepoint)

    def _aplicar_triage(self, triage_res: Dict[str, Any]) -> None:
        nivel = triage_res.get("nivel", "verde")
        colores = {
            "verde": (t.NORMAL, "Vigilancia nominal"),
            "amarillo": (t.ATENCION, "Alerta de fatiga"),
            "rojo": (t.ALERTA, "Restricción operativa"),
        }
        col, txt_estado = colores.get(nivel, (t.NORMAL, "Vigilancia nominal"))
        self.lbl_estado.setText(tr(txt_estado))
        self.lbl_foco_titulo.setText(triage_res.get("titulo", tr("Nominal")))
        self.lbl_foco_titulo.setStyleSheet(f"color: {col}; font-size: {t.T_DESTACADO}px; font-weight: 600;")
        self.lbl_foco_desc.setText(triage_res.get("razon", ""))
        self.lbl_foco_protocolo.setText(triage_res.get("accion", ""))

    def _on_insignia_seleccionada(self, _iid: str, nombre: str, relevancia: str, objetivo: str) -> None:
        self.lbl_foco_tag.setText(tr("Detalle de logro · Misión espacial"))
        self.lbl_foco_titulo.setText(tr(nombre))
        self.lbl_foco_titulo.setStyleSheet(f"color: {t.NORMAL}; font-size: {t.T_DESTACADO}px; font-weight: 600;")
        self.lbl_foco_desc.setText(tr(objetivo))
        self.lbl_foco_protocolo.setText(tr("Relevancia operativa: {r}", r=tr(relevancia)))

    # ------------------------------------------------------------------ PVT-B
    def _iniciar_test_pvt(self) -> None:
        self._pvt_intentos = []
        self._pvt_lapsus = 0
        self.btn_iniciar_pvt.setEnabled(False)
        self._preparar_siguiente_intento_pvt()

    def _preparar_siguiente_intento_pvt(self) -> None:
        self._pvt_estado = "esperando"
        self.lbl_pvt_ms.setStyleSheet(f"color: {t.ALERTA};")
        self.lbl_pvt_ms.setText(tr("ESPERE..."))
        self.lbl_pvt_estado_sub.setText(
            tr("Ronda {r} de 3 · Mantén la vista al centro.", r=len(self._pvt_intentos) + 1)
        )
        self.btn_responder_pvt.setEnabled(False)
        self._pvt_timer.start(random.randint(1500, 3200))

    def _on_pvt_disparo(self) -> None:
        self._pvt_timer.stop()
        self._pvt_estado = "reaccionar"
        self._pvt_ts_inicio = time.monotonic()
        self.lbl_pvt_ms.setStyleSheet(f"color: {t.NORMAL};")
        self.lbl_pvt_ms.setText("000 ms")
        self.lbl_pvt_estado_sub.setText(tr("Toca 'Responder ahora'"))
        self.btn_responder_pvt.setEnabled(True)
        self._pvt_anim_timer.start()

    def _on_pvt_tick(self) -> None:
        if self._pvt_estado == "reaccionar":
            ms = int((time.monotonic() - self._pvt_ts_inicio) * 1000)
            self.lbl_pvt_ms.setText(f"{ms} ms")
            if ms > 500:
                self.lbl_pvt_ms.setStyleSheet(f"color: {t.ATENCION};")

    def _reaccionar_pvt(self) -> None:
        if self._pvt_estado != "reaccionar":
            return
        self._pvt_anim_timer.stop()
        latencia_ms = (time.monotonic() - self._pvt_ts_inicio) * 1000.0
        self._pvt_intentos.append(latencia_ms)
        if latencia_ms > 500.0:
            self._pvt_lapsus += 1
        self.btn_responder_pvt.setEnabled(False)

        if len(self._pvt_intentos) < 3:
            self.lbl_pvt_ms.setText(f"{int(latencia_ms)} ms")
            QTimer.singleShot(700, self._preparar_siguiente_intento_pvt)
            return

        self._pvt_estado = "completado"
        media_ms = sum(self._pvt_intentos) / len(self._pvt_intentos)
        self.lbl_pvt_ms.setStyleSheet(f"color: {t.TEXTO};")
        self.lbl_pvt_ms.setText(f"{int(media_ms)} ms")
        self.lbl_pvt_estado_sub.setText(
            tr("Prueba completada · Latencia media: {ms} ms · Lapsus: {lap}", ms=int(media_ms), lap=self._pvt_lapsus)
        )
        self.btn_iniciar_pvt.setEnabled(True)

        crew_id = self.state.crew_id
        cabina = get_cabina_dataset()
        horas_s = float(cabina.get("tripulantes", {}).get(crew_id, {}).get("horasSueno", 6.8) or 6.8)
        eval_res = evaluar_salud_mental_determinista(
            horas_sueno=horas_s,
            pvt_latencia_ms=media_ms,
            pvt_lapsus=self._pvt_lapsus,
        )
        guardar_evaluacion_mental(
            crew_id=crew_id,
            timepoint=self.state.timepoint,
            horas_sueno=horas_s,
            nivel_estres=3,
            animo=4,
            fatiga=2 if media_ms < 350 else 5,
            aislamiento=3,
            pvt_latencia_ms=media_ms,
            pvt_lapsus=self._pvt_lapsus,
            nivel_triage=eval_res["nivel"],
            notas="[Operaciones] Test PVT-B de 3 rondas completado.",
        )
        marcar_mision_gamificacion(crew_id, "pvt", True)
        if media_ms < 300.0 and self._pvt_lapsus == 0:
            desbloquear_insignia(crew_id, "mercurio")
        self.refrescar()

    # ------------------------------------------------------------------ Rutina y confirmaciones
    def _ejecutar_accion_mision(self, mid: str) -> None:
        if mid == "pvt":
            self.seleccionar_seccion("pvt")
        elif mid == "descompresion":
            self.seleccionar_seccion("descompresion")
        elif mid == "luz_circadiana":
            self.seleccionar_seccion("sueno")
        elif mid == "ejercicio":
            self._registrar_ejercicio()
        elif mid == "hidratacion":
            self._registrar_hidratacion()

    def _enfocar_mision(self, mid: str) -> None:
        self._ejecutar_accion_mision(mid)

    def _confirmar_dialogo(self, titulo: str, cuerpo: str, txt_ok: str, cb) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(tr(titulo))
        dlg.setFixedSize(460, 220)
        dlg.setStyleSheet(f"QDialog {{ background: {t.FONDO}; border: 1px solid {t.BORDE}; border-radius: 14px; }}")
        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(22, 18, 22, 18)
        dv.setSpacing(12)
        dv.addWidget(etiqueta(tr(titulo), t.T_DESTACADO, "TEXTO", peso=600, wrap=True))
        dv.addWidget(etiqueta(tr(cuerpo), t.T_CUERPO, "SECUNDARIO", wrap=True))
        dv.addStretch(1)
        dh = QHBoxLayout()
        dh.addStretch(1)
        b_cancel = boton(tr("Cancelar"), al_pulsar=dlg.reject)
        b_cancel.setMinimumHeight(48)
        dh.addWidget(b_cancel)
        b_ok = boton(tr(txt_ok), estilo="primario", al_pulsar=lambda: (cb(), dlg.accept()))
        b_ok.setMinimumHeight(48)
        dh.addWidget(b_ok)
        dv.addLayout(dh)
        dlg.exec()

    def _registrar_ejercicio(self) -> None:
        self._confirmar_dialogo(
            "Registro de entrenamiento ARED",
            "¿Confirmar sesión física diaria en microgravedad (+30 puntos)?",
            "Confirmar sesión",
            self._confirmar_ejercicio,
        )

    def _confirmar_ejercicio(self) -> None:
        marcar_mision_gamificacion(self.state.crew_id, "ejercicio", True)
        self.refrescar()

    def _registrar_hidratacion(self) -> None:
        self._confirmar_dialogo(
            "Registro de hidratación",
            "¿Confirmar ingesta acumulada de 2.5 L en cabina (+15 puntos)?",
            "Confirmar 2.5 L",
            self._confirmar_hidratacion,
        )

    def _confirmar_hidratacion(self) -> None:
        marcar_mision_gamificacion(self.state.crew_id, "hidratacion", True)
        self.refrescar()

    # ------------------------------------------------------------------ Respiración & Biofilia
    def _toggle_respiracion(self) -> None:
        if self._resp_activo:
            self._resp_activo = False
            self._resp_timer.stop()
            self.btn_resp.setText(tr("Iniciar respiración 4x4"))
            self.orbe_resp.actualizar("Listo", "4s", 0.35, t.TEXTO_SUAVE)
            if self._resp_tiempo >= 16.0:
                marcar_mision_gamificacion(self.state.crew_id, "descompresion", True)
                desbloquear_insignia(self.state.crew_id, "biofilia")
                self.refrescar()
        else:
            self._resp_activo = True
            self._resp_tiempo = 0.0
            self._resp_mision_concedida = False
            self._resp_timer.start()
            self.btn_resp.setText(tr("Detener respiración"))

    def _on_respiracion_tick(self) -> None:
        self._resp_tiempo += 0.06
        ciclo = self._resp_tiempo % 16.0
        if ciclo < 4.0:
            fase, seg, prog, col = "INHALAR", f"{int(4.0 - ciclo)}s", 0.35 + 0.65 * (ciclo / 4.0), t.TEXTO_SUAVE
        elif ciclo < 8.0:
            fase, seg, prog, col = "RETENER", f"{int(8.0 - ciclo)}s", 1.0, t.NORMAL
        elif ciclo < 12.0:
            fase, seg, prog, col = "EXHALAR", f"{int(12.0 - ciclo)}s", 1.0 - 0.65 * ((ciclo - 8.0) / 4.0), t.ATENCION
        else:
            fase, seg, prog, col = "RETENER", f"{int(16.0 - ciclo)}s", 0.35, t.TERCIARIO
        self.orbe_resp.actualizar(fase, seg, prog, col)

        if self._resp_tiempo >= 16.0 and not self._resp_mision_concedida:
            self._resp_mision_concedida = True
            marcar_mision_gamificacion(self.state.crew_id, "descompresion", True)
            desbloquear_insignia(self.state.crew_id, "biofilia")
            self.refrescar()
        if self._resp_tiempo >= 120.0 and self._resp_activo:
            self._toggle_respiracion()

    def _cambiar_audio(self, tipo: str) -> None:
        for b, nom in ((self.btn_lluvia, "lluvia"), (self.btn_bosque, "bosque"), (self.btn_oceano, "oceano")):
            b.setChecked(nom == tipo)
        if self.biofilia.activo:
            self.biofilia.iniciar(tipo)

    def _toggle_audio(self) -> None:
        if self.biofilia.activo:
            self.biofilia.detener()
            self.btn_play_audio.setText(tr("Reproducir sonido"))
        else:
            tipo = "bosque" if self.btn_bosque.isChecked() else ("oceano" if self.btn_oceano.isChecked() else "lluvia")
            self.biofilia.iniciar(tipo)
            self.btn_play_audio.setText(tr("Detener sonido"))
            marcar_mision_gamificacion(self.state.crew_id, "descompresion", True)
            desbloquear_insignia(self.state.crew_id, "biofilia")
            self.refrescar()

    # ------------------------------------------------------------------ Luz & Siesta
    def _alternar_luz(self) -> None:
        self._luz_reposo = not self._luz_reposo
        self.btn_luz.setText(tr("Modo reposo") if self._luz_reposo else tr("Modo vigilia"))
        marcar_mision_gamificacion(self.state.crew_id, "luz_circadiana", True)
        desbloquear_insignia(self.state.crew_id, "centinela")
        self.refrescar()

    def _toggle_siesta(self) -> None:
        if self._siesta_activa:
            self._siesta_activa = False
            self._siesta_timer.stop()
            self.btn_siesta.setText(tr("Iniciar siesta (26m)"))
            self.btn_siesta_simular.setVisible(False)
            self.lbl_siesta_estado.setText(tr("Siesta interrumpida · Temporizador reiniciado"))
            self.lbl_siesta_estado.setStyleSheet(f"color: {t.SECUNDARIO};")
        else:
            self._siesta_activa = True
            self._siesta_segundos = 26 * 60
            self._siesta_timer.start()
            self.btn_siesta.setText(tr("Interrumpir siesta"))
            self.btn_siesta_simular.setVisible(True)
            self.lbl_siesta_estado.setText(tr("Siesta activa · {m:02d}:{s:02d} min · Espectro 600 nm", m=26, s=0))
            self.lbl_siesta_estado.setStyleSheet(f"color: {t.ATENCION}; font-family: {t.FUENTE_MONO};")
            if not self._luz_reposo:
                self._alternar_luz()

    def _on_siesta_tick(self) -> None:
        if not self._siesta_activa:
            return
        self._siesta_segundos -= 1
        if self._siesta_segundos <= 0:
            self._completar_siesta()
        else:
            m, s = divmod(self._siesta_segundos, 60)
            self.lbl_siesta_estado.setText(
                tr("Siesta activa · {m:02d}:{s:02d} min · Espectro 600 nm", m=m, s=s)
            )

    def _completar_siesta(self) -> None:
        self._siesta_activa = False
        self._siesta_timer.stop()
        self.btn_siesta.setText(tr("Iniciar siesta (26m)"))
        self.btn_siesta_simular.setVisible(False)
        self.lbl_siesta_estado.setText(tr("Siesta completada · Registro actualizado"))
        self.lbl_siesta_estado.setStyleSheet(f"color: {t.NORMAL}; font-family: {t.FUENTE_MONO}; font-weight: 600;")
        marcar_mision_gamificacion(self.state.crew_id, "luz_circadiana", True)
        desbloquear_insignia(self.state.crew_id, "centinela")
        self.refrescar()

    # ------------------------------------------------------------------ Stroop
    def _iniciar_test_stroop(self) -> None:
        self._stroop_activo = True
        self._stroop_ronda = 0
        self._stroop_aciertos = 0
        self._stroop_tiempos = []
        self.btn_iniciar_stroop.setEnabled(False)
        self.lbl_stroop_feedback.setText(tr("Toca el color de la tinta, no la palabra escrita."))
        self.lbl_stroop_feedback.setStyleSheet(f"color: {t.ATENCION};")
        self._siguiente_ronda_stroop()

    def _siguiente_ronda_stroop(self) -> None:
        self._stroop_ronda += 1
        if self._stroop_ronda > 3:
            self._finalizar_test_stroop()
            return
        for b in self.btns_stroop_colores.values():
            b.setEnabled(True)

        paleta = {cid: hex_col for cid, _n, hex_col in _colores_stroop()}
        combos = [
            ("VERDE", "rojo"), ("AZUL", "verde"), ("ROJO", "azul"), ("ÁMBAR", "rojo"),
            ("ROJO", "ámbar"), ("VERDE", "azul"), ("AZUL", "ámbar"), ("ÁMBAR", "verde"),
        ]
        palabra, cid_correcto = random.choice(combos)
        self._stroop_color_correcto = cid_correcto
        self._stroop_t0 = time.monotonic()
        self.lbl_stroop_ronda.setText(tr("Ronda {r} de 3", r=self._stroop_ronda))
        self.lbl_stroop_ronda.setStyleSheet(f"color: {t.SECUNDARIO}; font-family: {t.FUENTE_MONO};")
        self.lbl_stroop_palabra.setText(tr(palabra))
        self.lbl_stroop_palabra.setStyleSheet(f"color: {paleta[cid_correcto]}; font-size: 46px; font-weight: bold;")

    def _responder_stroop(self, color_elegido: str) -> None:
        if not self._stroop_activo:
            return
        dt = (time.monotonic() - self._stroop_t0) * 1000.0
        self._stroop_tiempos.append(dt)
        for b in self.btns_stroop_colores.values():
            b.setEnabled(False)

        if color_elegido == self._stroop_color_correcto:
            self._stroop_aciertos += 1
            self.lbl_stroop_ronda.setText(tr("Ronda {r} de 3 · Correcto ({ms} ms)", r=self._stroop_ronda, ms=int(dt)))
            self.lbl_stroop_ronda.setStyleSheet(f"color: {t.NORMAL}; font-family: {t.FUENTE_MONO}; font-weight: 600;")
        else:
            self.lbl_stroop_ronda.setText(tr("Ronda {r} de 3 · Interferencia ({ms} ms)", r=self._stroop_ronda, ms=int(dt)))
            self.lbl_stroop_ronda.setStyleSheet(f"color: {t.ALERTA}; font-family: {t.FUENTE_MONO}; font-weight: 600;")
        QTimer.singleShot(450, self._siguiente_ronda_stroop)

    def _finalizar_test_stroop(self) -> None:
        self._stroop_activo = False
        self.btn_iniciar_stroop.setEnabled(True)
        for b in self.btns_stroop_colores.values():
            b.setEnabled(False)
        media_ms = sum(self._stroop_tiempos) / len(self._stroop_tiempos) if self._stroop_tiempos else 400.0
        if self._stroop_aciertos >= 2:
            self.lbl_stroop_palabra.setText(tr("APROBADO"))
            self.lbl_stroop_palabra.setStyleSheet(f"color: {t.NORMAL}; font-size: 42px; font-weight: bold;")
            self.lbl_stroop_feedback.setText(
                tr("Aciertos: {a}/3 · Latencia: {ms} ms · Nominal", a=self._stroop_aciertos, ms=int(media_ms))
            )
            self.lbl_stroop_feedback.setStyleSheet(f"color: {t.NORMAL}; font-weight: 600;")
            marcar_mision_gamificacion(self.state.crew_id, "pvt", True)
            if media_ms < 420 and self._stroop_aciertos == 3:
                desbloquear_insignia(self.state.crew_id, "mercurio")
        else:
            self.lbl_stroop_palabra.setText(tr("REINTENTAR"))
            self.lbl_stroop_palabra.setStyleSheet(f"color: {t.ALERTA}; font-size: 42px; font-weight: bold;")
            self.lbl_stroop_feedback.setText(
                tr("Aciertos: {a}/3 · Latencia: {ms} ms · Repetir prueba", a=self._stroop_aciertos, ms=int(media_ms))
            )
            self.lbl_stroop_feedback.setStyleSheet(f"color: {t.ALERTA}; font-weight: 600;")
        self.refrescar()

    # ------------------------------------------------------------------ Bitácora
    def _cambiar_tab_bitacora(self, idx: int) -> None:
        self._tab_bitacora_idx = idx
        if hasattr(self, "stack_bitacora"):
            self.stack_bitacora.setCurrentIndex(idx)
        activo_css = (
            f"QPushButton {{ background: {t.ACTIVO}; border: 1.5px solid {t.NORMAL};"
            f" border-radius: 10px; color: {t.NORMAL}; font-size: {t.T_CUERPO}px; font-weight: 700; padding: 6px 14px; }}"
        )
        inactivo_css = (
            f"QPushButton {{ background: {t.FONDO}; border: 1px solid {t.BORDE};"
            f" border-radius: 10px; color: {t.SECUNDARIO}; font-size: {t.T_CUERPO}px; font-weight: 500; padding: 6px 14px; }}"
            f"QPushButton:hover {{ border-color: {t.BORDE_SUAVE}; color: {t.TEXTO}; }}"
        )
        self.btn_tab_bitacora_form.setStyleSheet(activo_css if idx == 0 else inactivo_css)
        self.btn_tab_bitacora_hist.setStyleSheet(activo_css if idx == 1 else inactivo_css)

    def _filtrar_timeline_bitacora(self, filtro: str) -> None:
        self._filtro_bitacora_activo = filtro
        self._recargar_timeline_bitacora()

    def _seleccionar_categoria_bitacora(self, cat: str) -> None:
        self._categoria_bitacora_activa = cat

    def _recargar_timeline_bitacora(self) -> None:
        while self.contenedor_timeline.count():
            item = self.contenedor_timeline.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        evaluaciones = obtener_evaluaciones_mentales(self.state.crew_id, limit=20)
        if not evaluaciones:
            guardar_evaluacion_mental(
                crew_id=self.state.crew_id,
                timepoint="R+38",
                horas_sueno=7.4,
                nivel_estres=2,
                animo=5,
                fatiga=1,
                aislamiento=2,
                pvt_latencia_ms=275.0,
                pvt_lapsus=0,
                nivel_triage="verde",
                notas="[Tierra] Llegó el paquete familiar desde Houston con retardo orbital. Ayuda a sostener la calma y el ánimo.",
            )
            guardar_evaluacion_mental(
                crew_id=self.state.crew_id,
                timepoint="R+41",
                horas_sueno=6.0,
                nivel_estres=4,
                animo=3,
                fatiga=4,
                aislamiento=2,
                pvt_latencia_ms=348.0,
                pvt_lapsus=0,
                nivel_triage="amarillo",
                notas="[Hábitat] Mantenimiento prolongado de filtros ECLSS. Una sesión de audio biofílico ayudó a descansar mejor.",
            )
            evaluaciones = obtener_evaluaciones_mentales(self.state.crew_id, limit=20)

        self.lbl_hist_count.setText(tr("{n} registros", n=len(evaluaciones)))
        self.btn_tab_bitacora_hist.setText(tr("Registros ({n})", n=len(evaluaciones)))

        paleta_animo = _colores_animo()
        mapa_num = {5: "optimo", 4: "nominal", 3: "fatiga", 2: "tension", 1: "aislamiento"}
        filtro = self._filtro_bitacora_activo
        mostrados = 0

        for ev in evaluaciones:
            raw_notas = str(ev.get("notas") or "").strip()
            cat_txt = "Hábitat"
            cuerpo_txt = raw_notas
            if raw_notas.startswith("[") and "]" in raw_notas:
                idx_fin = raw_notas.index("]")
                cat_txt = raw_notas[1:idx_fin].strip()
                cuerpo_txt = raw_notas[idx_fin + 1:].strip()

            if filtro != "Todos" and cat_txt.lower() != filtro.lower():
                continue

            mostrados += 1
            animo_num = int(ev.get("animo", 4) or 4)
            nom_a, col_a, bg_a, bdr_a = paleta_animo[mapa_num.get(animo_num, "nominal")]

            f = QFrame()
            f.setObjectName("itemBitacora")
            f.setStyleSheet(
                f"QFrame#itemBitacora {{ background: {t.FONDO}; border: 1px solid {t.BORDE}; border-left: 4px solid {col_a}; border-radius: 10px; }}"
            )
            vi = QVBoxLayout(f)
            vi.setContentsMargins(14, 12, 14, 12)
            vi.setSpacing(6)

            ht = QHBoxLayout()
            tp = ev.get("timepoint") or self.state.timepoint
            fecha_str = str(ev.get("createdAt") or ev.get("fecha") or "")[:10]
            ht.addWidget(etiqueta(f"{tp} · {fecha_str}", t.T_CUERPO, "TEXTO", peso=700))
            ht.addStretch(1)

            b_cat = QLabel(tr(cat_txt))
            b_cat.setStyleSheet(
                f"background: {t.TARJETA}; color: {t.SECUNDARIO}; border: 1px solid {t.BORDE};"
                f"border-radius: 6px; font-size: {t.T_PEQUENO}px; padding: 2px 10px;"
            )
            ht.addWidget(b_cat)

            b_mood = QLabel(tr(nom_a))
            b_mood.setStyleSheet(
                f"background: {bg_a}; color: {col_a}; border: 1px solid {bdr_a};"
                f"border-radius: 6px; font-size: {t.T_PEQUENO}px; font-weight: 600; padding: 2px 10px;"
            )
            ht.addWidget(b_mood)
            vi.addLayout(ht)

            if cuerpo_txt:
                vi.addWidget(etiqueta(cuerpo_txt, t.T_CUERPO, "TEXTO_SUAVE", wrap=True))
            self.contenedor_timeline.addWidget(f)

        if mostrados == 0:
            v_lbl = etiqueta(tr("No hay registros en esta categoría."), t.T_PEQUENO, "TERCIARIO", wrap=True)
            v_lbl.setAlignment(Qt.AlignCenter)
            self.contenedor_timeline.addWidget(v_lbl)

    def _guardar_bitacora(self) -> None:
        texto = self.txt_bitacora.toPlainText().strip()
        cat_labels = {"Cabina": "Hábitat", "Operaciones": "Operaciones", "Equipo": "Tripulación", "Tierra": "Tierra", "Descanso": "Descanso"}
        cat_nom = cat_labels.get(self._categoria_bitacora_activa, self._categoria_bitacora_activa)
        mapa = {"optimo": (5, 1, 5), "nominal": (4, 2, 4), "fatiga": (3, 3, 2), "tension": (2, 4, 3), "aislamiento": (1, 3, 2)}
        animo_val, estres, nrg = 4, 2, 4
        for k, b in self.btns_animo.items():
            if b.isChecked():
                animo_val, estres, nrg = mapa.get(k, (4, 2, 4))
                break

        tripulante = get_cabina_dataset().get("tripulantes", {}).get(self.state.crew_id, {})
        horas_s = float(tripulante.get("horasSueno", 6.5) or 6.5)
        nota = f"[{cat_nom}] {texto}" if texto else f"[{cat_nom}] {tr('Registro confidencial de jornada.')}"
        guardar_evaluacion_mental(
            crew_id=self.state.crew_id,
            timepoint=self.state.timepoint,
            horas_sueno=horas_s,
            nivel_estres=estres,
            animo=animo_val,
            fatiga=6 - nrg,
            aislamiento=2 if cat_nom != "Tierra" else 3,
            pvt_latencia_ms=self._pvt_intentos[-1] if self._pvt_intentos else 310.0,
            pvt_lapsus=self._pvt_lapsus,
            nivel_triage="verde" if animo_val >= 4 else "amarillo",
            notas=nota,
        )
        marcar_mision_gamificacion(self.state.crew_id, "descompresion", True)
        desbloquear_insignia(self.state.crew_id, "biofilia")
        self.txt_bitacora.clear()
        self.lbl_bitacora_status.setText(tr("Entrada archivada en la base local."))
        self.lbl_bitacora_status.setStyleSheet(f"color: {t.NORMAL}; font-weight: 600;")
        self.refrescar()

    # ------------------------------------------------------------------ DSN
    def _on_dsn_segundo_tick(self) -> None:
        self._dsn_segundos_ventana = (self._dsn_segundos_ventana - 1) if self._dsn_segundos_ventana > 0 else 3 * 3600
        h = self._dsn_segundos_ventana // 3600
        m = (self._dsn_segundos_ventana % 3600) // 60
        s = self._dsn_segundos_ventana % 60
        lbl_v = self.labels_dsn_telemetria.get("Próximo pase:")
        if lbl_v is not None:
            lbl_v.setText(f"{h:02d}h {m:02d}m {s:02d}s")

    def _on_dsn_audio_tick(self) -> None:
        if not self._dsn_audio_reproduciendo:
            return
        self._dsn_audio_segundos += 1
        if self._dsn_audio_segundos > 105:
            self._stop_dsn_audio()
            return
        self.prog_dsn_audio.setValue(self._dsn_audio_segundos)
        m, s = divmod(self._dsn_audio_segundos, 60)
        self.lbl_dsn_audio_tiempo.setText(f"{m:02d}:{s:02d} / 01:45")

    def _toggle_dsn_audio(self) -> None:
        self._dsn_audio_reproduciendo = not self._dsn_audio_reproduciendo
        if self._dsn_audio_reproduciendo:
            self.btn_dsn_audio_play.setText(tr("Pausar mensaje"))
            self._dsn_audio_timer.start()
            if self.motor_voz and hasattr(self.motor_voz, "hablar"):
                info = self._info_tripulante(self.state.crew_id)
                try:
                    self.motor_voz.hablar(
                        tr(
                            "Mensaje familiar desde Houston para {nombre}. Todos en casa estamos bien y muy orgullosos de ti.",
                            nombre=info["nombre_corto"],
                        )
                    )
                except Exception:
                    pass
        else:
            self.btn_dsn_audio_play.setText(tr("Reanudar mensaje"))
            self._dsn_audio_timer.stop()

    def _stop_dsn_audio(self) -> None:
        self._dsn_audio_reproduciendo = False
        self._dsn_audio_timer.stop()
        self._dsn_audio_segundos = 0
        self.prog_dsn_audio.setValue(0)
        self.lbl_dsn_audio_tiempo.setText("00:00 / 01:45")
        self.btn_dsn_audio_play.setText(tr("Reproducir mensaje"))

    def _on_dsn_rec_tick(self) -> None:
        if not self._dsn_grabando:
            return
        self._dsn_grabacion_segundos += 0.15
        m = int(self._dsn_grabacion_segundos) // 60
        s = int(self._dsn_grabacion_segundos) % 60
        self.lbl_dsn_rec_tiempo.setText(f"{m:02d}:{s:02d}")
        vol = random.randint(2, 9)
        for i, led in enumerate(self.dsn_vu_leds):
            col = (t.NORMAL if i < 6 else (t.ATENCION if i < 8 else t.ALERTA)) if i <= vol else t.BORDE
            led.setStyleSheet(f"background: {col}; border-radius: 2px;")

    def _toggle_dsn_rec(self) -> None:
        self._dsn_grabando = not self._dsn_grabando
        if self._dsn_grabando:
            self._dsn_grabacion_segundos = 0.0
            self.lbl_dsn_rec_tiempo.setText("00:00")
            self.btn_dsn_rec_toggle.setText(tr("Detener captura"))
            self.btn_dsn_rec_reset.setEnabled(True)
            self.btn_dsn_encolar.setEnabled(True)
            self.lbl_dsn_rec_status.setText(tr("Grabando captura simulada en cabina..."))
            self.lbl_dsn_rec_status.setStyleSheet(f"color: {t.ALERTA}; font-weight: 700;")
            self._dsn_rec_timer.start()
        else:
            self._dsn_rec_timer.stop()
            self.btn_dsn_rec_toggle.setText(tr("Grabar de nuevo"))
            dur = max(1.0, self._dsn_grabacion_segundos)
            self.lbl_dsn_rec_status.setText(tr("Cápsula capturada ({d:.1f}s) · Lista para encolar", d=dur))
            self.lbl_dsn_rec_status.setStyleSheet(f"color: {t.NORMAL}; font-weight: 600;")
            for led in self.dsn_vu_leds:
                led.setStyleSheet(f"background: {t.BORDE}; border-radius: 2px;")

    def _reset_dsn_rec(self) -> None:
        self._dsn_grabando = False
        self._dsn_rec_timer.stop()
        self._dsn_grabacion_segundos = 0.0
        self.lbl_dsn_rec_tiempo.setText("00:00")
        self.btn_dsn_rec_toggle.setText(tr("Iniciar grabación"))
        self.lbl_dsn_rec_status.setText(tr("Listo para captura de nota de voz [SIMULACIÓN]."))
        self.lbl_dsn_rec_status.setStyleSheet(f"color: {t.SECUNDARIO};")
        self.btn_dsn_rec_reset.setEnabled(False)
        self.btn_dsn_encolar.setEnabled(False)
        for led in self.dsn_vu_leds:
            led.setStyleSheet(f"background: {t.BORDE}; border-radius: 2px;")

    def _encolar_paquete_dsn(self) -> None:
        nota = self.txt_dsn_nota.toPlainText().strip()
        dur = max(1.0, self._dsn_grabacion_segundos)
        dest_txt = tr("Familia")
        for b in self.btns_dsn_dest.values():
            if b.isChecked():
                dest_txt = b.text()
                break
        pkg_id = f"PKG-RET-{len(self._dsn_paquetes_encolados) + 46:03d}"
        self._dsn_paquetes_encolados.append({"id": pkg_id, "dest": dest_txt, "dur": dur, "nota": nota})

        f_pkg = QFrame()
        f_pkg.setObjectName("cajaDsnEnv")
        self._frames_dsn_enviados.append(f_pkg)
        f_pkg.setStyleSheet(
            f"QFrame#cajaDsnEnv {{ background: {t.INSIGNIA_OK_BG}; border: 1px solid {t.INSIGNIA_OK_BORDE}; border-radius: 8px; }}"
        )
        hp = QHBoxLayout(f_pkg)
        hp.setContentsMargins(10, 8, 10, 8)
        hp.addWidget(etiqueta_mono(pkg_id))
        hp.addWidget(etiqueta(tr("Cápsula ({d:.1f}s) → {dest}", d=dur, dest=dest_txt), t.T_PEQUENO, "TEXTO", wrap=True), 1)
        hp.addWidget(etiqueta_mono(tr("EN COLA")))
        self.contenedor_dsn_cola.addWidget(f_pkg)

        n_cola = len(self._dsn_paquetes_encolados)
        self.lbl_dsn_cola_count.setText(tr("{n} en cola", n=n_cola))
        lbl_buf = self.labels_dsn_telemetria.get("Búfer:")
        if lbl_buf is not None:
            lbl_buf.setText(tr("1 recibido · {n} en cola", n=n_cola))
        self.lbl_dsn_encolar_status.setText(tr("Paquete {pid} encolado para próximo pase DSN.", pid=pkg_id))
        self.lbl_dsn_encolar_status.setStyleSheet(f"color: {t.NORMAL}; font-weight: 600;")
        self.txt_dsn_nota.clear()
        self._reset_dsn_rec()
