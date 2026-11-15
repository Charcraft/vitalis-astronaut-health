# -*- coding: utf-8 -*-
"""
desktop/theme.py — Sistema visual dual (oscuro y claro) de V.I.T.A.L.I.S.

Pensado para pantalla TÁCTIL: ningún control mide menos de 48 px de alto y el
texto de lectura no baja de 15 px. La información secundaria se apaga en color,
no en tamaño. Soporta cambio en vivo entre «oscuro» y «claro».
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtGui import QColor, QPalette

FUENTE = "Segoe UI"
FUENTE_MONO = "Consolas"

# Escala tipográfica (px)
T_PEQUENO = 15
T_CUERPO = 17
T_DESTACADO = 20
T_TITULO = 28
T_VALOR = 52

# Alto mínimo de cualquier control tocable (px)
ALTO_TOQUE = 52

PALETAS: Dict[str, Dict[str, Any]] = {
    "oscuro": {
        "FONDO": "#07080A",
        "TARJETA": "#0B0D11",
        "PANEL_FLOTANTE": "rgba(11, 13, 17, 240)",
        "PANEL_OPACO": "#0D1016",
        "BORDE": "#1C2029",
        "BORDE_SUAVE": "#2C313D",
        "BORDE_PANEL": "#262C38",
        "BORDE_DOCK": "#283040",
        "BORDE_BURBUJA": "#2E3748",
        "DIVISOR": "#14171D",
        "TEXTO": "#F2F4F8",
        "TEXTO_SUAVE": "#D8DEE9",
        "SECUNDARIO": "#8A91A0",
        "TERCIARIO": "#5C6371",
        "ETIQUETA": "#A3AAB8",
        "HOVER": "#141821",
        "ACTIVO": "#1B2030",
        "ALERTA": "#E5484D",
        "ATENCION": "#E8B04B",
        "NORMAL": "#5FC79A",
        "PRIMARIO_FG": "#07080A",
        "PRIMARIO_HOVER": "#FFFFFF",
        "PRIMARIO_PRESSED": "#C9CED8",
        "PRIMARIO_DISABLED_BG": "#3A3F4A",
        "PRIMARIO_DISABLED_FG": "#8A919E",
        "PELIGRO_BG": "#2A0E12",
        "PELIGRO_FG": "#FFE1E3",
        "PELIGRO_BORDE": "#7A2A31",
        "PELIGRO_HOVER_BG": "#3A1218",
        "PELIGRO_PRESSED_BG": "#4A161D",
        "BANNER_SOS_BG": "#260E11",
        "BANNER_SOS_BORDE": "#6E232A",
        "BANNER_SOS_FG": "#FFD7D9",
        "CAJA_FALLO_BG": "#1D1608",
        "CAJA_FALLO_BORDE": "#4D3B12",
        "CAJA_FALLO_FG": "#F2D49B",
        "INSIGNIA_OK_BG": "#0C1612",
        "INSIGNIA_OK_BORDE": "#1E3A2E",
        "METRO_COMP_BG": "#3A1218",
        "METRO_COMP_FG": "#FFE1E3",
        "SCROLL_HANDLE": "#262B35",
        "BANDA_REF_RGBA": (255, 255, 255, 6),
        "LINEA_REF": "#1B1F27",
        "PUNTO_ACTIVO": "#FFFFFF",
        "PUNTO_INACTIVO": "#3A404C",
        "HALO_PUNTO_RGB": (255, 255, 255),
        "SOMBRA_RGB": (0, 0, 0, 185),
        "VTK_FONDO_RGB": (7 / 255.0, 8 / 255.0, 10 / 255.0),
        "VTK_RADAR_RINGS": (
            (0.09, 0.11, 0.14),
            (0.11, 0.13, 0.18),
            (0.09, 0.11, 0.14),
        ),
    },
    "claro": {
        "FONDO": "#F2F5F9",
        "TARJETA": "#FFFFFF",
        "PANEL_FLOTANTE": "rgba(255, 255, 255, 244)",
        "PANEL_OPACO": "#FFFFFF",
        "BORDE": "#D5DCE6",
        "BORDE_SUAVE": "#B5C0D0",
        "BORDE_PANEL": "#CAD3DF",
        "BORDE_DOCK": "#C5CFDC",
        "BORDE_BURBUJA": "#BCC7D6",
        "DIVISOR": "#E4E9F1",
        "TEXTO": "#0F141C",
        "TEXTO_SUAVE": "#283242",
        "SECUNDARIO": "#556072",
        "TERCIARIO": "#697486",
        "ETIQUETA": "#3D495A",
        "HOVER": "#E8EEF5",
        "ACTIVO": "#DCE4F0",
        "ALERTA": "#C92A32",
        "ATENCION": "#B86B00",
        "NORMAL": "#137A4B",
        "PRIMARIO_FG": "#FFFFFF",
        "PRIMARIO_HOVER": "#1F2837",
        "PRIMARIO_PRESSED": "#313E52",
        "PRIMARIO_DISABLED_BG": "#CFD7E2",
        "PRIMARIO_DISABLED_FG": "#778191",
        "PELIGRO_BG": "#FDECEF",
        "PELIGRO_FG": "#A81D27",
        "PELIGRO_BORDE": "#E3959D",
        "PELIGRO_HOVER_BG": "#FAD8DE",
        "PELIGRO_PRESSED_BG": "#F4C2CB",
        "BANNER_SOS_BG": "#FDECEF",
        "BANNER_SOS_BORDE": "#DF8891",
        "BANNER_SOS_FG": "#9E1922",
        "CAJA_FALLO_BG": "#FFF7E3",
        "CAJA_FALLO_BORDE": "#E0BB64",
        "CAJA_FALLO_FG": "#7A5000",
        "INSIGNIA_OK_BG": "#E6F6EE",
        "INSIGNIA_OK_BORDE": "#9AD4B7",
        "METRO_COMP_BG": "#FDECEF",
        "METRO_COMP_FG": "#A81D27",
        "SCROLL_HANDLE": "#BCC5D3",
        "BANDA_REF_RGBA": (15, 20, 28, 12),
        "LINEA_REF": "#CDD6E2",
        "PUNTO_ACTIVO": "#0F141C",
        "PUNTO_INACTIVO": "#9BA6B6",
        "HALO_PUNTO_RGB": (15, 20, 28),
        "SOMBRA_RGB": (15, 20, 28, 52),
        "VTK_FONDO_RGB": (228 / 255.0, 234 / 255.0, 242 / 255.0),
        "VTK_RADAR_RINGS": (
            (0.75, 0.80, 0.86),
            (0.70, 0.75, 0.82),
            (0.75, 0.80, 0.86),
        ),
    },
}

_ROLES_TEXTO = (
    "TEXTO",
    "TEXTO_SUAVE",
    "SECUNDARIO",
    "TERCIARIO",
    "ETIQUETA",
    "ALERTA",
    "ATENCION",
    "NORMAL",
    "CAJA_FALLO_FG",
    "BANNER_SOS_FG",
    "METRO_COMP_FG",
)

_HEX_A_ROL: Dict[str, str] = {}
for _pal in PALETAS.values():
    for _rol in _ROLES_TEXTO:
        _HEX_A_ROL[str(_pal[_rol]).upper()] = _rol

MODO: str = "oscuro"
FONDO: str = PALETAS["oscuro"]["FONDO"]
TARJETA: str = PALETAS["oscuro"]["TARJETA"]
PANEL_FLOTANTE: str = PALETAS["oscuro"]["PANEL_FLOTANTE"]
PANEL_OPACO: str = PALETAS["oscuro"]["PANEL_OPACO"]
BORDE: str = PALETAS["oscuro"]["BORDE"]
BORDE_SUAVE: str = PALETAS["oscuro"]["BORDE_SUAVE"]
BORDE_PANEL: str = PALETAS["oscuro"]["BORDE_PANEL"]
BORDE_DOCK: str = PALETAS["oscuro"]["BORDE_DOCK"]
BORDE_BURBUJA: str = PALETAS["oscuro"]["BORDE_BURBUJA"]
DIVISOR: str = PALETAS["oscuro"]["DIVISOR"]
TEXTO: str = PALETAS["oscuro"]["TEXTO"]
TEXTO_SUAVE: str = PALETAS["oscuro"]["TEXTO_SUAVE"]
SECUNDARIO: str = PALETAS["oscuro"]["SECUNDARIO"]
TERCIARIO: str = PALETAS["oscuro"]["TERCIARIO"]
ETIQUETA: str = PALETAS["oscuro"]["ETIQUETA"]
HOVER: str = PALETAS["oscuro"]["HOVER"]
ACTIVO: str = PALETAS["oscuro"]["ACTIVO"]
ALERTA: str = PALETAS["oscuro"]["ALERTA"]
ATENCION: str = PALETAS["oscuro"]["ATENCION"]
NORMAL: str = PALETAS["oscuro"]["NORMAL"]
PRIMARIO_FG: str = PALETAS["oscuro"]["PRIMARIO_FG"]
PRIMARIO_HOVER: str = PALETAS["oscuro"]["PRIMARIO_HOVER"]
PRIMARIO_PRESSED: str = PALETAS["oscuro"]["PRIMARIO_PRESSED"]
PRIMARIO_DISABLED_BG: str = PALETAS["oscuro"]["PRIMARIO_DISABLED_BG"]
PRIMARIO_DISABLED_FG: str = PALETAS["oscuro"]["PRIMARIO_DISABLED_FG"]
PELIGRO_BG: str = PALETAS["oscuro"]["PELIGRO_BG"]
PELIGRO_FG: str = PALETAS["oscuro"]["PELIGRO_FG"]
PELIGRO_BORDE: str = PALETAS["oscuro"]["PELIGRO_BORDE"]
PELIGRO_HOVER_BG: str = PALETAS["oscuro"]["PELIGRO_HOVER_BG"]
PELIGRO_PRESSED_BG: str = PALETAS["oscuro"]["PELIGRO_PRESSED_BG"]
BANNER_SOS_BG: str = PALETAS["oscuro"]["BANNER_SOS_BG"]
BANNER_SOS_BORDE: str = PALETAS["oscuro"]["BANNER_SOS_BORDE"]
BANNER_SOS_FG: str = PALETAS["oscuro"]["BANNER_SOS_FG"]
CAJA_FALLO_BG: str = PALETAS["oscuro"]["CAJA_FALLO_BG"]
CAJA_FALLO_BORDE: str = PALETAS["oscuro"]["CAJA_FALLO_BORDE"]
CAJA_FALLO_FG: str = PALETAS["oscuro"]["CAJA_FALLO_FG"]
INSIGNIA_OK_BG: str = PALETAS["oscuro"]["INSIGNIA_OK_BG"]
INSIGNIA_OK_BORDE: str = PALETAS["oscuro"]["INSIGNIA_OK_BORDE"]
METRO_COMP_BG: str = PALETAS["oscuro"]["METRO_COMP_BG"]
METRO_COMP_FG: str = PALETAS["oscuro"]["METRO_COMP_FG"]
SCROLL_HANDLE: str = PALETAS["oscuro"]["SCROLL_HANDLE"]
BANDA_REF_RGBA = PALETAS["oscuro"]["BANDA_REF_RGBA"]
LINEA_REF: str = PALETAS["oscuro"]["LINEA_REF"]
PUNTO_ACTIVO: str = PALETAS["oscuro"]["PUNTO_ACTIVO"]
PUNTO_INACTIVO: str = PALETAS["oscuro"]["PUNTO_INACTIVO"]
HALO_PUNTO_RGB = PALETAS["oscuro"]["HALO_PUNTO_RGB"]
SOMBRA_RGB = PALETAS["oscuro"]["SOMBRA_RGB"]
VTK_FONDO_RGB = PALETAS["oscuro"]["VTK_FONDO_RGB"]
VTK_RADAR_RINGS = PALETAS["oscuro"]["VTK_RADAR_RINGS"]


def es_oscuro() -> bool:
    return MODO != "claro"


def rol_de_color(color: Optional[str]) -> str:
    """Convierte un hex o nombre de rol en una clave semántica actualizable."""
    if not color:
        return "TEXTO"
    up = str(color).strip().upper()
    if up in _ROLES_TEXTO:
        return up
    return _HEX_A_ROL.get(up, str(color))


def color_de_rol(rol_o_hex: Optional[str]) -> str:
    """Devuelve el color efectivo del tema activo para un rol o hex dado."""
    if not rol_o_hex:
        return TEXTO
    up = str(rol_o_hex).strip().upper()
    if up in PALETAS[MODO]:
        return str(PALETAS[MODO][up])
    return str(rol_o_hex)


# --- Triage: UNA sola fuente para el texto y el color de cada nivel ----------
# La usan el Inicio, el Cuerpo 3D, el Historial, los avisos y el visor 3D.
TRIAGE_TEXTO = {"NOMINAL": "Normal", "ATENCION": "Atención", "CRITICO": "Crítico"}
TRIAGE_ORDEN = {"NOMINAL": 0, "ATENCION": 1, "CRITICO": 2}
_TRIAGE_ROL = {"CRITICO": "ALERTA", "ATENCION": "ATENCION"}


def texto_triage(nivel: Optional[str]) -> str:
    return TRIAGE_TEXTO.get(str(nivel or "NOMINAL"), "Normal")


def color_triage(nivel: Optional[str]) -> str:
    """Hex del nivel en el tema activo."""
    return color_de_rol(_TRIAGE_ROL.get(str(nivel or "NOMINAL"), "NORMAL"))


def rgb_triage(nivel: Optional[str]):
    """Mismo color en 0–1, para VTK."""
    h = color_triage(nivel).lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def generar_qss() -> str:
    return f"""
* {{
    font-family: "{FUENTE}";
    color: {TEXTO};
    outline: none;
}}
QMainWindow, QWidget#raiz, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {FONDO};
}}
QToolTip {{
    background: {TARJETA}; color: {TEXTO}; border: 1px solid {BORDE}; padding: 6px 10px; font-size: {T_PEQUENO}px;
}}
QFrame#tarjeta {{
    background: {TARJETA};
    border: 1px solid {BORDE};
    border-radius: 20px;
}}
QFrame#celdaTactil {{
    background: {TARJETA};
    border: 1px solid {BORDE};
    border-radius: 16px;
}}
QFrame#celdaTactil:hover {{
    background: {HOVER};
    border-color: {BORDE_SUAVE};
}}
QFrame#barraSegmentada {{
    background: {TARJETA};
    border: 1px solid {BORDE};
    border-radius: 16px;
}}
QFrame#divisor {{ background: {DIVISOR}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#barraNav {{ background: {FONDO}; border-bottom: 1px solid {DIVISOR}; }}
QFrame#pie {{ background: {FONDO}; border-top: 1px solid {DIVISOR}; }}

QLabel {{ background: transparent; }}
QLabel#etiquetaMono {{
    font-size: {T_PEQUENO}px; font-weight: 600; color: {ETIQUETA};
}}
QLabel#titulo {{ font-size: {T_TITULO}px; font-weight: 500; color: {TEXTO}; }}
QLabel#subtitulo {{ font-size: {T_PEQUENO}px; color: {SECUNDARIO}; }}
QLabel#secundario {{ font-size: {T_PEQUENO}px; color: {SECUNDARIO}; }}

QPushButton {{
    background: transparent; border: 1px solid {BORDE}; border-radius: 12px;
    padding: 12px 20px; font-size: {T_CUERPO}px; color: {TEXTO_SUAVE};
}}
QPushButton:hover {{ border-color: {BORDE_SUAVE}; color: {TEXTO}; background: {HOVER}; }}
QPushButton:pressed {{ background: {ACTIVO}; }}
QPushButton:disabled {{ color: {TERCIARIO}; border-color: {DIVISOR}; }}
QPushButton#primario {{
    background: {TEXTO}; color: {PRIMARIO_FG}; border: none; font-weight: 600;
    padding: 14px 22px; font-size: {T_CUERPO + 1}px;
}}
QPushButton#primario:hover {{ background: {PRIMARIO_HOVER}; }}
QPushButton#primario:pressed {{ background: {PRIMARIO_PRESSED}; }}
QPushButton#primario:disabled {{ background: {PRIMARIO_DISABLED_BG}; color: {PRIMARIO_DISABLED_FG}; }}
QPushButton#peligro {{
    background: {PELIGRO_BG}; color: {PELIGRO_FG}; border: 1px solid {PELIGRO_BORDE}; font-weight: 600;
    padding: 14px 22px; font-size: {T_CUERPO + 1}px;
}}
QPushButton#peligro:hover {{ background: {PELIGRO_HOVER_BG}; border-color: {ALERTA}; }}
QPushButton#peligro:pressed {{ background: {PELIGRO_PRESSED_BG}; }}
QPushButton#chip, QPushButton#chipTp {{
    font-size: {T_CUERPO}px; padding: 12px 18px; border-radius: 12px; color: {SECUNDARIO};
}}
QPushButton#chip:checked, QPushButton#chipTp:checked {{
    border: 1px solid {TEXTO_SUAVE}; background: {ACTIVO}; color: {TEXTO}; font-weight: 600;
}}
QPushButton#nav {{
    border: 1px solid transparent; background: transparent; font-size: {T_CUERPO}px; color: {SECUNDARIO};
    padding: 12px 8px; border-radius: 12px; min-height: 28px;
}}
QPushButton#nav:hover {{ color: {TEXTO_SUAVE}; background: {HOVER}; }}
QPushButton#nav:checked {{
    color: {TEXTO}; font-weight: 600; background: {ACTIVO}; border-color: {BORDE_SUAVE};
}}
QPushButton#navIcono {{
    border: 1px solid transparent; background: transparent; padding: 0px; border-radius: 12px;
}}
QPushButton#navIcono:hover {{ background: {HOVER}; border-color: {BORDE}; }}
QPushButton#navIcono:checked {{ background: {ACTIVO}; border-color: {BORDE_SUAVE}; }}
QPushButton#marcaNav {{
    border: none; background: transparent; padding: 8px 4px; border-radius: 12px;
    color: {TEXTO}; font-size: 16px; font-weight: 700; letter-spacing: 0.08em;
}}
QPushButton#marcaNav:hover {{ background: {HOVER}; }}
QPushButton#marcaNav:pressed {{ background: {ACTIVO}; }}
QPushButton#navEmergencia {{
    border: 1px solid {PELIGRO_BORDE}; background: {PELIGRO_BG}; color: {PELIGRO_FG}; font-size: {T_CUERPO}px;
    font-weight: 600; padding: 12px 11px; border-radius: 12px; min-height: 28px;
}}
QPushButton#navEmergencia:hover {{ border-color: {ALERTA}; background: {PELIGRO_HOVER_BG}; }}
QPushButton#navEmergencia:checked {{ background: {ALERTA}; color: #FFFFFF; border-color: {ALERTA}; }}
QPushButton#subnavFlujo {{
    border: 1px solid {BORDE}; background: transparent; font-size: {T_PEQUENO}px; color: {SECUNDARIO};
    padding: 12px 16px; border-radius: 14px; font-weight: 500;
}}
QPushButton#subnavFlujo:hover {{ color: {TEXTO_SUAVE}; background: {HOVER}; border-color: {BORDE_SUAVE}; }}
QPushButton#subnavFlujo:checked {{
    color: {TEXTO}; font-weight: 600; background: {ACTIVO}; border-color: {TEXTO_SUAVE};
}}
QPushButton#pasoPlay {{
    border: 1px solid {BORDE_SUAVE}; border-radius: 12px; background: transparent;
    color: {ETIQUETA}; font-size: {T_CUERPO}px; padding: 0px;
}}
QPushButton#pasoPlay:checked {{
    color: {PRIMARIO_FG}; background: {TEXTO}; border-color: {TEXTO};
}}
QPushButton#segmento {{
    border: none; background: transparent; font-size: {T_CUERPO}px; color: {SECUNDARIO};
    padding: 12px 12px; border-radius: 10px;
}}
QPushButton#segmento:checked {{ color: {TEXTO}; font-weight: 600; background: {ACTIVO}; }}
QPushButton#lista {{
    border: none; border-bottom: 1px solid {DIVISOR}; border-radius: 0; text-align: left;
    padding: 20px 16px; font-size: {T_DESTACADO}px; color: {SECUNDARIO};
}}
QPushButton#lista:hover {{ color: {TEXTO_SUAVE}; background: {HOVER}; }}
QPushButton#lista:checked {{ color: {TEXTO}; font-weight: 600; background: {ACTIVO}; border-radius: 12px; }}
QPushButton#tecla {{
    font-size: 26px; font-weight: 400; padding: 0px; border-radius: 14px; color: {TEXTO};
}}
QPushButton#interruptor {{
    font-size: {T_CUERPO}px; padding: 12px 22px; border-radius: 26px; color: {SECUNDARIO};
}}
QPushButton#interruptor:checked {{
    background: {TEXTO}; color: {PRIMARIO_FG}; border-color: {TEXTO}; font-weight: 600;
}}

QLineEdit, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {TARJETA}; border: 1px solid {BORDE}; border-radius: 12px;
    padding: 12px 16px; font-size: {T_CUERPO + 1}px; color: {TEXTO};
    selection-background-color: {ACTIVO}; selection-color: {TEXTO};
    min-height: 28px;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {TEXTO_SUAVE}; }}
QComboBox::drop-down {{ border: none; width: 40px; }}
QComboBox QAbstractItemView {{
    background: {TARJETA}; border: 1px solid {BORDE}; selection-background-color: {ACTIVO};
    selection-color: {TEXTO}; color: {TEXTO};
    font-size: {T_CUERPO + 1}px; outline: none;
}}
QComboBox QAbstractItemView::item {{ min-height: 56px; padding: 0 16px; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QCheckBox {{ font-size: {T_CUERPO}px; color: {TEXTO_SUAVE}; spacing: 14px; min-height: 48px; }}
QCheckBox::indicator {{ width: 32px; height: 32px; border: 1px solid {BORDE_SUAVE}; border-radius: 8px; background: {FONDO}; }}
QCheckBox::indicator:checked {{ background: {TEXTO}; border-color: {TEXTO}; }}

QSlider {{ min-height: 52px; }}
QSlider::groove:horizontal {{ height: 8px; background: {BORDE}; border-radius: 4px; }}
QSlider::sub-page:horizontal {{ background: {TEXTO_SUAVE}; border-radius: 4px; }}
QSlider::handle:horizontal {{ background: {TEXTO}; width: 34px; height: 34px; margin: -13px 0; border-radius: 17px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {SCROLL_HANDLE}; border-radius: 5px; min-height: 40px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL_HANDLE}; border-radius: 5px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QTableWidget {{
    background: {TARJETA}; border: 1px solid {BORDE}; border-radius: 16px; gridline-color: transparent;
    font-size: {T_CUERPO}px; color: {TEXTO};
}}
QTableWidget::item {{ padding: 0 14px; border-bottom: 1px solid {DIVISOR}; color: {TEXTO}; }}
QTableWidget::item:selected {{ background: {ACTIVO}; color: {TEXTO}; }}
QHeaderView::section {{
    background: {TARJETA}; color: {SECUNDARIO}; border: none; border-bottom: 1px solid {BORDE};
    padding: 14px; font-size: {T_PEQUENO}px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {TARJETA}; border: none; }}
"""


def paleta_qt() -> QPalette:
    """QPalette coherente con el modo activo para controles y menús nativos."""
    p = QPalette()
    c_fondo = QColor(FONDO)
    c_tarjeta = QColor(TARJETA)
    c_texto = QColor(TEXTO)
    c_sec = QColor(SECUNDARIO)
    c_act = QColor(ACTIVO)
    for grupo in (QPalette.Active, QPalette.Inactive):
        p.setColor(grupo, QPalette.Window, c_fondo)
        p.setColor(grupo, QPalette.WindowText, c_texto)
        p.setColor(grupo, QPalette.Base, c_tarjeta)
        p.setColor(grupo, QPalette.AlternateBase, QColor(HOVER))
        p.setColor(grupo, QPalette.ToolTipBase, c_tarjeta)
        p.setColor(grupo, QPalette.ToolTipText, c_texto)
        p.setColor(grupo, QPalette.Text, c_texto)
        p.setColor(grupo, QPalette.Button, c_tarjeta)
        p.setColor(grupo, QPalette.ButtonText, c_texto)
        p.setColor(grupo, QPalette.Highlight, c_act)
        p.setColor(grupo, QPalette.HighlightedText, c_texto)
        p.setColor(grupo, QPalette.PlaceholderText, c_sec)
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(TERCIARIO))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TERCIARIO))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(TERCIARIO))
    return p


def aplicar_tema(modo: str = "oscuro") -> str:
    """Actualiza las variables globales de color y regenera la hoja QSS."""
    global MODO, QSS
    clave = "claro" if str(modo).strip().lower() == "claro" else "oscuro"
    MODO = clave
    pal = PALETAS[clave]
    g = globals()
    for k, v in pal.items():
        g[k] = v
    QSS = generar_qss()
    return QSS


QSS = generar_qss()
