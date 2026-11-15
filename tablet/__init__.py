# -*- coding: utf-8 -*-
"""
tablet/ — Pantalla remota táctil de V.I.T.A.L.I.S. para tablets Android.

La aplicación de escritorio (PySide6 + VTK) sigue corriendo íntegra en la PC.
Este paquete renderiza su ventana a la resolución de la tablet, la envía por
WebSocket (USB con `adb reverse`, o LAN opcional) y devuelve el touch, el
teclado, el audio y el micrófono de la tablet a la aplicación real.
"""

__version__ = "1.0.0"
PUERTO = 8781
