# -*- coding: utf-8 -*-
"""
desktop/state.py — Estado global de la app nativa (equivalente al store Zustand web).
Todas las vistas escuchan estas señales; L.I.S. también las dispara para controlar el software.
"""

from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import QObject, Signal

from backend.database import (
    get_cabina_dataset,
    guardar_config_lis,
    obtener_config_lis,
    restaurar_config_lis,
)

CREW_IDS = ["C001", "C002", "C003", "C004"]
TIMEPOINTS = ["L-92", "L-44", "L-3", "R+1", "R+45", "R+82", "R+194"]
ENTORNOS_MISION = ["nave", "estacion", "base-lunar"]
MODOS_TELEMETRIA = ["simulado", "replay-osdr"]

SISTEMAS = {
    "cardiovascular": "Cardiovascular",
    "respiratorio": "Respiratorio",
    "neuro-ocular": "Neuro-ocular (SANS)",
    "metabolico": "Metabólico y renal",
    "musculoesqueletico": "Musculoesquelético",
    "inmune-radiacion": "Inmune y radiación",
}

PAGINAS = {
    "inicio": "Inicio",
    "cuerpo": "Cuerpo 3D",
    "medir": "Medir",
    "historial": "Historial",
    "salud_mental": "Bienestar",
    "sala": "Sala",
    "emergencia": "Emergencia",
    # La clave sigue siendo "lis" porque el agente navega con ella; la
    # pantalla ya reúne todos los ajustes, no sólo los del asistente.
    "lis": "Ajustes",
}


class AppState(QObject):
    crewChanged = Signal(str)
    timepointChanged = Signal(str)
    sistemaChanged = Signal(str)
    entornoCambiado = Signal(str)
    modoTelemetriaCambiado = Signal(str)
    enlaceTierraCambiado = Signal(bool)
    telemetriaEnVivoActualizada = Signal()
    paginaSolicitada = Signal(str, dict)
    configChanged = Signal(dict)
    ayudaCambiada = Signal()
    vistaCamaraSolicitada = Signal(str)
    controlVisor3DSolicitado = Signal(str, str)
    controlEmergenciaSolicitado = Signal(str, dict)
    controlHistorialSolicitado = Signal(str)
    controlAvisosSolicitado = Signal(str)
    medicionRegistrada = Signal(str)
    historialLimpiado = Signal()
    alarmaEmergenciaChanged = Signal(bool, bool)

    def __init__(self) -> None:
        super().__init__()
        self.config: Dict[str, Any] = obtener_config_lis()
        self.crew_id: str = self.config.get("crewId", "C003")
        self.timepoint: str = self.config.get("timepoint", "R+1")
        self.entorno: str = self.config.get("entorno", "nave")
        if self.entorno not in ENTORNOS_MISION:
            self.entorno = "nave"
        self.modo_telemetria: str = self.config.get("modoTelemetria", "simulado")
        if self.modo_telemetria not in MODOS_TELEMETRIA:
            self.modo_telemetria = "simulado"
        self.enlace_tierra_online: bool = bool(self.config.get("enlaceTierraOnline", True))
        self.sistema: str = "metabolico"
        self.pagina: str = "inicio"
        self.modo_camara_3d: str = "cuerpo"
        self.organo_seleccionado: str = ""
        self.indicador_en_pantalla: str = "glucose"
        self.analito_historial: str = "glucose"
        self.protocolo_emergencia_activo: str = "cardiovascular"
        self.paso_emergencia: int = 0
        self.equipo_alsp_activo: str = "dea"
        self.acto_alsp_activo: int = 0
        self.metronomo_activo: bool = False
        self.alarma_roja_presente: bool = False
        self.alarma_emergencia_sonando: bool = False

    def contexto_pantalla_actual(self) -> Dict[str, Any]:
        return {
            "pagina": self.pagina,
            "nombrePagina": PAGINAS.get(self.pagina, "Vista general"),
            "sistema": self.sistema,
            "nombreSistema": SISTEMAS.get(self.sistema, "Metabólico"),
            "entorno": self.entorno,
            "modoTelemetria": self.modo_telemetria,
            "enlaceTierraOnline": self.enlace_tierra_online,
            "modoCamara3d": self.modo_camara_3d,
            "organoSeleccionado": self.organo_seleccionado,
            "indicadorEnPantalla": self.indicador_en_pantalla,
            "analitoHistorial": self.analito_historial,
            "protocoloEmergencia": self.protocolo_emergencia_activo,
            "pasoEmergencia": self.paso_emergencia,
            "equipoAlsp": self.equipo_alsp_activo,
            "actoAlsp": self.acto_alsp_activo,
            "metronomoActivo": self.metronomo_activo,
            "temaVisual": self.config.get("temaVisual", "oscuro"),
            "vozActiva": bool(self.config.get("vozActiva", True)),
            "vozId": self.config.get("vozId", "jarvis-clone-latam"),
            "velocidadVoz": float(self.config.get("velocidadVoz", 1.04)),
            "personalidad": self.config.get("personalidad", "jarvis-cordial"),
            "motorLLM": self.config.get("motorLLM", "cloud-api-auto"),
        }

    # --- tripulación / tiempo / sistema -----------------------------------
    def set_crew(self, crew_id: str) -> None:
        if crew_id in CREW_IDS and crew_id != self.crew_id:
            self.crew_id = crew_id
            self.config = guardar_config_lis({"crewId": crew_id})
            self.crewChanged.emit(crew_id)

    def set_timepoint(self, tp: str) -> None:
        if tp in TIMEPOINTS and tp != self.timepoint:
            self.timepoint = tp
            self.config = guardar_config_lis({"timepoint": tp})
            self.timepointChanged.emit(tp)

    def set_sistema(self, sistema: str) -> None:
        if sistema in SISTEMAS and sistema != self.sistema:
            self.sistema = sistema
            self.sistemaChanged.emit(sistema)

    def set_entorno(self, entorno: str) -> None:
        if entorno in ENTORNOS_MISION and entorno != self.entorno:
            self.entorno = entorno
            self.config = guardar_config_lis({"entorno": entorno})
            self.entornoCambiado.emit(entorno)

    def set_modo_telemetria(self, modo: str) -> None:
        if modo in MODOS_TELEMETRIA and modo != self.modo_telemetria:
            self.modo_telemetria = modo
            self.config = guardar_config_lis({"modoTelemetria": modo})
            self.modoTelemetriaCambiado.emit(modo)

    def set_enlace_tierra(self, online: bool) -> None:
        nuevo = bool(online)
        if nuevo != self.enlace_tierra_online:
            self.enlace_tierra_online = nuevo
            self.config = guardar_config_lis({"enlaceTierraOnline": nuevo})
            self.enlaceTierraCambiado.emit(nuevo)

    def ir_a(self, pagina: str, **params: Any) -> None:
        if pagina in PAGINAS:
            self.pagina = pagina
            self.paginaSolicitada.emit(pagina, params)

    # --- configuración de L.I.S. ------------------------------------------
    def actualizar_config(self, **cambios: Any) -> None:
        self.config = guardar_config_lis(cambios)
        self.configChanged.emit(self.config)

    def restaurar_config(self) -> None:
        self.config = restaurar_config_lis()
        cfg = self.config
        crew_cfg = str(cfg.get("crewId", "C003"))
        if crew_cfg != self.crew_id:
            self.crew_id = crew_cfg
            self.crewChanged.emit(crew_cfg)
        tp_cfg = str(cfg.get("timepoint", "R+1"))
        if tp_cfg != self.timepoint:
            self.timepoint = tp_cfg
            self.timepointChanged.emit(tp_cfg)
        ent_cfg = str(cfg.get("entorno", "nave"))
        if ent_cfg != self.entorno:
            self.entorno = ent_cfg
            self.entornoCambiado.emit(ent_cfg)
        modo_cfg = str(cfg.get("modoTelemetria", "simulado"))
        if modo_cfg != self.modo_telemetria:
            self.modo_telemetria = modo_cfg
            self.modoTelemetriaCambiado.emit(modo_cfg)
        enlace_cfg = bool(cfg.get("enlaceTierraOnline", True))
        if enlace_cfg != self.enlace_tierra_online:
            self.enlace_tierra_online = enlace_cfg
            self.enlaceTierraCambiado.emit(enlace_cfg)
        self.configChanged.emit(self.config)

    # --- utilidades --------------------------------------------------------
    def rol_actual(self) -> str:
        return (
            get_cabina_dataset()
            .get("tripulantes", {})
            .get(self.crew_id, {})
            .get("rol", "Tripulante")
        )
