# -*- coding: utf-8 -*-
"""tablet/adb.py — Detección de la tablet Android y túnel USB (`adb reverse`)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional

from tablet import PUERTO

log = logging.getLogger("vitalis.tablet.adb")
_NOWIN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def ruta_adb() -> Optional[str]:
    cand = shutil.which("adb")
    if cand:
        return cand
    for base in (
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk"),
    ):
        if base:
            p = os.path.join(base, "platform-tools", "adb.exe" if os.name == "nt" else "adb")
            if os.path.exists(p):
                return p
    return None


def _adb(args: List[str], serie: Optional[str] = None, timeout: float = 8.0) -> str:
    exe = ruta_adb()
    if not exe:
        raise FileNotFoundError("adb no encontrado")
    cmd = [exe] + (["-s", serie] if serie else []) + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=_NOWIN)
    return (r.stdout or "") + (r.stderr or "")


def dispositivos() -> List[Dict[str, str]]:
    try:
        out = _adb(["devices", "-l"])
    except Exception:
        return []
    res = []
    for linea in out.splitlines()[1:]:
        partes = linea.split()
        if len(partes) >= 2:
            res.append({"serie": partes[0], "estado": partes[1], "detalle": " ".join(partes[2:])})
    return res


def info_tablet(serie: Optional[str] = None) -> Optional[Dict[str, object]]:
    """Modelo, resolución física y densidad de la tablet conectada (None si no hay)."""
    devs = [d for d in dispositivos() if d["estado"] == "device"]
    if serie:
        devs = [d for d in devs if d["serie"] == serie]
    if not devs:
        return None
    s = devs[0]["serie"]
    try:
        tam = re.search(r"(\d+)x(\d+)", _adb(["shell", "wm", "size"], s))
        den = re.search(r"(\d+)", _adb(["shell", "wm", "density"], s).split(":")[-1])
        modelo = _adb(["shell", "getprop", "ro.product.model"], s).strip()
        w, h = (int(tam.group(1)), int(tam.group(2))) if tam else (2000, 1200)
        dens = int(den.group(1)) if den else 240
    except Exception:
        return None
    w, h = max(w, h), min(w, h)  # la app se usa en horizontal
    return {"serie": s, "modelo": modelo, "pw": w, "ph": h, "dpr": round(dens / 160.0, 3)}


def conectar_usb(serie: str, puerto: int = PUERTO, abrir_chrome: bool = False) -> bool:
    """Túnel tablet:localhost:puerto -> PC (y permiso de micrófono para Chrome)."""
    try:
        _adb(["reverse", f"tcp:{puerto}", f"tcp:{puerto}"], serie)
        # L.I.S. escucha con el micrófono de la tablet: se pre-concede el permiso de Android.
        _adb(["shell", "pm", "grant", "com.android.chrome", "android.permission.RECORD_AUDIO"], serie)
        if abrir_chrome:
            abrir_pagina(serie, puerto)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo preparar la tablet por USB: %s", exc)
        return False


def abrir_pagina(serie: str, puerto: int = PUERTO) -> bool:
    """Despierta la tablet y abre la pantalla remota en Chrome."""
    try:
        _adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], serie)
        _adb([
            "shell", "am", "start", "-a", "android.intent.action.VIEW",
            "-d", f"http://localhost:{puerto}/", "com.android.chrome",
        ], serie)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo abrir Chrome en la tablet: %s", exc)
        return False
