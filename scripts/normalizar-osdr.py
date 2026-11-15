"""Descarga y normaliza el panel metabolico de Inspiration4 desde NASA OSDR.

Dataset: OSD-575 - SpaceX Inspiration4 Blood Serum Metabolic Panel
Archivo:  LSDS-8_Comprehensive_Metabolic_Panel_CMP_TRANSFORMED.csv
Origen:   NASA Open Science Data Repository

Salida:   recursos/datos/seed/osdr-inspiration4-cmp.json

Uso:      python scripts/normalizar-osdr.py

El script es idempotente: vuelve a descargar y a generar el mismo JSON.
No se edita el JSON a mano. Si cambia algo, se cambia aqui y se regenera.
"""
import csv
import io
import json
import re
import urllib.request
from datetime import date
from pathlib import Path

ACCESSION = "OSD-575"
FILE_NAME = "LSDS-8_Comprehensive_Metabolic_Panel_CMP_TRANSFORMED.csv"
URL = (
    "https://osdr.nasa.gov/geode-py/ws/studies/OSD-575/download"
    f"?source=datamanager&file={FILE_NAME}"
)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "recursos" / "datos" / "seed" / "osdr-inspiration4-cmp.json"

# Nombre legible y etiqueta clinica de cada analito del CMP
NOMBRES = {
    "albumin": ("Albúmina", "proteínas"),
    "albumin_to_globulin_ratio": ("Relación albúmina/globulina", "proteínas"),
    "alkaline_phosphatase": ("Fosfatasa alcalina", "hígado"),
    "alt": ("ALT (alanina aminotransferasa)", "hígado"),
    "ast": ("AST (aspartato aminotransferasa)", "hígado"),
    "total_bilirubin": ("Bilirrubina total", "hígado"),
    "bun_to_creatinine_ratio": ("Relación BUN/creatinina", "riñón"),
    "calcium": ("Calcio", "electrolitos"),
    "carbon_dioxide": ("CO₂ total", "electrolitos"),
    "chloride": ("Cloruro", "electrolitos"),
    "creatinine": ("Creatinina", "riñón"),
    "egfr_african_american": ("eGFR (ajuste afroamericano)", "riñón"),
    "egfr_non_african_american": ("eGFR", "riñón"),
    "globulin": ("Globulina", "proteínas"),
    "glucose": ("Glucosa", "metabólico"),
    "potassium": ("Potasio", "electrolitos"),
    "total_protein": ("Proteína total", "proteínas"),
    "sodium": ("Sodio", "electrolitos"),
    "urea_nitrogen_bun": ("Nitrógeno ureico (BUN)", "riñón"),
}

UNIDADES = {
    "gram_per_deciliter": "g/dL",
    "units_per_liter": "U/L",
    "milligram_per_deciliter": "mg/dL",
    "millimol_per_liter": "mmol/L",
    "milliliter_per_minute_per_1.73_meter_squared": "mL/min/1.73m²",
}


def descargar() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("utf-8-sig")


def numero(txt):
    txt = (txt or "").strip()
    if txt in ("", "NA", "N/A", "n/a", "NaN"):
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def parsear_tiempo(sample: str):
    """C001_serum_L-92 -> ('C001', 'L-92', -92, 'pre-vuelo')"""
    partes = sample.split("_")
    crew = partes[0]
    tp = partes[-1]
    m = re.match(r"^([LR])([+-])(\d+)$", tp)
    if not m:
        return crew, tp, None, "desconocido"
    signo = -1 if m.group(1) == "L" else 1
    dias = signo * int(m.group(3))
    fase = "pre-vuelo" if dias < 0 else "post-vuelo"
    return crew, tp, dias, fase


def main():
    print(f"Descargando {ACCESSION} ...")
    crudo = descargar()
    filas = list(csv.reader(io.StringIO(crudo)))
    cabecera = filas[0]
    datos = filas[1:]
    print(f"  {len(datos)} muestras, {len(cabecera)} columnas")

    # --- analitos: <analito>_value_<unidad> + rango min/max -----------------
    analitos = []
    for i, col in enumerate(cabecera):
        if not col.endswith("_value_" + col.split("_value_")[-1]):
            continue
        if "_value_" not in col:
            continue
        nombre, unidad = col.split("_value_", 1)
        valor = numero(datos[0][i]) if datos else None
        rmin = rmax = None
        # el rango esta en las dos columnas siguientes, con sufijo variable
        if i + 1 < len(cabecera) and "range_min" in cabecera[i + 1]:
            rmin = numero(datos[0][i + 1])
        if i + 2 < len(cabecera) and ("range_max" in cabecera[i + 2] or "_max_" in cabecera[i + 2]):
            rmax = numero(datos[0][i + 2])
        analitos.append({
            "columna": col,
            "indice": i,
            "id": nombre,
            "unidad": UNIDADES.get(unidad, unidad.replace("_", " ")),
            "rangoMin": rmin,
            "rangoMax": rmax,
            "valorEjemplo": valor,
        })

    # --- timepoints y tripulantes ------------------------------------------
    timepoints = {}
    tripulantes = set()
    for fila in datos:
        crew, tp, dias, fase = parsear_tiempo(fila[0])
        tripulantes.add(crew)
        if tp not in timepoints:
            timepoints[tp] = {"id": tp, "diasRelativosAlLanzamiento": dias, "fase": fase}
        elif timepoints[tp]["diasRelativosAlLanzamiento"] is None:
            timepoints[tp]["diasRelativosAlLanzamiento"] = dias

    ordenados = sorted(
        timepoints.values(),
        key=lambda t: (t["diasRelativosAlLanzamiento"] is None, t["diasRelativosAlLanzamiento"] or 0),
    )

    # --- serie por analito -------------------------------------------------
    indicadores = []
    for a in analitos:
        nombre_es, sistema = NOMBRES.get(a["id"], (a["id"].replace("_", " ").capitalize(), "otros"))
        serie = {}
        for fila in datos:
            crew, tp, _, _ = parsear_tiempo(fila[0])
            v = numero(fila[a["indice"]])
            if v is None:
                continue
            serie.setdefault(crew, []).append({"timepoint": tp, "valor": v})

        # ordenar cada serie por dia relativo
        for crew in serie:
            serie[crew].sort(
                key=lambda p: timepoints[p["timepoint"]]["diasRelativosAlLanzamiento"] or 0
            )

        if not serie:
            continue

        indicadores.append({
            "id": a["id"],
            "nombre": nombre_es,
            "sistema": sistema,
            "unidad": a["unidad"],
            "rangoReferencia": {"min": a["rangoMin"], "max": a["rangoMax"]},
            "fuente": "OSDR OSD-575 (rango de referencia incluido en el dataset)",
            "serie": serie,
        })

    salida = {
        "meta": {
            "fuente": "NASA Open Science Data Repository (OSDR)",
            "accesion": ACCESSION,
            "titulo": "SpaceX Inspiration4 Blood Serum Metabolic Panel and Immune/Cytokine Panel",
            "archivo": FILE_NAME,
            "url": URL,
            "paginaDataset": f"https://osdr.nasa.gov/bio/repo/data/studies/{ACCESSION}",
            "obtenido": str(date.today()),
            "tripulantes": sorted(tripulantes),
            "puntosTemporales": len(ordenados),
            "nota": (
                "Datos desidentificados de los cuatro tripulantes de Inspiration4, "
                "anonimizados como C001-C004. Los rangos de referencia provienen del "
                "propio dataset, no de una tabla externa."
            ),
            "licencia": "Datos abiertos de NASA OSDR. Ver términos del repositorio.",
            "generadoPor": "scripts/normalizar-osdr.py",
        },
        "timepoints": ordenados,
        "indicadores": indicadores,
    }

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    print(f"\nOK -> {SALIDA.relative_to(RAIZ)}")
    print(f"  tripulantes: {', '.join(sorted(tripulantes))}")
    print(f"  timepoints:  {len(ordenados)}  ({', '.join(t['id'] for t in ordenados)})")
    print(f"  indicadores: {len(indicadores)}")
    muestra = next((i for i in indicadores if i["id"] == "glucose"), None)
    if muestra:
        print("\n  Glucosa (primer tripulante):")
        for p in muestra["serie"]["C001"]:
            print(f"    {p['timepoint']:<7} {p['valor']:>6} {muestra['unidad']}"
                  f"   ref {muestra['rangoReferencia']['min']}-{muestra['rangoReferencia']['max']}")


if __name__ == "__main__":
    main()
