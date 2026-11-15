# -*- coding: utf-8 -*-
"""
desktop/viewer3d.py — Visor Anatómico 3D Nativo en OpenGL/VTK (PySide6 + VTK).
Carga las mallas anatómicas de BodyParts3D más las piezas añadidas y sustitutas de
anatomy-extras.glb (anatomy-male.bin / catalog.json; se regeneran con
scripts/convertir-glb-nativo.mjs)
sin navegador web:
  - Piel translúcida tipo rayos X
  - Resaltado por sistema fisiológico (neuro-ocular, cardiovascular, respiratorio,
    metabólico, musculoesquelético, inmune-radiación)
  - Selección de órganos con clic (vtkCellPicker con prioridad clínica:
    órganos > vasos > nervios > músculos > esqueleto)
  - Barra inferior: Cuerpo · Frontal · Lateral · Capas
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import vtk
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.util import numpy_support

from desktop import theme as t
from desktop.i18n import idioma, tr
from desktop.nombres import nombre_es
from desktop.widgets import BarraSegmentada, boton

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_PATH = os.path.join(ROOT_DIR, "desktop", "assets", "anatomy-male.bin")
IDX_PATH = os.path.join(ROOT_DIR, "desktop", "assets", "anatomy-male.json")
CATALOG_PATH = os.path.join(ROOT_DIR, "recursos", "modelos", "catalog.json")

# Mismo reparto que grupoDeClave() en src/components/BodyModel3D.tsx
# Ojo: esclerótica (eye_l/eye_r) + las estructuras internas del ojo de la HRA
# (HuBMAP, CC BY 4.0). Todas van a neuro-ocular.
ESTRUCTURAS_OJO = {
    "cornea_l", "cornea_r", "iris_l", "iris_r", "pupil_l", "pupil_r",
    "lens_l", "lens_r", "retina_l", "retina_r", "macula_l", "macula_r",
    "optic_disc_l", "optic_disc_r", "optic_nerve_l", "optic_nerve_r",
}
ORGANOS_NEURO = {
    "brain", "brainstem", "cerebellum", "eye_l", "eye_r", "pituitary",
    "pineal", "ear_l", "ear_r", "inner_ear_l", "inner_ear_r",
} | ESTRUCTURAS_OJO
ORGANOS_RESPIRATORIOS = {
    "lung_l", "lung_r", "lung_tissue_l", "lung_tissue_r", "bronchi", "trachea",
    "larynx", "pharynx", "nasal_cavity", "paranasal_sinuses",
}
ORGANOS_INMUNES = {
    "thymus", "spleen", "lymph_nodes", "lymph_vessels", "tonsils", "bone_marrow",
}
# El diafragma viene en `muscles`, pero es el músculo de la respiración.
MUSCULOS_RESPIRATORIOS = {"diaphragm"}
# Envuelven otras estructuras: opacos las taparían.
# La esclerótica y la córnea, translúcidas, dejan ver iris, cristalino y retina.
TRANSLUCIDAS = {
    "lung_tissue_l", "lung_tissue_r", "diaphragm", "paranasal_sinuses",
    "eye_l", "eye_r", "cornea_l", "cornea_r",
}
OPACIDAD_TRANSLUCIDA = 0.3
# Por debajo de esto el actor no aporta nada a la imagen: se oculta.
OPACIDAD_MINIMA_VISIBLE = 0.06

# Núcleo de cada región para encuadrar (igual que VISTAS.enfoque en el visor
# web). Nervios y vasos recorren todo el cuerpo: encuadrar con la caja del
# sistema entero dejaría la región diminuta.
ENFOQUE_SISTEMA = {
    "neuro-ocular": ["brain", "cerebellum", "brainstem", "eye_l", "eye_r"],
    "cardiovascular": [
        "heart", "coronary_arteries", "aorta", "pulmonary_vessels", "vena_cava_superior",
    ],
    "respiratorio": ["lung_tissue_l", "lung_tissue_r", "trachea", "nasal_cavity"],
    "metabolico": ["liver", "stomach", "small_intestine", "colon", "kidney_l", "kidney_r"],
}
ORGANOS_REPRODUCTIVOS = {
    "prostate",
    "reproductive",
    "uterus",
    "ovary_l",
    "ovary_r",
    "fallopian_tubes",
    "vagina",
    "breast_l",
    "breast_r",
    "testis_l",
    "testis_r",
    "epididymis_l",
    "epididymis_r",
    "seminal_vesicles",
}

PRIORIDAD_TEJIDO = {
    "organs": 0,
    "vessels": 1,
    "nerves": 2,
    "muscles": 3,
    "skeleton": 4,
    "joints": 5,
    "skin": 9,
}

# Tejidos que el visor pinta translúcidos. Cullar sus caras traseras ahorra la
# mitad del relleno con blending y no se nota: son cascarones cerrados y el
# vídeo de "cuerpo completo" sale igual (comprobado con el modelo real).
TEJIDOS_TRANSLUCIDOS = {"skin", "skeleton", "vessels", "nerves"}

# Perfil de calidad de la cámara. Mientras se orbita o se vuela a un órgano no
# hace falta el peeling completo: al parar se recupera y se repinta el frame.
PEELS_REPOSO = 4
PEELS_MOVIMIENTO = 1

COLOR_POR_DEFECTO_TEJIDO = {
    "skeleton": "#E6E1D6",
    "muscles": "#9E4747",
    "organs": "#D07A66",
    "vessels": "#C93B4B",
    "nerves": "#E2C55A",
    "skin": "#8FA3BD",
}


def hex_a_rgb(hex_str: str) -> Tuple[float, float, float]:
    h = (hex_str or "#D8DEE9").lstrip("#")
    if len(h) != 6:
        return (0.85, 0.87, 0.91)
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


def grupo_de_malla(nombre: str, tejido: str) -> str:
    if nombre in MUSCULOS_RESPIRATORIOS:
        return "respiratorio"
    if tejido == "vessels":
        return "cardiovascular"
    if tejido in ("skeleton", "muscles", "joints"):
        return "musculoesqueletico"
    if tejido == "nerves":
        return "neuro-ocular"
    if tejido == "skin":
        return "inmune-radiacion"
    if nombre in ORGANOS_NEURO:
        return "neuro-ocular"
    if nombre in ORGANOS_RESPIRATORIOS:
        return "respiratorio"
    if nombre in ORGANOS_INMUNES:
        return "inmune-radiacion"
    if nombre in ORGANOS_REPRODUCTIVOS:
        # Fuera de los 6 sistemas: se ve en "cuerpo", no se enciende con ninguno.
        return "reproductivo"
    if nombre == "heart":
        return "cardiovascular"
    return "metabolico"


class _InteractorStyleSeleccion(vtk.vtkInteractorStyleUser):
    """Navegación de OBSERVACIÓN, pensada para el dedo.

    El trackball de VTK giraba el cuerpo en cualquier eje y con mucha
    sensibilidad: un roce lo dejaba boca abajo. Aquí el arrastre sólo gira
    alrededor del eje vertical (con tope) e inclina un poco; la cámara llega a
    su destino con una transición suave. Tocar sin arrastrar selecciona.
    """

    UMBRAL_TOQUE = 14  # px: un dedo se mueve más que un ratón al tocar

    def __init__(self, visor: "VisorAnatomico3D") -> None:
        super().__init__()
        self.visor = visor
        self._pos_down = (0, 0)
        self._pos_ant = (0, 0)
        self._pulsado = False
        self._arrastrando = False
        # Con observadores propios, VTK no ejecuta su manejador por defecto.
        self.AddObserver("LeftButtonPressEvent", self._on_press)
        self.AddObserver("LeftButtonReleaseEvent", self._on_release)
        self.AddObserver("MouseMoveEvent", self._on_move)
        self.AddObserver("MouseWheelForwardEvent", lambda *_: self.visor._zoom(1.12))
        self.AddObserver("MouseWheelBackwardEvent", lambda *_: self.visor._zoom(1 / 1.12))
        # Sin teclas: «e» o «q» cerraban la ventana en el estilo por defecto.
        for ev in ("CharEvent", "KeyPressEvent", "KeyReleaseEvent"):
            self.AddObserver(ev, lambda *_: None)

    def _on_press(self, *_args) -> None:
        iren = self.GetInteractor()
        if iren:
            self._pos_down = self._pos_ant = iren.GetEventPosition()
        self._pulsado = True
        self._arrastrando = False

    def _on_move(self, *_args) -> None:
        if not self._pulsado:
            return
        iren = self.GetInteractor()
        if not iren:
            return
        x, y = iren.GetEventPosition()
        if not self._arrastrando:
            if (abs(x - self._pos_down[0]) <= self.UMBRAL_TOQUE
                    and abs(y - self._pos_down[1]) <= self.UMBRAL_TOQUE):
                return
            self._arrastrando = True
        self.visor.orbitar(x - self._pos_ant[0], y - self._pos_ant[1])
        self._pos_ant = (x, y)

    def _on_release(self, *_args) -> None:
        iren = self.GetInteractor()
        if iren and self._pulsado and not self._arrastrando:
            x, y = iren.GetEventPosition()
            try:
                self.visor.seleccionar_en_pixel(x, y)
            except Exception:
                pass
        self._pulsado = False
        self._arrastrando = False


# Esqueleto de referencia en las vistas de un sistema: orienta sin tapar.
# Las costillas, al 12 %, se leían como rayas horizontales sobre los órganos.
ESQUELETO_REFERENCIA = {"spine_cervical", "spine_thoracic", "spine_lumbar", "pelvis", "skull"}

# Color con el que pulsa un órgano afectado: el mismo triage que el resto del programa.
def color_problema(nivel: str):
    return t.rgb_triage(nivel)

# Límites de la cámara de observación (radianes y metros).
AZIMUT_MAX = math.radians(105)
ELEVACION_MIN, ELEVACION_MAX = math.radians(-12), math.radians(28)
DISTANCIA_MIN, DISTANCIA_MAX = 0.32, 4.2


class VisorAnatomico3D(QWidget):
    """Widget OpenGL/VTK nativo con el modelo anatómico 3D completo de V.I.T.A.L.I.S."""

    sistemaSeleccionado = Signal(str, str)  # (sistema, etiqueta_organo)
    modoVistaCambiado = Signal(str)

    def __init__(self, mostrar_barra: bool = True, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.sistema_activo = "metabolico"
        self.modo_vista = "cuerpo"  # cuerpo | frontal | lateral | capas
        self.mallas_info: List[Dict[str, Any]] = []
        self.actor_a_info: Dict[vtk.vtkActor, Dict[str, Any]] = {}
        self.catalogo: Dict[str, Dict[str, Any]] = {}
        self._bounds_cuerpo = (-0.4, 0.4, 0.0, 1.75, -0.25, 0.25)

        # Cámara de observación: foco, distancia, azimut y elevación. El estado
        # actual persigue al objetivo en cada tick: transiciones sin saltos.
        self._cam = {"f": [0.0, 0.9, 0.0], "d": 2.6, "az": 0.0, "el": 0.05}
        self._cam_obj = dict(self._cam, f=list(self._cam["f"]))
        # Último encuadre con el que se recalculó el clipping. ResetCameraClippingRange
        # recorre todos los actores visibles: no hace falta en cada tick.
        self._clip_d = -1.0
        self._clip_f = (0.0, 0.0, 0.0)
        # La primera vez que la ventana se muestra se reencuadra: al construir
        # el widget todavía no tiene tamaño y el aspecto sería inventado.
        self._encuadre_pendiente = True
        self._timer_cam = QTimer(self)
        self._timer_cam.setInterval(16)
        self._timer_cam.timeout.connect(self._tick_camara)

        # Órganos afectados por el estado actual -> nivel ("ATENCION"/"CRITICO").
        self.animacion_activa = True
        self.problemas: Dict[str, str] = {}
        self._fase_pulso = 0.0
        self._timer_pulso = QTimer(self)
        self._timer_pulso.setInterval(90)
        self._timer_pulso.timeout.connect(self._tick_pulso)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(8)

        # Cabecera: sólo el órgano tocado, en grande. El modo de vista ya se ve
        # en la barra inferior; el rótulo técnico queda oculto.
        fila_sup = QHBoxLayout()
        fila_sup.setContentsMargins(6, 0, 6, 0)
        self.lbl_estado_3d = QLabel("")
        self.lbl_estado_3d.setVisible(False)
        self.lbl_organo = QLabel("")
        self.lbl_organo.setMinimumHeight(t.ALTO_TOQUE)
        self.lbl_organo.setStyleSheet(
            f"font-family: '{t.FUENTE}'; font-size: {t.T_DESTACADO}px; font-weight: 600; color: {t.TEXTO};"
        )
        fila_sup.addWidget(self.lbl_organo)
        # Leyenda: cuántos órganos están en cada nivel, con el color del triage.
        self.lbl_leyenda = QLabel("")
        self.lbl_leyenda.setVisible(False)
        fila_sup.addWidget(self.lbl_leyenda)
        fila_sup.addStretch(1)
        # Sin rueda de ratón ni pellizco, el zoom necesita botones. Van arriba,
        # donde sobra sitio: abajo no cabían junto a las vistas con texto grande.
        for texto, accion, ayuda in (
            ("−", lambda: self._zoom(0.8), "Alejar"),
            ("+", lambda: self._zoom(1.25), "Acercar"),
            ("⟲", lambda: self.enfocar_sistema(self.sistema_activo), "Centrar la vista"),
        ):
            b = boton(texto, al_pulsar=accion)
            b.setFixedWidth(60)
            b.setToolTip(tr(ayuda))
            b.setStyleSheet("font-size: 24px; padding: 0px;")
            fila_sup.addWidget(b)
        capa.addLayout(fila_sup)

        # Lienzo OpenGL VTK nativo
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.vtk_widget.setMinimumHeight(470)
        capa.addWidget(self.vtk_widget, 1)

        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(*t.VTK_FONDO_RGB)
        self._radar_actors: List[vtk.vtkActor] = []
        self.renderer.SetUseDepthPeeling(1)
        # 4 capas y ratio 0.3: frente a 8 / 0.1 cambia el 0.8 % de los píxeles
        # (diferencia media 1/255) y casi duplica los fps. Con 2 capas ya se nota.
        self.renderer.SetMaximumNumberOfPeels(4)
        self.renderer.SetOcclusionRatio(0.3)
        self._modo_calidad = "reposo"

        rw = self.vtk_widget.GetRenderWindow()
        rw.SetAlphaBitPlanes(1)
        # 2 muestras y no 4: con 670k triángulos y 172 actores translúcidos el
        # antialiasing se come el frame, y a 1100 px la diferencia no se ve.
        rw.SetMultiSamples(2)
        rw.AddRenderer(self.renderer)

        self._estilo_interactor = _InteractorStyleSeleccion(self)
        self._estilo_interactor.SetDefaultRenderer(self.renderer)
        self.vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(self._estilo_interactor)

        # Barra inferior estilo Ref1: Cuerpo · Frontal · Lateral · Capas
        if mostrar_barra:
            fila_inf = QHBoxLayout()
            fila_inf.addStretch(1)
            self.barra = BarraSegmentada(["cuerpo", "frontal", "lateral", "capas"])
            self.barra.marcar("cuerpo")
            self.barra.seleccionado.connect(self.cambiar_modo_vista)
            fila_inf.addWidget(self.barra)
            fila_inf.addStretch(1)
            capa.addLayout(fila_inf)
        else:
            self.barra = None

        self._cargar_catalogo()
        self._construir_escena_3d()
        self.vtk_widget.Initialize()

    def _cargar_catalogo(self) -> None:
        if os.path.exists(CATALOG_PATH):
            try:
                with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                    items = json.load(f)
                for it in items:
                    self.catalogo[it["key"]] = it
            except Exception:
                pass

    def _construir_escena_3d(self) -> None:
        # Anillos concéntricos sutiles en el plano trasero (estética Ref1)
        self._agregar_anillos_radar()

        if not (os.path.exists(BIN_PATH) and os.path.exists(IDX_PATH)):
            return

        with open(IDX_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)
        with open(BIN_PATH, "rb") as f:
            raw_bin = f.read()

        xmin, xmax = 1e9, -1e9
        ymin, ymax = 1e9, -1e9
        zmin, zmax = 1e9, -1e9

        for item in meta.get("mallas", []):
            nombre = item["nombre"]
            tejido = item["tejido"]
            n_verts = int(item["vertices"])
            n_tris = int(item["triangulos"])
            off_pos = int(item["offsetPos"])
            off_idx = int(item["offsetIdx"])

            verts = np.frombuffer(
                raw_bin, dtype=np.float32, count=n_verts * 3, offset=off_pos
            ).reshape((n_verts, 3))
            tris = np.frombuffer(
                raw_bin, dtype=np.uint32, count=n_tris * 3, offset=off_idx
            ).reshape((n_tris, 3))

            if tejido == "skin" and n_verts > 0:
                xmin = min(xmin, float(verts[:, 0].min()))
                xmax = max(xmax, float(verts[:, 0].max()))
                ymin = min(ymin, float(verts[:, 1].min()))
                ymax = max(ymax, float(verts[:, 1].max()))
                zmin = min(zmin, float(verts[:, 2].min()))
                zmax = max(zmax, float(verts[:, 2].max()))

            poly = vtk.vtkPolyData()
            pts = vtk.vtkPoints()
            pts.SetData(numpy_support.numpy_to_vtk(verts, deep=True))
            poly.SetPoints(pts)

            # Construir celdas triangulares VTK
            celdas_np = np.empty((n_tris, 4), dtype=np.int64)
            celdas_np[:, 0] = 3
            celdas_np[:, 1:] = tris
            cells = vtk.vtkCellArray()
            cells.SetCells(
                n_tris,
                numpy_support.numpy_to_vtkIdTypeArray(celdas_np.ravel(), deep=True),
            )
            poly.SetPolys(cells)

            normals = vtk.vtkPolyDataNormals()
            normals.SetInputData(poly)
            normals.SetFeatureAngle(60.0)
            normals.ConsistencyOn()
            normals.SplittingOff()

            # Normales una sola vez al cargar; el mapper estático no vuelve a
            # consultar el pipeline en cada render.
            normals.Update()
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(normals.GetOutput())
            mapper.ScalarVisibilityOff()
            mapper.StaticOn()

            actor = vtk.vtkActor()
            actor.SetMapper(mapper)

            cat_entry = self.catalogo.get(nombre, {})
            color_hex = cat_entry.get(
                "color", COLOR_POR_DEFECTO_TEJIDO.get(tejido, "#C5CCD6")
            )
            rgb = hex_a_rgb(color_hex)
            etiqueta_catalogo = cat_entry.get("label", nombre.replace("_", " ").title())
            etiqueta_es = nombre_es(nombre, etiqueta_catalogo)
            sistema = grupo_de_malla(nombre, tejido)

            prop = actor.GetProperty()
            prop.SetColor(*rgb)
            prop.SetAmbient(0.28)
            prop.SetDiffuse(0.78)
            prop.SetSpecular(0.18)
            prop.SetSpecularPower(18.0)
            # Lo translúcido se pinta dos veces (cara y contracara). Con 172
            # mallas eso es la mitad del coste de relleno del visor.
            if tejido in TEJIDOS_TRANSLUCIDOS:
                prop.BackfaceCullingOn()

            if tejido == "skin":
                prop.SetColor(0.58, 0.66, 0.78)
                prop.SetOpacity(0.14)
                prop.SetSpecular(0.35)
            elif nombre in TRANSLUCIDAS:
                prop.SetOpacity(OPACIDAD_TRANSLUCIDA)
            elif tejido == "muscles":
                prop.SetOpacity(0.28)
            elif tejido == "skeleton":
                prop.SetOpacity(0.55)
            else:
                # Opaco de verdad: con 0.95 cada órgano pasaba por depth peeling.
                prop.SetOpacity(1.0)

            self.renderer.AddActor(actor)
            info = {
                "actor": actor,
                "nombre": nombre,
                "etiqueta": etiqueta_es,
                "etiqueta_catalogo": etiqueta_catalogo,
                "tejido": tejido,
                "sistema": sistema,
                "rgb": rgb,
                "bounds": poly.GetBounds(),
            }
            self.mallas_info.append(info)
            self.actor_a_info[actor] = info

        if xmin < xmax:
            self._bounds_cuerpo = (xmin, xmax, ymin, ymax, zmin, zmax)

        self.lbl_estado_3d.setText(
            tr(
                "MODELO ANATÓMICO 3D · CUERPO COMPLETO ({n} ESTRUCTURAS)",
                n=len(self.mallas_info),
            )
        )

        self._encuadrar_camara(vista="frontal", solo_sistema=None, inmediato=True)
        self.enfocar_sistema(self.sistema_activo, encuadrar=False)

    def aplicar_tema(self) -> None:
        self.lbl_organo.setStyleSheet(
            f"font-family: '{t.FUENTE}'; font-size: {t.T_DESTACADO}px; font-weight: 600; color: {t.TEXTO};"
        )
        self.renderer.SetBackground(*t.VTK_FONDO_RGB)
        rings = t.VTK_RADAR_RINGS
        for idx, actor in enumerate(getattr(self, "_radar_actors", [])):
            color = rings[idx] if idx < len(rings) else rings[-1]
            actor.GetProperty().SetColor(*color)
            actor.GetProperty().SetOpacity(0.55 if not t.es_oscuro() else 0.65)
        if getattr(self, "_vtk_iniciado", False) and self.isVisible():
            self.vtk_widget.GetRenderWindow().Render()

    def _agregar_anillos_radar(self) -> None:
        """Dibuja 3 anillos concéntricos sutiles detrás del astronauta 3D (estética Ref1)."""
        radios = (0.82, 0.58, 0.36)
        rings = t.VTK_RADAR_RINGS
        self._radar_actors = []
        for idx, radio in enumerate(radios):
            color = rings[idx] if idx < len(rings) else rings[-1]
            circ = vtk.vtkRegularPolygonSource()
            circ.GeneratePolygonOff()
            circ.SetNumberOfSides(96)
            circ.SetRadius(radio)
            circ.SetCenter(0.0, 0.88, -0.22)
            circ.SetNormal(0.0, 0.0, 1.0)
            m = vtk.vtkPolyDataMapper()
            m.SetInputConnection(circ.GetOutputPort())
            a = vtk.vtkActor()
            a.SetMapper(m)
            a.GetProperty().SetColor(*color)
            a.GetProperty().SetOpacity(0.55 if not t.es_oscuro() else 0.65)
            a.PickableOff()
            self.renderer.AddActor(a)
            self._radar_actors.append(a)

    def enfocar_sistema(self, sistema: str, encuadrar: bool = True) -> None:
        """Decide qué se ve. Regla: sólo lo que ayuda a leer el estado.

        - Músculos: sólo en Musculoesquelético o Capas (son 1/3 del modelo y
          tapan los órganos).
        - Aparato reproductor: nunca (no lo mide OSD-575).
        - Vista de un sistema: ese sistema + un esqueleto tenue de referencia.
        - Órganos con problemas: siempre visibles y pulsando.
        """
        self.sistema_activo = sistema
        es_cuerpo = self.modo_vista == "cuerpo"
        es_capas = self.modo_vista == "capas"
        regional = self.modo_vista in ("frontal", "lateral")
        mostrar_musculos = es_capas or (regional and sistema == "musculoesqueletico")
        # Si el sistema tiene órganos afectados, el resto del sistema se vuelve
        # translúcido: lo afectado se ve aunque esté detrás (páncreas tras el estómago).
        hay_problema_en_sistema = regional and any(
            i["nombre"] in self.problemas and i["sistema"] == sistema for i in self.mallas_info
        )

        for info in self.mallas_info:
            prop = info["actor"].GetProperty()
            tejido, sis, rgb, nombre = info["tejido"], info["sistema"], info["rgb"], info["nombre"]
            prop.SetAmbient(0.28)
            prop.SetAmbientColor(1.0, 1.0, 1.0)
            prop.SetColor(*rgb)

            if tejido == "skin":
                op = 0.0 if es_capas else (0.07 if regional else 0.11)
            elif sis == "reproductivo":
                op = 0.0
            elif tejido == "muscles" and nombre not in MUSCULOS_RESPIRATORIOS:
                op = (0.30 if es_capas else 1.0) if mostrar_musculos else 0.0
            elif nombre in TRANSLUCIDAS:
                op = OPACIDAD_TRANSLUCIDA if (sis == sistema or not regional) else 0.0
                if self.problemas and not regional:
                    op = 0.06
            elif regional:
                if sis == sistema:
                    op = 0.35 if (hay_problema_en_sistema and tejido == "organs") else 1.0
                    prop.SetColor(*(min(1.0, c * 1.15) for c in rgb))
                elif tejido == "skeleton" and nombre in ESQUELETO_REFERENCIA:
                    op = 0.12
                    prop.SetColor(*(c * 0.6 for c in rgb))
                else:
                    op = 0.0
            else:  # cuerpo o capas: vista general
                if self.problemas:
                    # Hay algo que atender: el resto del cuerpo queda como silueta
                    # y sólo lo afectado se ve sólido (y pulsa).
                    op = {"skeleton": 0.22, "vessels": 0.10, "nerves": 0.10}.get(tejido, 0.16)
                elif tejido == "skeleton":
                    op = 0.35
                elif tejido in ("vessels", "nerves"):
                    op = 0.45
                else:
                    op = 1.0

            if nombre in self.problemas:
                nivel_rgb = color_problema(self.problemas[nombre])
                prop.SetColor(*(0.25 * a + 0.75 * b for a, b in zip(rgb, nivel_rgb)))
                op = 0.6 if nombre in TRANSLUCIDAS else 1.0

            prop.SetOpacity(op)
            # Lo casi invisible no se dibuja: cada actor translúcido, por tenue
            # que sea, cuesta una pasada de depth peeling.
            info["actor"].SetVisibility(op > OPACIDAD_MINIMA_VISIBLE)

        if encuadrar:
            vista_cam = "lateral" if self.modo_vista == "lateral" else "frontal"
            solo_sis = None if not regional else sistema
            self._encuadrar_camara(vista=vista_cam, solo_sistema=solo_sis)

        self._actualizar_pulso()
        # La escena cambió de visibilidad: el recorte near/far debe recalcularse
        # (cuesta 0,04 ms) aunque la cámara no se haya movido.
        self.renderer.ResetCameraClippingRange()
        self._clip_d = self._cam["d"]
        self._clip_f = tuple(self._cam["f"])
        if self.isVisible() and not self._timer_cam.isActive():
            self.vtk_widget.GetRenderWindow().Render()

    # --- órganos con problemas ------------------------------------------------
    def marcar_problemas(self, problemas: Dict[str, str]) -> None:
        """Recibe órgano -> nivel del estado actual y los hace resaltar."""
        self.problemas = dict(problemas)
        self._pintar_leyenda()
        self.enfocar_sistema(self.sistema_activo, encuadrar=False)

    def _pintar_leyenda(self) -> None:
        n_c = sum(1 for v in self.problemas.values() if v == "CRITICO")
        n_a = sum(1 for v in self.problemas.values() if v == "ATENCION")
        partes = []
        for n, nivel in ((n_c, "CRITICO"), (n_a, "ATENCION")):
            if n:
                partes.append(
                    f"<span style='color:{t.color_triage(nivel)};'>●</span> "
                    f"<span style='color:{t.SECUNDARIO};'>{n} {tr(t.texto_triage(nivel)).lower()}</span>"
                )
        self.lbl_leyenda.setText(
            f"<span style='font-size:{t.T_PEQUENO}px;'>" + "&nbsp;&nbsp;&nbsp;".join(partes) + "</span>"
        )
        self.lbl_leyenda.setVisible(bool(partes))

    def set_animacion_activa(self, activa: bool) -> None:
        self.animacion_activa = bool(activa)
        if not self.animacion_activa:
            if self._timer_cam.isActive():
                self._timer_cam.stop()
                self._cam = dict(self._cam_obj, f=list(self._cam_obj["f"]))
                if self.isVisible():
                    self._aplicar_camara()
        self._actualizar_pulso()

    def hideEvent(self, ev) -> None:  # noqa: N802
        if self._timer_cam.isActive():
            self._timer_cam.stop()
            self._calidad("reposo")
            self._cam = dict(self._cam_obj, f=list(self._cam_obj["f"]))
        if self._timer_pulso.isActive():
            self._timer_pulso.stop()
        super().hideEvent(ev)

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        # Al construir el widget mide 0 x 0, así que el encuadre inicial se hizo
        # con un aspecto inventado. En el primer mostrado ya hay tamaño real.
        if getattr(self, "_encuadre_pendiente", False):
            self._encuadre_pendiente = False
            self._encuadrar_camara(vista="frontal", solo_sistema=None, inmediato=True)
        self._actualizar_pulso()

    def _actualizar_pulso(self) -> None:
        if self.problemas and self.animacion_activa and self.isVisible():
            if not self._timer_pulso.isActive():
                self._timer_pulso.start()
        elif self._timer_pulso.isActive():
            self._timer_pulso.stop()

    def _tick_pulso(self) -> None:
        # Pulso lento (~1 Hz) en la luz ambiente del órgano: se ve sin parpadear.
        if not self.isVisible():
            return
        self._fase_pulso += 0.09 * 2 * math.pi * 0.9
        brillo = 0.5 + 0.5 * math.sin(self._fase_pulso)
        for info in self.mallas_info:
            nivel = self.problemas.get(info["nombre"])
            if nivel and info["actor"].GetVisibility():
                prop = info["actor"].GetProperty()
                prop.SetAmbientColor(*color_problema(nivel))
                # Lo crítico late más fuerte que lo que sólo pide atención.
                prop.SetAmbient(0.22 + (0.6 if nivel == "CRITICO" else 0.3) * brillo)
        if not self._timer_cam.isActive():
            self.vtk_widget.GetRenderWindow().Render()

    @staticmethod
    def nombre_visible(info: Dict[str, Any]) -> str:
        """Español propio; en otro idioma, la traducción o, si no la hay, el catálogo (inglés)."""
        traducido = tr(info["etiqueta"])
        if idioma() == "es" or traducido != info["etiqueta"]:
            return traducido
        return info.get("etiqueta_catalogo", info["etiqueta"])

    def enfocar_organo(self, nombre: str, etiqueta: Optional[str] = None) -> None:
        self.enfocar_organos([nombre], etiqueta)

    def _iniciar_o_aplicar_camara(self) -> None:
        if self.animacion_activa and self.isVisible():
            self._calidad("movimiento")
            self._timer_cam.start()
        else:
            self._timer_cam.stop()
            self._calidad("reposo")
            self._cam = dict(self._cam_obj, f=list(self._cam_obj["f"]))
            if self.isVisible():
                self._aplicar_camara()

    def enfocar_organos(self, nombres: List[str], etiqueta: Optional[str] = None) -> None:
        """Encuadra uno o varios órganos dejando contexto alrededor."""
        infos = [i for i in self.mallas_info if i["nombre"] in set(nombres)]
        if not infos:
            return
        b = [
            min(i["bounds"][0] for i in infos), max(i["bounds"][1] for i in infos),
            min(i["bounds"][2] for i in infos), max(i["bounds"][3] for i in infos),
            min(i["bounds"][4] for i in infos), max(i["bounds"][5] for i in infos),
        ]
        tam = max(b[1] - b[0], b[3] - b[2], b[5] - b[4], 0.08)
        self._cam_obj["f"] = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]
        # Lo bastante lejos para ver el órgano y lo que lo rodea.
        self._cam_obj["d"] = min(max(tam * 4.2, 0.62), DISTANCIA_MAX)
        self.lbl_organo.setText(tr(etiqueta) if etiqueta else self.nombre_visible(infos[0]))
        self._iniciar_o_aplicar_camara()

    # --- cámara de observación ---------------------------------------------------
    def orbitar(self, dx: float, dy: float) -> None:
        """Arrastre: giro horizontal con tope e inclinación leve. Nunca vuelca."""
        self._cam_obj["az"] = max(-AZIMUT_MAX, min(AZIMUT_MAX, self._cam_obj["az"] - dx * 0.0055))
        self._cam_obj["el"] = max(ELEVACION_MIN, min(ELEVACION_MAX, self._cam_obj["el"] - dy * 0.0035))
        self._iniciar_o_aplicar_camara()

    def _zoom(self, factor: float) -> None:
        self._cam_obj["d"] = max(DISTANCIA_MIN, min(DISTANCIA_MAX, self._cam_obj["d"] / factor))
        self._iniciar_o_aplicar_camara()

    def _tick_camara(self) -> None:
        if not self.isVisible() or not self.animacion_activa:
            self._cam = dict(self._cam_obj, f=list(self._cam_obj["f"]))
            self._timer_cam.stop()
            self._calidad("reposo")
            if self.isVisible():
                self._aplicar_camara()
            return
        c, o = self._cam, self._cam_obj
        a = 0.2  # fracción del camino por tick (16 ms): llega en ~0.3 s sin brusquedad
        resto = 0.0
        for k in ("d", "az", "el"):
            c[k] += (o[k] - c[k]) * a
            resto = max(resto, abs(o[k] - c[k]))
        for i in range(3):
            c["f"][i] += (o["f"][i] - c["f"][i]) * a
            resto = max(resto, abs(o["f"][i] - c["f"][i]))
        if resto < 1e-4:
            self._cam = dict(o, f=list(o["f"]))
            self._timer_cam.stop()
            # El último frame de la transición se pinta ya con calidad completa.
            self._calidad("reposo")
        self._aplicar_camara()

    def _calidad(self, modo: str) -> None:
        """Baja el coste por frame mientras la cámara se mueve.

        Durante una órbita o un vuelo a un órgano, 4 capas de peeling no aportan
        nada que el ojo pueda ver; al llegar, se recupera y se repinta.
        """
        if getattr(self, "_modo_calidad", None) == modo:
            return
        self._modo_calidad = modo
        self.renderer.SetMaximumNumberOfPeels(
            PEELS_MOVIMIENTO if modo == "movimiento" else PEELS_REPOSO
        )

    def _aplicar_camara(self) -> None:
        c = self._cam
        fx, fy, fz = c["f"]
        d, az, el = c["d"], c["az"], c["el"]
        cam = self.renderer.GetActiveCamera()
        cam.SetFocalPoint(fx, fy, fz)
        cam.SetPosition(
            fx + d * math.cos(el) * math.sin(az),
            fy + d * math.sin(el),
            fz + d * math.cos(el) * math.cos(az),
        )
        cam.SetViewUp(0.0, 1.0, 0.0)
        # ResetCameraClippingRange recorre todos los actores visibles; solo se
        # recalcula cuando el encuadre cambia de verdad, no en cada tick.
        cambio_d = abs(d - self._clip_d) > 0.02 * max(d, 0.1)
        cambio_f = max(abs(a - b) for a, b in zip((fx, fy, fz), self._clip_f)) > 0.01
        if self._clip_d < 0 or cambio_d or cambio_f:
            self.renderer.ResetCameraClippingRange()
            self._clip_d = d
            self._clip_f = (fx, fy, fz)
        self.vtk_widget.GetRenderWindow().Render()

    def cambiar_modo_vista(self, modo: str, forzar: bool = False) -> None:
        if modo == self.modo_vista and not forzar:
            return
        self.modo_vista = modo
        self.modoVistaCambiado.emit(modo)
        if self.barra:
            self.barra.marcar(modo)
        etiquetas = {
            "cuerpo": tr("MODELO ANATÓMICO 3D · CUERPO COMPLETO"),
            "frontal": tr("VISTA FRONTAL") + f" · {tr(self.sistema_activo).upper()}",
            "lateral": tr("VISTA LATERAL") + f" · {tr(self.sistema_activo).upper()}",
            "capas": tr("CAPAS INTERNAS RAYOS X") + f" · {tr(self.sistema_activo).upper()}",
        }
        self.lbl_estado_3d.setText(etiquetas.get(modo, tr("MODELO 3D")))
        self.enfocar_sistema(self.sistema_activo, encuadrar=True)

    def _aspecto(self) -> float:
        """Ancho/alto de la ventana de render, acotado a un rango sensato.

        Al construir el widget todavía no tiene tamaño; en ese momento devuelve
        1.0 y el primer `showEvent` reencuadra con el tamaño real.
        """
        rw = self.vtk_widget.GetRenderWindow()
        w, h = rw.GetSize()
        if w < 8 or h < 8:
            w, h = self.vtk_widget.width(), self.vtk_widget.height()
        if w < 8 or h < 8:
            return 1.0
        return max(0.6, min(2.2, w / h))

    def _distancia_encuadre(self, alto: float, ancho: float, margen: float = 1.06) -> float:
        """Distancia mínima para que una caja quepa entera en pantalla.

        El `ViewAngle` de la cámara de VTK es el **vertical**. El visor usaba
        `alto * 1.48`: para 1.719 m daba 2.54 m, cuando con 30° de campo hacen
        falta 3.21 m, así que el cuerpo salía cortado por la cabeza y los pies.
        """
        media = math.tan(math.radians(self.renderer.GetActiveCamera().GetViewAngle()) / 2.0)
        if media <= 0.01:
            return 3.4
        distancia_v = (alto / 2.0) / media
        distancia_h = (ancho / 2.0) / (media * self._aspecto())
        return max(distancia_v, distancia_h) * margen

    def _encuadrar_camara(
        self, vista: str = "frontal", solo_sistema: Optional[str] = None, inmediato: bool = False
    ) -> None:
        bounds_list = []
        if solo_sistema and solo_sistema not in ("musculoesqueletico", "inmune-radiacion"):
            enfoque = set(ENFOQUE_SISTEMA.get(solo_sistema, []))
            for info in self.mallas_info:
                if enfoque:
                    if info["nombre"] in enfoque:
                        bounds_list.append(info["bounds"])
                elif info["sistema"] == solo_sistema and info["tejido"] in ("organs", "vessels", "nerves"):
                    bounds_list.append(info["bounds"])

        if bounds_list:
            xmin = min(b[0] for b in bounds_list)
            xmax = max(b[1] for b in bounds_list)
            ymin = min(b[2] for b in bounds_list)
            ymax = max(b[3] for b in bounds_list)
            zmin = min(b[4] for b in bounds_list)
            zmax = max(b[5] for b in bounds_list)
            # El encuadre por sistema está afinado a ojo; se respeta, pero si el
            # panel es muy estrecho se aleja lo justo para no cortar a los lados.
            dist = max(
                max(ymax - ymin, xmax - xmin, 0.36) * 2.35,
                self._distancia_encuadre(ymax - ymin, xmax - xmin, 1.0),
            )
        else:
            xmin, xmax, ymin, ymax, zmin, zmax = self._bounds_cuerpo
            dist = self._distancia_encuadre(ymax - ymin, xmax - xmin)

        self._cam_obj = {
            "f": [(xmin + xmax) * 0.5, (ymin + ymax) * 0.5, (zmin + zmax) * 0.5],
            "d": min(max(dist, DISTANCIA_MIN), DISTANCIA_MAX),
            "az": -math.pi / 2 if vista == "lateral" else 0.0,
            "el": 0.05,
        }
        if inmediato or not self.animacion_activa or not self.isVisible():
            self._timer_cam.stop()
            self._calidad("reposo")
            self._cam = dict(self._cam_obj, f=list(self._cam_obj["f"]))
            if self.isVisible() or inmediato:
                self._aplicar_camara()
        else:
            self._calidad("movimiento")
            self._timer_cam.start()

    def seleccionar_en_pixel(self, x: int, y: int) -> None:
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.005)
        picker.Pick(x, y, 0, self.renderer)
        props = picker.GetProp3Ds()
        props.InitTraversal()

        mejor_info: Optional[Dict[str, Any]] = None
        mejor_prio = 99
        actor = props.GetNextProp3D()
        while actor:
            info = self.actor_a_info.get(actor)
            if info and info["tejido"] != "skin":
                prio = PRIORIDAD_TEJIDO.get(info["tejido"], 6)
                if prio < mejor_prio:
                    mejor_prio = prio
                    mejor_info = info
            actor = props.GetNextProp3D()

        if mejor_info is None:
            hit_actor = picker.GetActor()
            if hit_actor in self.actor_a_info and self.actor_a_info[hit_actor]["tejido"] != "skin":
                mejor_info = self.actor_a_info[hit_actor]

        if mejor_info:
            etiqueta_org = self.nombre_visible(mejor_info)
            sis = mejor_info["sistema"]
            self.lbl_organo.setText(etiqueta_org)
            self.modo_vista = "frontal"
            if self.barra:
                self.barra.marcar("frontal")
            self.enfocar_sistema(sis, encuadrar=True)
            self.enfocar_organo(mejor_info["nombre"])
            self.sistemaSeleccionado.emit(sis, etiqueta_org)
