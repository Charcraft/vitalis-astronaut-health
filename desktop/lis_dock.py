# -*- coding: utf-8 -*-
"""
desktop/lis_dock.py — Panel nativo del Agente Autónomo L.I.S. (Life-support In Space)
integrado en la ventana de escritorio PySide6:
  - Rostro holográfico no humano (RostroLIS) reactivo a la energía de voz
  - Control autónomo del software por voz o texto (cambiar tripulante, timepoint,
    vista 3D, sistema anatómico o abrir pantalla)
  - Grounding estricto sobre NASA OSDR OSD-575 + validador anti-alucinación
  - Solicitud de ayuda médica SBAR a CMO (C001) en 1 clic
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from backend.database import (
    crear_solicitud_ayuda,
    guardar_medicion_local,
    guardar_mensaje_chat,
    obtener_historial_chat,
    obtener_memoria_astronauta,
    recordar_dato_astronauta,
)
from backend.lis_agent import (
    construir_alerta_proactiva_lis,
    construir_snapshot_contexto,
    consultar_agente_libre,
    generar_respuesta_determinista,
    resolver_equipo_alsp,
    resolver_indicador_id,
    resolver_protocolo_id,
)
from backend.triage import evaluar_lectura_determinista
from desktop import theme as t
from desktop import i18n
from desktop.i18n import tr
from desktop.state import CREW_IDS, PAGINAS, SISTEMAS, TIMEPOINTS, AppState
from desktop.voice_engine import MotorVozNativo
from desktop.widgets import RostroLIS, boton, etiqueta, etiqueta_mono


_CONSULTAS_LECTURA_O_PANTALLA = (
    "estoy viendo",
    "tengo en pantalla",
    "ves mi pantalla",
    "en qué pantalla",
    "en que pantalla",
    "qué es esto",
    "que es esto",
    "qué ves",
    "que ves",
    "am i looking at",
    "on my screen",
    "on screen",
    "see my screen",
    "which screen",
    "what screen",
    "what is this",
    "what do you see",
    "am i viewing",
    "lee ",
    "leer ",
    "léeme",
    "leeme",
    "read ",
    "read me",
    "recita",
    "recite",
    "dicta",
    "en voz alta",
    "aloud",
    "out loud",
    "instrucciones",
    "instructions",
    "cómo se usa",
    "como se usa",
    "cómo usar",
    "como usar",
    "how to use",
    "how do i use",
    "how does",
    "how to measure",
    "how do i measure",
    "pasos del protocolo",
    "pasos de ",
    "steps of ",
    "what steps",
    "qué pasos",
    "que pasos",
    "dosis",
    "dose",
    "doses",
    "aviso",
    "avisos",
    "alert",
    "alerts",
    "warnings",
    "notificaci",
)

_PREGUNTAS_CLINICAS = (
    "como esta",
    "cómo está",
    "how is",
    "how's",
    "how am i",
    "estado",
    "status",
    "dime",
    "tell me",
    "reporte",
    "report",
    "sbar",
    "fuera de rango",
    "out of range",
    "anomalia",
    "anomalía",
    "anomaly",
    "anomalies",
    "glucosa",
    "glucose",
    "blood sugar",
    "calcio",
    "calcium",
    "potasio",
    "potassium",
    "sodio",
    "sodium",
    "cabina",
    "cabin",
    "radiacion",
    "radiación",
    "radiation",
    "dolor",
    "pain",
    "emergencia medica",
    "emergencia médica",
    "medical emergency",
    "tendencia",
    "trend",
    "compara",
    "compare",
    "registra",
    "log ",
    "anota",
    "note ",
    "recuerda",
    "remember",
    "analito",
    "analyte",
)


def interpretar_comando_control_nativo(
    texto: str, state: AppState
) -> Tuple[bool, Optional[str]]:
    """
    Control directo de la aplicación nativa respetando permisos de configuración.
    Soporta español e inglés y deja pasar consultas de pantalla, lectura en voz
    alta y análisis clínicos al motor de agente sin secuestrarlas como navegación.
    """
    low = (texto or "").lower().strip()
    if any(q in low for q in _CONSULTAS_LECTURA_O_PANTALLA):
        return False, None

    permitir_nav = bool(state.config.get("permitirNavegacionAutonoma", True))
    permitir_params = bool(state.config.get("permitirControlParametros", True))
    acciones_hechas: list[str] = []

    if permitir_params:
        # Cambio de idioma (español / inglés)
        if any(
            k in low
            for k in (
                "habla en inglés",
                "habla en ingles",
                "cambia a inglés",
                "cambia a ingles",
                "idioma inglés",
                "idioma ingles",
                "speak english",
                "speak in english",
                "switch to english",
                "change to english",
                "english mode",
            )
        ):
            state.actualizar_config(idioma="en")
            acciones_hechas.append(tr("idioma inglés"))
        elif any(
            k in low
            for k in (
                "habla en español",
                "habla en espanol",
                "cambia a español",
                "cambia a espanol",
                "idioma español",
                "idioma espanol",
                "speak spanish",
                "speak in spanish",
                "switch to spanish",
                "change to spanish",
                "spanish mode",
            )
        ):
            state.actualizar_config(idioma="es")
            acciones_hechas.append(tr("idioma español"))

        # Cambio de tripulante (roles coherentes con signos-vitales-cabina.json)
        alias_crew = {
            "c001": "C001",
            "oficial medico": "C001",
            "oficial médico": "C001",
            "crew medical officer": "C001",
            "medical officer": "C001",
            "cmo": "C001",
            "c002": "C002",
            "piloto": "C002",
            "mission pilot": "C002",
            "pilot": "C002",
            "c003": "C003",
            "especialista de mision": "C003",
            "especialista de misión": "C003",
            "mission specialist": "C003",
            "c004": "C004",
            "comandante": "C004",
            "mission commander": "C004",
            "commander": "C004",
        }
        for kw, up in alias_crew.items():
            if kw in low:
                state.set_crew(up)
                acciones_hechas.append(tr("tripulante {c}", c=up))
                break

        # Cambio de punto temporal
        for tp in ("l-92", "l-44", "l-3", "r+194", "r+82", "r+45", "r+1"):
            if tp in low:
                up = tp.upper()
                state.set_timepoint(up)
                acciones_hechas.append(tr("punto temporal {t}", t=up))
                break

        # Tema visual (oscuro / claro)
        if any(k in low for k in ("modo claro", "tema claro", "pantalla clara", "light mode", "light theme")):
            state.actualizar_config(temaVisual="claro")
            acciones_hechas.append(tr("modo claro"))
        elif any(k in low for k in ("modo oscuro", "tema oscuro", "pantalla oscura", "dark mode", "dark theme")):
            state.actualizar_config(temaVisual="oscuro")
            acciones_hechas.append(tr("modo oscuro"))

        # Voz y velocidad
        if any(k in low for k in ("voz rápida", "voz rapida", "voz de jorge", "fast voice", "guy voice")):
            state.actualizar_config(vozId="es-MX-JorgeNeural", vozActiva=True)
            acciones_hechas.append(tr("voz rápida"))
        elif any(k in low for k in ("voz de jarvis", "voz estudio", "voz clonada", "jarvis voice", "studio voice", "cloned voice")):
            state.actualizar_config(vozId="jarvis-clone-latam", vozActiva=True)
            acciones_hechas.append(tr("voz JARVIS Estudio"))
        elif any(k in low for k in ("habla más rápido", "habla mas rapido", "acelera la voz", "speak faster", "faster voice", "speed up")):
            nueva_vel = min(1.45, round(float(state.config.get("velocidadVoz", 1.04)) + 0.15, 2))
            state.actualizar_config(velocidadVoz=nueva_vel)
            acciones_hechas.append(tr("velocidad {v}x", v=f"{nueva_vel:.2f}"))
        elif any(k in low for k in ("habla más despacio", "habla mas despacio", "más lento", "mas lento", "speak slower", "slower voice", "slow down")):
            nueva_vel = max(0.85, round(float(state.config.get("velocidadVoz", 1.04)) - 0.15, 2))
            state.actualizar_config(velocidadVoz=nueva_vel)
            acciones_hechas.append(tr("velocidad {v}x", v=f"{nueva_vel:.2f}"))

        # Metrónomo RCP
        if "metrónomo" in low or "metronomo" in low or "metronome" in low:
            if any(w in low for w in ("detén", "deten", "para", "apaga", "desactiva", "stop", "halt", "off", "disable")):
                state.controlEmergenciaSolicitado.emit("metronomo", {"accion": "detener"})
                acciones_hechas.append(tr("metrónomo RCP detenido"))
            elif any(w in low for w in ("inicia", "activa", "enciende", "pon", "empieza", "start", "turn on", "enable", "begin")):
                if permitir_nav and state.pagina != "emergencia":
                    state.ir_a("emergencia", protocoloId="cardiovascular")
                state.controlEmergenciaSolicitado.emit("metronomo", {"accion": "iniciar"})
                acciones_hechas.append(tr("metrónomo RCP iniciado"))

        # Control de cámara y zoom del Modelo 3D
        if "vista lateral" in low or "modo lateral" in low or "side view" in low:
            state.vistaCamaraSolicitada.emit("lateral")
            acciones_hechas.append(tr("vista lateral 3D"))
        elif "vista frontal" in low or "modo frontal" in low or "front view" in low:
            state.vistaCamaraSolicitada.emit("frontal")
            acciones_hechas.append(tr("vista frontal 3D"))
        elif "capas" in low or "rayos x" in low or "x-ray" in low or "xray" in low or "internal layers" in low:
            state.vistaCamaraSolicitada.emit("capas")
            acciones_hechas.append(tr("capas internas 3D"))
        elif "cuerpo completo" in low or "ver cuerpo" in low or "full body" in low:
            state.vistaCamaraSolicitada.emit("cuerpo")
            acciones_hechas.append(tr("cuerpo completo 3D"))
        elif any(k in low for k in ("acerca", "haz zoom", "más cerca", "mas cerca", "zoom in", "closer")) and any(
            m in low for m in ("3d", "modelo", "model", "cuerpo", "body", "cámara", "camara", "camera", "zoom")
        ):
            state.controlVisor3DSolicitado.emit("zoom", "acercar")
            acciones_hechas.append(tr("zoom 3D acercado"))
        elif any(k in low for k in ("aleja", "aléjate", "más lejos", "mas lejos", "zoom out", "farther")) and any(
            m in low for m in ("3d", "modelo", "model", "cuerpo", "body", "cámara", "camara", "camera", "zoom")
        ):
            state.controlVisor3DSolicitado.emit("zoom", "alejar")
            acciones_hechas.append(tr("zoom 3D alejado"))

        # Enfoque de sistema anatómico
        mapa_sis = {
            "cardiovascular": ("cardiovascular", "corazón", "corazon", "heart"),
            "respiratorio": ("respiratorio", "respiratory", "pulmones", "pulmon", "pulmón", "lungs", "lung"),
            "neuro-ocular": ("neuro", "cerebro", "brain", "ocular", "sans"),
            "metabolico": ("metabolico", "metabólico", "metabolic", "higado", "hígado", "liver", "renal", "kidney"),
            "musculoesqueletico": ("musculo", "músculo", "muscle", "hueso", "bone", "oseo", "óseo", "skeletal"),
            "inmune-radiacion": ("inmune", "immune", "radiacion", "radiación", "radiation"),
        }
        if any(v in low for v in ("enfoca", "muestra", "selecciona", "sistema", "ver", "focus", "show", "select", "system", "view")):
            for sis_id, kws in mapa_sis.items():
                if any(k in low for k in kws):
                    state.set_sistema(sis_id)
                    acciones_hechas.append(tr("sistema {s}", s=tr(sis_id)))
                    break

    # Navegación entre vistas de la aplicación nativa
    if permitir_nav and any(
        v in low
        for v in (
            "ve a ",
            "ir a ",
            "abre ",
            "abrir ",
            "lleva",
            "llévame",
            "muéstrame",
            "muestrame",
            "cambia a ",
            "cambiar a ",
            "go to ",
            "open ",
            "show me ",
            "take me to ",
            "switch to ",
        )
    ):
        if any(k in low for k in ("emergencia", "emergency", "emergencies", "sos", "protocolo", "protocol")):
            state.ir_a("emergencia")
            acciones_hechas.append(tr("módulo de emergencias"))
        elif any(k in low for k in ("historial", "history", "tabla", "table", "analitos", "analytes", "lab")):
            state.ir_a("historial")
            acciones_hechas.append(tr("tabla de 17 analitos OSDR-575"))
        elif any(k in low for k in ("medir", "medicion", "medición", "measure", "measurement")):
            state.ir_a("medir")
            acciones_hechas.append(tr("asistente de medición 0G"))
        elif any(k in low for k in ("cuerpo", "body", "3d", "anatomia", "anatomía", "anatomy")):
            state.ir_a("cuerpo")
            acciones_hechas.append(tr("inspector anatómico 3D"))
        elif any(k in low for k in ("configuracion", "configuración", "ajustes", "settings", "preferences", "config")):
            state.ir_a("lis")
            acciones_hechas.append(tr("configuración de V.I.T.A.L.I.S."))
        elif any(k in low for k in ("inicio", "general", "resumen", "panel", "home", "overview", "dashboard")):
            state.ir_a("inicio")
            acciones_hechas.append(tr("panel principal"))

    tiene_pregunta_clinica = any(k in low for k in _PREGUNTAS_CLINICAS)
    if acciones_hechas and not tiene_pregunta_clinica:
        return True, tr("A sus órdenes, señor. He actualizado: {lista}.", lista=", ".join(acciones_hechas))

    return False, None


# Alto de la burbuja minimizada; el pie de la ventana se reserva para ella.
ALTO_BURBUJA = 64


class PanelAsistenteLIS(QFrame):
    """Panel flotante y arrastrable del agente L.I.S. que acompaña al usuario en todas las vistas."""

    respuestaLista = Signal(dict)

    def __init__(
        self,
        state: AppState,
        motor_voz: MotorVozNativo,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self.motor_voz = motor_voz
        self._expandido = False
        self._minimizado = False
        self._movido_manual = False
        self._drag_offset: Optional[QPoint] = None
        self._nivel_actual = "NOMINAL"
        self._ultimo_aviso_proactivo_firma = ""
        self._chips_rapidos: list[QPushButton] = []
        self._chips_def: list[tuple[str, str]] = []
        self._ultimas_acciones: list = []
        self._ultimas_confs: list[str] = []

        self.setObjectName("lis_flotante")
        self._sombra = QGraphicsDropShadowEffect(self)
        self._sombra.setBlurRadius(28)
        self._sombra.setOffset(0, 8)
        self.setGraphicsEffect(self._sombra)

        self.setMaximumWidth(640)

        capa = QVBoxLayout(self)
        self._capa = capa
        capa.setContentsMargins(14, 12, 14, 12)
        capa.setSpacing(8)

        # --- Fila superior flotante: Rostro holográfico + burbuja + controles ---
        fila_top = QHBoxLayout()
        fila_top.setSpacing(12)

        self.rostro = RostroLIS(tam=68)
        self.rostro.setCursor(Qt.CursorShape.OpenHandCursor)
        self.rostro.setToolTip(tr("Arrastra para mover a L.I.S. · Clic en ▾ para minimizar"))
        fila_top.addWidget(self.rostro, 0, Qt.AlignTop)

        self.cuerpo_flotante = QWidget()
        col_txt = QVBoxLayout(self.cuerpo_flotante)
        col_txt.setContentsMargins(0, 0, 0, 0)
        col_txt.setSpacing(6)

        fila_id = QHBoxLayout()
        fila_id.setSpacing(6)
        self.lbl_nombre = etiqueta(
            "L.I.S.", t.T_DESTACADO, t.TEXTO, peso=600
        )
        self.lbl_contexto = etiqueta_mono(
            f"{self.state.crew_id} · {self.state.timepoint} · VISTA GENERAL",
            t.SECUNDARIO,
        )
        # El contexto (tripulante · momento · pantalla) ya está en la barra superior.
        self.lbl_contexto.setVisible(False)
        self.btn_callar = QPushButton("🔇")
        self.btn_callar.setFixedSize(48, 48)
        self.btn_callar.setVisible(False)
        self.btn_callar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_callar.setToolTip(tr("Silenciar voz de L.I.S."))
        self.btn_callar.clicked.connect(self.motor_voz.detener_habla)

        self.btn_minimizar = QPushButton("▾")
        self.btn_minimizar.setFixedSize(48, 48)
        self.btn_minimizar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_minimizar.setToolTip(tr("Minimizar / expandir panel flotante"))
        self.btn_minimizar.clicked.connect(self._toggle_minimizado)

        fila_id.addWidget(self.lbl_nombre)
        fila_id.addWidget(self.lbl_contexto)
        fila_id.addStretch(1)
        fila_id.addWidget(self.btn_callar)
        fila_id.addWidget(self.btn_minimizar)
        col_txt.addLayout(fila_id)

        self.lbl_burbuja = etiqueta(
            "A sus órdenes, señor. Modelo anatómico 3D activo.",
            t.T_CUERPO,
            t.TEXTO_SUAVE,
            wrap=True,
        )
        self.lbl_burbuja.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.lbl_burbuja.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        col_txt.addWidget(self.lbl_burbuja)

        self.fila_acciones_sugeridas = QHBoxLayout()
        self.fila_acciones_sugeridas.setSpacing(6)
        col_txt.addLayout(self.fila_acciones_sugeridas)

        # Entrada rápida de comando / consulta
        fila_input = QHBoxLayout()
        fila_input.setSpacing(6)
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText(tr("Pregunta a L.I.S.…"))
        self.txt_input.setMinimumWidth(240)
        self.txt_input.returnPressed.connect(self._enviar_consulta)
        fila_input.addWidget(self.txt_input, 1)

        self.btn_mic = boton("🎤", al_pulsar=self._activar_microfono)
        self.btn_mic.setFixedWidth(64)
        self.btn_mic.setToolTip(tr("Hablar por micrófono"))
        fila_input.addWidget(self.btn_mic)

        self.btn_enviar = boton("Enviar", estilo="primario", al_pulsar=self._enviar_consulta)
        fila_input.addWidget(self.btn_enviar)

        self.btn_expandir = boton("Más ▴", al_pulsar=self._toggle_expandido)
        fila_input.addWidget(self.btn_expandir)
        col_txt.addLayout(fila_input)

        fila_top.addWidget(self.cuerpo_flotante, 1)

        # Botón rápido visible sólo cuando está minimizado a burbuja
        self.btn_restaurar = QPushButton(tr("Hablar con L.I.S."))
        self.btn_restaurar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_restaurar.setVisible(False)
        self.btn_restaurar.setMinimumHeight(t.ALTO_TOQUE)
        self.btn_restaurar.clicked.connect(self._toggle_minimizado)
        fila_top.addWidget(self.btn_restaurar, 0, Qt.AlignVCenter)

        capa.addLayout(fila_top)

        # --- Barra de consultas rápidas en microgravedad (1 clic) ---
        self.widget_rapido = QWidget()
        fila_rapida = QHBoxLayout(self.widget_rapido)
        fila_rapida.setContentsMargins(0, 0, 0, 0)
        fila_rapida.setSpacing(8)
        for titulo_chip, prompt_chip in (
            ("Estado", "Estado actual completo"),
            ("Anomalías", "Parámetros fuera de rango"),
            ("Cabina", "Estado de cabina y radiación"),
            ("En pantalla", "¿Qué estoy viendo en pantalla?"),
            ("SBAR", "Generar reporte SBAR"),
        ):
            btn_chip = QPushButton(tr(titulo_chip))
            btn_chip.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_chip.setMinimumHeight(48)
            btn_chip.setStyleSheet(f"QPushButton {{ padding: 8px 14px; font-size: {t.T_PEQUENO}px; border-radius: 12px; }}")
            btn_chip.clicked.connect(lambda _=False, p=prompt_chip: self._consulta_rapida(p))
            self._chips_rapidos.append(btn_chip)
            self._chips_def.append((titulo_chip, prompt_chip))
            fila_rapida.addWidget(btn_chip)
        fila_rapida.addStretch(1)
        capa.addWidget(self.widget_rapido)

        # --- Área desplegable de bitácora de conversación + SOS rápido ---
        self.panel_chat = QWidget()
        v_chat = QVBoxLayout(self.panel_chat)
        v_chat.setContentsMargins(0, 6, 0, 0)
        v_chat.setSpacing(8)

        self.area_historial = QPlainTextEdit()
        self.area_historial.setReadOnly(True)
        self.area_historial.setMaximumHeight(160)
        v_chat.addWidget(self.area_historial)

        fila_acc = QHBoxLayout()
        self.btn_sos = boton(
            "Pedir ayuda médica",
            estilo="peligro",
            al_pulsar=self._disparar_sos,
        )
        self.btn_cfg = boton(
            "Ajustes del asistente",
            al_pulsar=lambda: self.state.ir_a("lis"),
        )
        fila_acc.addWidget(self.btn_sos)
        fila_acc.addWidget(self.btn_cfg)
        fila_acc.addStretch(1)
        v_chat.addLayout(fila_acc)

        self.panel_chat.setVisible(False)
        capa.addWidget(self.panel_chat)

        # Conexiones de estado y voz
        self.respuestaLista.connect(self._mostrar_respuesta)
        self.motor_voz.estadoHablaCambiado.connect(self._on_habla)
        self.motor_voz.energiaActualizada.connect(self.rostro.set_energia)
        self.motor_voz.estadoEscuchaCambiado.connect(self._on_escucha)
        self.motor_voz.estadoTranscribiendoCambiado.connect(self._on_transcribiendo)
        self.motor_voz.transcripcionLista.connect(self._on_transcripcion)
        self.motor_voz.sinAudioDetectado.connect(self._on_sin_audio)

        self.state.crewChanged.connect(self._on_contexto_tripulante_cambiado)
        self.state.timepointChanged.connect(self._on_contexto_tripulante_cambiado)
        self.state.paginaSolicitada.connect(self._actualizar_etiqueta_contexto)
        self.state.historialLimpiado.connect(self._on_historial_limpiado)
        self._cargar_historial()
        self._refrescar_briefing_silencioso()
        self.aplicar_tema()
        QTimer.singleShot(2000, self.motor_voz.prewarm_stt)

        # Arranca como burbuja: abierto tapaba la esquina de cada pantalla.
        self._toggle_minimizado()

    def aplicar_tema(self) -> None:
        self.setStyleSheet(
            f"QFrame#lis_flotante {{ "
            f"background: {t.PANEL_FLOTANTE}; "
            f"border: 1px solid {t.BORDE_DOCK}; "
            f"border-radius: 18px; "
            f"}}"
        )
        self._sombra.setColor(QColor(*t.SOMBRA_RGB))
        self.btn_callar.setStyleSheet(
            f"QPushButton {{ background: {t.FONDO}; color: {t.ATENCION}; border: 1px solid {t.BORDE}; "
            f"border-radius: 24px; font-size: 18px; padding: 0px; }} "
            f"QPushButton:hover {{ border-color: {t.ATENCION}; color: {t.TEXTO}; }}"
        )
        self.btn_minimizar.setStyleSheet(
            f"QPushButton {{ background: {t.FONDO}; color: {t.TEXTO_SUAVE}; border: 1px solid {t.BORDE}; "
            f"border-radius: 24px; font-size: 18px; }} "
            f"QPushButton:hover {{ border-color: {t.ETIQUETA}; color: {t.TEXTO}; }}"
        )
        chip_css = (
            f"QPushButton {{ background: {t.TARJETA}; color: {t.TEXTO_SUAVE}; border: 1px solid {t.BORDE}; "
            f"border-radius: 12px; padding: 8px 12px; font-size: {t.T_PEQUENO}px; }} "
            f"QPushButton:hover {{ border-color: {t.ETIQUETA}; color: {t.TEXTO}; background: {t.HOVER}; }}"
        )
        for btn_chip in self._chips_rapidos:
            btn_chip.setStyleSheet(chip_css)
        self._actualizar_estilo_burbuja_alerta(self._nivel_actual)
        if self._ultimas_acciones or self._ultimas_confs:
            self._renderizar_acciones_sugeridas(self._ultimas_acciones, self._ultimas_confs)
        self.rostro.update()

    def retraducir(self) -> None:
        """Reaplica los textos fijos del panel tras un cambio de idioma."""
        self._ultimo_aviso_proactivo_firma = ""
        self.lbl_nombre.setText(tr("L.I.S."))
        self.rostro.setToolTip(tr("Arrastra para mover a L.I.S. · Clic en ▾ para minimizar"))
        self.btn_callar.setToolTip(tr("Silenciar voz de L.I.S."))
        self.btn_minimizar.setToolTip(tr("Minimizar / expandir panel flotante"))
        self.txt_input.setPlaceholderText(tr("Pregunta a L.I.S.…"))
        self.btn_mic.setToolTip(tr("Hablar por micrófono"))
        self.btn_enviar.setText(tr("Enviar"))
        self.btn_expandir.setText(tr("Menos ▾") if self._expandido else tr("Más ▴"))
        self.btn_sos.setText(tr("Pedir ayuda médica"))
        self.btn_cfg.setText(tr("Ajustes del asistente"))
        for btn_chip, (titulo, _prompt) in zip(self._chips_rapidos, self._chips_def):
            btn_chip.setText(tr(titulo))
        self._actualizar_estilo_burbuja_alerta(self._nivel_actual)
        self._refrescar_briefing_silencioso()
        self.aplicar_tema()
        self.reposicionar_en_padre()

    def _toggle_minimizado(self) -> None:
        self._minimizado = not self._minimizado
        # Minimizado cabe dentro del pie de la ventana: nunca tapa contenido.
        self.rostro.setFixedSize(*((ALTO_BURBUJA - 12,) * 2 if self._minimizado else (68, 68)))
        if self._minimizado:
            self._capa.setContentsMargins(6, 6, 6, 6)
        else:
            self._capa.setContentsMargins(14, 12, 14, 12)
        self.cuerpo_flotante.setVisible(not self._minimizado)
        self.widget_rapido.setVisible(not self._minimizado)
        self.panel_chat.setVisible(False if self._minimizado else self._expandido)
        self.btn_restaurar.setVisible(self._minimizado)
        self.btn_minimizar.setText("▴" if self._minimizado else "▾")
        self.reposicionar_en_padre()

    def _toggle_expandido(self) -> None:
        self._expandido = not self._expandido
        self.panel_chat.setVisible(self._expandido)
        self.btn_expandir.setText(tr("Menos ▾") if self._expandido else tr("Más ▴"))
        self.reposicionar_en_padre()

    def reposicionar_en_padre(self) -> None:
        p = self.parentWidget()
        if p is None:
            return
        margen_x = 24
        margen_y = 48
        pw, ph = p.width(), p.height()
        if self._minimizado:
            self.lbl_burbuja.setMinimumHeight(0)
            self._capa.activate()
            self.adjustSize()
            w = self.sizeHint().width()
            h = self.sizeHint().height()
        else:
            w = min(640, max(440, pw - margen_x * 2))
            burbuja_w = max(240, w - 116)
            bh = self.lbl_burbuja.heightForWidth(burbuja_w)
            if bh > 0:
                self.lbl_burbuja.setMinimumHeight(bh + 4)
            self._capa.activate()
            h_wf = self._capa.totalHeightForWidth(w) if self._capa.hasHeightForWidth() else 0
            h = max(self.sizeHint().height(), h_wf)
        self.resize(w, h)
        if self._minimizado and not self._movido_manual:
            # Centrada en la franja del pie (ver PIE_ALTO en main_window).
            self.move(max(margen_x, pw - w - margen_x), ph - h - 8)
        elif not self._movido_manual:
            x = max(margen_x, pw - w - margen_x)
            y = max(72, ph - h - margen_y)
            self.move(x, y)
        else:
            x = max(12, min(self.x(), max(12, pw - w - 12)))
            y = max(64, min(self.y(), max(64, ph - h - 36)))
            self.move(x, y)
        self.raise_()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = ev.globalPosition().toPoint() - self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag_offset is not None and (ev.buttons() & Qt.MouseButton.LeftButton):
            self._movido_manual = True
            nuevo = ev.globalPosition().toPoint() - self._drag_offset
            p = self.parentWidget()
            if p is not None:
                x = max(12, min(nuevo.x(), max(12, p.width() - self.width() - 12)))
                y = max(64, min(nuevo.y(), max(64, p.height() - self.height() - 36)))
                self.move(x, y)
            else:
                self.move(nuevo)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        self._drag_offset = None
        self.unsetCursor()
        super().mouseReleaseEvent(ev)

    def _on_contexto_tripulante_cambiado(self, *_args) -> None:
        self._ultimo_aviso_proactivo_firma = ""
        self._actualizar_etiqueta_contexto()
        self._refrescar_briefing_silencioso()

    def _actualizar_etiqueta_contexto(self, *_args) -> None:
        nom_pag = tr(PAGINAS.get(self.state.pagina, "Vista general")).upper()
        self.lbl_contexto.setText(
            f"{self.state.crew_id} · {self.state.timepoint} · {nom_pag}"
        )
        self._cargar_historial()

    def _refrescar_briefing_silencioso(self) -> None:
        try:
            det = generar_respuesta_determinista(
                "estado actual",
                self.state.crew_id,
                self.state.timepoint,
                "rutina",
            )
            self.lbl_burbuja.setText(det.get("texto", ""))
            nivel = det.get("nivelAlerta", "NOMINAL")
            self._actualizar_estilo_burbuja_alerta(nivel)
            self.rostro.set_expresion(self._nivel_actual)
            self._renderizar_acciones_sugeridas(det.get("accionesSugeridas", []))
        except Exception:
            pass

    def _cargar_historial(self) -> None:
        hist = obtener_historial_chat(self.state.crew_id, 15)
        lineas = []
        for m in hist:
            quien = (
                self.state.crew_id
                if m["emisor"] == "astronauta"
                else self.state.config.get("nombreAgente", "L.I.S.")
            )
            lineas.append(f"[{quien}] {m['texto']}")
        self.area_historial.setPlainText("\n".join(lineas))

    def _actualizar_estilo_burbuja_alerta(self, nivel: str) -> None:
        self._nivel_actual = nivel if nivel in ("CRITICO", "ATENCION") else "NOMINAL"
        if self._nivel_actual == "CRITICO":
            borde = t.ALERTA
            fondo = t.PELIGRO_BG
            texto_btn = tr("Hablar con L.I.S. · Alerta")
        elif self._nivel_actual == "ATENCION":
            borde = t.ATENCION
            c_amb = QColor(t.ATENCION)
            fondo = f"rgba({c_amb.red()}, {c_amb.green()}, {c_amb.blue()}, 26)"
            texto_btn = tr("Aviso preventivo · Ver consejo")
        else:
            borde = t.BORDE_BURBUJA
            fondo = t.TARJETA
            texto_btn = tr("Hablar con L.I.S.")
        self.btn_restaurar.setText(texto_btn)
        self.btn_restaurar.setStyleSheet(
            f"QPushButton {{ background: {fondo}; color: {t.TEXTO}; border: 1px solid {borde}; "
            f"border-radius: 14px; padding: 12px 20px; font-size: {t.T_CUERPO}px; font-weight: 600; }}"
        )

    def notificar_alerta_proactiva(
        self, pend: list, crew: str, tp: str
    ) -> Optional[Dict[str, Any]]:
        """Mantiene a L.I.S. proactivo en alertas rojas y amarillas (sin alarmar en amarillo)."""
        if not pend:
            if self._ultimo_aviso_proactivo_firma:
                self._ultimo_aviso_proactivo_firma = ""
                self._refrescar_briefing_silencioso()
                self.reposicionar_en_padre()
            return None

        alerta = construir_alerta_proactiva_lis(
            pend,
            crew,
            personalidad=str(self.state.config.get("personalidad", "jarvis-cordial")),
        )
        firma = f"{tp}|{alerta.get('firma', '')}"
        alerta["firma"] = firma
        if firma == self._ultimo_aviso_proactivo_firma:
            return None

        self._ultimo_aviso_proactivo_firma = firma
        self.lbl_burbuja.setText(alerta.get("texto", ""))
        self._actualizar_estilo_burbuja_alerta(alerta.get("nivel", "ATENCION"))
        self.rostro.set_expresion(self._nivel_actual)
        self._renderizar_acciones_sugeridas(alerta.get("accionesSugeridas", []))
        self.reposicionar_en_padre()
        return alerta

    def _on_habla(self, hablando: bool) -> None:
        self.btn_callar.setVisible(hablando)
        self.rostro.set_expresion("HABLANDO" if hablando else self._nivel_actual)

    def _on_escucha(self, escuchando: bool) -> None:
        self.rostro.set_expresion("ESCUCHANDO" if escuchando else self._nivel_actual)
        self.btn_mic.setText("●" if escuchando else "🎤")
        self.btn_mic.setToolTip(
            tr("Toca para detener y procesar tu voz ahora")
            if escuchando
            else tr("Hablar por micrófono")
        )
        if escuchando:
            self.lbl_burbuja.setText(
                tr("Escuchando, señor… Hable ahora (toque ● para procesar antes).")
            )
            self.reposicionar_en_padre()

    def _on_transcribiendo(self, transcribiendo: bool) -> None:
        if transcribiendo:
            self.rostro.set_expresion("ANALIZANDO")
            self.lbl_burbuja.setText(tr("Procesando su voz, señor…"))
            self.reposicionar_en_padre()

    def _on_sin_audio(self, aviso: str) -> None:
        self.lbl_burbuja.setText(aviso)
        self.reposicionar_en_padre()

    def _on_historial_limpiado(self) -> None:
        self._ultimas_acciones = []
        self._ultimas_confs = []
        self._cargar_historial()
        self.lbl_burbuja.setText(tr("Historial reiniciado, señor. Listo cuando me necesite."))
        self._limpiar_acciones_sugeridas()
        self.reposicionar_en_padre()

    def _activar_microfono(self) -> None:
        dur = float(self.state.config.get("duracionMicrofonoSeg", 4.5))
        self.motor_voz.escuchar_orden_microfono(dur)

    def _on_transcripcion(self, texto: str) -> None:
        self.txt_input.setText(texto)
        self._enviar_consulta()

    def _disparar_sos(self) -> None:
        nueva = crear_solicitud_ayuda(
            crew_id_solicitante=self.state.crew_id,
            destinatario="CMO_A_BORDO_C001",
            nivel="CRITICO",
            motivo=tr("Solicitud de asistencia médica desde L.I.S. para {c}", c=self.state.crew_id),
            resumen_clinico=self.lbl_burbuja.text(),
            protocolo_sugerido_id="cardiovascular",
        )
        msg_txt = tr(
            "Alerta {hash} enviada al Oficial Médico C001 y encolada para Tierra, señor.",
            hash=nueva["hash"],
        )
        self.lbl_burbuja.setText(msg_txt)
        self.rostro.set_expresion("CRITICO")
        self.state.ayudaCambiada.emit()
        if self.state.config.get("vozActiva", True):
            self.motor_voz.hablar(
                msg_txt,
                voz_id=self.state.config.get("vozId", "jarvis-clone-latam"),
                velocidad=float(self.state.config.get("velocidadVoz", 1.04)),
                lang=i18n.idioma(),
            )

    def _enviar_consulta(self) -> None:
        texto = self.txt_input.text().strip()
        if not texto:
            return
        self.txt_input.clear()

        low = texto.lower().strip()
        if low in (
            "cállate",
            "callate",
            "silencio",
            "para de hablar",
            "deja de hablar",
            "detén la voz",
            "deten la voz",
            "shut up",
            "quiet",
            "be quiet",
            "stop talking",
            "stop speaking",
            "mute",
            "silence",
        ):
            self.motor_voz.detener_habla()
            self.lbl_burbuja.setText(tr("En silencio, señor."))
            self.reposicionar_en_padre()
            return

        guardar_mensaje_chat(
            {
                "crewId": self.state.crew_id,
                "emisor": "astronauta",
                "texto": texto,
                "nivelAlerta": "NOMINAL",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # 1) Control rápido local (actualiza contexto/ajustes sin llamada LLM redundante)
        es_nota = low.startswith(("recuerda ", "anota ", "remember ", "note "))
        ejecuto, confirmacion = interpretar_comando_control_nativo(texto, self.state)
        if ejecuto and confirmacion and not es_nota:
            resp = {
                "crewId": self.state.crew_id,
                "emisor": "asistente",
                "texto": confirmacion,
                "nivelAlerta": "NOMINAL",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            guardar_mensaje_chat(resp)
            self._mostrar_respuesta(resp)
            return

        # 2) Nota de memoria ("recuerda que..." / "anota..." / "remember that...")
        if es_nota:
            nota = re.sub(
                r"^(?:recuerda(?:\s+que)?|anota(?:\s+que)?|remember(?:\s+that)?|note(?:\s+that)?)\s+",
                "",
                texto,
                flags=re.IGNORECASE,
            ).strip()
            if nota:
                recordar_dato_astronauta(self.state.crew_id, nota, "observacion")

        # 3) Agente libre con LLM + control autónomo + validación anti-alucinación
        self.rostro.set_expresion("ANALIZANDO")
        self.lbl_burbuja.setText(tr("Analizando su consulta, señor…"))
        self._limpiar_acciones_sugeridas()
        self.reposicionar_en_padre()
        crew = self.state.crew_id
        tp = self.state.timepoint
        estado_ui = self.state.contexto_pantalla_actual()
        pag = estado_ui["pagina"]
        modo = "emergencia" if pag == "emergencia" else "rutina"
        cfg = dict(self.state.config)

        def _worker() -> None:
            snap = construir_snapshot_contexto(crew, tp, modo)
            mem = obtener_memoria_astronauta(crew)
            hist = obtener_historial_chat(crew, 4)
            det = generar_respuesta_determinista(
                mensaje_usuario=texto,
                crew_id=crew,
                timepoint=tp,
                modo_operacion=modo,
                memoria=mem,
                estado_ui=estado_ui,
                personalidad=str(cfg.get("personalidad", "jarvis-cordial")),
            )
            texto_final, acciones_llm, _motor = consultar_agente_libre(
                cfg,
                texto,
                snap,
                det,
                estado_ui=estado_ui,
                memoria=mem,
                historial=hist,
            )
            det["texto"] = texto_final
            if acciones_llm:
                det["accionesControl"] = acciones_llm
            guardar_mensaje_chat(det)
            self.respuestaLista.emit(det)

        threading.Thread(target=_worker, daemon=True).start()

    def _consulta_rapida(self, texto: str) -> None:
        self.txt_input.setText(texto)
        self._enviar_consulta()

    def _limpiar_acciones_sugeridas(self) -> None:
        while self.fila_acciones_sugeridas.count():
            item = self.fila_acciones_sugeridas.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _renderizar_acciones_sugeridas(
        self, acciones: list, confirmaciones: Optional[list[str]] = None
    ) -> None:
        self._ultimas_acciones = list(acciones or [])
        self._ultimas_confs = list(confirmaciones or [])
        self._limpiar_acciones_sugeridas()
        confs = self._ultimas_confs[:3]
        c_ok = QColor(t.NORMAL)
        for tag in confs:
            chip = QLabel(f"✓ {tag}")
            chip.setStyleSheet(
                f"color: {t.NORMAL}; background: rgba({c_ok.red()}, {c_ok.green()}, {c_ok.blue()}, 28); "
                f"border: 1px solid rgba({c_ok.red()}, {c_ok.green()}, {c_ok.blue()}, 85); border-radius: 8px; "
                f"padding: 6px 10px; font-size: {t.T_PEQUENO - 1}px; font-weight: 600;"
            )
            self.fila_acciones_sugeridas.addWidget(chip)
        for acc in self._ultimas_acciones[:3]:
            etq = tr(acc.get("etiqueta", "Acción"))
            prio = acc.get("prioridad", "normal")
            estilo = "peligro" if prio == "critica" else ("primario" if prio == "alta" else "secundario")
            btn = boton(etq, estilo=estilo, al_pulsar=lambda _=False, a=acc: self._ejecutar_accion_sugerida(a))
            if estilo == "peligro":
                btn.setStyleSheet(
                    f"QPushButton {{ background: {t.PELIGRO_BG}; color: {t.PELIGRO_FG}; border: 1px solid {t.PELIGRO_BORDE};"
                    f" border-radius: 12px; padding: 8px 14px; font-size: {t.T_PEQUENO}px; font-weight: 600; }}"
                )
            elif estilo == "primario":
                btn.setStyleSheet(
                    f"QPushButton {{ background: {t.TEXTO}; color: {t.PRIMARIO_FG}; border: none;"
                    f" border-radius: 12px; padding: 8px 14px; font-size: {t.T_PEQUENO}px; font-weight: 600; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {t.TEXTO_SUAVE}; border: 1px solid {t.BORDE};"
                    f" border-radius: 12px; padding: 8px 14px; font-size: {t.T_PEQUENO}px; }}"
                )
            self.fila_acciones_sugeridas.addWidget(btn)
        if confs or acciones:
            self.fila_acciones_sugeridas.addStretch(1)

    def _ejecutar_accion_sugerida(self, acc: Dict[str, Any]) -> None:
        tipo = acc.get("tipo", "")
        if tipo == "ABRIR_EMERGENCIA":
            proto = acc.get("protocoloId") or "cardiovascular"
            self.state.ir_a("emergencia", protocoloId=proto)
        elif tipo == "PEDIR_AYUDA_CMO":
            self._disparar_sos()
        elif tipo == "INICIAR_MEDICION":
            pid = acc.get("parametroId")
            if pid:
                self.state.ir_a("medir", indicadorId=pid)
            else:
                self.state.ir_a("medir")
        elif tipo == "ENFOCAR_SISTEMA":
            sis = acc.get("sistemaId")
            if sis:
                self.state.set_sistema(sis)
                if self.state.pagina not in ("inicio", "cuerpo"):
                    self.state.ir_a("cuerpo")
        elif tipo == "PANEL_AVISOS":
            self.state.controlAvisosSolicitado.emit(str(acc.get("valor") or "abrir"))
        elif tipo == "NAVEGAR":
            ruta = (acc.get("destinoRuta") or "").strip("/")
            self.state.ir_a(ruta or "cuerpo")

    def _aplicar_config_accion(self, clave: str, raw_val: Any) -> Optional[str]:
        """Valida y aplica cambios seguros de configuración solicitados al agente."""
        if not clave:
            return None
        sval = str(raw_val).strip()
        low = sval.lower()

        def _a_bool(v: Any) -> Optional[bool]:
            if isinstance(v, bool):
                return v
            if low in ("true", "1", "si", "sí", "yes", "on", "activo", "active", "activar", "habilitar", "enable"):
                return True
            if low in ("false", "0", "no", "off", "inactivo", "inactive", "desactivar", "deshabilitar", "disable"):
                return False
            return None

        if clave == "temaVisual":
            tema = "claro" if any(k in low for k in ("clar", "light")) else ("oscuro" if any(k in low for k in ("oscur", "dark")) else "")
            if tema:
                self.state.actualizar_config(temaVisual=tema)
                return tr("Tema {t}", t=tr(tema))
        elif clave == "idioma":
            cod = "en" if any(k in low for k in ("en", "ing", "eng")) else ("es" if any(k in low for k in ("es", "esp", "spa")) else "")
            if cod:
                self.state.actualizar_config(idioma=cod)
                return tr("Idioma: {v}", v="English" if cod == "en" else "Español")
        elif clave in (
            "vozActiva",
            "animacion3D",
            "mostrarAsistente",
            "mostrarAvisosEmergentes",
            "autoEscalarAyudaCritica",
            "permitirNavegacionAutonoma",
            "permitirControlParametros",
            "alarmaEmergenciaSonora",
            "alarmaEmergenciaIncluirSbar",
            "sonidoMonitorOverview",
        ):
            b = _a_bool(raw_val)
            if b is not None:
                self.state.actualizar_config(**{clave: b})
                return tr("{c}: {v}", c=clave, v=tr("sí") if b else tr("no"))
        elif clave == "alarmaEmergenciaVolumen":
            try:
                num = float(sval.replace("%", "").strip())
                if num > 1.0:
                    num = num / 100.0
                vol = round(max(0.25, min(1.0, num)), 2)
                self.state.actualizar_config(alarmaEmergenciaVolumen=vol)
                return tr("Volumen de alarma {v} %", v=int(round(vol * 100)))
            except Exception:
                return None
        elif clave == "volumenMonitorOverview":
            try:
                num = float(sval.replace("%", "").strip())
                if num > 1.0:
                    num = num / 100.0
                vol = round(max(0.15, min(1.0, num)), 2)
                self.state.actualizar_config(volumenMonitorOverview=vol)
                return tr("Volumen del monitor {v} %", v=int(round(vol * 100)))
            except Exception:
                return None
        elif clave == "alarmaEmergenciaIntervaloMs":
            try:
                ms_raw = float(sval.lower().replace("ms", "").replace("s", "").strip())
                if ms_raw < 100:
                    ms_raw *= 1000.0
                ms = min((2000, 2800, 4500, 6000), key=lambda x: abs(x - ms_raw))
                self.state.actualizar_config(alarmaEmergenciaIntervaloMs=ms)
                return tr("Intervalo de alarma {v}", v=f"{ms / 1000.0:g} s")
            except Exception:
                return None
        elif clave == "alarmaEmergenciaTono":
            mapa_tonos = {
                "doble-suave": "doble-suave",
                "doble": "doble-suave",
                "pulso-unico": "pulso-unico",
                "unico": "pulso-unico",
                "único": "pulso-unico",
                "acorde-tibio": "acorde-tibio",
                "acorde": "acorde-tibio",
            }
            tono = mapa_tonos.get(low)
            if tono:
                self.state.actualizar_config(alarmaEmergenciaTono=tono)
                return tr("Timbre de alarma: {v}", v=tono)
        elif clave == "vozId":
            mapa_voces = {
                "jarvis-clone-latam": "jarvis-clone-latam",
                "jarvis-clone-en": "jarvis-clone-latam",
                "jarvis-clone-classic": "jarvis-clone-classic",
                "jarvis": "jarvis-clone-latam",
                "estudio": "jarvis-clone-latam",
                "studio": "jarvis-clone-latam",
                "clonada": "jarvis-clone-latam",
                "es-mx-jorgeneural": "es-MX-JorgeNeural",
                "jorge": "es-MX-JorgeNeural",
                "en-us-guyneural": "en-US-GuyNeural",
                "guy": "en-US-GuyNeural",
                "rapida": "es-MX-JorgeNeural",
                "rápida": "es-MX-JorgeNeural",
                "fast": "en-US-GuyNeural",
                "es-es-alvaroneural": "es-ES-AlvaroNeural",
                "alvaro": "es-ES-AlvaroNeural",
                "álvaro": "es-ES-AlvaroNeural",
                "en-gb-ryanneural": "en-GB-RyanNeural",
                "ryan": "en-GB-RyanNeural",
                "es-mx-dalianeural": "es-MX-DaliaNeural",
                "dalia": "es-MX-DaliaNeural",
                "en-us-arianeural": "en-US-AriaNeural",
                "aria": "en-US-AriaNeural",
            }
            vid = mapa_voces.get(low) or (
                sval
                if sval
                in (
                    "jarvis-clone-latam",
                    "jarvis-clone-classic",
                    "es-MX-JorgeNeural",
                    "es-ES-AlvaroNeural",
                    "es-MX-DaliaNeural",
                    "en-US-GuyNeural",
                    "en-US-AriaNeural",
                    "en-GB-RyanNeural",
                )
                else None
            )
            if vid:
                self.state.actualizar_config(vozId=vid)
                return tr("Voz: {v}", v=vid)
        elif clave == "velocidadVoz":
            try:
                vel = round(max(0.85, min(1.45, float(sval.replace("x", "")))), 2)
                self.state.actualizar_config(velocidadVoz=vel)
                return tr("Velocidad {v}x", v=f"{vel:.2f}")
            except Exception:
                return None
        elif clave == "personalidad":
            pers = (
                "jarvis-cordial"
                if any(k in low for k in ("cordial", "jarvis", "warm"))
                else ("directo-clinico" if any(k in low for k in ("direct", "clinic")) else "")
            )
            if pers:
                self.state.actualizar_config(personalidad=pers)
                return tr("Tono: {p}", p=tr("Cordial") if pers == "jarvis-cordial" else tr("Directo"))
        elif clave in ("escalaFuente", "escalaUI"):
            try:
                esc = min((1.0, 1.15, 1.3), key=lambda x: abs(x - float(sval)))
                esc_txt = {1.0: "1.0", 1.15: "1.15", 1.3: "1.3"}[esc]
                self.state.actualizar_config(escalaUI=esc_txt)
                return tr("Fuente {v}x", v=esc_txt)
            except Exception:
                return None
        elif clave == "duracionMicrofonoSeg":
            try:
                dur = min((3.0, 4.5, 7.0), key=lambda x: abs(x - float(sval)))
                self.state.actualizar_config(duracionMicrofonoSeg=dur)
                return tr("Micrófono {v}s", v=dur)
            except Exception:
                return None
        return None

    def _ejecutar_acciones_control_llm(self, acciones: list) -> list[str]:
        permitir_nav = bool(self.state.config.get("permitirNavegacionAutonoma", True))
        permitir_params = bool(self.state.config.get("permitirControlParametros", True))
        confirmaciones: list[str] = []
        alias_paginas = {
            "ajustes": "lis",
            "configuracion": "lis",
            "configuración": "lis",
            "config": "lis",
            "settings": "lis",
            "preferences": "lis",
            "emergencias": "emergencia",
            "emergency": "emergencia",
            "emergencies": "emergencia",
            "3d": "cuerpo",
            "modelo": "cuerpo",
            "body": "cuerpo",
            "anatomy": "cuerpo",
            "medicion": "medir",
            "medición": "medir",
            "measure": "medir",
            "historia": "historial",
            "history": "historial",
            "home": "inicio",
            "overview": "inicio",
            "sala": "sala",
            "control": "sala",
            "mision": "sala",
            "misión": "sala",
            "tripulacion": "sala",
            "tripulación": "sala",
            "crew": "sala",
            "mission": "sala",
            "salud_mental": "salud_mental",
            "salud mental": "salud_mental",
            "mental": "salud_mental",
            "mental health": "salud_mental",
            "emocional": "salud_mental",
            "emotional": "salud_mental",
            "bienestar": "salud_mental",
            "wellbeing": "salud_mental",
            "conducta": "salud_mental",
            "bhp": "salud_mental",
            "mind": "salud_mental",
            "sueño": "salud_mental",
            "sueno": "salud_mental",
            "sleep": "salud_mental",
            "pvt": "salud_mental",
            "descompresion": "salud_mental",
            "descompresión": "salud_mental",
            "dsn": "salud_mental",
        }
        alias_organos = {
            "heart": "corazon",
            "lungs": "pulmones",
            "lung": "pulmones",
            "liver": "higado",
            "kidneys": "riñones",
            "kidney": "riñones",
            "brain": "cerebro",
            "eyes": "ojos",
            "eye": "ojos",
            "stomach": "estomago",
            "pancreas": "pancreas",
            "spleen": "bazo",
            "bones": "huesos",
            "bone": "huesos",
        }

        for acc in acciones:
            tipo = str(acc.get("tipo", "")).upper().strip()
            val = str(acc.get("valor", "")).strip()

            if tipo == "SET_CREW" and permitir_params:
                cid = val.upper()
                if cid in CREW_IDS:
                    self.state.set_crew(cid)
                    confirmaciones.append(tr("Tripulante {c}", c=cid))
            elif tipo == "SET_TIMEPOINT" and permitir_params:
                tp = val.upper()
                if tp in TIMEPOINTS:
                    self.state.set_timepoint(tp)
                    confirmaciones.append(tr("Etapa {t}", t=tp))
            elif tipo == "SET_SISTEMA" and permitir_params:
                sis = val.lower()
                if sis in SISTEMAS:
                    self.state.set_sistema(sis)
                    confirmaciones.append(tr("Sistema: {s}", s=tr(SISTEMAS[sis])))
            elif tipo == "SET_CAMARA_3D" and permitir_params:
                cam = val.lower()
                if cam in ("cuerpo", "frontal", "lateral", "capas"):
                    if permitir_nav and self.state.pagina != "cuerpo":
                        self.state.ir_a("cuerpo")
                    self.state.vistaCamaraSolicitada.emit(cam)
                    confirmaciones.append(tr("Vista 3D: {v}", v=tr(cam)))
            elif tipo == "CONTROL_ZOOM_3D" and permitir_params:
                z_raw = str(acc.get("accion") or val or "acercar").strip().lower()
                mapa_z = {
                    "acercar": "acercar",
                    "zoom_in": "acercar",
                    "in": "acercar",
                    "alejar": "alejar",
                    "zoom_out": "alejar",
                    "out": "alejar",
                    "reiniciar": "reiniciar",
                    "reset": "reiniciar",
                }
                z_cmd = mapa_z.get(z_raw, "acercar")
                if permitir_nav and self.state.pagina != "cuerpo":
                    self.state.ir_a("cuerpo")
                self.state.controlVisor3DSolicitado.emit("zoom", z_cmd)
                confirmaciones.append(tr("Zoom 3D: {z}", z=tr(z_cmd)))
            elif tipo == "ENFOCAR_ORGANO" and permitir_params:
                org_raw = str(acc.get("organo") or val or "").strip()
                org = alias_organos.get(org_raw.lower(), org_raw)
                if org:
                    if permitir_nav and self.state.pagina != "cuerpo":
                        self.state.ir_a("cuerpo")
                    self.state.controlVisor3DSolicitado.emit("organo", org)
                    confirmaciones.append(tr("Órgano: {o}", o=org_raw))
            elif tipo == "IR_A" and permitir_nav:
                ind_raw = str(acc.get("indicadorId") or "").lower().strip("/")
                raw_dest = val.lower().strip("/")
                if ind_raw in alias_paginas and raw_dest in ("", "inicio"):
                    raw_dest = ind_raw
                dest = alias_paginas.get(raw_dest, raw_dest)
                if dest in PAGINAS:
                    kwargs: Dict[str, Any] = {}
                    if dest == "medir" and acc.get("indicadorId"):
                        kwargs["indicadorId"] = (
                            resolver_indicador_id(str(acc["indicadorId"]))
                            or str(acc["indicadorId"])
                        )
                    if dest == "emergencia" and acc.get("protocoloId"):
                        kwargs["protocoloId"] = (
                            resolver_protocolo_id(str(acc["protocoloId"]))
                            or "cardiovascular"
                        )
                    self.state.ir_a(dest, **kwargs)
                    confirmaciones.append(tr("Pantalla: {p}", p=tr(PAGINAS[dest])))
            elif tipo == "SELECCIONAR_ANALITO" and permitir_params:
                ind = resolver_indicador_id(str(acc.get("indicadorId") or val or ""))
                if ind:
                    if permitir_nav and self.state.pagina != "historial":
                        self.state.ir_a("historial")
                    self.state.controlHistorialSolicitado.emit(ind)
                    confirmaciones.append(tr("Analito: {a}", a=ind))
            elif tipo == "REGISTRAR_MEDICION":
                ind = resolver_indicador_id(
                    str(acc.get("indicadorId") or self.state.indicador_en_pantalla or "")
                )
                num_raw = acc.get("valor")
                try:
                    num = float(str(num_raw).replace(",", "."))
                except Exception:
                    num = None
                if ind and num is not None:
                    eval_det = evaluar_lectura_determinista(
                        self.state.crew_id, ind, num
                    )
                    guardar_medicion_local(
                        crew_id=self.state.crew_id,
                        indicador_id=ind,
                        valor=num,
                        unidad=str(acc.get("unidad") or eval_det.get("unidad") or ""),
                        nivel_triage=eval_det.get("nivel", "NOMINAL"),
                        notas=tr("Registro asistido por L.I.S."),
                    )
                    self.state.medicionRegistrada.emit(ind)
                    confirmaciones.append(tr("Registro {a}: {v}", a=ind, v=num))
            elif tipo == "LEER_PROTOCOLO":
                pid = (
                    resolver_protocolo_id(
                        str(
                            acc.get("protocoloId")
                            or val
                            or self.state.protocolo_emergencia_activo
                        )
                    )
                    or "cardiovascular"
                )
                paso_raw = acc.get("paso")
                paso_idx = (
                    max(0, int(paso_raw) - 1)
                    if isinstance(paso_raw, (int, float, str))
                    and str(paso_raw).isdigit()
                    and int(paso_raw) >= 1
                    else 0
                )
                if permitir_nav and self.state.pagina != "emergencia":
                    self.state.ir_a("emergencia", protocoloId=pid)
                if permitir_params or self.state.pagina == "emergencia":
                    self.state.controlEmergenciaSolicitado.emit(
                        "paso", {"protocoloId": pid, "paso": paso_idx}
                    )
                confirmaciones.append(tr("Lectura protocolo: {p}", p=tr(pid)))
            elif tipo == "SELECCIONAR_PASO" and permitir_params:
                pid = (
                    resolver_protocolo_id(str(acc.get("protocoloId") or ""))
                    or self.state.protocolo_emergencia_activo
                )
                if permitir_nav and self.state.pagina != "emergencia":
                    self.state.ir_a("emergencia", protocoloId=pid)
                if "delta" in acc and acc.get("delta") is not None:
                    self.state.controlEmergenciaSolicitado.emit(
                        "paso", {"protocoloId": pid, "delta": int(acc["delta"])}
                    )
                else:
                    paso_raw = acc.get("paso") or val or 1
                    try:
                        paso_idx = max(0, int(paso_raw) - 1)
                    except Exception:
                        paso_idx = 0
                    self.state.controlEmergenciaSolicitado.emit(
                        "paso", {"protocoloId": pid, "paso": paso_idx}
                    )
                confirmaciones.append(tr("Paso {p}", p=tr(pid)))
            elif tipo in ("CONTROL_ALSP", "LEER_ALSP"):
                eid = resolver_equipo_alsp(str(acc.get("equipoId") or val or ""))
                if not eid and tipo == "LEER_ALSP":
                    eid = self.state.equipo_alsp_activo or "dea"
                cmd = str(acc.get("comando") or ("seleccionar" if eid else "alternar")).strip().lower()
                paso_raw = acc.get("paso")
                paso_idx = (
                    max(0, int(paso_raw) - 1)
                    if isinstance(paso_raw, (int, float, str))
                    and str(paso_raw).isdigit()
                    and int(paso_raw) >= 1
                    else None
                )
                if tipo == "CONTROL_ALSP" and not permitir_params:
                    continue
                if permitir_nav and self.state.pagina != "emergencia":
                    self.state.ir_a("emergencia")
                if permitir_params or self.state.pagina == "emergencia":
                    self.state.controlEmergenciaSolicitado.emit(
                        "alsp",
                        {
                            "equipoId": eid or self.state.equipo_alsp_activo,
                            "comando": cmd,
                            "paso": paso_idx,
                        },
                    )
                confirmaciones.append(f"ALSP: {eid or self.state.equipo_alsp_activo}")
            elif tipo == "LEER_GUIA_MEDICION":
                ind = (
                    resolver_indicador_id(
                        str(acc.get("indicadorId") or val or self.state.indicador_en_pantalla)
                    )
                    or self.state.indicador_en_pantalla
                )
                if permitir_nav and self.state.pagina != "medir":
                    self.state.ir_a("medir", indicadorId=ind)
                elif permitir_params and self.state.pagina == "medir":
                    self.state.ir_a("medir", indicadorId=ind)
                confirmaciones.append(f"Guía 0G: {ind}")
            elif tipo == "METRONOMO_RCP" and permitir_params:
                m_raw = str(acc.get("accion") or val or "alternar").strip().lower()
                if m_raw in ("iniciar", "activar", "on", "start"):
                    m_cmd = "iniciar"
                elif m_raw in ("detener", "parar", "apagar", "off", "stop"):
                    m_cmd = "detener"
                else:
                    m_cmd = "alternar"
                if permitir_nav and self.state.pagina != "emergencia":
                    self.state.ir_a("emergencia")
                self.state.controlEmergenciaSolicitado.emit("metronomo", {"accion": m_cmd})
                confirmaciones.append(f"Metrónomo RCP ({m_cmd})")
            elif tipo == "PANEL_AVISOS" and permitir_params:
                a_cmd = str(acc.get("accion") or val or "abrir").strip().lower()
                if a_cmd not in ("abrir", "cerrar", "alternar"):
                    a_cmd = "abrir"
                self.state.controlAvisosSolicitado.emit(a_cmd)
                confirmaciones.append(f"Avisos: {a_cmd}")
            elif tipo == "CONFIGURAR" and permitir_params:
                res_cfg = self._aplicar_config_accion(
                    str(acc.get("clave") or "").strip(), acc.get("valor")
                )
                if res_cfg:
                    confirmaciones.append(res_cfg)
            elif tipo == "RECORDAR":
                nota = str(acc.get("nota") or val).strip()
                if nota:
                    recordar_dato_astronauta(self.state.crew_id, nota, "observacion")
                    confirmaciones.append("Nota guardada")
            elif tipo == "DISPARAR_SOS":
                proto = (
                    resolver_protocolo_id(str(acc.get("protocoloId") or ""))
                    or "cardiovascular"
                )
                motivo = str(
                    acc.get("motivo")
                    or f"Escalamiento autónomo de L.I.S. para {self.state.crew_id}"
                )
                crear_solicitud_ayuda(
                    crew_id_solicitante=self.state.crew_id,
                    destinatario="CMO_A_BORDO_C001",
                    nivel="CRITICO",
                    motivo=motivo,
                    resumen_clinico=self.lbl_burbuja.text(),
                    protocolo_sugerido_id=proto,
                )
                self.state.ayudaCambiada.emit()
                confirmaciones.append(tr("Alerta SBAR enviada"))
            elif tipo == "ATENDER_SOS":
                self.state.controlEmergenciaSolicitado.emit("sbar", {"accion": "atender"})
                confirmaciones.append("SOS atendido")
            elif tipo == "SILENCIAR_VOZ":
                self.motor_voz.detener_habla()
                self.state.controlEmergenciaSolicitado.emit("alarma", {"accion": "silenciar"})
                confirmaciones.append("En silencio")
        return confirmaciones

    def _mostrar_respuesta(self, resp: Dict[str, Any]) -> None:
        acciones_ctrl = resp.get("accionesControl") or []
        silenciar = any(
            str(a.get("tipo", "")).upper().strip() == "SILENCIAR_VOZ"
            for a in acciones_ctrl
        )
        confirmaciones = self._ejecutar_acciones_control_llm(acciones_ctrl) if acciones_ctrl else []

        texto = resp.get("texto", "")
        texto_voz = str(resp.get("textoVoz") or texto).strip()
        nivel = resp.get("nivelAlerta", "NOMINAL")
        self.lbl_burbuja.setText(texto)
        self._actualizar_estilo_burbuja_alerta(nivel)
        self.rostro.set_expresion(self._nivel_actual)
        self._renderizar_acciones_sugeridas(
            resp.get("accionesSugeridas", []),
            confirmaciones=confirmaciones,
        )
        self._cargar_historial()
        self.reposicionar_en_padre()

        # Autonomía en emergencia crítica (respetando configuración del usuario)
        if (
            nivel == "CRITICO"
            and resp.get("solicitoAyudaAutomatica")
            and self.state.config.get("autoEscalarAyudaCritica", True)
        ):
            sis = resp.get("sistema3dSugerido")
            if sis and self.state.config.get("permitirControlParametros", True):
                self.state.set_sistema(sis)
            if self.state.config.get("permitirNavegacionAutonoma", True):
                proto = resp.get("protocoloSugerido") or "cardiovascular"
                self.state.ir_a("emergencia", protocoloId=proto)

        if silenciar:
            self.motor_voz.detener_habla()
        elif self.state.config.get("vozActiva", True) and texto_voz:
            self.motor_voz.hablar(
                texto_voz,
                voz_id=self.state.config.get("vozId", "jarvis-clone-latam"),
                velocidad=float(self.state.config.get("velocidadVoz", 1.04)),
                lang=i18n.idioma(),
            )
