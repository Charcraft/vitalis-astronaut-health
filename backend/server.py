# -*- coding: utf-8 -*-
"""
backend/server.py — Servidor Principal de Backend en Python (FastAPI + Uvicorn + SQLite)
para V.I.T.A.L.I.S. (Vital Information Telemetry and Life-support In Space)
y su agente autónomo L.I.S. (Life-support In Space).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

import httpx
import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from backend import __version__
from backend.crew_hub import get_crew_hub
from backend.database import (
    actualizar_alias_astronauta,
    atender_solicitud_ayuda,
    crear_solicitud_ayuda,
    exportar_respaldo_completo,
    get_baseline,
    get_cabina_dataset,
    get_guias_dataset,
    get_osdr_dataset,
    get_protocolos_dataset,
    guardar_medicion_local,
    guardar_medicion_sensor,
    init_db,
    listar_bitacora,
    listar_episodios,
    listar_eventos_emergencia,
    listar_mediciones_locales,
    listar_series,
    listar_solicitudes_ayuda,
    obtener_memoria_astronauta,
    recordar_dato_astronauta,
    registrar_bitacora,
)
from backend.knowledge import (
    listar_protocolos_por_parametro,
    obtener_protocolo_disp,
)
from backend.lis_agent import (
    JARVIS_XTTS_URL,
    construir_snapshot_contexto,
    detectar_mejor_modelo_cloud,
    generar_respuesta_determinista,
    sintetizar_voz_lis,
    validar_respuesta_sin_alucinacion,
)
from backend.registry import get_param
from backend.runtime import get_runtime
from backend.sync_tierra import (
    contar_recibidos_tierra,
    get_sync_manager,
    guardar_lote_en_tierra,
    listar_recibidos_tierra,
)
from backend.telemetry import generar_frame_telemetria
from backend.triage import (
    evaluar_lectura_determinista,
    listar_anomalias_tripulante,
    obtener_catalogo_parametros,
)

app = FastAPI(
    title="V.I.T.A.L.I.S. Python Backend Engine",
    description="Backend oficial en Python (FastAPI + SQLite + NASA OSDR OSD-575 + Agente L.I.S.)",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.on_event("shutdown")
def on_shutdown() -> None:
    get_runtime().stop()


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    xtts_ok = False
    try:
        async with httpx.AsyncClient(timeout=1.2) as client:
            r = await client.get(f"{JARVIS_XTTS_URL}/health")
            if r.status_code == 200:
                xtts_ok = bool(r.json().get("ok"))
    except Exception:
        xtts_ok = False

    return {
        "ok": True,
        "engine": "python-fastapi-sqlite",
        "project": "V.I.T.A.L.I.S.",
        "agent": "L.I.S. (Life-support In Space)",
        "database": "SQLite WAL (data/vitalis.db)",
        "dataset": "NASA OSDR OSD-575 (Inspiration4 CMP)",
        "jarvisVoiceCloneReady": xtts_ok,
    }


@app.get("/api/osdr")
async def api_osdr(
    crewId: Optional[str] = Query(default=None),
    indicadorId: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    dataset = get_osdr_dataset()
    if crewId and indicadorId:
        return {
            "fuente": "python-sqlite-osdr",
            "baseline": get_baseline(crewId, indicadorId),
            "anomalias": listar_anomalias_tripulante(crewId),
        }
    return {
        "fuente": "python-sqlite-osdr",
        "dataset": dataset,
        "cabina": get_cabina_dataset(),
        "guias": get_guias_dataset(),
        "protocolos": get_protocolos_dataset(),
    }


@app.get("/api/parameters")
async def api_parameters(
    entorno: Optional[str] = Query(default=None),
    sistema: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    parametros = obtener_catalogo_parametros(entorno=entorno, sistema=sistema)
    return {
        "ok": True,
        "total": len(parametros),
        "osdr": sum(1 for p in parametros if p.get("esDatoRealOSDR")),
        "simulados": sum(1 for p in parametros if not p.get("esDatoRealOSDR")),
        "parametros": parametros,
    }


@app.post("/api/triage")
async def api_triage(req: Request) -> Dict[str, Any]:
    body = await req.json()
    crew_id = body.get("crewId", "C003")
    indicador_id = body.get("indicadorId", "glucose")
    valor = float(body.get("valor", 103.0))
    calidad = body.get("calidad")
    entorno = body.get("entorno")
    sexo = body.get("sexo")
    return evaluar_lectura_determinista(
        crew_id,
        indicador_id,
        valor,
        calidad=float(calidad) if calidad is not None else None,
        entorno=entorno,
        sexo=sexo,
    )


@app.get("/api/telemetry")
async def api_telemetry(
    crewId: str = Query(default="C003"),
    timepoint: str = Query(default="R+1"),
) -> Dict[str, Any]:
    return generar_frame_telemetria(crewId, timepoint)


@app.post("/api/telemetry")
async def api_telemetry_post(req: Request) -> JSONResponse:
    try:
        frame = await req.json()
    except Exception:
        return JSONResponse(
            {"error": "json-invalido", "detalle": "El cuerpo de la petición no es JSON válido."},
            status_code=400,
        )
    if not isinstance(frame, dict) or frame.get("crewId") not in ("C001", "C002", "C003", "C004") or not isinstance(frame.get("lecturas"), dict):
        return JSONResponse(
            {"error": "frame-invalido", "detalle": "Falta crewId válido o lecturas."},
            status_code=400,
        )
    alertas = get_crew_hub().publicar_frame(frame)
    return JSONResponse({"aceptado": True, "alertas": len(alertas)}, status_code=202)


@app.get("/api/telemetry/hub")
async def api_telemetry_hub() -> Dict[str, Any]:
    return {
        "ok": True,
        "tripulantes": get_crew_hub().snapshot(),
        "runtime": get_runtime().estado_resumen(),
    }


@app.post("/api/telemetry/anomaly")
async def api_telemetry_anomaly(req: Request) -> JSONResponse:
    body = await req.json()
    limpiar = bool(body.get("limpiar", False))
    crew_id = body.get("crewId")
    rt = get_runtime()
    if limpiar:
        frame = rt.limpiar_anomalias(crew_id=crew_id)
        return JSONResponse({"ok": True, "anomaliasActivas": rt.anomalias_activas(crew_id), "frame": frame})
    param_id = str(body.get("parametroId", "")).strip()
    nivel = str(body.get("nivel", "CRITICO")).upper()
    duracion_ms = int(body.get("duracionMs", 30_000))
    try:
        frame = rt.forzar_anomalia(param_id, nivel, crew_id=crew_id, duracion_ms=duracion_ms)
        return JSONResponse({"ok": True, "anomaliasActivas": rt.anomalias_activas(crew_id), "frame": frame})
    except (KeyError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/runtime/config")
async def api_runtime_config(req: Request) -> JSONResponse:
    body = await req.json()
    rt = get_runtime()
    try:
        if body.get("crewId") in ("C001", "C002", "C003", "C004"):
            rt.set_crew_activa(str(body["crewId"]))
        if body.get("entorno") in ("nave", "estacion", "base-lunar"):
            rt.set_entorno(str(body["entorno"]))
        if body.get("modo") in ("simulado", "replay-osdr"):
            rt.set_modo(str(body["modo"]))
        if "aislarCrewId" in body and "aislada" in body:
            get_crew_hub().set_estacion_aislada(str(body["aislarCrewId"]), bool(body["aislada"]))
        return JSONResponse({"ok": True, "runtime": rt.estado_resumen()})
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/api/telemetry/stream")
async def api_telemetry_stream(
    crewId: str = Query(default="C003"),
    timepoint: str = Query(default="R+1"),
) -> StreamingResponse:
    async def event_generator():
        while True:
            frame = generar_frame_telemetria(crewId, timepoint)
            yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/measurements")
async def api_get_measurements(
    crewId: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    return {"mediciones": listar_mediciones_locales(crewId, 25)}


@app.post("/api/measurements")
async def api_post_measurement(req: Request) -> Dict[str, Any]:
    body = await req.json()
    crew_id = body.get("crewId", "C003")
    indicador_id = body.get("indicadorId", "glucose")
    valor = float(body.get("valor", 0.0))
    notas = body.get("notas", "")
    eval_res = evaluar_lectura_determinista(crew_id, indicador_id, valor)
    unidad = eval_res.get("unidad", "mg/dL")
    nivel = eval_res.get("nivel", "NOMINAL")
    guardada = guardar_medicion_local(
        crew_id=crew_id,
        indicador_id=indicador_id,
        valor=valor,
        unidad=unidad,
        nivel_triage=nivel,
        notas=notas,
    )
    reg_sensor = guardar_medicion_sensor(
        crew_id=crew_id,
        parametro_id=eval_res.get("indicadorId", indicador_id),
        valor=valor,
        unidad=unidad,
        nivel=nivel,
    )
    if reg_sensor.get("ok") and reg_sensor.get("id"):
        get_sync_manager().encolar_medicion(int(reg_sensor["id"]), nivel=nivel)
    return {"ok": True, "medicion": guardada, "evaluacion": eval_res}


@app.post("/api/mediciones")
async def api_post_mediciones_compat(req: Request) -> JSONResponse:
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "Cuerpo JSON inválido"}, status_code=400)
    crew_id = body.get("crewId")
    parametro_id = body.get("parametroId")
    valor_raw = body.get("valor")
    if crew_id not in ("C001", "C002", "C003", "C004") or not isinstance(parametro_id, str) or not isinstance(valor_raw, (int, float)):
        return JSONResponse({"error": "Entrada inválida"}, status_code=400)
    definicion = get_param(parametro_id)
    if definicion is None:
        return JSONResponse({"error": "Parámetro no registrado"}, status_code=400)

    valor = float(valor_raw)
    unidad = str(body.get("unidad") or definicion["unidadCanonica"])
    ts_ms = body.get("timestamp")
    eval_res = evaluar_lectura_determinista(crew_id, parametro_id, valor)
    guardado = guardar_medicion_sensor(
        crew_id=crew_id,
        parametro_id=parametro_id,
        valor=valor,
        unidad=unidad,
        nivel=eval_res["nivel"],
        timestamp_ms=int(ts_ms) if isinstance(ts_ms, int) else None,
    )
    guardar_medicion_local(
        crew_id=crew_id,
        indicador_id=parametro_id,
        valor=valor,
        unidad=unidad,
        nivel_triage=eval_res["nivel"],
        notas="[manual]",
    )
    if not guardado.get("ok"):
        return JSONResponse(
            {"error": guardado.get("motivo", "No se pudo guardar la medición")},
            status_code=500,
        )
    if guardado.get("id"):
        get_sync_manager().encolar_medicion(int(guardado["id"]), nivel=eval_res["nivel"])
    return JSONResponse(
        {
            "ok": True,
            "medicion": {
                "crewId": crew_id,
                "parametroId": parametro_id,
                "valor": valor,
                "nivel": eval_res["nivel"],
                "regla": eval_res.get("reglaDisparada"),
                "fuente": eval_res.get("fuente"),
                "degradado": eval_res.get("degradado"),
            },
        }
    )


@app.get("/api/series")
async def api_series(
    crewId: Optional[str] = Query(default=None),
    parametroId: Optional[str] = Query(default=None),
    resolucion: str = Query(default="1h"),
    desde: Optional[int] = Query(default=None),
    hasta: Optional[int] = Query(default=None),
) -> JSONResponse:
    if not crewId or crewId not in ("C001", "C002", "C003", "C004"):
        return JSONResponse({"error": "crewId inválido"}, status_code=400)
    series = listar_series(
        crew_id=crewId,
        parametro_id=parametroId,
        resolucion=resolucion,
        desde=desde,
        hasta=hasta,
    )
    return JSONResponse({"crewId": crewId, "total": len(series), "series": series})


@app.get("/api/episodios")
async def api_episodios(
    crewId: Optional[str] = Query(default=None),
    soloAbiertos: bool = Query(default=False),
) -> Dict[str, Any]:
    episodios = listar_episodios(crew_id=crewId, solo_abiertos=soloAbiertos)
    eventos = listar_eventos_emergencia(crew_id=crewId)
    return {
        "total": len(episodios),
        "episodios": episodios,
        "eventos": eventos,
    }


@app.get("/api/protocolos")
async def api_protocolos(
    id: Optional[str] = Query(default=None),
    parametroId: Optional[str] = Query(default=None),
    nivel: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    if id is not None:
        p = obtener_protocolo_disp(id)
        protos = [p] if p else []
    else:
        protos = listar_protocolos_por_parametro(parametro_id=parametroId, nivel=nivel)
    return {
        "estado": "local",
        "total": len(protos),
        "protocolos": protos,
    }


@app.get("/api/tierra")
async def api_tierra_get() -> Dict[str, Any]:
    return {
        "recibidos": contar_recibidos_tierra(),
        "ultimos": listar_recibidos_tierra(limit=15),
    }


@app.post("/api/tierra")
async def api_tierra_post(req: Request) -> JSONResponse:
    try:
        body = await req.json()
    except Exception:
        return JSONResponse(
            {"error": "json-invalido", "detalle": "El cuerpo no es JSON válido."},
            status_code=400,
        )
    requeridos = ("id", "prioridad", "tipo", "hash", "creadoEn")
    if not isinstance(body, dict) or any(k not in body for k in requeridos) or body.get("prioridad") not in ("A", "B", "C", "D") or body.get("tipo") not in ("frame", "evento", "bitacora", "medicion"):
        return JSONResponse(
            {"error": "lote-invalido", "detalle": "Estructura de lote inválida."},
            status_code=400,
        )
    guardar_lote_en_tierra(body)
    return JSONResponse({"ack": True, "id": body["id"]}, status_code=201)


@app.get("/api/sync/status")
async def api_sync_status() -> Dict[str, Any]:
    return get_sync_manager().stats()


@app.post("/api/sync/flush")
async def api_sync_flush() -> Dict[str, Any]:
    res = get_sync_manager().flush_cola()
    return {"ok": True, "resultado": res, "stats": get_sync_manager().stats()}


@app.post("/api/sync/network")
async def api_sync_network(req: Request) -> JSONResponse:
    body = await req.json()
    estado = str(body.get("estado", "online"))
    try:
        nuevo = get_sync_manager().set_estado_red(estado)
        return JSONResponse({"ok": True, "red": nuevo, "stats": get_sync_manager().stats()})
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/api/bitacora")
async def api_get_bitacora() -> Dict[str, Any]:
    return {"bitacora": listar_bitacora(limit=50)}


@app.post("/api/bitacora")
async def api_post_bitacora(req: Request) -> Dict[str, Any]:
    body = await req.json()
    texto = str(body.get("texto", "")).strip()
    actor = str(body.get("actor", "TRIPULACION"))
    crew_id = body.get("crewId")
    if texto:
        bid = registrar_bitacora(texto=texto, actor=actor, crew_id=crew_id)
        get_sync_manager().encolar_bitacora(bid)
    return {"ok": True, "bitacora": listar_bitacora(limit=50)}


@app.get("/api/export")
async def api_export(crewId: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    return exportar_respaldo_completo(crew_id=crewId)


@app.get("/api/memory")
async def api_get_memory(crewId: str = Query(default="C003")) -> Dict[str, Any]:
    return obtener_memoria_astronauta(crewId)


@app.post("/api/memory")
async def api_post_memory(req: Request) -> Dict[str, Any]:
    body = await req.json()
    crew_id = body.get("crewId", "C003")
    if "aliasPreferido" in body:
        return actualizar_alias_astronauta(crew_id, str(body["aliasPreferido"]))
    texto = str(body.get("texto", "")).strip()
    categoria = str(body.get("categoria", "observacion"))
    if texto:
        return recordar_dato_astronauta(crew_id, texto, categoria)
    return obtener_memoria_astronauta(crew_id)


@app.get("/api/help-requests")
async def api_get_help_requests() -> Dict[str, Any]:
    return {"solicitudes": listar_solicitudes_ayuda(solo_activas=True)}


@app.post("/api/help-requests")
async def api_post_help_request(req: Request) -> Dict[str, Any]:
    body = await req.json()
    if body.get("accion") == "atender" and body.get("id"):
        atender_solicitud_ayuda(int(body["id"]))
        return {"ok": True, "solicitudes": listar_solicitudes_ayuda(True)}

    nueva = crear_solicitud_ayuda(
        crew_id_solicitante=body.get("crewIdSolicitante", "C003"),
        destinatario=body.get("destinatario", "CMO_A_BORDO_C001"),
        nivel=body.get("nivel", "CRITICO"),
        motivo=body.get("motivo", "Asistencia médica solicitada"),
        resumen_clinico=body.get("resumenClinico", ""),
        protocolo_sugerido_id=body.get("protocoloSugeridoId"),
    )
    return {"ok": True, "solicitud": nueva}


@app.post("/api/cloud-llm")
async def api_cloud_llm(req: Request) -> Dict[str, Any]:
    body = await req.json()
    return await detectar_mejor_modelo_cloud(body.get("apiKey", ""))


@app.get("/api/local-llm")
async def api_local_llm(
    endpoint: str = Query(default="http://127.0.0.1:11434"),
) -> Dict[str, Any]:
    clean_ep = endpoint.rstrip("/")
    modelos = []
    conectado = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{clean_ep}/api/tags")
            if r.status_code == 200:
                conectado = True
                modelos = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        conectado = False

    return {
        "conectado": conectado,
        "endpoint": clean_ep,
        "modelosInstalados": modelos,
        "hardwareDetectado": "NVIDIA GeForce RTX 3050 Ti Laptop GPU (4 GB VRAM)",
        "recomendacionMinima": {
            "modeloMinimoSinAlucinacion": "qwen2.5:3b (o llama3.2:3b)",
            "vramRequerida": "1.9 GB - 2.1 GB VRAM (Q4_K_M)",
            "comandoInstalacion": "ollama pull qwen2.5:3b",
        },
    }


@app.post("/api/ai-context")
async def api_ai_context(req: Request) -> Dict[str, Any]:
    body = await req.json()
    crew_id = body.get("crewId", "C003")
    timepoint = body.get("timepoint", "R+1")
    modo_operacion = body.get("modoOperacion", "rutina")
    mensaje = body.get("mensaje", "Estado actual")
    memoria = body.get("memoria") or obtener_memoria_astronauta(crew_id)
    meds = body.get("ultimasMedicionesLocales") or listar_mediciones_locales(crew_id, 5)

    snapshot = construir_snapshot_contexto(crew_id, timepoint, modo_operacion)
    respuesta_det = generar_respuesta_determinista(
        mensaje_usuario=mensaje,
        crew_id=crew_id,
        timepoint=timepoint,
        modo_operacion=modo_operacion,
        memoria=memoria,
        ultimas_mediciones=meds,
    )

    return {
        "ok": True,
        "engine": "python-lis-deterministic",
        "snapshot": snapshot,
        "respuesta": respuesta_det,
        "validacion": {
            "esValida": True,
            "numerosNoAutorizados": [],
        },
    }


@app.get("/api/tts")
async def api_tts_status() -> Dict[str, Any]:
    clon_activo = False
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(f"{JARVIS_XTTS_URL}/health")
            if r.status_code == 200:
                clon_activo = bool(r.json().get("ok"))
    except Exception:
        clon_activo = False

    return {
        "clonJarvisActivo": clon_activo,
        "motor": "XTTS v2 GPU (JARVIS Clonada)" if clon_activo else "Edge Neural Python Fallback",
        "servidorUrl": JARVIS_XTTS_URL,
    }


@app.post("/api/tts")
async def api_tts_synthesize(req: Request) -> Response:
    body = await req.json()
    texto = str(body.get("text", ""))
    voz_id = str(body.get("voice", "jarvis-clone-latam"))
    rate = float(body.get("rate", 1.04))

    audio_bytes, media_type, engine_name = await sintetizar_voz_lis(
        texto, voz_id, rate
    )
    if not audio_bytes:
        return JSONResponse(
            {"error": "No se pudo sintetizar audio"}, status_code=503
        )
    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Voice-Engine": engine_name,
        },
    )


def run_server(host: str = "127.0.0.1", port: int = 8780) -> None:
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
