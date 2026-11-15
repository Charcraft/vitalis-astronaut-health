"""Explora OSDR y lista datasets humanos con ensayos no-omicos (fisiologicos/clinicos).

Uso:  python scripts/explorar-osdr.py
Salida: scripts/.osdr-humano.json  (cache de trabajo, no se commitea)
"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://visualization.osdr.nasa.gov/biodata/api/v2"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
CACHE = "scripts/.osdr-humano.json"


def get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def metadata(acc):
    try:
        d = get(f"{API}/dataset/{acc}/?format=json")
        return acc, d[acc].get("metadata", {})
    except Exception as e:
        return acc, {"_error": str(e)}


def main():
    humanos = get(
        f"{API}/query/datasets/?study.characteristics.organism=Homo%20sapiens&format=json.records"
    )
    accs = [row["id.accession"] for row in humanos]
    print(f"datasets humanos: {len(accs)}")

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(metadata, accs))

    filas = []
    for acc, md in results:
        tipos = md.get("study assay measurement type") or md.get("study.assay measurement type")
        titulo = md.get("study title") or md.get("study.title") or md.get("study name")
        filas.append({
            "accesion": acc,
            "titulo": titulo,
            "tipos": tipos,
            "mission": md.get("study mission") or md.get("mission"),
            "spaceflight": md.get("study.characteristics.spaceflight"),
        })

    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(filas, f, ensure_ascii=False, indent=1)

    omicos = ("transcription", "proteom", "metabolom", "metagenom", "epigen", "sequenc", "microarray")
    candidatos = []
    for f in filas:
        tipos = f["tipos"]
        if tipos is None:
            continue
        t = " ".join(tipos).lower() if isinstance(tipos, list) else str(tipos).lower()
        if not any(o in t for o in omicos):
            candidatos.append(f)

    print(f"\nno-omicos: {len(candidatos)}")
    for c in candidatos[:40]:
        print(f"  {c['accesion']:<10} {str(c['tipos'])[:70]:<72} {str(c['titulo'])[:60]}")


if __name__ == "__main__":
    main()
