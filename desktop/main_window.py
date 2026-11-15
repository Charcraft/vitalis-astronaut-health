# -*- coding: utf-8 -*-
"""
desktop/main_window.py — Ventana Principal Nativa de Escritorio (QMainWindow)
para V.I.T.A.L.I.S. (Vital Information Telemetry and Life-support In Space).
100% Nativa en PC (PySide6 + VTK OpenGL 3D + SQLite + Voz JARVIS XTTS GPU).
"""

from __future__ import annotations

import ctypes
import os
from typing import Dict, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from backend.database import atender_solicitud_ayuda, listar_solicitudes_ayuda
from backend.crew_hub import get_crew_hub
from backend.lis_agent import resolver_voz_neural_por_idioma
from backend.runtime import get_runtime
from backend.sync_tierra import get_sync_manager
from desktop import i18n
from desktop import theme as t
from desktop.i18n import tr
from desktop.avisos import (
    AvisoEmergente,
    BotonAvisos,
    PanelAvisos,
    avisos_actuales,
    organos_con_problema,
    nivel_maximo,
    pendientes,
)
from desktop.lis_dock import ALTO_BURBUJA, PanelAsistenteLIS
from desktop.salud_mental import VistaSaludMental
from desktop.state import PAGINAS, AppState
from desktop.viewer3d import VisorAnatomico3D
from desktop.vista_sala import VistaSala
from desktop.views import (
    VistaConfigLIS,
    VistaCuerpo3D,
    VistaEmergencia,
    VistaHistorial,
    VistaInicio,
    VistaMedicion,
)
from desktop.voice_engine import MotorVozNativo
from desktop.widgets import boton, etiqueta, etiqueta_mono, icono_engrane, reaplicar_tema_widgets

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_PATH = os.path.join(ROOT_DIR, "assets", "vitalis.ico")
ICON_FALLBACK_PATH = os.path.join(ROOT_DIR, "assets", "brand", "proyecto.ico")


def ruta_icono_app() -> str:
    """Devuelve la ruta existente del icono principal de V.I.T.A.L.I.S."""
    for ruta in (ICON_PATH, ICON_FALLBACK_PATH):
        if os.path.exists(ruta):
            return ruta
    return ICON_PATH


class VentanaPrincipalVitalis(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(
            "V.I.T.A.L.I.S. — Vital Information Telemetry and Life-support In Space"
        )
        self._hicons_so: list[int] = []
        self._icono_so_aplicado: Optional[tuple[int, str]] = None
        ruta_ico = ruta_icono_app()
        if os.path.exists(ruta_ico):
            self.setWindowIcon(QIcon(ruta_ico))
        self.resize(1460, 920)
        self.setMinimumSize(1180, 760)

        self.state = AppState()
        self._reconstruyendo = False
        self._recursos_cerrados = False
        # El idioma se fija ANTES de construir ninguna vista: cada etiqueta ya nace traducida.
        i18n.fijar_idioma(
            str(self.state.config.get("idioma", i18n.IDIOMA_POR_DEFECTO)), notificar=False
        )
        i18n.al_cambiar(self._on_idioma_cambiado)
        t.aplicar_tema(str(self.state.config.get("temaVisual", "oscuro")))
        self._tema_actual = t.MODO
        app = QApplication.instance()
        if app is not None:
            app.setPalette(t.paleta_qt())
            app.aboutToQuit.connect(self._cerrar_recursos)
        self.setStyleSheet(t.QSS)
        self.motor_voz = MotorVozNativo()

        raiz = QWidget()
        raiz.setObjectName("raiz")
        self.setCentralWidget(raiz)
        capa_raiz = QVBoxLayout(raiz)
        capa_raiz.setContentsMargins(0, 0, 0, 0)
        capa_raiz.setSpacing(0)

        # --- 1. Barra de navegación superior táctil ---
        barra_nav = QFrame()
        self.barra_nav = barra_nav
        barra_nav.setObjectName("barraNav")
        h_nav = QHBoxLayout(barra_nav)
        h_nav.setContentsMargins(12, 10, 12, 10)
        h_nav.setSpacing(3)

        self.btn_marca = QPushButton("V.I.T.A.L.I.S.")
        self.btn_marca.setObjectName("marcaNav")
        self.btn_marca.setMinimumHeight(t.ALTO_TOQUE)
        self.btn_marca.setCursor(Qt.PointingHandCursor)
        self.btn_marca.setToolTip(tr("Ir a Inicio"))
        self.btn_marca.clicked.connect(lambda: self.state.ir_a("inicio"))
        self.lbl_marca = self.btn_marca
        h_nav.addWidget(self.btn_marca)

        # Tripulante y momento: tocar lleva a Ajustes, donde se cambian.
        self.lbl_tripulante_top = boton("", al_pulsar=lambda: self.state.ir_a("lis"))
        self.lbl_tripulante_top.setToolTip(tr("Tocar para cambiar tripulante, momento o entorno"))
        h_nav.addWidget(self.lbl_tripulante_top)
        # Avisos del estado actual: tocar abre la lista.
        self.btn_avisos = BotonAvisos()
        self.btn_avisos.clicked.connect(self._alternar_panel_avisos)
        h_nav.addWidget(self.btn_avisos)
        self.btn_alarma_roja = boton(
            "Alarma · Silenciar", al_pulsar=self._alternar_silencio_alarma
        )
        self.btn_alarma_roja.setVisible(False)
        h_nav.addWidget(self.btn_alarma_roja)
        h_nav.addStretch(1)

        self.grupo_nav = QButtonGroup(self)
        self.grupo_nav.setExclusive(True)
        self.botones_nav: Dict[str, QPushButton] = {}
        for clave, titulo_nav in PAGINAS.items():
            if clave == "lis":
                b = QPushButton("")
                b.setObjectName("navIcono")
                b.setFixedSize(52, t.ALTO_TOQUE)
                b.setIconSize(QSize(24, 24))
                b.setToolTip(tr("Ajustes"))
                b.setAccessibleName(tr("Ajustes"))
            else:
                b = QPushButton(tr(titulo_nav))
                # Emergencia en rojo y al final: se encuentra sin buscarla.
                b.setObjectName("navEmergencia" if clave == "emergencia" else "nav")
                b.setMinimumHeight(t.ALTO_TOQUE)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=clave: self.state.ir_a(k))
            self.grupo_nav.addButton(b)
            self.botones_nav[clave] = b
        self.botones_nav["lis"].toggled.connect(lambda *_: self._actualizar_icono_ajustes())

        orden_nav = [c for c in PAGINAS if c not in ("lis", "emergencia")] + ["lis", "emergencia"]
        for clave in orden_nav:
            h_nav.addWidget(self.botones_nav[clave])
        self._aplicar_estilos_cabecera()
        capa_raiz.addWidget(barra_nav)

        # --- 2. Banner de Alerta SBAR Activa (oculto si no hay SOS) ---
        self.banner_sos = QFrame()
        h_sos = QHBoxLayout(self.banner_sos)
        h_sos.setContentsMargins(28, 10, 28, 10)
        self.lbl_sos_banner = etiqueta("", t.T_CUERPO, t.BANNER_SOS_FG, peso=600)
        btn_atender = boton("Marcar atendido", al_pulsar=self._atender_sos)
        h_sos.addWidget(self.lbl_sos_banner, 1)
        h_sos.addWidget(btn_atender)
        self.banner_sos.setVisible(False)
        self._aplicar_estilos_cabecera()
        capa_raiz.addWidget(self.banner_sos)

        # --- 3. Área central de vistas + Visor Anatómico 3D compartido ---
        cuerpo = QWidget()
        v_cuerpo = QVBoxLayout(cuerpo)
        v_cuerpo.setContentsMargins(28, 22, 28, 16)
        v_cuerpo.setSpacing(16)

        self.stack = QStackedWidget()
        self.vista_inicio = VistaInicio(self.state, self.motor_voz)
        self.vista_sala = VistaSala(self.state)
        self.vista_cuerpo = VistaCuerpo3D(self.state)
        self.vista_medir = VistaMedicion(self.state)
        self.vista_historial = VistaHistorial(self.state)
        self.vista_salud_mental = VistaSaludMental(self.state, self.motor_voz)
        self.vista_emergencia = VistaEmergencia(self.state)
        self.vista_lis = VistaConfigLIS(self.state, self.motor_voz)

        self.mapa_vistas = {
            "inicio": self.vista_inicio,
            "sala": self.vista_sala,
            "cuerpo": self.vista_cuerpo,
            "medir": self.vista_medir,
            "historial": self.vista_historial,
            "salud_mental": self.vista_salud_mental,
            "emergencia": self.vista_emergencia,
            "lis": self.vista_lis,
        }
        for w in self.mapa_vistas.values():
            self.stack.addWidget(w)

        # Instanciar el Visor Anatómico 3D OpenGL/VTK único y montarlo en el panel principal
        self.visor_3d = VisorAnatomico3D(mostrar_barra=True)
        self.visor_3d.sistemaSeleccionado.connect(self._on_organo_3d_seleccionado)
        self.visor_3d.modoVistaCambiado.connect(self._on_modo_3d_cambiado)
        self.vista_inicio.contenedor_3d.addWidget(self.visor_3d)

        v_cuerpo.addWidget(self.stack, 1)

        # --- 4. Panel flotante del agente L.I.S. (sigue al usuario en todas las vistas) ---
        self.dock_lis = PanelAsistenteLIS(self.state, self.motor_voz, parent=self)
        self.dock_lis.reposicionar_en_padre()
        self.dock_lis.raise_()

        capa_raiz.addWidget(cuerpo, 1)

        # --- 5. Pie legal: una línea. Créditos completos en Ajustes > Acerca de ---
        pie = QFrame()
        pie.setObjectName("pie")
        # Alto suficiente para alojar la burbuja minimizada de L.I.S. a la derecha.
        pie.setFixedHeight(ALTO_BURBUJA + 16)
        h_pie = QHBoxLayout(pie)
        h_pie.setContentsMargins(28, 10, 28, 10)
        h_pie.addWidget(
            etiqueta(
                "No es un dispositivo médico · Datos NASA OSDR OSD-575",
                t.T_PEQUENO,
                t.TERCIARIO,
            )
        )
        h_pie.addStretch(1)
        capa_raiz.addWidget(pie)

        # Señales globales
        self.state.crewChanged.connect(self._actualizar_cabecera)
        self.state.timepointChanged.connect(self._actualizar_cabecera)
        self.state.sistemaChanged.connect(self._on_sistema_cambiado)
        self.state.paginaSolicitada.connect(self._cambiar_pagina)
        self.state.ayudaCambiada.connect(self._refrescar_banner_sos)
        self.state.vistaCamaraSolicitada.connect(self.visor_3d.cambiar_modo_vista)
        self.state.controlVisor3DSolicitado.connect(self._on_control_visor_3d)
        self.state.controlAvisosSolicitado.connect(self._on_control_avisos)
        self.state.controlEmergenciaSolicitado.connect(self._on_control_emergencia_global)
        self.state.configChanged.connect(self._aplicar_config)

        # --- 6. Avisos: panel desplegable y aviso emergente (sobre todo lo demás) ---
        self.panel_avisos = PanelAvisos(self)
        self.panel_avisos.verEn3D.connect(self._ver_aviso_en_3d)
        self.panel_avisos.medir.connect(self._medir_desde_aviso)
        self.panel_avisos.protocolo.connect(self._protocolo_desde_aviso)
        self.panel_avisos.revisar.connect(self._revisar_aviso)
        self._ultimo_anuncio_voz = ""
        self._alarma_silenciada_items: set[str] = set()
        self._alarma_roja_activa = False
        self._timer_alarma = QTimer(self)
        intervalo_init = max(1500, min(10000, int(self.state.config.get("alarmaEmergenciaIntervaloMs", 2800))))
        self._timer_alarma.setInterval(intervalo_init)
        self._timer_alarma.timeout.connect(self._tick_alarma_emergencia)
        self.aviso_emergente = AvisoEmergente(self)
        self.aviso_emergente.abrir.connect(self._abrir_panel_avisos)
        self._avisos = []
        self.state.crewChanged.connect(lambda *_: self._refrescar_avisos(emergente=True))
        self.state.timepointChanged.connect(lambda *_: self._refrescar_avisos(emergente=True))
        # Una medición nueva (desde Medir o desde L.I.S.) cambia el estado actual.
        self.vista_medir.lecturaGuardada.connect(lambda *_: self._refrescar_avisos(emergente=True))
        self.vista_medir.lecturaGuardada.connect(lambda *_: self.vista_historial.refrescar())
        self.state.medicionRegistrada.connect(lambda *_: self._refrescar_avisos(emergente=True))

        self._tema_actual = t.MODO
        self._actualizar_marco_ventana_so()
        self._actualizar_cabecera()
        self._refrescar_banner_sos()
        self._aplicar_config(self.state.config)

        # Runtime autónomo 1 Hz + sincronización con Tierra
        self.runtime = get_runtime()
        get_sync_manager().set_estado_red("online" if self.state.enlace_tierra_online else "offline")
        self.runtime.start(
            crew_id=self.state.crew_id,
            entorno=self.state.entorno,
            modo=self.state.modo_telemetria,
        )
        self._firma_alertas_vivas = self._firma_viva_actual()
        self.state.crewChanged.connect(lambda c: self.runtime.set_crew_activa(c))
        self.state.entornoCambiado.connect(self._on_entorno_cambiado)
        self.state.modoTelemetriaCambiado.connect(lambda m: self.runtime.set_modo(m))
        self.state.enlaceTierraCambiado.connect(
            lambda on: get_sync_manager().set_estado_red("online" if on else "offline")
        )

        self._timer_vivo = QTimer(self)
        self._timer_vivo.timeout.connect(self._on_tick_vivo)
        self._timer_vivo.start(1000)

        self._refrescar_avisos(emergente=True)
        self.botones_nav["inicio"].setChecked(True)

    def _firma_viva_actual(self) -> str:
        crew = self.state.crew_id
        snap = get_crew_hub().snapshot()
        est = next((e for e in snap if e.get("crewId") == crew), {})
        alertas = est.get("alertasActivas", []) or []
        return "|".join([
            crew,
            self.state.entorno,
            ",".join(
                f"{a.get('parametroId')}:{a.get('nivel')}:{a.get('reglaDisparada')}"
                for a in sorted(alertas, key=lambda x: str(x.get("parametroId", "")))
            ),
        ])

    def _on_entorno_cambiado(self, entorno: str) -> None:
        self.runtime.set_entorno(entorno)
        self._actualizar_cabecera()
        self._refrescar_avisos(emergente=False)

    def _on_tick_vivo(self) -> None:
        self.state.telemetriaEnVivoActualizada.emit()
        firma = self._firma_viva_actual()
        if firma != self._firma_alertas_vivas:
            emergente = bool(self._firma_alertas_vivas)
            self._firma_alertas_vivas = firma
            self._refrescar_avisos(emergente=emergente)

    def _cerrar_recursos(self) -> None:
        if getattr(self, "_recursos_cerrados", False):
            return
        self._recursos_cerrados = True
        if hasattr(self, "_timer_vivo"):
            self._timer_vivo.stop()
        if hasattr(self, "_timer_alarma"):
            self._timer_alarma.stop()
        for w in list(getattr(self, "mapa_vistas", {}).values()):
            if hasattr(w, "detener_recursos"):
                w.detener_recursos()
            for attr_tm in ("_timer", "_timer_anim"):
                tm = getattr(w, attr_tm, None)
                if tm is not None:
                    tm.stop()
        if hasattr(self, "visor_3d"):
            for attr_tm in ("_timer_cam", "_timer_pulso"):
                tm = getattr(self.visor_3d, attr_tm, None)
                if tm is not None:
                    tm.stop()
        if hasattr(self, "motor_voz"):
            self.motor_voz.cerrar()
        if hasattr(self, "runtime"):
            self.runtime.stop()
        self._liberar_hicons_so()

    def closeEvent(self, ev) -> None:  # noqa: N802
        self._cerrar_recursos()
        super().closeEvent(ev)

    def _liberar_hicons_so(self) -> None:
        hicons = list(getattr(self, "_hicons_so", []) or [])
        if not hicons:
            return
        self._hicons_so = []
        try:
            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                windll.user32.DestroyIcon.argtypes = [ctypes.c_void_p]
                windll.user32.DestroyIcon.restype = ctypes.c_int
                for h in hicons:
                    if h:
                        windll.user32.DestroyIcon(h)
        except Exception:
            pass

    def _sincronizar_icono_so(self) -> None:
        """Asigna WM_SETICON (chico y grande) en Windows para evitar icono genérico."""
        try:
            windll = getattr(ctypes, "windll", None)
            if windll is None:
                return
            ruta_ico = ruta_icono_app()
            if not os.path.exists(ruta_ico):
                return
            hwnd = int(self.winId())
            clave = (hwnd, ruta_ico)
            if getattr(self, "_icono_so_aplicado", None) == clave:
                return
            user32 = windll.user32
            user32.LoadImageW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_uint,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            user32.LoadImageW.restype = ctypes.c_void_p
            user32.SendMessageW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_size_t,
                ctypes.c_void_p,
            ]
            user32.SendMessageW.restype = ctypes.c_ssize_t

            sm_cxsm = max(16, int(user32.GetSystemMetrics(49) or 16))
            sm_cx = max(32, int(user32.GetSystemMetrics(11) or 32))
            nuevos: list[int] = []
            # IMAGE_ICON = 1, LR_LOADFROMFILE = 0x0010, WM_SETICON = 0x0080
            for idx_icon, lado in ((0, sm_cxsm), (1, sm_cx)):
                hicon = user32.LoadImageW(None, ruta_ico, 1, lado, lado, 0x0010)
                if hicon:
                    user32.SendMessageW(hwnd, 0x0080, idx_icon, hicon)
                    nuevos.append(int(hicon))
            if nuevos:
                self._liberar_hicons_so()
                self._hicons_so = nuevos
                self._icono_so_aplicado = clave
        except Exception:
            pass

    def _actualizar_marco_ventana_so(self) -> None:
        """Sincroniza la barra de título nativa de Windows con el tema activo."""
        try:
            windll = getattr(ctypes, "windll", None)
            if windll is None:
                return
            hwnd = int(self.winId())
            valor = ctypes.c_int(1 if t.es_oscuro() else 0)
            for attr in (20, 19):
                windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(valor), ctypes.sizeof(valor)
                )
        except Exception:
            pass

    def _actualizar_icono_ajustes(self) -> None:
        btn = getattr(self, "botones_nav", {}).get("lis")
        if btn is None:
            return
        color = t.TEXTO if btn.isChecked() else t.TEXTO_SUAVE
        btn.setIcon(icono_engrane(color, 24))

    def _aplicar_estilos_cabecera(self) -> None:
        if hasattr(self, "lbl_tripulante_top"):
            self.lbl_tripulante_top.setStyleSheet(
                f"QPushButton {{ color: {t.TEXTO_SUAVE}; border: 1px solid {t.BORDE}; "
                f"border-radius: 12px; padding: 8px 8px; font-size: {t.T_PEQUENO}px; font-weight: 600; }}"
                f"QPushButton:hover {{ border-color: {t.BORDE_SUAVE}; color: {t.TEXTO}; background: {t.HOVER}; }}"
            )
        self._actualizar_icono_ajustes()
        if hasattr(self, "banner_sos"):
            self.banner_sos.setStyleSheet(
                f"QFrame {{ background: {t.BANNER_SOS_BG}; border-bottom: 1px solid {t.BANNER_SOS_BORDE}; }}"
            )
        if hasattr(self, "btn_alarma_roja"):
            self._aplicar_estilo_btn_alarma()

    def aplicar_tema(self, modo: str) -> None:
        """Aplica el tema oscuro/claro en caliente en toda la ventana, 3D, QPainter y dock."""
        t.aplicar_tema(modo)
        self._tema_actual = t.MODO
        app = QApplication.instance()
        if app is not None:
            app.setPalette(t.paleta_qt())
        self._actualizar_marco_ventana_so()
        self.setStyleSheet(t.QSS)
        self._aplicar_estilos_cabecera()
        reaplicar_tema_widgets(self)
        if hasattr(self, "visor_3d") and hasattr(self.visor_3d, "aplicar_tema"):
            self.visor_3d.aplicar_tema()
        if hasattr(self, "dock_lis") and hasattr(self.dock_lis, "aplicar_tema"):
            self.dock_lis.aplicar_tema()
        for w_name in ("btn_avisos", "panel_avisos", "aviso_emergente"):
            w = getattr(self, w_name, None)
            if w is not None and hasattr(w, "aplicar_tema"):
                w.aplicar_tema()
        for vista in self.mapa_vistas.values():
            if hasattr(vista, "aplicar_tema"):
                vista.aplicar_tema()
        if hasattr(self, "dock_lis"):
            self.dock_lis.reposicionar_en_padre()

    def _actualizar_cabecera(self, *_args) -> None:
        ent = {"nave": "Nave", "estacion": "Estación", "base-lunar": "Base lunar"}.get(
            self.state.entorno, self.state.entorno
        )
        self.lbl_tripulante_top.setText(f"{self.state.crew_id} · {self.state.timepoint} · {tr(ent)}")

    # --- idioma ---------------------------------------------------------------
    def _on_idioma_cambiado(self, _codigo: str) -> None:
        """i18n avisa de un cambio de idioma: se reconstruye la UI sin reiniciar."""
        if hasattr(self, "_reconstruyendo") and not self._reconstruyendo:
            QTimer.singleShot(0, self._retraducir_todo)

    def _retraducir_todo(self) -> None:
        """Reconstruye vistas, panel del asistente y avisos en el idioma activo."""
        if getattr(self, "_reconstruyendo", False):
            return
        self._reconstruyendo = True
        try:
            pagina = self.state.pagina
            if hasattr(self, "motor_voz"):
                self.motor_voz.detener_monitor_cardiaco()
            vista_lis_ant = self.mapa_vistas.get("lis")
            if vista_lis_ant is not None and hasattr(vista_lis_ant, "detener_recursos"):
                vista_lis_ant.detener_recursos()
            nuevas = {
                "inicio": VistaInicio(self.state, self.motor_voz),
                "sala": VistaSala(self.state),
                "cuerpo": VistaCuerpo3D(self.state),
                "medir": VistaMedicion(self.state),
                "historial": VistaHistorial(self.state),
                "salud_mental": VistaSaludMental(self.state, self.motor_voz),
                "emergencia": VistaEmergencia(self.state),
                "lis": VistaConfigLIS(self.state, self.motor_voz),
            }

            # El visor 3D es único y compartido: se muda antes de borrar su vista.
            destino = nuevas["cuerpo"] if pagina == "cuerpo" else nuevas["inicio"]
            anterior = self.visor_3d.parentWidget()
            if anterior is not None and hasattr(anterior, "contenedor_3d"):
                anterior.contenedor_3d.removeWidget(self.visor_3d)
            destino.contenedor_3d.addWidget(self.visor_3d)

            for w in list(self.mapa_vistas.values()):
                if hasattr(w, "detener_recursos"):
                    w.detener_recursos()
                for attr_tm in ("_timer", "_timer_anim"):
                    tm = getattr(w, attr_tm, None)
                    if tm is not None:
                        tm.stop()
                self.stack.removeWidget(w)
                w.setParent(None)
                w.deleteLater()

            self.mapa_vistas = nuevas
            self.vista_inicio = nuevas["inicio"]
            self.vista_sala = nuevas["sala"]
            self.vista_cuerpo = nuevas["cuerpo"]
            self.vista_medir = nuevas["medir"]
            self.vista_historial = nuevas["historial"]
            self.vista_salud_mental = nuevas["salud_mental"]
            self.vista_emergencia = nuevas["emergencia"]
            self.vista_lis = nuevas["lis"]
            self.vista_medir.lecturaGuardada.connect(lambda *_: self._refrescar_avisos(emergente=True))
            self.vista_medir.lecturaGuardada.connect(lambda *_: self.vista_historial.refrescar())
            for w in nuevas.values():
                self.stack.addWidget(w)
            self.stack.setCurrentWidget(nuevas.get(pagina, nuevas["inicio"]))

            for clave, btn in self.botones_nav.items():
                if clave == "lis":
                    btn.setText("")
                    btn.setToolTip(tr("Ajustes"))
                    btn.setAccessibleName(tr("Ajustes"))
                else:
                    btn.setText(tr(PAGINAS[clave]))
            if hasattr(self, "btn_marca"):
                self.btn_marca.setToolTip(tr("Ir a Inicio"))
            if hasattr(self, "lbl_tripulante_top"):
                self.lbl_tripulante_top.setToolTip(tr("Tocar para cambiar tripulante, momento o entorno"))
            if pagina in self.botones_nav:
                self.botones_nav[pagina].setChecked(True)
            self._actualizar_icono_ajustes()

            if hasattr(self, "dock_lis"):
                self.dock_lis.retraducir()
            if hasattr(self, "panel_avisos"):
                self.panel_avisos.retraducir()
            if hasattr(self, "aviso_emergente"):
                self.aviso_emergente.retraducir()
            self._actualizar_cabecera()
            self._refrescar_banner_sos()
            self._refrescar_avisos(emergente=False)
            self._actualizar_alarma_emergencia()
            self._actualizar_marco_ventana_so()
        finally:
            self._reconstruyendo = False

    def _aplicar_config(self, cfg: dict) -> None:
        idioma_cfg = str(cfg.get("idioma", i18n.IDIOMA_POR_DEFECTO))
        if idioma_cfg != i18n.idioma() and i18n.ruta_paquete(idioma_cfg):
            i18n.fijar_idioma(idioma_cfg, notificar=False)
            # La voz por defecto sigue al idioma: un texto inglés con una voz
            # castellana suena mal, y al revés también.
            voz_actual = str(cfg.get("vozId", ""))
            if idioma_cfg == "en" and voz_actual.startswith("es-"):
                voz_en = resolver_voz_neural_por_idioma(voz_actual, "en")
                if voz_en not in ("en-US-GuyNeural", "en-US-AriaNeural"):
                    voz_en = "en-US-GuyNeural"
                self.state.actualizar_config(vozId=voz_en)
            elif idioma_cfg == "es" and voz_actual.startswith("en-"):
                self.state.actualizar_config(
                    vozId=resolver_voz_neural_por_idioma(voz_actual, "es")
                )
            # Fuera del manejador de la señal: las vistas actuales se destruyen.
            QTimer.singleShot(0, self._retraducir_todo)
        tema = "claro" if str(cfg.get("temaVisual", "oscuro")).strip().lower() == "claro" else "oscuro"
        if tema != getattr(self, "_tema_actual", None):
            self.aplicar_tema(tema)
        self.dock_lis.setVisible(bool(cfg.get("mostrarAsistente", True)))
        if hasattr(self, "visor_3d"):
            self.visor_3d.set_animacion_activa(bool(cfg.get("animacion3D", True)))
        if hasattr(self, "aviso_emergente") and not cfg.get("mostrarAvisosEmergentes", True):
            self.aviso_emergente.hide()
        if hasattr(self, "_timer_alarma"):
            intervalo = max(1500, min(10000, int(cfg.get("alarmaEmergenciaIntervaloMs", 2800))))
            if self._timer_alarma.interval() != intervalo:
                self._timer_alarma.setInterval(intervalo)
        self._actualizar_alarma_emergencia()

    def _on_organo_3d_seleccionado(self, sistema: str, organo: str) -> None:
        self.state.organo_seleccionado = organo
        self.state.set_sistema(sistema)

    def _on_modo_3d_cambiado(self, modo: str) -> None:
        self.state.modo_camara_3d = modo

    def _on_control_avisos(self, accion: str) -> None:
        if accion == "abrir":
            self._abrir_panel_avisos()
        elif accion == "cerrar" and hasattr(self, "panel_avisos"):
            self.panel_avisos.hide()
        elif accion == "alternar":
            self._alternar_panel_avisos()

    def _on_control_emergencia_global(self, tipo: str, datos: dict) -> None:
        if tipo == "sbar" and datos.get("accion") == "atender":
            self._atender_sos()
        elif tipo == "alarma":
            accion = str(datos.get("accion") or "alternar").strip().lower()
            if accion == "silenciar":
                self._silenciar_alarma_emergencia()
            elif accion == "reactivar":
                self._alarma_silenciada_items.clear()
                self._actualizar_alarma_emergencia()
            elif accion == "pulso":
                self._reproducir_pulso_alarma_con_config()
            else:
                self._alternar_silencio_alarma()

    def _on_control_visor_3d(self, accion: str, valor: str) -> None:
        if not hasattr(self, "visor_3d"):
            return
        if accion == "zoom":
            if valor == "acercar":
                self.visor_3d._zoom(1.25)
            elif valor == "alejar":
                self.visor_3d._zoom(0.8)
            elif valor == "reiniciar":
                self.visor_3d.enfocar_sistema(self.visor_3d.sistema_activo, encuadrar=True)
        elif accion == "organo":
            q = (valor or "").strip().lower()
            aliases = {
                "corazon": (["heart", "coronary_arteries"], "Corazón"),
                "corazón": (["heart", "coronary_arteries"], "Corazón"),
                "pulmon": (["lung_tissue_l", "lung_tissue_r", "lung_l", "lung_r"], "Pulmones"),
                "pulmón": (["lung_tissue_l", "lung_tissue_r", "lung_l", "lung_r"], "Pulmones"),
                "pulmones": (["lung_tissue_l", "lung_tissue_r", "lung_l", "lung_r"], "Pulmones"),
                "higado": (["liver"], "Hígado"),
                "hígado": (["liver"], "Hígado"),
                "riñon": (["kidney_l", "kidney_r"], "Riñones"),
                "riñón": (["kidney_l", "kidney_r"], "Riñones"),
                "riñones": (["kidney_l", "kidney_r"], "Riñones"),
                "rinon": (["kidney_l", "kidney_r"], "Riñones"),
                "cerebro": (["brain", "cerebellum", "brainstem"], "Encéfalo"),
                "encefalo": (["brain", "cerebellum", "brainstem"], "Encéfalo"),
                "encéfalo": (["brain", "cerebellum", "brainstem"], "Encéfalo"),
                "ojo": (["eye_l", "eye_r"], "Ojos"),
                "ojos": (["eye_l", "eye_r"], "Ojos"),
                "estomago": (["stomach"], "Estómago"),
                "estómago": (["stomach"], "Estómago"),
                "pancreas": (["pancreas"], "Páncreas"),
                "páncreas": (["pancreas"], "Páncreas"),
                "bazo": (["spleen"], "Bazo"),
                "intestino": (["small_intestine", "colon"], "Intestino"),
                "colon": (["colon"], "Colon"),
                "hueso": (["femur_l", "femur_r", "pelvis", "spine_lumbar"], "Sistema óseo"),
                "huesos": (["femur_l", "femur_r", "pelvis", "spine_lumbar"], "Sistema óseo"),
            }
            nombres, etq = aliases.get(q, ([], ""))
            if not nombres:
                coinc = [
                    info["nombre"]
                    for info in self.visor_3d.mallas_info
                    if q in info.get("nombre", "").lower() or q in info.get("etiqueta", "").lower()
                ]
                nombres = coinc[:3]
                etq = valor.capitalize()
            if nombres:
                self.state.organo_seleccionado = etq or nombres[0]
                self.visor_3d.enfocar_organos(nombres, etq or None)

    def _on_sistema_cambiado(self, sistema: str) -> None:
        if self.state.pagina == "cuerpo":
            self.visor_3d.modo_vista = "frontal"
            if self.visor_3d.barra:
                self.visor_3d.barra.marcar("frontal")
        self.visor_3d.enfocar_sistema(sistema, encuadrar=True)

    def _cambiar_pagina(self, pagina: str, params: dict) -> None:
        w = self.mapa_vistas.get(pagina)
        if not w:
            return
        if self.stack.currentWidget() is w and not params:
            if pagina in self.botones_nav:
                self.botones_nav[pagina].setChecked(True)
            self.dock_lis.raise_()
            return

        self.stack.setUpdatesEnabled(False)
        try:
            if pagina != "inicio" and hasattr(self, "motor_voz"):
                self.motor_voz.detener_monitor_cardiaco()
            if pagina != "salud_mental" and hasattr(self, "vista_salud_mental"):
                self.vista_salud_mental.detener_recursos()
            # Compartir el único contexto OpenGL VTK entre Vista general y Cuerpo 3D
            if pagina == "inicio":
                if self.visor_3d.parent() is not self.vista_inicio:
                    self.vista_cuerpo.contenedor_3d.removeWidget(self.visor_3d)
                    self.vista_inicio.contenedor_3d.addWidget(self.visor_3d)
                self.stack.setCurrentWidget(w)
                self.visor_3d.cambiar_modo_vista("cuerpo")
            elif pagina == "cuerpo":
                if self.visor_3d.parent() is not self.vista_cuerpo:
                    self.vista_inicio.contenedor_3d.removeWidget(self.visor_3d)
                    self.vista_cuerpo.contenedor_3d.addWidget(self.visor_3d)
                self.stack.setCurrentWidget(w)
                self.visor_3d.cambiar_modo_vista("frontal")
            else:
                if pagina == "medir" and params.get("indicadorId"):
                    self.vista_medir.seleccionar_indicador(str(params["indicadorId"]))
                elif pagina == "historial" and params.get("paramId"):
                    self.vista_historial.seleccionar_analito(
                        str(params["paramId"]), modo=params.get("modo")
                    )
                elif pagina == "emergencia" and params.get("protocoloId"):
                    self.vista_emergencia.seleccionar_protocolo(str(params["protocoloId"]))
                elif pagina == "salud_mental" and (params.get("seccion") or params.get("panel")):
                    self.vista_salud_mental.seleccionar_seccion(
                        str(params.get("seccion") or params.get("panel"))
                    )
                elif pagina == "sala" and params.get("panel"):
                    self.vista_sala.seleccionar_panel(str(params["panel"]))
                self.stack.setCurrentWidget(w)
        finally:
            self.stack.setUpdatesEnabled(True)

        if pagina in self.botones_nav:
            self.botones_nav[pagina].setChecked(True)
        self._actualizar_icono_ajustes()
        self.dock_lis.raise_()

    # --- avisos ---------------------------------------------------------------
    def _refrescar_avisos(self, emergente: bool = False) -> None:
        crew, tp = self.state.crew_id, self.state.timepoint
        revisados = set(self.state.config.get("avisosRevisados", []) or [])
        self._avisos = avisos_actuales(crew, tp, revisados)
        pend = pendientes(self._avisos)
        # El botón y el emergente cuentan lo pendiente; el modelo resalta todo lo
        # que sigue fuera de rango, revisado o no: el órgano no se ha curado.
        self.btn_avisos.set_estado(len(pend), nivel_maximo(pend), len(self._avisos), nivel_maximo(self._avisos))
        self.panel_avisos.cargar(self._avisos, crew, tp)
        claves = {a["clave"] for a in self._avisos}
        if claves != getattr(self, "_claves_avisos", None):
            # Cambió lo que está fuera de rango: la etiqueta del 3D no debe
            # seguir nombrando un aviso que ya no existe.
            self._claves_avisos = claves
            self.visor_3d.lbl_organo.setText("")
        self.visor_3d.marcar_problemas(organos_con_problema(self._avisos))
        # Inicio y Cuerpo 3D leen los mismos avisos: tras una medición nueva
        # también cambian (sólo se repintan si están a la vista).
        self.vista_inicio.refrescar()
        self.vista_cuerpo.refrescar()
        mostrar_popups = bool(self.state.config.get("mostrarAvisosEmergentes", True))
        if emergente and mostrar_popups and pend and not self.panel_avisos.isVisible():
            self.aviso_emergente.mostrar(pend, crew, tp)
            self._colocar_capas_avisos()
        elif not pend or not mostrar_popups:
            self.aviso_emergente.hide()
        alerta_lis = None
        if hasattr(self, "dock_lis") and self.dock_lis is not None:
            alerta_lis = self.dock_lis.notificar_alerta_proactiva(pend, crew, tp)
        if emergente:
            self._anunciar_alertas(pend, alerta_lis)
        self._actualizar_alarma_emergencia()

    def _anunciar_alertas(self, pend: list, alerta_lis: Optional[dict] = None) -> None:
        """Avisa en voz alta tanto en alerta roja (urgente) como amarilla (calmada con indicaciones)."""
        if not pend:
            self._ultimo_anuncio_voz = ""
            return
        if alerta_lis and alerta_lis.get("firma"):
            clave = str(alerta_lis["firma"])
            texto = str(alerta_lis.get("textoVoz") or alerta_lis.get("texto") or "").strip()
        else:
            orden = sorted(
                pend,
                key=lambda x: (
                    0 if x["nivel"] == "CRITICO" else 1,
                    -abs(float(x.get("desvio", 0.0) or 0.0)),
                ),
            )
            a = orden[0]
            tp = self.state.timepoint
            clave = f"{tp}|" + "|".join(
                f"{self.state.crew_id}:{x.get('indicadorId')}:{x.get('nivel')}:{x.get('reglaDisparada', '')}"
                if x.get("origen") == "vivo"
                else str(x.get("clave", ""))
                for x in orden
            )
            accion = tr(str(a.get("accion") or ""))
            if a["nivel"] == "CRITICO":
                texto = tr(
                    "Aviso crítico para {crew}: {titulo}. {accion}",
                    crew=self.state.crew_id,
                    titulo=a["titulo"],
                    accion=accion,
                )
            else:
                texto = tr(
                    "Aviso preventivo para {crew}, sin alarma crítica: {titulo}. Para mejorar: {accion}",
                    crew=self.state.crew_id,
                    titulo=a["titulo"],
                    accion=accion,
                )
        if not clave or not texto or clave == self._ultimo_anuncio_voz:
            return
        self._ultimo_anuncio_voz = clave
        if not bool(self.state.config.get("vozActiva", True)):
            return
        try:
            self.motor_voz.hablar(
                texto,
                voz_id=self.state.config.get("vozId", "jarvis-clone-latam"),
                velocidad=float(self.state.config.get("velocidadVoz", 1.04)),
                lang=i18n.idioma(),
            )
        except Exception:
            pass

    def _revisar_aviso(self, aviso: dict) -> None:
        revisados = list(self.state.config.get("avisosRevisados", []) or [])
        clave = aviso.get("clave", "")
        if clave in revisados:
            revisados.remove(clave)
        else:
            revisados.append(clave)
        self.state.actualizar_config(avisosRevisados=revisados[-200:])
        self._refrescar_avisos()

    def _protocolo_desde_aviso(self, protocolo_id: str) -> None:
        self.panel_avisos.hide()
        self.state.ir_a("emergencia", protocoloId=protocolo_id)

    def _alternar_panel_avisos(self) -> None:
        if self.panel_avisos.isVisible():
            self.panel_avisos.hide()
        else:
            self._abrir_panel_avisos()

    def _abrir_panel_avisos(self) -> None:
        self.aviso_emergente.hide()
        self.panel_avisos.show()
        self._colocar_capas_avisos()
        self.panel_avisos.raise_()

    def _ver_aviso_en_3d(self, aviso: dict) -> None:
        self.panel_avisos.hide()
        self.state.set_sistema(aviso.get("sistema", self.state.sistema))
        self.state.ir_a("cuerpo")
        if aviso.get("organos"):
            # La etiqueta lleva sólo el aviso: con los órganos no cabía.
            self.visor_3d.enfocar_organos(aviso["organos"], aviso["titulo"])

    def _medir_desde_aviso(self, indicador_id: str) -> None:
        self.panel_avisos.hide()
        self.state.ir_a("medir", indicadorId=indicador_id)

    def _colocar_capas_avisos(self) -> None:
        if not hasattr(self, "panel_avisos"):
            return
        nav_geo = self.barra_nav.geometry()
        nav_bottom = nav_geo.bottom() if self.barra_nav.height() <= 140 else self.barra_nav.sizeHint().height()
        y = max(nav_bottom, 56) + 10
        x = self.width() - self.panel_avisos.width() - 24
        alto = min(self.height() - y - 110, 720)
        self.panel_avisos.setGeometry(x, y, self.panel_avisos.width(), max(alto, 240))
        self.aviso_emergente.adjustSize()
        self.aviso_emergente.move(self.width() - self.aviso_emergente.width() - 24, y)
        self.panel_avisos.raise_()
        self.aviso_emergente.raise_()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self._sincronizar_icono_so()
        if hasattr(self, "panel_avisos"):
            QTimer.singleShot(0, self._colocar_capas_avisos)
        if hasattr(self, "dock_lis"):
            QTimer.singleShot(0, self.dock_lis.reposicionar_en_padre)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        if hasattr(self, "panel_avisos"):
            self._colocar_capas_avisos()
        super().resizeEvent(ev)
        if hasattr(self, "dock_lis"):
            self.dock_lis.reposicionar_en_padre()

    def _refrescar_banner_sos(self) -> None:
        activas = listar_solicitudes_ayuda(solo_activas=True)
        if activas:
            s0 = activas[0]
            self.lbl_sos_banner.setText(
                tr(
                    "▲ ALERTA SBAR ACTIVA [{hash}] · {crew} → CMO (C001) + Tierra · {motivo}",
                    hash=s0["hash"],
                    crew=s0["crewIdSolicitante"],
                    motivo=tr(s0["motivo"]),
                )
            )
            self.banner_sos.setVisible(True)
        else:
            self.banner_sos.setVisible(False)
        self._actualizar_alarma_emergencia()

    def _atender_sos(self) -> None:
        activas = listar_solicitudes_ayuda(solo_activas=True)
        if activas:
            atender_solicitud_ayuda(int(activas[0]["id"]))
            self.state.ayudaCambiada.emit()

    # --- Alarma sonora intermitente en emergencia roja ------------------------
    def _items_emergencia_roja_activos(self) -> set[str]:
        items: set[str] = set()
        for a in pendientes(getattr(self, "_avisos", []) or []):
            if a.get("nivel") == "CRITICO":
                if a.get("origen") == "vivo":
                    items.add(
                        f"av:{self.state.crew_id}:{a.get('indicadorId')}:{a.get('reglaDisparada', '')}"
                    )
                else:
                    items.add(f"av:{a.get('clave', a.get('indicadorId', ''))}")
        if bool(self.state.config.get("alarmaEmergenciaIncluirSbar", True)):
            try:
                for s in listar_solicitudes_ayuda(solo_activas=True):
                    items.add(f"sos:{s['hash']}")
            except Exception:
                pass
        return items

    def _aplicar_estilo_btn_alarma(self) -> None:
        if not hasattr(self, "btn_alarma_roja"):
            return
        sonando = getattr(self, "_alarma_roja_activa", False)
        if sonando:
            self.btn_alarma_roja.setStyleSheet(
                f"QPushButton {{ background: {t.PELIGRO_BG}; color: {t.ALERTA}; "
                f"border: 1px solid {t.PELIGRO_BORDE}; border-radius: 10px; "
                f"padding: 6px 12px; font-size: {t.T_PEQUENO}px; font-weight: 600; }}"
            )
            self.btn_alarma_roja.setText(tr("Alarma · Silenciar"))
        else:
            self.btn_alarma_roja.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {t.SECUNDARIO}; "
                f"border: 1px solid {t.BORDE}; border-radius: 10px; "
                f"padding: 6px 12px; font-size: {t.T_PEQUENO}px; }}"
            )
            self.btn_alarma_roja.setText(tr("Alarma silenciada"))

    def _actualizar_alarma_emergencia(self) -> None:
        if not hasattr(self, "_timer_alarma"):
            return
        items = self._items_emergencia_roja_activos()
        hay_rojo = bool(items)
        if not hay_rojo:
            self._alarma_silenciada_items.clear()
        habilitada = bool(self.state.config.get("alarmaEmergenciaSonora", True))
        sonando = hay_rojo and habilitada and bool(items - self._alarma_silenciada_items)

        estaba_sonando = self._alarma_roja_activa
        self._alarma_roja_activa = sonando
        self.state.alarma_roja_presente = hay_rojo
        self.state.alarma_emergencia_sonando = sonando

        if sonando:
            if not self._timer_alarma.isActive():
                self._timer_alarma.start()
            if not estaba_sonando:
                self._tick_alarma_emergencia()
        else:
            if self._timer_alarma.isActive():
                self._timer_alarma.stop()
            self.motor_voz.detener_alarma_emergencia()

        if hasattr(self, "btn_alarma_roja"):
            self.btn_alarma_roja.setVisible(hay_rojo and habilitada)
            self._aplicar_estilo_btn_alarma()
        self.state.alarmaEmergenciaChanged.emit(hay_rojo, sonando)

    def _reproducir_pulso_alarma_con_config(self) -> bool:
        cfg = self.state.config
        try:
            vol = max(0.25, min(1.0, float(cfg.get("alarmaEmergenciaVolumen", 0.70))))
        except Exception:
            vol = 0.70
        tono = str(cfg.get("alarmaEmergenciaTono", "doble-suave") or "doble-suave")
        return self.motor_voz.reproducir_pulso_alarma_emergencia(volumen=vol, tono=tono)

    def _tick_alarma_emergencia(self) -> None:
        if not self._alarma_roja_activa:
            return
        if not bool(self.state.config.get("alarmaEmergenciaSonora", True)):
            return
        self._reproducir_pulso_alarma_con_config()

    def _silenciar_alarma_emergencia(self) -> None:
        self._alarma_silenciada_items.update(self._items_emergencia_roja_activos())
        self._actualizar_alarma_emergencia()

    def _alternar_silencio_alarma(self) -> None:
        items = self._items_emergencia_roja_activos()
        if not items:
            return
        if items - self._alarma_silenciada_items:
            self._alarma_silenciada_items.update(items)
        else:
            self._alarma_silenciada_items.clear()
        self._actualizar_alarma_emergencia()
