# -*- coding: utf-8 -*-
"""
backend/knowledge.py — Cliente O(1) de protocolos clínicos disparados por triage y perfil de sexo.

Complementa `recursos/datos/knowledge/protocolos-emergencia.json` (protocolos ALSP paso a paso)
con los protocolos ligeros para tripulación no médica de `protocolos-disparadores.json`
y la asignación sexo-específica de `tripulacion.json`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional

from backend.database import (
    get_protocolos_disparadores_dataset,
    get_tripulacion_dataset,
    sexo_de,
)


@lru_cache(maxsize=1)
def _indices_protocolos() -> tuple[
    List[Dict[str, Any]],
    Dict[str, Dict[str, Any]],
    Dict[str, List[Dict[str, Any]]],
]:
    lista = list(get_protocolos_disparadores_dataset())
    por_id: Dict[str, Dict[str, Any]] = {}
    por_param: Dict[str, List[Dict[str, Any]]] = {}
    for p in lista:
        pid = p.get("id")
        if pid:
            por_id[pid] = p
        for d in p.get("disparadores", []):
            param_id = d.get("parametroId")
            if param_id:
                por_param.setdefault(param_id, []).append(p)
    return lista, por_id, por_param


def listar_protocolos_disp() -> List[Dict[str, Any]]:
    lista, _, _ = _indices_protocolos()
    return lista


def obtener_protocolo_disp(protocolo_id: str) -> Optional[Dict[str, Any]]:
    _, por_id, _ = _indices_protocolos()
    return por_id.get(protocolo_id)


def protocolo_para(parametro_id: str, nivel: str) -> Optional[Dict[str, Any]]:
    """Resuelve el protocolo de lenguaje simple asociado a (parametroId, nivel), o None."""
    _, _, por_param = _indices_protocolos()
    candidatos = por_param.get(parametro_id) or []
    for p in candidatos:
        for d in p.get("disparadores", []):
            if d.get("parametroId") == parametro_id and d.get("nivel") == nivel:
                return p
    return None


def listar_protocolos_por_parametro(
    parametro_id: Optional[str] = None, nivel: Optional[str] = None
) -> List[Dict[str, Any]]:
    if parametro_id is not None and nivel in ("ATENCION", "CRITICO"):
        match = protocolo_para(parametro_id, nivel)
        return [match] if match else []
    if parametro_id is not None:
        return [
            p
            for p in listar_protocolos_disp()
            if any(d.get("parametroId") == parametro_id for d in p.get("disparadores", []))
        ]
    return listar_protocolos_disp()


__all__ = [
    "get_tripulacion_dataset",
    "listar_protocolos_disp",
    "listar_protocolos_por_parametro",
    "obtener_protocolo_disp",
    "protocolo_para",
    "sexo_de",
]
