# recursos/datos/seed/ — Datos reales

> **Regla:** aquí solo entran datos reales, descargados de una fuente pública y normalizados por un script.
> Nada se edita a mano. Nada ficticio. Los mocks viven en `recursos/datos/mock/`.

---

## Archivos

| Archivo | Origen | Contenido |
|---|---|---|
| `osdr-inspiration4-cmp.json` | NASA OSDR — **OSD-575** | Panel metabólico completo (CMP) de los 4 tripulantes de Inspiration4, 7 puntos temporales |

---

## `osdr-inspiration4-cmp.json`

### Qué es
El panel metabólico completo de sangre de la misión **SpaceX Inspiration4**, publicado en abierto por NASA en el Open Science Data Repository.

### Por qué este dataset
- Son **datos humanos reales de vuelo**, no simulaciones.
- Tiene **línea base pre-vuelo** (L-92, L-44, L-3) y **seguimiento post-vuelo** (R+1, R+45, R+82, R+194).
- Incluye **rangos de referencia clínicos dentro del propio archivo**, así que los umbrales de la app no los inventamos nosotros.
- Cubre **glucosa**, que es uno de los indicadores que el reto menciona explícitamente.

### Estructura

```jsonc
{
  "meta": { "accesion": "OSD-575", "url": "...", "obtenido": "2026-11-13", ... },
  "timepoints": [
    { "id": "L-92", "diasRelativosAlLanzamiento": -92, "fase": "pre-vuelo" },
    ...
  ],
  "indicadores": [
    {
      "id": "glucose",
      "nombre": "Glucosa",
      "unidad": "mg/dL",
      "rangoReferencia": { "min": 65, "max": 99 },
      "fuente": "OSDR OSD-575",
      "serie": {
        "C001": [ { "timepoint": "L-92", "valor": 83 }, ... ]
      }
    }
  ]
}
```

### Datos personales
Los cuatro tripulantes están **anonimizados como C001–C004** por la propia fuente. No hay información identificable. No se debe intentar reidentificar a nadie.

### Cómo se regenera

```bash
python scripts/normalizar-osdr.py
```

El script descarga el CSV desde OSDR y regenera el JSON. Es idempotente.

### Limitaciones (decirlas en el pitch, no esconderlas)

- Es **química sanguínea**, no signos vitales continuos. No hay presión arterial ni frecuencia cardíaca en este dataset.
- Son **4 personas**. Sirve para demostrar el concepto de línea base personal, no para inferir poblaciones.
- Los puntos temporales son **discretos** (7 por tripulante), no una serie continua.
- Los datos son de **vuelo orbital corto** (3 días), no de una misión a Marte.

### Calidad del dato: 24 de 475 valores fuera de rango

Del total de **475 valores** (17 indicadores × 4 tripulantes × 7 puntos), **24 caen fuera del rango de referencia que trae el propio dataset** (5.1 %).

Ejemplos reales:

| Tripulante | Punto | Analito | Valor | Rango |
|---|---|---|---|---|
| C003 | R+45 | Glucosa | 36 mg/dL | 65–99 |
| C002 | R+45 | Glucosa | 44 mg/dL | 65–99 |
| C004 | L-92 | Glucosa | 100 mg/dL | 65–99 |

**Cómo tratarlo:**

1. El script **reproduce exactamente** los valores publicados. No hay error de parseo: se verificó contra el CSV original.
2. **No se interpretan clínicamente.** Una glucosa de 36 mg/dL en un astronauta sano no se explica con este dataset y no es nuestra tarea explicarla.
3. **Se usan como argumento de producto:** si casi el 5 % de los valores de un dataset real cae fuera de rango, una app que muestre todo en verde está mintiendo. Eso es exactamente lo que justifica el semáforo.
4. En el pitch: *"24 de 475 valores del propio dataset caen fuera de su rango de referencia. Nosotros no los interpretamos: los marcamos."*


### Citación

```
SpaceX Inspiration4 Blood Serum Metabolic Panel and Immune/Cytokine Panel.
NASA Open Science Data Repository, OSD-575.
```

---

## Reglas para añadir un dataset nuevo

1. Debe ser público y descargable sin cuenta.
2. Debe venir de NASA o de una agencia socia.
3. Se normaliza **con un script** en `scripts/`, nunca a mano.
4. Se documenta aquí: origen, qué contiene, limitaciones y citación.
5. El JSON incluye `meta.url` y `meta.obtenido` (fecha).
