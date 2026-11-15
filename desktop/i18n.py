# -*- coding: utf-8 -*-
"""
desktop/i18n.py — Motor de idiomas de V.I.T.A.L.I.S.

Las cadenas de la interfaz se escriben en el código en español (idioma fuente
del proyecto, ver AGENTS.md §4). Cada paquete de idioma es un JSON que traduce
esas cadenas; el idioma se elige en Ajustes y queda guardado en SQLite
(lis_config.idioma), por lo que sobrevive a reinicios y a la reinstalación.

Diseño:
  - ``tr(texto, **datos)`` traduce una cadena del español al idioma activo.
    Si no hay traducción devuelve la cadena original: nunca rompe la interfaz.
  - Los paquetes incluidos viven en ``desktop/locales/<codigo>.json``.
  - Al "descargar" (instalar) un idioma se copia el paquete a
    ``data/locales/<codigo>.json``: queda en el equipo, disponible sin conexión
    y con prioridad sobre el incluido en la aplicación.
  - ``al_cambiar(cb)`` avisa a la ventana principal para que reconstruya las
    vistas en caliente, sin reiniciar.

Formato del paquete::

    {
      "meta": {"codigo": "en", "nombre": "Inglés", "nativo": "English",
               "version": "1.0", "fecha": "2026-11-14", "autores": "Equipo ROCKET"},
      "cadenas": {"Ajustes": "Settings", "base {v}": "baseline {v}"}
    }
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Callable, Dict, List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES_INCLUIDOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
LOCALES_INSTALADOS = os.path.join(ROOT_DIR, "data", "locales")

IDIOMA_FUENTE = "es"
IDIOMA_POR_DEFECTO = "en"

# Metadatos de los idiomas que la aplicación conoce aunque el paquete no esté
# instalado: así el selector siempre puede mostrar su nombre nativo.
IDIOMAS_CONOCIDOS: Dict[str, Dict[str, str]] = {
    "en": {"nombre": "Inglés", "nativo": "English", "bandera": "EN"},
    "es": {"nombre": "Español", "nativo": "Español", "bandera": "ES"},
}

_estado: Dict[str, Any] = {
    "codigo": IDIOMA_POR_DEFECTO,
    "catalogo": {},
    "meta": {},
    "origen": "incluido",
}

_suscriptores: List[Callable[[str], None]] = []


# ---------------------------------------------------------------------------
# Lectura de paquetes
# ---------------------------------------------------------------------------

def _leer_paquete(ruta: str) -> Dict[str, Any]:
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except Exception:
        return {}
    if not isinstance(datos, dict):
        return {}
    return datos


def ruta_paquete(codigo: str) -> Optional[str]:
    """Ruta efectiva del paquete: instalado primero, incluido después."""
    codigo = (codigo or "").strip().lower()
    if not codigo:
        return None
    for carpeta in (LOCALES_INSTALADOS, LOCALES_INCLUIDOS):
        ruta = os.path.join(carpeta, f"{codigo}.json")
        if os.path.isfile(ruta):
            return ruta
    return None


def paquete_instalado(codigo: str) -> bool:
    codigo = (codigo or "").strip().lower()
    return bool(codigo) and os.path.isfile(os.path.join(LOCALES_INSTALADOS, f"{codigo}.json"))


def _cadenas(paquete: Dict[str, Any]) -> Dict[str, str]:
    """Aplana 'cadenas' y tolera ficheros escritos como diccionario plano."""
    crudo = paquete.get("cadenas")
    origen = crudo if isinstance(crudo, dict) else paquete
    salida: Dict[str, str] = {}
    for clave, valor in origen.items():
        if clave == "meta":
            continue
        if isinstance(valor, str):
            salida[clave] = valor
        elif isinstance(valor, dict):
            # Secciones anidadas (ui, datos, lis…) se fusionan.
            for k2, v2 in valor.items():
                if isinstance(v2, str):
                    salida[k2] = v2
    return salida


def idiomas_disponibles() -> List[Dict[str, Any]]:
    """Idiomas con paquete incluido o instalado, listos para el selector."""
    codigos = set(IDIOMAS_CONOCIDOS)
    for carpeta in (LOCALES_INCLUIDOS, LOCALES_INSTALADOS):
        if not os.path.isdir(carpeta):
            continue
        for nombre in os.listdir(carpeta):
            if nombre.lower().endswith(".json"):
                codigos.add(os.path.splitext(nombre)[0].lower())

    lista: List[Dict[str, Any]] = []
    for codigo in sorted(codigos):
        ruta = ruta_paquete(codigo)
        meta: Dict[str, Any] = {}
        if ruta:
            meta = _leer_paquete(ruta).get("meta") or {}
        conocido = IDIOMAS_CONOCIDOS.get(codigo, {})
        lista.append(
            {
                "codigo": codigo,
                "nombre": str(meta.get("nombre") or conocido.get("nombre") or codigo),
                "nativo": str(meta.get("nativo") or conocido.get("nativo") or codigo.upper()),
                "bandera": str(conocido.get("bandera") or codigo.upper()[:2]),
                "version": str(meta.get("version") or ""),
                "fecha": str(meta.get("fecha") or ""),
                "autores": str(meta.get("autores") or ""),
                "incluido": bool(ruta),
                "instalado": paquete_instalado(codigo),
                "activo": codigo == _estado["codigo"],
            }
        )
    return lista


def info_idioma(codigo: str) -> Dict[str, Any]:
    for item in idiomas_disponibles():
        if item["codigo"] == codigo:
            return item
    return {
        "codigo": codigo,
        "nombre": codigo,
        "nativo": codigo.upper(),
        "bandera": codigo.upper()[:2],
        "version": "",
        "incluido": False,
        "instalado": False,
        "activo": codigo == _estado["codigo"],
    }


# ---------------------------------------------------------------------------
# Instalación ("descarga") de un paquete en el equipo
# ---------------------------------------------------------------------------

def instalar_idioma(codigo: str) -> Dict[str, Any]:
    """Copia el paquete incluido a data/locales para dejarlo instalado.

    Es la operación que la interfaz llama «descargar idioma»: deja el paquete
    guardado en el equipo, disponible sin conexión y con prioridad sobre el que
    viaja dentro de la aplicación. Devuelve el estado resultante.
    """
    codigo = (codigo or "").strip().lower()
    if not codigo:
        return {"ok": False, "error": "Código de idioma vacío."}

    origen = os.path.join(LOCALES_INCLUIDOS, f"{codigo}.json")
    if not os.path.isfile(origen):
        return {"ok": False, "error": f"No hay paquete disponible para «{codigo}»."}

    os.makedirs(LOCALES_INSTALADOS, exist_ok=True)
    destino = os.path.join(LOCALES_INSTALADOS, f"{codigo}.json")
    try:
        shutil.copyfile(origen, destino)
    except Exception as exc:  # pragma: no cover - depende del sistema de archivos
        return {"ok": False, "error": f"No se pudo guardar el paquete: {exc}"}

    ya_activo = codigo == _estado["codigo"]
    if ya_activo:
        # Recarga para que el paquete recién instalado mande sobre el incluido.
        fijar_idioma(codigo, notificar=False)
    return {
        "ok": True,
        "codigo": codigo,
        "ruta": destino,
        "bytes": os.path.getsize(destino),
        "info": info_idioma(codigo),
    }


def desinstalar_idioma(codigo: str) -> Dict[str, Any]:
    """Quita el paquete instalado; el incluido en la aplicación sigue ahí."""
    codigo = (codigo or "").strip().lower()
    destino = os.path.join(LOCALES_INSTALADOS, f"{codigo}.json")
    if not os.path.isfile(destino):
        return {"ok": False, "error": "Ese idioma no está instalado."}
    if codigo == IDIOMA_FUENTE:
        return {"ok": False, "error": "El idioma fuente no se puede quitar."}
    try:
        os.remove(destino)
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"No se pudo borrar: {exc}"}
    return {"ok": True, "codigo": codigo}


# ---------------------------------------------------------------------------
# Idioma activo
# ---------------------------------------------------------------------------

def idioma() -> str:
    return str(_estado["codigo"])


def meta_idioma() -> Dict[str, Any]:
    return dict(_estado["meta"])


def fijar_idioma(codigo: str, *, notificar: bool = True) -> bool:
    """Activa un idioma. Devuelve False si no hay paquete y se mantiene el actual."""
    codigo = (codigo or "").strip().lower()
    if not codigo:
        return False

    ruta = ruta_paquete(codigo)
    if not ruta:
        return False

    paquete = _leer_paquete(ruta)
    anterior = _estado["codigo"]
    _estado["codigo"] = codigo
    _estado["catalogo"] = _cadenas(paquete)
    _estado["meta"] = dict(paquete.get("meta") or {})
    _estado["origen"] = "instalado" if paquete_instalado(codigo) else "incluido"

    if notificar and anterior != codigo:
        _notificar(codigo)
    return True


def al_cambiar(callback: Callable[[str], None]) -> None:
    """Suscripción al cambio de idioma (la ventana principal reconstruye la UI)."""
    if callback not in _suscriptores:
        _suscriptores.append(callback)


def _notificar(codigo: str) -> None:
    for cb in list(_suscriptores):
        try:
            cb(codigo)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Traducción
# ---------------------------------------------------------------------------

def tr(texto: str, **datos: Any) -> str:
    """Traduce una cadena del idioma fuente al idioma activo.

    ``datos`` permite plantillas: tr("base {v}", v=68) -> "baseline 68".
    Cualquier fallo de formato devuelve la cadena tal cual.
    """
    if not isinstance(texto, str) or not texto:
        return texto
    traduccion = _estado["catalogo"].get(texto)
    if traduccion is None:
        # Sin traducción: se devuelve el original, formateado si trae datos.
        if datos:
            try:
                return texto.format(**datos)
            except Exception:
                return texto
        return texto
    if datos:
        try:
            return traduccion.format(**datos)
        except Exception:
            return traduccion
    return traduccion


# Alias corto: se usa en todas las vistas.
T = tr


def idioma_nombre(codigo: Optional[str] = None) -> str:
    return str(info_idioma(codigo or idioma()).get("nativo", codigo or idioma()))
