# -*- coding: utf-8 -*-
"""
backend/database.py — Base de datos SQLite local (Offline-First) e indexador O(1)
para NASA OSDR OSD-575, telemetría de cabina, mediciones en 0G y memoria de L.I.S.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "vitalis.db")

SEED_OSDR_PATH = os.path.join(
    ROOT_DIR, "recursos", "datos", "seed", "osdr-inspiration4-cmp.json"
)
MOCK_CABINA_PATH = os.path.join(
    ROOT_DIR, "recursos", "datos", "mock", "signos-vitales-cabina.json"
)
KNOWLEDGE_GUIA_PATH = os.path.join(
    ROOT_DIR, "recursos", "datos", "knowledge", "indicadores-guia.json"
)
KNOWLEDGE_PROTOCOLOS_PATH = os.path.join(
    ROOT_DIR, "recursos", "datos", "knowledge", "protocolos-emergencia.json"
)
KNOWLEDGE_PROTOCOLOS_DISP_PATH = os.path.join(
    ROOT_DIR, "recursos", "datos", "knowledge", "protocolos-disparadores.json"
)
KNOWLEDGE_TRIPULACION_PATH = os.path.join(
    ROOT_DIR, "recursos", "datos", "knowledge", "tripulacion.json"
)
KNOWLEDGE_ALSP_PATH = os.path.join(
    ROOT_DIR, "recursos", "datos", "knowledge", "alsp-equipos.json"
)

PREFLIGHT_TIMEPOINTS = {"L-92", "L-44", "L-3"}

_db_lock = threading.RLock()
_osdr_cache: Optional[Dict[str, Any]] = None
_cabina_cache: Optional[Dict[str, Any]] = None
_guias_cache: Optional[Dict[str, Any]] = None
_protocolos_cache: Optional[Dict[str, Any]] = None
_protocolos_disp_cache: Optional[List[Dict[str, Any]]] = None
_tripulacion_cache: Optional[Dict[str, Any]] = None
_alsp_cache: Optional[Dict[str, Any]] = None
_baselines_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
_inicializado = False


def get_connection() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def init_db(forzar: bool = False) -> None:
    """Inicializa el esquema SQLite y siembra los datos oficiales de NASA OSDR OSD-575.

    Es idempotente: tras la primera llamada no vuelve a leer ni a sembrar nada.
    """
    global _osdr_cache, _cabina_cache, _guias_cache, _protocolos_cache, _protocolos_disp_cache, _tripulacion_cache, _alsp_cache, _inicializado

    if _inicializado and not forzar:
        return

    with _db_lock:
        if _inicializado and not forzar:
            return
        _osdr_cache = _load_json_file(SEED_OSDR_PATH)
        _cabina_cache = _load_json_file(MOCK_CABINA_PATH)
        _guias_cache = _load_json_file(KNOWLEDGE_GUIA_PATH)
        _protocolos_cache = _load_json_file(KNOWLEDGE_PROTOCOLOS_PATH)
        _protocolos_disp_cache = (
            _load_json_file(KNOWLEDGE_PROTOCOLOS_DISP_PATH)
            if os.path.exists(KNOWLEDGE_PROTOCOLOS_DISP_PATH)
            else []
        )
        _tripulacion_cache = (
            _load_json_file(KNOWLEDGE_TRIPULACION_PATH)
            if os.path.exists(KNOWLEDGE_TRIPULACION_PATH)
            else {"tripulantes": {}}
        )
        _alsp_cache = _load_json_file(KNOWLEDGE_ALSP_PATH)

        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS osdr_indicators (
                    id TEXT PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    sistema TEXT NOT NULL,
                    unidad TEXT NOT NULL,
                    rango_min REAL,
                    rango_max REAL,
                    fuente TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS osdr_measurements (
                    crew_id TEXT NOT NULL,
                    indicador_id TEXT NOT NULL,
                    timepoint TEXT NOT NULL,
                    valor REAL NOT NULL,
                    es_prevuelo INTEGER NOT NULL,
                    PRIMARY KEY (crew_id, indicador_id, timepoint)
                );

                CREATE TABLE IF NOT EXISTS local_measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crew_id TEXT NOT NULL,
                    indicador_id TEXT NOT NULL,
                    valor REAL NOT NULL,
                    unidad TEXT NOT NULL,
                    nivel_triage TEXT NOT NULL,
                    notas TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS astronaut_memory (
                    crew_id TEXT PRIMARY KEY,
                    alias_preferido TEXT NOT NULL,
                    rol TEXT NOT NULL,
                    notas_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crew_id TEXT NOT NULL,
                    emisor TEXT NOT NULL,
                    texto TEXT NOT NULL,
                    nivel_alerta TEXT NOT NULL,
                    modo_verificacion TEXT NOT NULL,
                    datos_citados_json TEXT,
                    acciones_json TEXT,
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS help_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hash TEXT NOT NULL,
                    crew_id_solicitante TEXT NOT NULL,
                    destinatario TEXT NOT NULL,
                    nivel TEXT NOT NULL,
                    motivo TEXT NOT NULL,
                    resumen_clinico TEXT NOT NULL,
                    protocolo_sugerido_id TEXT,
                    estado TEXT NOT NULL DEFAULT 'ACTIVA',
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS lis_config (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sensor_measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crew_id TEXT NOT NULL,
                    parametro_id TEXT NOT NULL,
                    valor REAL NOT NULL,
                    unidad TEXT NOT NULL,
                    nivel TEXT NOT NULL,
                    sincronizado_tierra INTEGER NOT NULL DEFAULT 0,
                    timestamp_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sensor_crew_ts
                    ON sensor_measurements (crew_id, timestamp_ms);
                CREATE INDEX IF NOT EXISTS idx_sensor_ts
                    ON sensor_measurements (timestamp_ms);

                CREATE TABLE IF NOT EXISTS telemetry_series (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crew_id TEXT NOT NULL,
                    parametro_id TEXT NOT NULL,
                    resolucion TEXT NOT NULL,
                    inicio_ms INTEGER NOT NULL,
                    fin_ms INTEGER NOT NULL,
                    min_val REAL NOT NULL,
                    max_val REAL NOT NULL,
                    media_val REAL NOT NULL,
                    n INTEGER NOT NULL,
                    UNIQUE(crew_id, parametro_id, resolucion, inicio_ms)
                );
                CREATE INDEX IF NOT EXISTS idx_series_lookup
                    ON telemetry_series (crew_id, parametro_id, resolucion, inicio_ms);

                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crew_id TEXT NOT NULL,
                    parametro_id TEXT NOT NULL,
                    inicio_ms INTEGER NOT NULL,
                    fin_ms INTEGER,
                    abierto INTEGER NOT NULL DEFAULT 1,
                    nivel_maximo TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_episodes_open
                    ON episodes (crew_id, parametro_id, abierto);

                CREATE TABLE IF NOT EXISTS emergency_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crew_id TEXT NOT NULL,
                    timestamp_ms INTEGER NOT NULL,
                    severidad TEXT NOT NULL,
                    detalle TEXT NOT NULL,
                    sincronizado_tierra INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS mission_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crew_id TEXT,
                    actor TEXT NOT NULL,
                    texto TEXT NOT NULL,
                    sincronizado_tierra INTEGER NOT NULL DEFAULT 0,
                    timestamp_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prioridad TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    payload_id INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    hash_previo TEXT,
                    estado TEXT NOT NULL DEFAULT 'pendiente',
                    creado_en_ms INTEGER NOT NULL,
                    intentos INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_sync_estado_prio
                    ON sync_queue (estado, prioridad, creado_en_ms);

                CREATE TABLE IF NOT EXISTS evaluaciones_salud_mental (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crew_id TEXT NOT NULL,
                    fecha TEXT NOT NULL,
                    timepoint TEXT NOT NULL,
                    horas_sueno REAL NOT NULL,
                    nivel_estres INTEGER NOT NULL,
                    animo INTEGER NOT NULL,
                    fatiga INTEGER NOT NULL,
                    aislamiento INTEGER NOT NULL,
                    pvt_latencia_ms REAL NOT NULL,
                    pvt_lapsus INTEGER NOT NULL,
                    nivel_triage TEXT NOT NULL,
                    notas TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gamificacion_misiones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crew_id TEXT NOT NULL,
                    fecha TEXT NOT NULL,
                    misiones_json TEXT NOT NULL,
                    score INTEGER NOT NULL DEFAULT 0,
                    racha_dias INTEGER NOT NULL DEFAULT 1,
                    insignias_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(crew_id, fecha)
                );
                """
            )

            # Sembrar indicadores y series de NASA OSDR OSD-575
            for ind in _osdr_cache.get("indicadores", []):
                ind_id = ind["id"]
                rango = ind.get("rangoReferencia") or {}
                cur.execute(
                    """
                    INSERT OR REPLACE INTO osdr_indicators
                    (id, nombre, sistema, unidad, rango_min, rango_max, fuente)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ind_id,
                        ind["nombre"],
                        ind["sistema"],
                        ind["unidad"],
                        rango.get("min"),
                        rango.get("max"),
                        ind.get("fuente", "NASA OSDR OSD-575"),
                    ),
                )

                serie_por_crew = ind.get("serie", {})
                for crew_id, puntos in serie_por_crew.items():
                    vals_pre: List[float] = []
                    for pt in puntos:
                        tp = pt["timepoint"]
                        val = float(pt["valor"])
                        es_pre = 1 if tp in PREFLIGHT_TIMEPOINTS else 0
                        if es_pre:
                            vals_pre.append(val)
                        cur.execute(
                            """
                            INSERT OR REPLACE INTO osdr_measurements
                            (crew_id, indicador_id, timepoint, valor, es_prevuelo)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (crew_id, ind_id, tp, val, es_pre),
                        )

                    # Precalcular línea base personal en memoria O(1)
                    media = sum(vals_pre) / len(vals_pre) if vals_pre else 0.0
                    varianza = (
                        sum((x - media) ** 2 for x in vals_pre) / len(vals_pre)
                        if vals_pre
                        else 0.0
                    )
                    sd = math.sqrt(varianza)
                    _baselines_cache.setdefault(crew_id, {})[ind_id] = {
                        "crewId": crew_id,
                        "indicadorId": ind_id,
                        "mediaPreVuelo": round(media, 1),
                        "desviacionPreVuelo": round(sd, 2),
                        "puntosPreVuelo": vals_pre,
                    }

            # Sembrar perfiles de memoria por tripulante (C001–C004)
            now_iso = datetime.now(timezone.utc).isoformat()
            perfiles_iniciales = {
                "C001": (
                    "Comandante (C001)",
                    "Comandante · Oficial Médico (CMO)",
                    [
                        {
                            "id": "seed-c001-1",
                            "texto": "Oficial Médico de Tripulación (CMO) responsable de soporte vital.",
                            "categoria": "preferencia",
                            "fecha": now_iso,
                        },
                        {
                            "id": "seed-c001-2",
                            "texto": "Glucosa R+1 en 100 mg/dL (+22.0% sobre su base pre-vuelo de 82.0 mg/dL).",
                            "categoria": "observacion",
                            "fecha": now_iso,
                        },
                    ],
                ),
                "C002": (
                    "Piloto (C002)",
                    "Piloto",
                    [
                        {
                            "id": "seed-c002-1",
                            "texto": "Antecedente de glucosa pre-vuelo L-92 baja (36 mg/dL) en registro OSD-575.",
                            "categoria": "antecedente",
                            "fecha": now_iso,
                        }
                    ],
                ),
                "C003": (
                    "Especialista (C003)",
                    "Especialista de Misión",
                    [
                        {
                            "id": "seed-c003-1",
                            "texto": "Glucosa en R+1 de 103 mg/dL (+44.4% respecto a su base pre-vuelo de 71.3 mg/dL).",
                            "categoria": "observacion",
                            "fecha": now_iso,
                        },
                        {
                            "id": "seed-c003-2",
                            "texto": "Prefiere reportes directos con comparación frente a su media pre-vuelo.",
                            "categoria": "preferencia",
                            "fecha": now_iso,
                        },
                    ],
                ),
                "C004": (
                    "Ingeniero (C004)",
                    "Ingeniero de Vuelo",
                    [
                        {
                            "id": "seed-c004-1",
                            "texto": "Glucosa L-3 en 44 mg/dL en serie pre-vuelo OSD-575; vigilar energía en EVA.",
                            "categoria": "antecedente",
                            "fecha": now_iso,
                        }
                    ],
                ),
            }

            for c_id, (alias, rol, notas) in perfiles_iniciales.items():
                cur.execute(
                    "SELECT crew_id FROM astronaut_memory WHERE crew_id = ?",
                    (c_id,),
                )
                if not cur.fetchone():
                    cur.execute(
                        """
                        INSERT INTO astronaut_memory
                        (crew_id, alias_preferido, rol, notas_json, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            c_id,
                            alias,
                            rol,
                            json.dumps(notas, ensure_ascii=False),
                            now_iso,
                        ),
                    )

            conn.commit()
            _inicializado = True
        finally:
            conn.close()


def get_osdr_dataset() -> Dict[str, Any]:
    if _osdr_cache is None:
        init_db()
    return _osdr_cache or {}


def get_cabina_dataset() -> Dict[str, Any]:
    if _cabina_cache is None:
        init_db()
    return _cabina_cache or {}


def get_guias_dataset() -> Dict[str, Any]:
    if _guias_cache is None:
        init_db()
    return _guias_cache or {}


def get_protocolos_dataset() -> Dict[str, Any]:
    if _protocolos_cache is None:
        init_db()
    return _protocolos_cache or {}


def get_alsp_dataset() -> Dict[str, Any]:
    if _alsp_cache is None:
        init_db()
    return _alsp_cache or {}


def get_tripulacion_dataset() -> Dict[str, Any]:
    if _tripulacion_cache is None:
        init_db()
    return _tripulacion_cache or {"tripulantes": {}}


def get_protocolos_disparadores_dataset() -> List[Dict[str, Any]]:
    if _protocolos_disp_cache is None:
        init_db()
    return _protocolos_disp_cache or []


def sexo_de(crew_id: str) -> Optional[str]:
    """Devuelve el sexo biológico asignado para la demo ('M'|'F') o None."""
    trip = get_tripulacion_dataset().get("tripulantes", {})
    val = trip.get(crew_id)
    return val if val in ("M", "F") else None


def baseline_prevuelo_opcional(crew_id: str, indicador_id: str) -> Optional[float]:
    """Devuelve la media pre-vuelo si existe para el indicador OSDR; None si no aplica."""
    if not _baselines_cache:
        init_db()
    entry = _baselines_cache.get(crew_id, {}).get(indicador_id)
    if entry and entry.get("puntosPreVuelo"):
        return float(entry["mediaPreVuelo"])
    return None


def get_baseline(crew_id: str, indicador_id: str) -> Dict[str, Any]:
    if not _baselines_cache:
        init_db()
    return _baselines_cache.get(crew_id, {}).get(
        indicador_id,
        {
            "crewId": crew_id,
            "indicadorId": indicador_id,
            "mediaPreVuelo": 0.0,
            "desviacionPreVuelo": 0.0,
            "puntosPreVuelo": [],
        },
    )


def get_valor_osdr(
    crew_id: str, indicador_id: str, timepoint: str
) -> Optional[float]:
    dataset = get_osdr_dataset()
    for ind in dataset.get("indicadores", []):
        if ind["id"] == indicador_id:
            for pt in ind.get("serie", {}).get(crew_id, []):
                if pt["timepoint"] == timepoint:
                    return float(pt["valor"])
    return None


def get_indicador_osdr(indicador_id: str) -> Optional[Dict[str, Any]]:
    dataset = get_osdr_dataset()
    for ind in dataset.get("indicadores", []):
        if ind["id"] == indicador_id:
            return ind
    return None


def obtener_memoria_astronauta(crew_id: str) -> Dict[str, Any]:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM astronaut_memory WHERE crew_id = ?", (crew_id,)
            ).fetchone()
            if not row:
                return {
                    "crewId": crew_id,
                    "aliasPreferido": crew_id,
                    "rol": "Tripulante",
                    "notasRecordadas": [],
                    "ultimaInteraccion": datetime.now(timezone.utc).isoformat(),
                }
            return {
                "crewId": row["crew_id"],
                "aliasPreferido": row["alias_preferido"],
                "rol": row["rol"],
                "notasRecordadas": json.loads(row["notas_json"] or "[]"),
                "ultimaInteraccion": row["updated_at"],
            }
        finally:
            conn.close()


def recordar_dato_astronauta(
    crew_id: str, texto: str, categoria: str = "observacion"
) -> Dict[str, Any]:
    perfil = obtener_memoria_astronauta(crew_id)
    notas: List[Dict[str, Any]] = perfil.get("notasRecordadas", [])
    now_iso = datetime.now(timezone.utc).isoformat()
    nueva_nota = {
        "id": f"mem-{int(datetime.now().timestamp() * 1000)}",
        "texto": texto.strip(),
        "categoria": categoria,
        "fecha": now_iso,
    }
    notas.insert(0, nueva_nota)
    notas = notas[:25]
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE astronaut_memory
                SET notas_json = ?, updated_at = ?
                WHERE crew_id = ?
                """,
                (json.dumps(notas, ensure_ascii=False), now_iso, crew_id),
            )
            conn.commit()
        finally:
            conn.close()
    return obtener_memoria_astronauta(crew_id)


def actualizar_alias_astronauta(crew_id: str, nuevo_alias: str) -> Dict[str, Any]:
    init_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE astronaut_memory
                SET alias_preferido = ?, updated_at = ?
                WHERE crew_id = ?
                """,
                (nuevo_alias.strip(), now_iso, crew_id),
            )
            conn.commit()
        finally:
            conn.close()
    return obtener_memoria_astronauta(crew_id)


def guardar_medicion_local(
    crew_id: str,
    indicador_id: str,
    valor: float,
    unidad: str,
    nivel_triage: str,
    notas: str = "",
) -> Dict[str, Any]:
    init_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO local_measurements
                (crew_id, indicador_id, valor, unidad, nivel_triage, notas, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (crew_id, indicador_id, valor, unidad, nivel_triage, notas, now_iso),
            )
            conn.commit()
            return {
                "id": cur.lastrowid,
                "crewId": crew_id,
                "indicadorId": indicador_id,
                "valor": valor,
                "unidad": unidad,
                "nivel": nivel_triage,
                "notas": notas,
                "createdAt": now_iso,
            }
        finally:
            conn.close()


def listar_mediciones_locales(
    crew_id: Optional[str] = None, limit: int = 20
) -> List[Dict[str, Any]]:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            if crew_id:
                rows = conn.execute(
                    """
                    SELECT * FROM local_measurements
                    WHERE crew_id = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (crew_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM local_measurements ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "id": r["id"],
                    "crewId": r["crew_id"],
                    "indicadorId": r["indicador_id"],
                    "valor": r["valor"],
                    "unidad": r["unidad"],
                    "nivel": r["nivel_triage"],
                    "notas": r["notas"],
                    "createdAt": r["created_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()


def crear_solicitud_ayuda(
    crew_id_solicitante: str,
    destinatario: str,
    nivel: str,
    motivo: str,
    resumen_clinico: str,
    protocolo_sugerido_id: Optional[str] = None,
) -> Dict[str, Any]:
    init_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(
        f"{crew_id_solicitante}:{motivo}:{now_iso}".encode("utf-8")
    ).hexdigest()[:8].upper()
    code_hash = f"SOS-{digest}"

    with _db_lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO help_requests
                (hash, crew_id_solicitante, destinatario, nivel, motivo, resumen_clinico, protocolo_sugerido_id, estado, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVA', ?)
                """,
                (
                    code_hash,
                    crew_id_solicitante,
                    destinatario,
                    nivel,
                    motivo,
                    resumen_clinico,
                    protocolo_sugerido_id,
                    now_iso,
                ),
            )
            conn.commit()
            return {
                "id": cur.lastrowid,
                "hash": code_hash,
                "crewIdSolicitante": crew_id_solicitante,
                "destinatario": destinatario,
                "nivel": nivel,
                "motivo": motivo,
                "resumenClinico": resumen_clinico,
                "protocoloSugeridoId": protocolo_sugerido_id,
                "estado": "ACTIVA",
                "timestamp": now_iso,
            }
        finally:
            conn.close()


def listar_solicitudes_ayuda(solo_activas: bool = True) -> List[Dict[str, Any]]:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            if solo_activas:
                rows = conn.execute(
                    "SELECT * FROM help_requests WHERE estado = 'ACTIVA' ORDER BY id DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM help_requests ORDER BY id DESC LIMIT 30"
                ).fetchall()
            return [
                {
                    "id": r["id"],
                    "hash": r["hash"],
                    "crewIdSolicitante": r["crew_id_solicitante"],
                    "destinatario": r["destinatario"],
                    "nivel": r["nivel"],
                    "motivo": r["motivo"],
                    "resumenClinico": r["resumen_clinico"],
                    "protocoloSugeridoId": r["protocolo_sugerido_id"],
                    "estado": r["estado"],
                    "timestamp": r["timestamp"],
                }
                for r in rows
            ]
        finally:
            conn.close()


def atender_solicitud_ayuda(req_id: int) -> None:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE help_requests SET estado = 'ATENDIDA' WHERE id = ?",
                (req_id,),
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Configuración persistente de L.I.S. y conversación (app nativa de escritorio)
# ---------------------------------------------------------------------------

CONFIG_LIS_DEFECTO: Dict[str, Any] = {
    "nombreAgente": "L.I.S.",
    "idioma": "en",
    "mostrarAsistente": True,
    "temaVisual": "oscuro",
    "escalaUI": "1.0",
    "animacion3D": True,
    "mostrarAvisosEmergentes": True,
    "duracionMicrofonoSeg": 4.5,
    "vozId": "jarvis-clone-latam",
    "velocidadVoz": 1.04,
    "vozActiva": True,
    "personalidad": "jarvis-cordial",
    "motorLLM": "cloud-api-auto",
    "llmEndpointLocal": "http://127.0.0.1:11434",
    "llmModeloLocal": "qwen2.5:3b",
    "cloudApiKey": "",
    "cloudProvider": "nvidia",
    "cloudModeloAuto": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "permitirNavegacionAutonoma": True,
    "permitirControlParametros": True,
    "autoEscalarAyudaCritica": True,
    "alarmaEmergenciaSonora": True,
    "alarmaEmergenciaVolumen": 0.70,
    "alarmaEmergenciaIntervaloMs": 2800,
    "alarmaEmergenciaTono": "doble-suave",
    "alarmaEmergenciaIncluirSbar": True,
    "sonidoMonitorOverview": True,
    "volumenMonitorOverview": 0.35,
    "crewId": "C003",
    "timepoint": "R+1",
    "entorno": "nave",
    "modoTelemetria": "simulado",
    "enlaceTierraOnline": True,
    "avisosRevisados": [],
}


def obtener_config_lis() -> Dict[str, Any]:
    init_db()
    cfg = dict(CONFIG_LIS_DEFECTO)
    with _db_lock:
        conn = get_connection()
        try:
            for row in conn.execute("SELECT key, value_json FROM lis_config"):
                try:
                    cfg[row["key"]] = json.loads(row["value_json"])
                except Exception:
                    pass
        finally:
            conn.close()
    return cfg


def guardar_config_lis(cambios: Dict[str, Any]) -> Dict[str, Any]:
    init_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection()
        try:
            for k, v in cambios.items():
                conn.execute(
                    "INSERT OR REPLACE INTO lis_config (key, value_json, updated_at) VALUES (?, ?, ?)",
                    (k, json.dumps(v, ensure_ascii=False), now_iso),
                )
            conn.commit()
        finally:
            conn.close()
    return obtener_config_lis()


def restaurar_config_lis() -> Dict[str, Any]:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM lis_config")
            conn.commit()
        finally:
            conn.close()
    return obtener_config_lis()


def limpiar_memoria_astronauta(crew_id: str) -> Dict[str, Any]:
    init_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE astronaut_memory SET notas_json = '[]', updated_at = ? WHERE crew_id = ?",
                (now_iso, crew_id),
            )
            conn.commit()
        finally:
            conn.close()
    return obtener_memoria_astronauta(crew_id)


def limpiar_historial_chat(crew_id: str) -> int:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                "DELETE FROM chat_messages WHERE crew_id = ?", (crew_id,)
            )
            conn.commit()
            return int(cur.rowcount or 0)
        finally:
            conn.close()


def guardar_mensaje_chat(mensaje: Dict[str, Any]) -> None:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO chat_messages
                (crew_id, emisor, texto, nivel_alerta, modo_verificacion, datos_citados_json, acciones_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mensaje.get("crewId", "C003"),
                    mensaje.get("emisor", "asistente"),
                    mensaje.get("texto", ""),
                    mensaje.get("nivelAlerta", "NOMINAL"),
                    mensaje.get("modoVerificacion", "DETERMINISTA_ESTRICTO"),
                    json.dumps(mensaje.get("datosCitados") or [], ensure_ascii=False),
                    json.dumps(mensaje.get("accionesSugeridas") or [], ensure_ascii=False),
                    mensaje.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def obtener_historial_chat(crew_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE crew_id = ? ORDER BY id DESC LIMIT ?",
                (crew_id, limit),
            ).fetchall()
        finally:
            conn.close()
    salida = []
    for r in reversed(rows):
        salida.append(
            {
                "crewId": r["crew_id"],
                "emisor": r["emisor"],
                "texto": r["texto"],
                "nivelAlerta": r["nivel_alerta"],
                "modoVerificacion": r["modo_verificacion"],
                "datosCitados": json.loads(r["datos_citados_json"] or "[]"),
                "accionesSugeridas": json.loads(r["acciones_json"] or "[]"),
                "timestamp": r["timestamp"],
            }
        )
    return salida



# ===========================================================================
# Repositorios Back 2 · Telemetría en vivo, series, episodios y cola sync
# ===========================================================================

_ORDEN_NIVEL = {"NOMINAL": 0, "ATENCION": 1, "CRITICO": 2}
_MS_POR_MINUTO = 60_000
_MS_POR_HORA = 3_600_000
_MS_POR_DIA = 86_400_000


def _ahora_ms() -> int:
    return int(time.time() * 1000)


def _inicio_ventana(ts_ms: int, resolucion: str) -> int:
    base = _MS_POR_MINUTO if resolucion == "1min" else _MS_POR_HORA
    return (int(ts_ms) // base) * base


def _fin_ventana(ts_ms: int, resolucion: str) -> int:
    base = _MS_POR_MINUTO if resolucion == "1min" else _MS_POR_HORA
    return _inicio_ventana(ts_ms, resolucion) + base


def guardar_frame_bd(frame: Dict[str, Any]) -> Dict[str, Any]:
    """Persiste todas las lecturas de un RealtimeTelemetryFrame en sensor_measurements."""
    init_db()
    lecturas = frame.get("lecturas") or {}
    if not lecturas:
        return {"ok": True, "guardadas": 0}
    crew_id = str(frame.get("crewId", "C001"))
    ts_ms = int(frame.get("timestamp") or _ahora_ms())
    filas: List[Tuple[Any, ...]] = []
    for param_id, lec in lecturas.items():
        filas.append(
            (
                crew_id,
                param_id,
                float(lec.get("valor", 0.0)),
                str(lec.get("unidad", "")),
                str(lec.get("nivel", "NOMINAL")),
                0,
                ts_ms,
            )
        )
    try:
        with _db_lock:
            conn = get_connection()
            try:
                conn.executemany(
                    """
                    INSERT INTO sensor_measurements
                    (crew_id, parametro_id, valor, unidad, nivel, sincronizado_tierra, timestamp_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    filas,
                )
                conn.commit()
            finally:
                conn.close()
        return {"ok": True, "guardadas": len(filas)}
    except Exception as exc:
        return {"ok": False, "guardadas": 0, "codigo": "E-DB-001", "motivo": str(exc)}


def guardar_medicion_sensor(
    crew_id: str,
    parametro_id: str,
    valor: float,
    unidad: str,
    nivel: str,
    timestamp_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Persiste una medición manual en sensor_measurements sin bloquear la UI."""
    init_db()
    ts_ms = int(timestamp_ms if timestamp_ms is not None else _ahora_ms())
    try:
        with _db_lock:
            conn = get_connection()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO sensor_measurements
                    (crew_id, parametro_id, valor, unidad, nivel, sincronizado_tierra, timestamp_ms)
                    VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (crew_id, parametro_id, float(valor), unidad, nivel, ts_ms),
                )
                conn.commit()
                return {"ok": True, "guardadas": 1, "id": cur.lastrowid, "timestamp": ts_ms}
            finally:
                conn.close()
    except Exception as exc:
        return {"ok": False, "guardadas": 0, "codigo": "E-DB-001", "motivo": str(exc)}


def ventana_reciente(crew_id: str, minutos: int = 15) -> List[Dict[str, Any]]:
    init_db()
    corte = _ahora_ms() - int(minutos) * _MS_POR_MINUTO
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM sensor_measurements
                WHERE crew_id = ? AND timestamp_ms >= ?
                ORDER BY timestamp_ms ASC
                """,
                (crew_id, corte),
            ).fetchall()
        finally:
            conn.close()
    return [
        {
            "id": r["id"],
            "crewId": r["crew_id"],
            "parametroId": r["parametro_id"],
            "valor": r["valor"],
            "unidad": r["unidad"],
            "nivel": r["nivel"],
            "sincronizadoTierra": bool(r["sincronizado_tierra"]),
            "timestamp": r["timestamp_ms"],
        }
        for r in rows
    ]


def pendientes_sincronizar() -> List[Dict[str, Any]]:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM sensor_measurements WHERE sincronizado_tierra = 0 ORDER BY timestamp_ms ASC"
            ).fetchall()
        finally:
            conn.close()
    return [
        {
            "id": r["id"],
            "crewId": r["crew_id"],
            "parametroId": r["parametro_id"],
            "valor": r["valor"],
            "unidad": r["unidad"],
            "nivel": r["nivel"],
            "sincronizadoTierra": False,
            "timestamp": r["timestamp_ms"],
        }
        for r in rows
    ]


def marcar_sincronizado(ids: List[int]) -> int:
    if not ids:
        return 0
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            conn.executemany(
                "UPDATE sensor_measurements SET sincronizado_tierra = 1 WHERE id = ?",
                [(int(i),) for i in ids],
            )
            conn.commit()
            return len(ids)
        finally:
            conn.close()


def marcar_sincronizado_por_frame(crew_id: str, timestamp_ms: int) -> int:
    """Reconcilia el ACK de Tierra con las mediciones de un frame específico."""
    init_db()
    try:
        with _db_lock:
            conn = get_connection()
            try:
                cur = conn.execute(
                    """
                    UPDATE sensor_measurements
                    SET sincronizado_tierra = 1
                    WHERE crew_id = ? AND timestamp_ms = ? AND sincronizado_tierra = 0
                    """,
                    (crew_id, int(timestamp_ms)),
                )
                conn.commit()
                return int(cur.rowcount or 0)
            finally:
                conn.close()
    except Exception:
        return 0


def podar_ventana(dias: int = 30) -> int:
    init_db()
    corte = _ahora_ms() - int(dias) * _MS_POR_DIA
    with _db_lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                "DELETE FROM sensor_measurements WHERE timestamp_ms < ?", (corte,)
            )
            conn.commit()
            return int(cur.rowcount or 0)
        finally:
            conn.close()


def agregar_y_persistir_series(frame: Dict[str, Any]) -> int:
    """Agrega un frame a las resoluciones 1min y 1h y lo persiste (upsert)."""
    init_db()
    lecturas = frame.get("lecturas") or {}
    if not lecturas:
        return 0
    crew_id = str(frame.get("crewId", "C001"))
    ts_ms = int(frame.get("timestamp") or _ahora_ms())
    guardadas = 0
    try:
        with _db_lock:
            conn = get_connection()
            try:
                for param_id, lec in lecturas.items():
                    val = float(lec.get("valor", 0.0))
                    for res in ("1min", "1h"):
                        ini = _inicio_ventana(ts_ms, res)
                        fin = _fin_ventana(ts_ms, res)
                        row = conn.execute(
                            """
                            SELECT id, min_val, max_val, media_val, n
                            FROM telemetry_series
                            WHERE crew_id = ? AND parametro_id = ? AND resolucion = ? AND inicio_ms = ?
                            """,
                            (crew_id, param_id, res, ini),
                        ).fetchone()
                        if row is None:
                            conn.execute(
                                """
                                INSERT INTO telemetry_series
                                (crew_id, parametro_id, resolucion, inicio_ms, fin_ms, min_val, max_val, media_val, n)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                                """,
                                (crew_id, param_id, res, ini, fin, val, val, val),
                            )
                        else:
                            n_old = int(row["n"])
                            n_new = n_old + 1
                            media_new = (float(row["media_val"]) * n_old + val) / n_new
                            min_new = min(float(row["min_val"]), val)
                            max_new = max(float(row["max_val"]), val)
                            conn.execute(
                                """
                                UPDATE telemetry_series
                                SET min_val = ?, max_val = ?, media_val = ?, n = ?
                                WHERE id = ?
                                """,
                                (min_new, max_new, media_new, n_new, row["id"]),
                            )
                        guardadas += 1
                conn.commit()
            finally:
                conn.close()
    except Exception:
        return 0
    return guardadas


def listar_series(
    crew_id: str,
    parametro_id: Optional[str] = None,
    resolucion: str = "1h",
    desde: Optional[int] = None,
    hasta: Optional[int] = None,
) -> List[Dict[str, Any]]:
    init_db()
    res = resolucion if resolucion in ("1min", "1h") else "1h"
    sql = "SELECT * FROM telemetry_series WHERE crew_id = ? AND resolucion = ?"
    params: List[Any] = [crew_id, res]
    if parametro_id:
        sql += " AND parametro_id = ?"
        params.append(parametro_id)
    if desde is not None:
        sql += " AND inicio_ms >= ?"
        params.append(int(desde))
    if hasta is not None:
        sql += " AND fin_ms <= ?"
        params.append(int(hasta))
    sql += " ORDER BY inicio_ms ASC"
    try:
        with _db_lock:
            conn = get_connection()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        return [
            {
                "id": r["id"],
                "crewId": r["crew_id"],
                "parametroId": r["parametro_id"],
                "resolucion": r["resolucion"],
                "inicio": r["inicio_ms"],
                "fin": r["fin_ms"],
                "min": round(float(r["min_val"]), 3),
                "max": round(float(r["max_val"]), 3),
                "media": round(float(r["media_val"]), 3),
                "n": int(r["n"]),
            }
            for r in rows
        ]
    except Exception:
        return []


def podar_series(dias: int = 30) -> int:
    init_db()
    corte = _ahora_ms() - int(dias) * _MS_POR_DIA
    with _db_lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                "DELETE FROM telemetry_series WHERE inicio_ms < ?", (corte,)
            )
            conn.commit()
            return int(cur.rowcount or 0)
        finally:
            conn.close()


def _row_to_episode(r: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "crewId": r["crew_id"],
        "parametroId": r["parametro_id"],
        "inicio": r["inicio_ms"],
        "fin": r["fin_ms"],
        "abierto": bool(r["abierto"]),
        "nivelMaximo": r["nivel_maximo"],
    }


def episodio_abierto(crew_id: str, parametro_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT * FROM episodes
                WHERE crew_id = ? AND parametro_id = ? AND abierto = 1
                ORDER BY id DESC LIMIT 1
                """,
                (crew_id, parametro_id),
            ).fetchone()
        finally:
            conn.close()
    return _row_to_episode(row) if row is not None else None


def abrir_episodio(
    crew_id: str,
    parametro_id: str,
    nivel: str,
    inicio_ms: Optional[int] = None,
) -> int:
    init_db()
    ts_ms = int(inicio_ms if inicio_ms is not None else _ahora_ms())
    with _db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT id, nivel_maximo FROM episodes
                WHERE crew_id = ? AND parametro_id = ? AND abierto = 1
                ORDER BY id DESC LIMIT 1
                """,
                (crew_id, parametro_id),
            ).fetchone()
            if row is not None:
                actual_rank = _ORDEN_NIVEL.get(str(row["nivel_maximo"]), 0)
                nuevo_rank = _ORDEN_NIVEL.get(nivel, 0)
                if nuevo_rank > actual_rank:
                    conn.execute(
                        "UPDATE episodes SET nivel_maximo = ? WHERE id = ?",
                        (nivel, row["id"]),
                    )
                    conn.commit()
                return int(row["id"])
            cur = conn.execute(
                """
                INSERT INTO episodes (crew_id, parametro_id, inicio_ms, fin_ms, abierto, nivel_maximo)
                VALUES (?, ?, ?, NULL, 1, ?)
                """,
                (crew_id, parametro_id, ts_ms, nivel),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def cerrar_episodio(
    crew_id: str,
    parametro_id: str,
    fin_ms: Optional[int] = None,
) -> Optional[int]:
    init_db()
    ts_ms = int(fin_ms if fin_ms is not None else _ahora_ms())
    with _db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT id FROM episodes
                WHERE crew_id = ? AND parametro_id = ? AND abierto = 1
                ORDER BY id DESC LIMIT 1
                """,
                (crew_id, parametro_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE episodes SET fin_ms = ?, abierto = 0 WHERE id = ?",
                (ts_ms, row["id"]),
            )
            conn.commit()
            return int(row["id"])
        finally:
            conn.close()


def listar_episodios(
    crew_id: Optional[str] = None,
    solo_abiertos: bool = False,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    init_db()
    sql = "SELECT * FROM episodes WHERE 1=1"
    params: List[Any] = []
    if crew_id:
        sql += " AND crew_id = ?"
        params.append(crew_id)
    if solo_abiertos:
        sql += " AND abierto = 1"
    sql += " ORDER BY abierto DESC, inicio_ms DESC LIMIT ?"
    params.append(int(limit))
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    return [_row_to_episode(r) for r in rows]


def registrar_evento_emergencia(
    crew_id: str,
    timestamp_ms: int,
    severidad: str,
    detalle: str,
) -> int:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO emergency_events (crew_id, timestamp_ms, severidad, detalle, sincronizado_tierra)
                VALUES (?, ?, ?, ?, 0)
                """,
                (crew_id, int(timestamp_ms), severidad, detalle),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def listar_eventos_emergencia(
    crew_id: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    init_db()
    sql = "SELECT * FROM emergency_events"
    params: List[Any] = []
    if crew_id:
        sql += " WHERE crew_id = ?"
        params.append(crew_id)
    sql += " ORDER BY timestamp_ms DESC, id DESC LIMIT ?"
    params.append(int(limit))
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    return [
        {
            "id": r["id"],
            "crewId": r["crew_id"],
            "timestamp": r["timestamp_ms"],
            "severidad": r["severidad"],
            "detalle": r["detalle"],
            "sincronizadoTierra": bool(r["sincronizado_tierra"]),
        }
        for r in rows
    ]


def registrar_bitacora(
    texto: str,
    actor: str = "TRIPULACION",
    crew_id: Optional[str] = None,
    timestamp_ms: Optional[int] = None,
) -> int:
    init_db()
    ts_ms = int(timestamp_ms if timestamp_ms is not None else _ahora_ms())
    with _db_lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO mission_log (crew_id, actor, texto, sincronizado_tierra, timestamp_ms)
                VALUES (?, ?, ?, 0, ?)
                """,
                (crew_id, actor, texto, ts_ms),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def listar_bitacora(
    limit: int = 50, crew_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    init_db()
    sql = "SELECT * FROM mission_log"
    params: List[Any] = []
    if crew_id:
        sql += " WHERE crew_id = ?"
        params.append(crew_id)
    sql += " ORDER BY timestamp_ms DESC, id DESC LIMIT ?"
    params.append(int(limit))
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    return [
        {
            "id": r["id"],
            "crewId": r["crew_id"],
            "actor": r["actor"],
            "texto": r["texto"],
            "sincronizadoTierra": bool(r["sincronizado_tierra"]),
            "timestamp": r["timestamp_ms"],
        }
        for r in rows
    ]


def marcar_evento_sincronizado(evt_id: int) -> None:
    """Marca un evento de emergencia como confirmado en Tierra."""
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE emergency_events SET sincronizado_tierra = 1 WHERE id = ?",
                (int(evt_id),),
            )
            conn.commit()
        finally:
            conn.close()


def marcar_bitacora_sincronizada(bitacora_id: int) -> None:
    """Marca una entrada de bitácora como confirmada en Tierra."""
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE mission_log SET sincronizado_tierra = 1 WHERE id = ?",
                (int(bitacora_id),),
            )
            conn.commit()
        finally:
            conn.close()


def obtener_ultimo_hash_confirmado_bd() -> Optional[str]:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT hash FROM sync_queue
                WHERE estado != 'pendiente'
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT hash FROM sync_queue ORDER BY id DESC LIMIT 1"
                ).fetchone()
        finally:
            conn.close()
    return str(row["hash"]) if row is not None else None


def encolar_lote_bd(
    prioridad: str,
    tipo: str,
    payload_id: int,
    payload_json: str,
    hash_val: str,
    hash_previo: Optional[str],
    creado_en_ms: Optional[int] = None,
) -> int:
    init_db()
    ts_ms = int(creado_en_ms if creado_en_ms is not None else _ahora_ms())
    with _db_lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO sync_queue
                (prioridad, tipo, payload_id, payload_json, hash, hash_previo, estado, creado_en_ms, intentos)
                VALUES (?, ?, ?, ?, ?, ?, 'pendiente', ?, 0)
                """,
                (prioridad, tipo, int(payload_id), payload_json, hash_val, hash_previo, ts_ms),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def tomar_siguiente_lote_bd() -> Optional[Dict[str, Any]]:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            for prio in ("A", "B", "C", "D"):
                row = conn.execute(
                    """
                    SELECT * FROM sync_queue
                    WHERE prioridad = ? AND estado = 'pendiente'
                    ORDER BY creado_en_ms ASC, id ASC
                    LIMIT 1
                    """,
                    (prio,),
                ).fetchone()
                if row is not None:
                    try:
                        payload = json.loads(row["payload_json"] or "{}")
                    except Exception:
                        payload = {}
                    return {
                        "id": int(row["id"]),
                        "prioridad": row["prioridad"],
                        "tipo": row["tipo"],
                        "payloadId": int(row["payload_id"]),
                        "payload": payload,
                        "hash": row["hash"],
                        "hashPrevio": row["hash_previo"],
                        "creadoEn": int(row["creado_en_ms"]),
                        "intentos": int(row["intentos"]),
                        "estado": row["estado"],
                    }
        finally:
            conn.close()
    return None


def marcar_lote_enviado_bd(lote_id: int) -> None:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE sync_queue SET estado = 'enviado' WHERE id = ?", (int(lote_id),)
            )
            conn.commit()
        finally:
            conn.close()


def marcar_lote_rechazado_bd(lote_id: int) -> None:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE sync_queue SET estado = 'rechazado', intentos = intentos + 1 WHERE id = ?",
                (int(lote_id),),
            )
            conn.commit()
        finally:
            conn.close()


def reintentar_rechazados_bd() -> int:
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE sync_queue SET estado = 'pendiente' WHERE estado = 'rechazado' AND intentos < 3"
            )
            conn.commit()
            return int(cur.rowcount or 0)
        finally:
            conn.close()


def stats_cola_bd() -> Dict[str, Any]:
    init_db()
    por_prio = {"A": 0, "B": 0, "C": 0, "D": 0}
    mas_antigua: Optional[int] = None
    total_enviados = 0
    ultimo_hash: Optional[str] = None
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT prioridad, creado_en_ms FROM sync_queue WHERE estado = 'pendiente'"
            ).fetchall()
            for r in rows:
                p = str(r["prioridad"])
                if p in por_prio:
                    por_prio[p] += 1
                c = int(r["creado_en_ms"])
                if mas_antigua is None or c < mas_antigua:
                    mas_antigua = c
            row_env = conn.execute(
                "SELECT COUNT(*) AS n FROM sync_queue WHERE estado = 'enviado'"
            ).fetchone()
            total_enviados = int(row_env["n"]) if row_env else 0
            row_hash = conn.execute(
                "SELECT hash FROM sync_queue ORDER BY id DESC LIMIT 1"
            ).fetchone()
            ultimo_hash = str(row_hash["hash"]) if row_hash else None
        finally:
            conn.close()
    return {
        "pendientes": sum(por_prio.values()),
        "enviados": total_enviados,
        "porPrioridad": por_prio,
        "masAntigua": mas_antigua,
        "ultimoHash": ultimo_hash,
    }


def listar_cola_sync_bd(
    limit: int = 50, estado: Optional[str] = None
) -> List[Dict[str, Any]]:
    init_db()
    sql = "SELECT * FROM sync_queue"
    params: List[Any] = []
    if estado:
        sql += " WHERE estado = ?"
        params.append(estado)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    return [
        {
            "id": int(r["id"]),
            "prioridad": r["prioridad"],
            "tipo": r["tipo"],
            "payloadId": int(r["payload_id"]),
            "hash": r["hash"],
            "hashPrevio": r["hash_previo"],
            "estado": r["estado"],
            "creadoEn": int(r["creado_en_ms"]),
            "intentos": int(r["intentos"]),
        }
        for r in rows
    ]


def exportar_respaldo_completo(crew_id: Optional[str] = None) -> Dict[str, Any]:
    """Exporta el estado local completo listo para respaldo portátil JSON."""
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            meds_sql = "SELECT * FROM sensor_measurements"
            meds_p: List[Any] = []
            if crew_id:
                meds_sql += " WHERE crew_id = ?"
                meds_p.append(crew_id)
            meds_sql += " ORDER BY timestamp_ms ASC"
            meds = [dict(r) for r in conn.execute(meds_sql, meds_p).fetchall()]

            locales = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM local_measurements"
                    + (" WHERE crew_id = ?" if crew_id else "")
                    + " ORDER BY id ASC",
                    ([crew_id] if crew_id else []),
                ).fetchall()
            ]
            series = listar_series(crew_id or "C001") if crew_id else [
                dict(r) for r in conn.execute("SELECT * FROM telemetry_series ORDER BY inicio_ms ASC").fetchall()
            ]
            episodios = listar_episodios(crew_id=crew_id, limit=500)
            eventos = listar_eventos_emergencia(crew_id=crew_id, limit=500)
            bitacora = listar_bitacora(limit=500)
            salud_mental = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM evaluaciones_salud_mental"
                    + (" WHERE crew_id = ?" if crew_id else "")
                    + " ORDER BY id ASC",
                    ([crew_id] if crew_id else []),
                ).fetchall()
            ]
        finally:
            conn.close()
    return {
        "version": 1,
        "exportadoEn": _ahora_ms(),
        "tripulante": crew_id,
        "mediciones": meds,
        "medicionesLocales": locales,
        "series": series,
        "episodios": episodios,
        "eventos": eventos,
        "bitacora": bitacora,
        "evaluacionesMentales": salud_mental,
    }


# =====================================================================
# SALUD MENTAL, CONDUCTA (NASA BHP) Y GAMIFICACIÓN DE MISIÓN
# =====================================================================

MISIONES_DEFECTO: List[Dict[str, Any]] = [
    {"id": "pvt", "titulo": "Test de Reflejos PVT-B", "puntos": 25, "completada": False},
    {"id": "ejercicio", "titulo": "Ejercicio Resistivo / Cardio ARED", "puntos": 30, "completada": False},
    {"id": "hidratacion", "titulo": "Registro de Hidratación 0G (2.5L)", "puntos": 15, "completada": False},
    {"id": "descompresion", "titulo": "Descompresión Cognitiva (Box Breathing)", "puntos": 20, "completada": False},
    {"id": "luz_circadiana", "titulo": "Ajuste de Luz Circadiana en Litera", "puntos": 10, "completada": False},
]

INSIGNIAS_DEFECTO: List[Dict[str, Any]] = [
    {"id": "mercurio", "nombre": "Reflejos de Mercurio", "desc": "PVT-B < 300 ms sin lapsus [POR VALIDAR]", "desbloqueada": False},
    {"id": "centinela", "nombre": "Centinela Circadiano", "desc": "Sueño nominal > 6.5h [POR VALIDAR]", "desbloqueada": True},
    {"id": "biofilia", "nombre": "Conexión Terrestre", "desc": "Sesión de biofilia en 0G", "desbloqueada": False},
    {"id": "marte", "nombre": "Listo para Marte", "desc": "Score diario al 100%", "desbloqueada": False},
]


def guardar_evaluacion_mental(
    crew_id: str,
    timepoint: str,
    horas_sueno: float,
    nivel_estres: int,
    animo: int,
    fatiga: int,
    aislamiento: int,
    pvt_latencia_ms: float,
    pvt_lapsus: int,
    nivel_triage: str,
    notas: str = "",
) -> Dict[str, Any]:
    """Registra una evaluación de salud emocional/conductual y rendimiento psicomotor."""
    init_db()
    fecha_hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO evaluaciones_salud_mental
                (crew_id, fecha, timepoint, horas_sueno, nivel_estres, animo, fatiga, aislamiento,
                 pvt_latencia_ms, pvt_lapsus, nivel_triage, notas, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    crew_id,
                    fecha_hoy,
                    timepoint,
                    float(horas_sueno),
                    int(nivel_estres),
                    int(animo),
                    int(fatiga),
                    int(aislamiento),
                    float(pvt_latencia_ms),
                    int(pvt_lapsus),
                    nivel_triage,
                    notas,
                    now_iso,
                ),
            )
            reg_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

    if pvt_latencia_ms > 0 and pvt_latencia_ms < 300 and pvt_lapsus == 0:
        desbloquear_insignia(crew_id, "mercurio")

    return {
        "id": reg_id,
        "crewId": crew_id,
        "fecha": fecha_hoy,
        "timepoint": timepoint,
        "horasSueno": horas_sueno,
        "nivelEstres": nivel_estres,
        "animo": animo,
        "fatiga": fatiga,
        "aislamiento": aislamiento,
        "pvtLatenciaMs": pvt_latencia_ms,
        "pvtLapsus": pvt_lapsus,
        "nivelTriage": nivel_triage,
        "notas": notas,
    }


def obtener_evaluaciones_mentales(crew_id: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Obtiene el historial de evaluaciones emocionales, psicológicas y cognitivas del astronauta."""
    init_db()
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM evaluaciones_salud_mental
                WHERE crew_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (crew_id, limit),
            ).fetchall()
        finally:
            conn.close()
    salida = []
    for r in rows:
        salida.append(
            {
                "id": r["id"],
                "crewId": r["crew_id"],
                "fecha": r["fecha"],
                "timepoint": r["timepoint"],
                "horasSueno": r["horas_sueno"],
                "nivelEstres": r["nivel_estres"],
                "animo": r["animo"],
                "fatiga": r["fatiga"],
                "aislamiento": r["aislamiento"],
                "pvtLatenciaMs": r["pvt_latencia_ms"],
                "pvtLapsus": r["pvt_lapsus"],
                "nivelTriage": r["nivel_triage"],
                "notas": r["notas"],
                "createdAt": r["created_at"],
            }
        )
    return salida


def obtener_estado_gamificacion(crew_id: str) -> Dict[str, Any]:
    """Obtiene o inicializa misiones diarias, racha [SUPUESTO] e insignias del astronauta."""
    init_db()
    fecha_hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM gamificacion_misiones WHERE crew_id = ? AND fecha = ?",
                (crew_id, fecha_hoy),
            ).fetchone()
            if row is None:
                racha = 12  # [SUPUESTO] racha de referencia simulada para demo en vuelo
                misiones = [dict(m) for m in MISIONES_DEFECTO]
                score = sum(m["puntos"] for m in misiones if m["completada"])
                insignias = [dict(i) for i in INSIGNIAS_DEFECTO]

                conn.execute(
                    """
                    INSERT INTO gamificacion_misiones
                    (crew_id, fecha, misiones_json, score, racha_dias, insignias_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        crew_id,
                        fecha_hoy,
                        json.dumps(misiones, ensure_ascii=False),
                        score,
                        racha,
                        json.dumps(insignias, ensure_ascii=False),
                        now_iso,
                    ),
                )
                conn.commit()
                return {
                    "crewId": crew_id,
                    "fecha": fecha_hoy,
                    "misiones": misiones,
                    "score": score,
                    "rachaDias": racha,
                    "insignias": insignias,
                }
            return {
                "crewId": row["crew_id"],
                "fecha": row["fecha"],
                "misiones": json.loads(row["misiones_json"]),
                "score": row["score"],
                "rachaDias": row["racha_dias"],
                "insignias": json.loads(row["insignias_json"]),
            }
        finally:
            conn.close()


def marcar_mision_gamificacion(crew_id: str, mision_id: str, completada: bool) -> Dict[str, Any]:
    """Marca o desmarca una misión de salud diaria y recalcula el puntaje de preparación."""
    estado = obtener_estado_gamificacion(crew_id)
    misiones = estado["misiones"]
    for m in misiones:
        if m["id"] == mision_id:
            m["completada"] = completada
            break
    nuevo_score = sum(m["puntos"] for m in misiones if m["completada"])
    fecha_hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()

    insignias = estado["insignias"]
    if all(m["completada"] for m in misiones):
        for ins in insignias:
            if ins["id"] == "marte":
                ins["desbloqueada"] = True

    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE gamificacion_misiones
                SET misiones_json = ?, score = ?, insignias_json = ?, updated_at = ?
                WHERE crew_id = ? AND fecha = ?
                """,
                (
                    json.dumps(misiones, ensure_ascii=False),
                    nuevo_score,
                    json.dumps(insignias, ensure_ascii=False),
                    now_iso,
                    crew_id,
                    fecha_hoy,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    estado["misiones"] = misiones
    estado["score"] = nuevo_score
    estado["insignias"] = insignias
    return estado


def desbloquear_insignia(crew_id: str, insignia_id: str) -> None:
    """Desbloquea una insignia específica de bienestar para el tripulante."""
    estado = obtener_estado_gamificacion(crew_id)
    insignias = estado["insignias"]
    cambio = False
    for ins in insignias:
        if ins["id"] == insignia_id and not ins["desbloqueada"]:
            ins["desbloqueada"] = True
            cambio = True
            break
    if cambio:
        fecha_hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_iso = datetime.now(timezone.utc).isoformat()
        with _db_lock:
            conn = get_connection()
            try:
                conn.execute(
                    "UPDATE gamificacion_misiones SET insignias_json = ?, updated_at = ? WHERE crew_id = ? AND fecha = ?",
                    (json.dumps(insignias, ensure_ascii=False), now_iso, crew_id, fecha_hoy),
                )
                conn.commit()
            finally:
                conn.close()
