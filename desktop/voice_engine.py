# -*- coding: utf-8 -*-
"""
desktop/voice_engine.py — Motor de Voz Nativo en Python para L.I.S.
Reproduce la voz clonada real de JARVIS (XTTS v2 GPU en 127.0.0.1:8795 + edge-tts fallback)
directamente por los altavoces del sistema usando sounddevice + soundfile,
emitiendo energía acústica en tiempo real para animar el rostro holográfico RostroLIS.
"""

from __future__ import annotations

import asyncio
import atexit
from concurrent.futures import ThreadPoolExecutor
import io
import math
import queue
import re
import threading
import time
from typing import Optional
import weakref

import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QObject, Signal

from backend.lis_agent import detectar_idioma_texto, sintetizar_voz_lis
from desktop import i18n
from desktop.i18n import tr


def _normalizar_texto_ingles(texto: str) -> str:
    """Normaliza símbolos, unidades clínicas, dosis y protocolos para TTS en inglés."""
    t = texto or ""
    t = re.sub(r"\r?\n+", ". ", t)

    # Etiquetas SBAR antes de quitar corchetes
    t = re.sub(r"\[S\]", "Situation,", t)
    t = re.sub(r"\[B\]", "Background,", t)
    t = re.sub(r"\[A\]", "Assessment,", t)
    t = re.sub(r"\[R\]", "Recommendation,", t)

    # Quitar códigos técnicos largos y normalizar hitos de misión L-XX / R+XX
    t = re.sub(r"\bISS-EMERG-[A-Z0-9-]+\b", "", t)
    t = re.sub(r"\bALSP-\d+\b", "Advanced Life Support Pack", t)
    t = re.sub(r"\bR\+(\d+)\b", r"return plus \1", t)
    t = re.sub(r"\bL-(\d+)\b", r"launch minus \1", t)

    reemplazos = [
        (r"V\.I\.T\.A\.L\.I\.S\.?", "Vitalis"),
        (r"\bL\.I\.S\.?", "Lis"),
        (r"OSD-575|OSDR-575", "O S D five seventy five"),
        (r"\{\s*S\s*\}", "Situation,"),
        (r"\bSBAR\b", "S B A R"),
        (r"\bCMO\b", "Crew Medical Officer"),
        (r"\bSANS\b", "spaceflight associated neuro-ocular syndrome"),
        (r"\b(?:RCP|CPR)\b", "C P R"),
        (r"\b(?:DEA|AED)\b", "A E D"),
        (r"\bBVM\b", "bag valve mask"),
        (r"\bCMRS\b", "crew medical restraint system"),
        (r"\bPBA\b", "portable breathing apparatus"),
        (r"\bEMI\b", "electromagnetic interference"),
        (r"\bIV/IO\b", "intravenous or intraosseous"),
        (r"\bIV\b", "intravenous"),
        (r"\bIO\b", "intraosseous"),
        (r"\bIM\b", "intramuscular"),
        (r"\bUTC\b", "U T C"),
        (r"\bACLS\b", "advanced cardiac life support"),
        (r"\bEtCO₂|EtCO2\b", "end-tidal carbon dioxide"),
        (r"\bSpO₂|SpO2\b", "blood oxygen saturation"),
        (r"\bCO₂|CO2\b", "carbon dioxide"),
        (r"\bO₂|\bO2\b", "oxygen"),
        (r"\b0G\b", "zero gravity"),
        (r"mg/dL", "milligrams per deciliter"),
        (r"mg/kg", "milligrams per kilogram"),
        (r"mmol/L", "millimoles per liter"),
        (r"mEq/L", "milliequivalents per liter"),
        (r"g/dL", "grams per deciliter"),
        (r"U/L", "units per liter"),
        (r"L/min", "liters per minute"),
        (r"\bmL\b", "milliliters"),
        (r"\bmg\b", "milligrams"),
        (r"\bcm\b", "centimeters"),
        (r"mmHg", "millimeters of mercury"),
        (r"mSv/day|mSv/día", "millisieverts per day"),
        (r"mSv", "millisieverts"),
        (r"[µu]Sv", "microsieverts"),
        (r"hPa", "hectopascals"),
        (r"kPa", "kilopascals"),
        (r"km/h", "kilometers per hour"),
        (r"\b(?:bpm|lpm)\b", "beats per minute"),
        (r"°C", "degrees Celsius"),
        (r"°", " degrees"),
        (r"\b30:2\b", "thirty compressions to two breaths"),
        (r"\b110\s*/\s*min\b", "110 per minute"),
    ]
    for patron, rep in reemplazos:
        t = re.sub(patron, rep, t)

    # Duraciones tipo "14m 20s" o "14 min 20 s" -> "14 minutes and 20 seconds"
    t = re.sub(r"\b(\d+)\s*m(?:in)?\s*(\d+)\s*s\b", r"\1 minutes and \2 seconds", t)
    # Rangos numéricos tipo "100–120" o "5-6" -> "100 to 120"
    t = re.sub(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)", r"\1 to \2", t)
    # Presión arterial tipo "116/74" -> "116 over 74"
    t = re.sub(r"\b(\d+)\s*/\s*(\d+)\b", r"\1 over \2", t)
    # Signos y porcentajes
    t = re.sub(r"\+(\d)", r"plus \1", t)
    t = re.sub(r"(?<!\w)-(\d)", r"minus \1", t)
    t = t.replace("%", " percent")

    # Decimales: ".0" a entero y decimales reales con "point"
    t = re.sub(r"\b(\d+)\.0\b", r"\1", t)
    t = re.sub(r"\b(\d+)\.(\d+)\b", r"\1 point \2", t)

    # Singularizar unidades cuando la cantidad exacta es 1
    t = re.sub(r"\b1 milligrams\b", "1 milligram", t)
    t = re.sub(r"\b1 milliliters\b", "1 milliliter", t)
    t = re.sub(r"\b1 beats\b", "1 beat", t)
    t = re.sub(r"\b1 degrees\b", "1 degree", t)
    t = re.sub(r"\b1 minutes\b", "1 minute", t)
    t = re.sub(r"\b1 seconds\b", "1 second", t)

    # Pausas suaves conservando apóstrofos dentro de palabras inglesas (can't, it's)
    t = re.sub(r"[·•→▲—–;:]+", ", ", t)
    t = re.sub(r"[\(\)\[\]\{\}\"\«\»\*_#\\/]+", " ", t)
    t = re.sub(r"(?<!\w)'|'(?!\w)", " ", t)
    t = re.sub(r"[¡¿!?]+", ". ", t)
    t = re.sub(r"\.{2,}", ".", t)
    t = re.sub(r"\s*,\s*", ", ", t)
    t = re.sub(r"(,\s*){2,}", ", ", t)
    t = re.sub(r",\s*\.", ".", t)
    t = re.sub(r"\s+([.,])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,")
    if t and t[-1] not in ".":
        t += "."
    return t


_HALLUCINACIONES_WHISPER = (
    "subtítulos realizados por",
    "subtítulos por",
    "subtítulos de la comunidad",
    "gracias por ver el video",
    "gracias por ver este video",
    "suscríbete al canal",
    "amara.org",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "subscribe to the channel",
    "subtitles by",
    "captions by",
    "transcribed by",
)


def normalizar_texto_para_voz(texto: str, lang: str | None = None) -> str:
    """
    Limpia símbolos/puntuación y expande siglas clínicas, de emergencia y ALSP
    según el idioma efectivo del texto ('es' o 'en') sin mezclar pronunciaciones.
    """
    lang_raw = lang or detectar_idioma_texto(texto, defecto=i18n.idioma())
    if str(lang_raw).lower().startswith("en"):
        return _normalizar_texto_ingles(texto)

    t = texto or ""
    t = re.sub(r"\r?\n+", ". ", t)

    # Etiquetas SBAR antes de quitar corchetes
    t = re.sub(r"\[S\]", "Situación,", t)
    t = re.sub(r"\[B\]", "Antecedentes,", t)
    t = re.sub(r"\[A\]", "Evaluación,", t)
    t = re.sub(r"\[R\]", "Recomendación,", t)

    # Quitar códigos de ficha técnicos largos antes de rangos/guiones
    t = re.sub(r"\bISS-EMERG-[A-Z0-9-]+\b", "", t)
    t = re.sub(r"\bALSP-\d+\b", "paquete de soporte vital", t)

    reemplazos = [
        (r"V\.I\.T\.A\.L\.I\.S\.?", "Vitalis"),
        (r"\bL\.I\.S\.?", "Lis"),
        (r"OSD-575|OSDR-575", "O S D quinientos setenta y cinco"),
        (r"\bSBAR\b", "esbar"),
        (r"\bCMO\b", "oficial médico"),
        (r"\bSANS\b", "síndrome neuro ocular"),
        (r"\bRCP\b", "reanimación cardiopulmonar"),
        (r"\bALSP\b", "paquete de soporte vital"),
        (r"\bDEA\b", "desfibrilador"),
        (r"\bBVM\b", "bolsa de ventilación"),
        (r"\bCMRS\b", "camilla de sujeción"),
        (r"\bPBA\b", "máscara portátil"),
        (r"\bIV/IO\b", "vía intravenosa o intraósea"),
        (r"\bIV\b", "vía intravenosa"),
        (r"\bIM\b", "vía intramuscular"),
        (r"\bIO\b", "vía intraósea"),
        (r"\bEMI\b", "interferencia electromagnética"),
        (r"\bEtCO[₂2]\b", "dióxido de carbono espirado"),
        (r"\b0G\b", "cero gravedad"),
        (r"\b1ª\b", "primera"),
        (r"\b2ª\b", "segunda"),
        (r"\b3ª\b", "tercera"),
        (r"\bFC\b", "frecuencia cardíaca"),
        (r"\bPA\b", "presión arterial"),
        (r"\bC001\b", "C cero cero uno"),
        (r"\bC002\b", "C cero cero dos"),
        (r"\bC003\b", "C cero cero tres"),
        (r"\bC004\b", "C cero cero cuatro"),
        (r"R\+194\b", "retorno más ciento noventa y cuatro días"),
        (r"R\+82\b", "retorno más ochenta y dos días"),
        (r"R\+45\b", "retorno más cuarenta y cinco días"),
        (r"R\+1\b", "retorno más un día"),
        (r"L-92\b", "lanzamiento menos noventa y dos días"),
        (r"L-44\b", "lanzamiento menos cuarenta y cuatro días"),
        (r"L-3\b", "lanzamiento menos tres días"),
        (r"mg/dL", "miligramos por decilitro"),
        (r"mg/kg", "miligramos por kilogramo"),
        (r"mmol/L", "milimoles por litro"),
        (r"g/dL", "gramos por decilitro"),
        (r"U/L", "unidades por litro"),
        (r"L/min", "litros por minuto"),
        (r"\bmL\b", "mililitros"),
        (r"\bmg\b", "miligramos"),
        (r"\bcm\b", "centímetros"),
        (r"mmHg", "milímetros de mercurio"),
        (r"mSv/día", "milisieverts por día"),
        (r"mSv", "milisieverts"),
        (r"[µu]Sv", "microsieverts"),
        (r"hPa", "hectopascales"),
        (r"kPa", "kilopascales"),
        (r"km/h", "kilómetros por hora"),
        (r"lpm", "latidos por minuto"),
        (r"SpO₂|SpO2", "saturación de oxígeno"),
        (r"CO₂|CO2", "dióxido de carbono"),
        (r"\bO₂|\bO2", "oxígeno"),
        (r"°C", "grados centígrados"),
        (r"°", " grados"),
        (r"\b30:2\b", "treinta compresiones por dos ventilaciones"),
    ]
    for patron, rep in reemplazos:
        t = re.sub(patron, rep, t)

    # Tiempos tipo "14m 20s" -> "14 minutos y 20 segundos"
    t = re.sub(r"\b(\d+)\s*m\s*(\d+)\s*s\b", r"\1 minutos y \2 segundos", t)
    # Rangos numéricos tipo "100–120" o "5-6" -> "100 a 120" (antes de signo negativo y decimales)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)", r"\1 a \2", t)
    # Presión arterial tipo "116/74" -> "116 sobre 74"
    t = re.sub(r"\b(\d+)\s*/\s*(\d+)\b", r"\1 sobre \2", t)
    # Signos y porcentajes antes de limpiar puntuación
    t = re.sub(r"\+(\d)", r"más \1", t)
    t = re.sub(r"(?<!\w)-(\d)", r"menos \1", t)
    t = t.replace("%", " por ciento")

    # Decimales: ".0" se omite y otros decimales se leen "con" para evitar "punto"
    t = re.sub(r"\b(\d+)\.0\b", r"\1", t)
    t = re.sub(r"\b(\d+)\.(\d+)\b", r"\1 con \2", t)

    # Convertir separadores visuales en pausas suaves y eliminar signos no hablados
    t = re.sub(r"\b1 miligramos\b", "1 miligramo", t)
    t = re.sub(r"\b1 mililitros\b", "1 mililitro", t)
    t = re.sub(r"\b1 minutos\b", "1 minuto", t)
    t = re.sub(r"[·•→▲—–;:]+", ", ", t)
    t = re.sub(r"[\(\)\[\]\{\}\"'\«\»\*_#\\/]+", " ", t)
    t = re.sub(r"[¡¿!?]+", ". ", t)
    t = re.sub(r"\.{2,}", ".", t)
    t = re.sub(r"\s*,\s*", ", ", t)
    t = re.sub(r"(,\s*){2,}", ", ", t)
    t = re.sub(r",\s*\.", ".", t)
    t = re.sub(r"\s+([.,])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,")
    if t and t[-1] not in ".":
        t += "."
    return t


def _dividir_chunks_voz(texto: str, max_chars: int = 260) -> list[str]:
    """Divide locuciones largas por límite de oración para evitar cortes y reducir latencia."""
    t = (texto or "").strip()
    if not t:
        return []
    if len(t) <= max_chars:
        return [t]

    oraciones = [s.strip() for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]
    partes: list[str] = []
    for oracion in oraciones:
        if len(oracion) <= max_chars:
            partes.append(oracion)
        else:
            # Subdividir oraciones muy largas por comas y luego palabras
            sub_buf = ""
            for seg in [c.strip() for c in oracion.split(",") if c.strip()]:
                cand = f"{sub_buf}, {seg}".strip(", ") if sub_buf else seg
                if len(cand) <= max_chars:
                    sub_buf = cand
                else:
                    if sub_buf:
                        partes.append(sub_buf)
                        sub_buf = ""
                    while len(seg) > max_chars:
                        corte = seg.rfind(" ", 0, max_chars)
                        if corte <= 0:
                            corte = max_chars
                        partes.append(seg[:corte].strip())
                        seg = seg[corte:].strip()
                    sub_buf = seg
            if sub_buf:
                partes.append(sub_buf)

    chunks: list[str] = []
    actual = ""
    for parte in partes:
        cand = f"{actual} {parte}".strip() if actual else parte
        if len(cand) <= max_chars:
            actual = cand
        else:
            if actual:
                chunks.append(actual)
            actual = parte
    if actual:
        chunks.append(actual)
    return chunks


def _ajustar_velocidad_pcm(data: np.ndarray, velocidad: float, sr: int) -> np.ndarray:
    """
    Time-stretch WSOLA en NumPy puro: aplica velocidadVoz (0.85x–1.45x)
    al audio PCM de XTTS preservando el timbre/tono de la voz clonada.
    """
    if abs(velocidad - 1.0) < 0.03 or len(data) < max(64, int(sr * 0.2)):
        return data
    vel = max(0.75, min(1.6, float(velocidad)))
    win = max(64, int(round(sr * 0.046)))
    if win % 2 != 0:
        win += 1
    hs = win // 2
    ha = max(8, int(round(hs * vel)))
    tol = max(8, int(round(sr * 0.008)))

    hann = np.hanning(win + 1)[:-1].astype(np.float32)
    target_len = max(win, int(round(len(data) / vel)))
    out = np.zeros(target_len + win * 2, dtype=np.float32)
    norm = np.zeros(target_len + win * 2, dtype=np.float32)

    n_src = len(data)
    if n_src <= win:
        return data

    out[:win] += data[:win] * hann
    norm[:win] += hann

    ones_hs = np.ones(hs, dtype=np.float32)
    frame_idx = 1
    while True:
        out_pos = frame_idx * hs
        in_nom = frame_idx * ha
        if in_nom + win >= n_src or out_pos + win >= len(out):
            break
        s0 = max(0, in_nom - tol)
        s1 = min(n_src - win, in_nom + tol)
        if s1 > s0:
            ref = out[out_pos : out_pos + hs]
            cand = data[s0 : s1 + hs]
            dots = np.correlate(cand, ref, mode="valid")
            energies = np.correlate(cand * cand, ones_hs, mode="valid")
            ncc = dots / np.sqrt(energies + 1e-8)
            best = s0 + int(np.argmax(ncc))
        else:
            best = min(max(0, in_nom), n_src - win)
        out[out_pos : out_pos + win] += data[best : best + win] * hann
        norm[out_pos : out_pos + win] += hann
        frame_idx += 1

    # Añadir la cola remanente si quedó material sin cubrir
    rem_in = min(max(0, frame_idx * ha), max(0, n_src - win))
    out_tail = min(frame_idx * hs, len(out) - win)
    if rem_in + win <= n_src and out_tail >= 0:
        out[out_tail : out_tail + win] += data[rem_in : rem_in + win] * hann
        norm[out_tail : out_tail + win] += hann

    recortado = out[:target_len] / np.maximum(norm[:target_len], 1e-3)
    return np.clip(recortado, -1.0, 1.0).astype(np.float32)


def _sintetizar_chunk_sync(texto: str, voz_id: str, velocidad: float, lang: str | None = None):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(sintetizar_voz_lis(texto, voz_id, velocidad, lang=lang))
    finally:
        loop.close()


_PULSO_ALARMA_CACHE: dict[tuple[int, float, str], np.ndarray] = {}

TONOS_ALARMA_EMERGENCIA = ("doble-suave", "pulso-unico", "acorde-tibio")


def construir_pulso_alarma_emergencia(
    sr: int = 22050,
    volumen: float = 0.70,
    tono: str = "doble-suave",
) -> np.ndarray:
    """Sintetiza un pulso intermitente cálido para emergencia roja configurable en Ajustes.

    Diseñado sin estridencias ni ondas cuadradas: bordes suaves raised-cosine y
    armónico contenido para comunicar urgencia sin provocar pánico.
    """
    vol_norm = max(0.25, min(1.0, round(float(volumen), 2)))
    tono_norm = tono if tono in TONOS_ALARMA_EMERGENCIA else "doble-suave"
    cache_key = (int(sr), vol_norm, tono_norm)
    cached = _PULSO_ALARMA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    escala = max(0.30, min(1.40, vol_norm / 0.70))

    def _nota(freq: float, dur_s: float, amp: float, fade_in_s: float = 0.024, fade_out_s: float = 0.085) -> np.ndarray:
        n = max(1, int(sr * dur_s))
        t = np.arange(n, dtype=np.float32) / float(sr)
        onda = np.sin(2.0 * np.pi * freq * t) + 0.12 * np.sin(4.0 * np.pi * freq * t)
        env = np.ones(n, dtype=np.float32)
        n_in = min(n // 2, max(1, int(sr * fade_in_s)))
        n_out = min(n - n_in, max(1, int(sr * fade_out_s)))
        if n_in > 0:
            env[:n_in] = 0.5 * (1.0 - np.cos(np.pi * np.arange(n_in, dtype=np.float32) / float(n_in)))
        if n_out > 0:
            env[-n_out:] = 0.5 * (1.0 + np.cos(np.pi * np.arange(n_out, dtype=np.float32) / float(n_out)))
        return (onda * env * amp * escala).astype(np.float32)

    if tono_norm == "pulso-unico":
        tono1 = _nota(440.00, 0.360, 0.16, fade_in_s=0.032, fade_out_s=0.220)
        cola = np.zeros(int(sr * 0.040), dtype=np.float32)
        pulso = np.concatenate([tono1, cola]).astype(np.float32)
    elif tono_norm == "acorde-tibio":
        nota_base = _nota(329.63, 0.360, 0.095, fade_in_s=0.036, fade_out_s=0.210)
        nota_quinta = _nota(493.88, 0.360, 0.065, fade_in_s=0.044, fade_out_s=0.210)
        cola = np.zeros(int(sr * 0.045), dtype=np.float32)
        pulso = np.concatenate([nota_base + nota_quinta, cola]).astype(np.float32)
    else:
        tono1 = _nota(587.33, 0.135, 0.17, fade_in_s=0.022, fade_out_s=0.065)  # D5 cálido
        pausa = np.zeros(int(sr * 0.075), dtype=np.float32)
        tono2 = _nota(440.00, 0.205, 0.15, fade_in_s=0.022, fade_out_s=0.125)  # A4 resuelto
        cola = np.zeros(int(sr * 0.030), dtype=np.float32)
        pulso = np.concatenate([tono1, pausa, tono2, cola]).astype(np.float32)

    _PULSO_ALARMA_CACHE[cache_key] = pulso
    return pulso


_MONITOR_LATIDO_CACHE: dict[tuple[int, int, int, float, str], np.ndarray] = {}


def intervalo_latido_ms(bpm: float) -> int:
    """Convierte los latidos por minuto (bpm) a intervalo entre pulsos en milisegundos."""
    try:
        bpm_val = float(bpm)
    except Exception:
        bpm_val = 64.0
    if not math.isfinite(bpm_val) or bpm_val <= 0.0:
        bpm_val = 64.0
    bpm_clamped = max(30.0, min(240.0, bpm_val))
    return max(250, min(2000, int(round(60_000.0 / bpm_clamped))))


def construir_pulso_latido_monitor(
    sr: int = 22050,
    spo2: float = 98.0,
    bpm: float = 64.0,
    volumen: float = 0.35,
    nivel: str = "NOMINAL",
) -> np.ndarray:
    """Sintetiza un pulso hospitalario tipo oxímetro/ECG con tono modulado por SpO₂.

    La frecuencia sonora sube con SpO₂ alta y desciende si baja la saturación, mientras
    el intervalo entre pulsos y la brevedad del golpe responden en vivo a los lpm.
    """
    try:
        spo2_val = float(spo2)
    except Exception:
        spo2_val = 98.0
    try:
        bpm_val = float(bpm)
    except Exception:
        bpm_val = 64.0

    spo2_q = int(round(max(75.0, min(100.0, spo2_val))))
    bpm_clamped = max(30.0, min(240.0, bpm_val if math.isfinite(bpm_val) else 64.0))
    dur_ms = 48 if bpm_clamped >= 140.0 else (58 if bpm_clamped >= 100.0 else 68)
    vol_q = max(0.15, min(1.0, round(float(volumen), 2)))
    nivel_norm = str(nivel or "NOMINAL").upper()

    cache_key = (int(sr), spo2_q, dur_ms, vol_q, nivel_norm)
    cached = _MONITOR_LATIDO_CACHE.get(cache_key)
    if cached is not None:
        return cached

    freq = 410.0 + ((max(80.0, min(100.0, float(spo2_q))) - 80.0) / 20.0) * 270.0
    dur_s = dur_ms / 1000.0
    n = max(1, int(sr * dur_s))
    t_arr = np.arange(n, dtype=np.float32) / float(sr)

    arm2 = 0.14 if nivel_norm == "CRITICO" else 0.08
    onda = np.sin(2.0 * np.pi * freq * t_arr) + arm2 * np.sin(4.0 * np.pi * freq * t_arr)

    env = np.ones(n, dtype=np.float32)
    n_in = min(n // 3, max(1, int(sr * 0.008)))
    n_out = min(n - n_in, max(1, int(sr * dur_s * 0.62)))
    env[:n_in] = 0.5 * (1.0 - np.cos(np.pi * np.arange(n_in, dtype=np.float32) / float(n_in)))
    env[-n_out:] = 0.5 * (1.0 + np.cos(np.pi * np.arange(n_out, dtype=np.float32) / float(n_out)))

    escala = max(0.25, min(2.2, vol_q / 0.35))
    pulso_activo = np.clip(onda * env * 0.105 * escala, -0.85, 0.85).astype(np.float32)
    cola = np.zeros(max(1, int(sr * 0.006)), dtype=np.float32)
    pulso = np.concatenate([pulso_activo, cola]).astype(np.float32)
    _MONITOR_LATIDO_CACHE[cache_key] = pulso
    return pulso


class MotorVozNativo(QObject):
    estadoHablaCambiado = Signal(bool)
    energiaActualizada = Signal(float)
    transcripcionLista = Signal(str)
    estadoEscuchaCambiado = Signal(bool)
    estadoTranscribiendoCambiado = Signal(bool)
    sinAudioDetectado = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._stop_event = threading.Event()
        self._mic_stop_event = threading.Event()
        self._alarma_stop_event = threading.Event()
        self._monitor_stop_event = threading.Event()
        self._hablando = False
        self._escuchando = False
        self._lock = threading.Lock()
        self._gen_lock = threading.Lock()
        self._alarma_lock = threading.Lock()
        self._monitor_lock = threading.Lock()
        self._monitor_buf = np.zeros(0, dtype=np.float32)
        self._monitor_last_beat_ts = 0.0
        self._monitor_thread: Optional[threading.Thread] = None
        self._alarma_thread: Optional[threading.Thread] = None
        self._cerrado = False
        self._speech_gen = 0
        self._whisper_lock = threading.Lock()
        self._whisper_model = None
        # Registra cierre previo a sounddevice._exit_handler (LIFO) para evitar
        # cerrar sd.OutputStream en paralelo con Pa_Terminate() al salir.
        ref = weakref.ref(self)

        def _atexit_cerrar() -> None:
            motor = ref()
            if motor is not None:
                motor.cerrar()

        atexit.register(_atexit_cerrar)

    @property
    def hablando(self) -> bool:
        return self._hablando

    @property
    def escuchando(self) -> bool:
        return self._escuchando

    def _cargar_whisper_seguro(self):
        with self._whisper_lock:
            if self._whisper_model is not None:
                return self._whisper_model
            from faster_whisper import WhisperModel

            try:
                self._whisper_model = WhisperModel(
                    "base", device="cpu", compute_type="int8", local_files_only=True
                )
            except Exception:
                self._whisper_model = WhisperModel(
                    "base", device="cpu", compute_type="int8"
                )
            return self._whisper_model

    def prewarm_stt(self) -> None:
        """Precarga faster-whisper en segundo plano para reducir latencia del primer dictado."""
        if self._cerrado or self._whisper_model is not None:
            return

        def _warm() -> None:
            if self._cerrado:
                return
            try:
                self._cargar_whisper_seguro()
            except Exception:
                pass

        threading.Thread(target=_warm, daemon=True, name="lis-stt-prewarm").start()

    def detener_habla(self) -> None:
        with self._gen_lock:
            self._speech_gen += 1
        self._stop_event.set()
        self._alarma_stop_event.set()
        self.detener_monitor_cardiaco()
        try:
            sd.stop()
        except Exception:
            pass

    def detener_alarma_emergencia(self, esperar: bool = False) -> None:
        """Detiene de inmediato cualquier pulso acústico de emergencia en curso."""
        self._alarma_stop_event.set()
        if esperar:
            hilo = self._alarma_thread
            if hilo is not None and hilo.is_alive() and hilo is not threading.current_thread():
                hilo.join(timeout=0.6)

    def detener_monitor_cardiaco(self, esperar: bool = False) -> None:
        """Silencia y libera el stream continuo del monitor hospitalario de Overview."""
        self._monitor_stop_event.set()
        with self._monitor_lock:
            self._monitor_buf = np.zeros(0, dtype=np.float32)
            hilo = self._monitor_thread
        if esperar and hilo is not None and hilo.is_alive() and hilo is not threading.current_thread():
            hilo.join(timeout=0.6)

    def cerrar(self) -> None:
        """Cierra streams activos y espera a sus hilos antes del apagado de PortAudio."""
        if self._cerrado:
            return
        self._cerrado = True
        with self._gen_lock:
            self._speech_gen += 1
        self._stop_event.set()
        self._mic_stop_event.set()
        self.detener_alarma_emergencia(esperar=True)
        self.detener_monitor_cardiaco(esperar=True)

    def reproducir_latido_monitor(
        self,
        bpm: float = 64.0,
        spo2: float = 98.0,
        volumen: float = 0.35,
        nivel: str = "NOMINAL",
    ) -> bool:
        """Programa un pulso cálido tipo monitor hospitalario sin bloquear la UI."""
        if self._cerrado or self._hablando or self._escuchando or self._alarma_lock.locked():
            return False
        pulso = construir_pulso_latido_monitor(
            22050, spo2=spo2, bpm=bpm, volumen=volumen, nivel=nivel
        )
        with self._monitor_lock:
            if self._cerrado:
                return False
            actual = self._monitor_buf
            if len(actual) == 0:
                self._monitor_buf = pulso
            else:
                largo = max(len(actual), len(pulso))
                mezcla = np.zeros(largo, dtype=np.float32)
                mezcla[: len(actual)] += actual
                mezcla[: len(pulso)] += pulso
                self._monitor_buf = np.clip(mezcla, -0.90, 0.90)
            self._monitor_last_beat_ts = time.monotonic()
            necesita_hilo = (
                self._monitor_thread is None or not self._monitor_thread.is_alive()
            )
            if necesita_hilo:
                self._monitor_stop_event.clear()
                self._monitor_thread = threading.Thread(
                    target=self._monitor_worker,
                    daemon=True,
                    name="vitalis-hr-monitor",
                )
                self._monitor_thread.start()
        return True

    def _monitor_worker(self) -> None:
        sr = 22050
        bloque = 512
        try:
            with sd.OutputStream(
                samplerate=sr, channels=1, dtype="float32", blocksize=bloque
            ) as stream:
                while (
                    not self._monitor_stop_event.is_set()
                    and not self._hablando
                    and not self._escuchando
                ):
                    with self._monitor_lock:
                        buf = self._monitor_buf
                        if len(buf) >= bloque:
                            trozo = buf[:bloque]
                            self._monitor_buf = buf[bloque:]
                        elif len(buf) > 0:
                            trozo = np.zeros(bloque, dtype=np.float32)
                            trozo[: len(buf)] = buf
                            self._monitor_buf = np.zeros(0, dtype=np.float32)
                        else:
                            trozo = np.zeros(bloque, dtype=np.float32)
                            inactivo = (
                                time.monotonic() - self._monitor_last_beat_ts
                            ) > 2.2
                            if inactivo:
                                break
                    stream.write(trozo.reshape(-1, 1))
        except Exception:
            pass
        finally:
            with self._monitor_lock:
                self._monitor_thread = None

    def reproducir_pulso_alarma_emergencia(
        self, volumen: float = 0.70, tono: str = "doble-suave"
    ) -> bool:
        """Emite un único pulso intermitente cálido en un stream aislado sin tapar voz ni micrófono."""
        if self._cerrado or self._hablando or self._escuchando:
            return False
        if not self._alarma_lock.acquire(blocking=False):
            return False
        self._alarma_stop_event.clear()

        def _beep_worker() -> None:
            sr = 22050
            try:
                pulso = construir_pulso_alarma_emergencia(sr, volumen=volumen, tono=tono)
                bloque = 1024
                with sd.OutputStream(samplerate=sr, channels=1, dtype="float32") as stream:
                    for idx in range(0, len(pulso), bloque):
                        if (
                            self._cerrado
                            or self._alarma_stop_event.is_set()
                            or self._hablando
                            or self._escuchando
                        ):
                            break
                        stream.write(pulso[idx : idx + bloque].reshape(-1, 1))
            except Exception:
                pass
            finally:
                self._alarma_thread = None
                try:
                    self._alarma_lock.release()
                except RuntimeError:
                    pass

        hilo = threading.Thread(target=_beep_worker, daemon=True, name="vitalis-red-alarm")
        self._alarma_thread = hilo
        hilo.start()
        return True

    def detener_escucha(self) -> None:
        """Detiene anticipadamente la captura de micrófono para transcribir de inmediato."""
        self._mic_stop_event.set()

    def hablar(
        self,
        texto: str,
        voz_id: str = "jarvis-clone-latam",
        velocidad: float = 1.04,
        lang: str | None = None,
    ) -> None:
        """Sintetiza y reproduce en fragmentos separando con precisión el idioma ('es' / 'en')."""
        with self._gen_lock:
            self._speech_gen += 1
            mi_gen = self._speech_gen
        self._stop_event.set()
        self._alarma_stop_event.set()
        self.detener_monitor_cardiaco()
        try:
            sd.stop()
        except Exception:
            pass

        lang_eff = (
            "en"
            if str(lang or detectar_idioma_texto(texto, defecto=i18n.idioma())).lower().startswith("en")
            else "es"
        )
        texto_limpio = normalizar_texto_para_voz(texto, lang=lang_eff)
        chunks = _dividir_chunks_voz(texto_limpio, max_chars=260)
        if not chunks:
            return

        def _emit(sig, *args) -> None:
            try:
                sig.emit(*args)
            except RuntimeError:
                pass

        def _worker() -> None:
            with self._lock:
                with self._gen_lock:
                    if mi_gen != self._speech_gen:
                        return
                    self._stop_event.clear()

                self._hablando = True
                _emit(self.estadoHablaCambiado, True)
                self.detener_monitor_cardiaco(esperar=True)
                try:
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        futuro = pool.submit(
                            _sintetizar_chunk_sync, chunks[0], voz_id, velocidad, lang_eff
                        )
                        for i in range(len(chunks)):
                            if self._stop_event.is_set() or mi_gen != self._speech_gen:
                                break
                            audio_bytes, _mime, eng = futuro.result()
                            if i + 1 < len(chunks) and not self._stop_event.is_set() and mi_gen == self._speech_gen:
                                futuro = pool.submit(
                                    _sintetizar_chunk_sync, chunks[i + 1], voz_id, velocidad, lang_eff
                                )
                            else:
                                futuro = None

                            if self._stop_event.is_set() or mi_gen != self._speech_gen or not audio_bytes:
                                break

                            data, samplerate = sf.read(io.BytesIO(audio_bytes), dtype="float32")
                            if data.ndim > 1:
                                data = data.mean(axis=1)
                            if eng == "jarvis-xtts-clone":
                                data = _ajustar_velocidad_pcm(data, velocidad, samplerate)

                            bloque = max(512, int(samplerate * 0.04))
                            sd.play(data, samplerate)
                            total = len(data)
                            idx = 0
                            while (
                                idx < total
                                and not self._stop_event.is_set()
                                and mi_gen == self._speech_gen
                            ):
                                trozo = data[idx : idx + bloque]
                                rms = float(np.sqrt(np.mean(np.square(trozo)))) if len(trozo) else 0.0
                                _emit(self.energiaActualizada, min(1.0, rms * 5.2))
                                time.sleep(0.038)
                                idx += bloque
                            if self._stop_event.is_set() or mi_gen != self._speech_gen:
                                try:
                                    sd.stop()
                                except Exception:
                                    pass
                                break
                            sd.wait()
                except Exception as exc:
                    import logging

                    logging.getLogger("vitalis.voz").warning(
                        "Error reproduciendo voz L.I.S.: %s", exc
                    )
                finally:
                    _emit(self.energiaActualizada, 0.0)
                    self._hablando = False
                    _emit(self.estadoHablaCambiado, False)

        threading.Thread(target=_worker, daemon=True, name="lis-tts-play").start()

    def escuchar_orden_microfono(self, duracion_seg: float = 5.5) -> None:
        """
        Captura audio del micrófono con energía en vivo, detección automática de silencio final
        (o cierre manual con detener_escucha()) y transcripción local con faster-whisper.
        """
        if self._escuchando:
            self.detener_escucha()
            return
        self.detener_habla()
        self._mic_stop_event.clear()

        def _stt_worker() -> None:
            self._escuchando = True
            self.estadoEscuchaCambiado.emit(True)
            transcribiendo_emitido = False
            try:
                sr = 16000
                try:
                    sd.check_input_settings(samplerate=sr, channels=1, dtype="float32")
                except Exception:
                    dev_info = sd.query_devices(kind="input")
                    sr = max(8000, int(round(float(dev_info.get("default_samplerate", 16000)))))

                bloques: list[np.ndarray] = []
                bloques_lock = threading.Lock()
                estado_audio = {"rms": 0.0, "peak": 0.0}

                def _cb(indata, _frames, _time_info, _status) -> None:
                    arr = indata[:, 0].copy()
                    rms = float(np.sqrt(np.mean(np.square(arr)))) if len(arr) else 0.0
                    peak = float(np.max(np.abs(arr))) if len(arr) else 0.0
                    with bloques_lock:
                        bloques.append(arr)
                        estado_audio["rms"] = rms
                        estado_audio["peak"] = peak

                blocksize = max(256, int(sr * 0.05))
                voz_detectada = False

                with sd.InputStream(
                    samplerate=sr,
                    channels=1,
                    dtype="float32",
                    blocksize=blocksize,
                    callback=_cb,
                ):
                    inicio = time.monotonic()
                    ultimo_sonido_ts = inicio
                    while True:
                        time.sleep(0.04)
                        ahora = time.monotonic()
                        transcurrido = ahora - inicio
                        with bloques_lock:
                            rms = estado_audio["rms"]
                            peak = estado_audio["peak"]
                            muestras_capturadas = sum(len(b) for b in bloques)

                        self.energiaActualizada.emit(min(1.0, rms * 10.0))
                        if rms > 0.008 or peak > 0.025:
                            voz_detectada = True
                            ultimo_sonido_ts = ahora

                        if (
                            self._mic_stop_event.is_set()
                            and transcurrido >= 0.35
                            and muestras_capturadas >= int(sr * 0.25)
                        ):
                            break
                        if transcurrido >= duracion_seg:
                            break
                        if (
                            voz_detectada
                            and transcurrido >= 1.2
                            and (ahora - ultimo_sonido_ts) >= 1.15
                        ):
                            break

                self.energiaActualizada.emit(0.0)
                self._escuchando = False
                self.estadoEscuchaCambiado.emit(False)

                with bloques_lock:
                    muestras = np.concatenate(bloques) if bloques else np.array([], dtype=np.float32)

                if len(muestras) < int(sr * 0.25):
                    self.sinAudioDetectado.emit(
                        tr("No escuché voz en el micrófono, señor. Puede escribirme o intentarlo de nuevo.")
                    )
                    return

                max_abs = float(np.max(np.abs(muestras)))
                if max_abs < 0.002:
                    self.sinAudioDetectado.emit(
                        tr("No escuché voz en el micrófono, señor. Puede escribirme o intentarlo de nuevo.")
                    )
                    return

                if sr != 16000:
                    from scipy.signal import resample_poly

                    g = math.gcd(16000, sr)
                    muestras = resample_poly(muestras, 16000 // g, sr // g).astype(np.float32)

                if max_abs < 0.18:
                    gain = min(15.0, 0.65 / max_abs)
                    muestras = np.clip(muestras * gain, -1.0, 1.0).astype(np.float32)

                transcribiendo_emitido = True
                self.estadoTranscribiendoCambiado.emit(True)

                modelo = self._cargar_whisper_seguro()
                idioma_voz = "es" if i18n.idioma() == "es" else "en"
                segments, _info = modelo.transcribe(
                    muestras,
                    language=idioma_voz,
                    beam_size=2,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 450},
                    condition_on_previous_text=False,
                    initial_prompt=(
                        "V.I.T.A.L.I.S., L.I.S., C001, C002, C003, C004, L-92, R+1, "
                        "SBAR, RCP, DEA, SANS, glucosa, oxígeno, epinefrina, "
                        "modo claro, modo oscuro, protocolo cardiovascular, respiratorio, neurológico, trauma, switch to English."
                        if idioma_voz == "es"
                        else "V.I.T.A.L.I.S., L.I.S., C001, C002, C003, C004, L-92, R+1, "
                        "SBAR, CPR, AED, SANS, glucose, oxygen, epinephrine, "
                        "dark mode, light mode, cardiovascular protocol, respiratory, neurological, trauma, habla en español."
                    ),
                )
                texto = " ".join(s.text.strip() for s in segments).strip()
                low_tx = texto.lower()
                if not texto or any(h in low_tx for h in _HALLUCINACIONES_WHISPER):
                    self.sinAudioDetectado.emit(
                        tr("No alcancé a entender la orden de voz, señor. ¿Puede repetirla?")
                    )
                else:
                    self.transcripcionLista.emit(texto)
            except Exception:
                self.sinAudioDetectado.emit(
                    tr("El micrófono no respondió en este momento, señor. Puede escribir su consulta.")
                )
            finally:
                self.energiaActualizada.emit(0.0)
                if self._escuchando:
                    self._escuchando = False
                    self.estadoEscuchaCambiado.emit(False)
                if transcribiendo_emitido:
                    self.estadoTranscribiendoCambiado.emit(False)

        threading.Thread(target=_stt_worker, daemon=True, name="lis-stt-mic").start()
