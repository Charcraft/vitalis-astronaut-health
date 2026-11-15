# Prompts — Backend Architecture, OSDR CMP Analytes, Multi-Environment & Sync Pipeline (`feat/backend`)

Prompts used by the **Backend & Data engineering track (Back 1 & Back 2)** during the hackathon (Nov 14–15, 2026) to design, document and implement the unified backend architecture (`backend/registry.py`, `backend/triage.py`, `backend/database.py`, `backend/realtime.py`, `backend/crew_hub.py`, `backend/sync_tierra.py`, `backend/runtime.py`, and `backend/server.py`).

Original prompts are recorded verbatim in Spanish with their English translation and the complete technical specification and code artifacts each prompt produced.

---

## Summary of the 5 Backend Prompts

| ID | Title | Core Target in Codebase |
|---|---|---|
| **BK-01** | **Arquitectura y acoplamiento de frentes** (*Backend architecture and domain coupling*) | Separation of **Back 1** (`registry.py`, `realtime.py`, `crew_hub.py`) and **Back 2** (`database.py`, `triage.py`, `sync_tierra.py`), shared contracts, and integration points in `runtime.py` |
| **BK-02** | **Adaptación multi-entorno** (*Multi-environment adaptation model*) | Mission environments `nave` (26 params), `estacion` (26 params), and `base-lunar` (25 params, omitting `intracranial_pressure_est`) grounded in NASA HRP |
| **BK-03** | **Documentación de los 17 analitos OSDR** (*Documentation of the 17 NASA OSDR `OSD-575` CMP analytes*) | Clinical function, unit, reference range, laboratory method, and flight examples (`Inspiration4` `C001–C004`, `L-92` to `R+194`) in `backend/registry.py` and `osdr-inspiration4-cmp.json` |
| **BK-04** | **Contrato de integración front-back** (*Front-end / Back-end REST integration contract*) | Complete REST & SSE API specification implemented in `backend/server.py` (`127.0.0.1:8780`) |
| **BK-05** | **Pipeline de ingesta y sincronización** (*End-to-end ingestion and synchronization pipeline*) | `StreamEngine (1 Hz) → Triage → CrewHub → SQLite WAL (single write boundary) → SyncTierraManager (A>B>C>D + chained djb2 hash)` |

---

## BK-01 · Arquitectura y acoplamiento de frentes (*Backend architecture and domain coupling*)

> **Original (ES):** `"Proporciona un análisis de la arquitectura del backend, detallando los módulos, los contratos de datos compartidos y las dependencias entre frentes. Determina si los dominios Back 1 y Back 2 pueden desarrollarse de forma independiente, identificando explícitamente los puntos de acoplamiento, los riesgos de integración y los contratos que deben congelarse antes del desarrollo paralelo"`
>
> **English:** *"Provide an analysis of the backend architecture detailing the modules, shared data contracts, and dependencies across tracks. Determine whether the Back 1 and Back 2 domains can be developed independently, explicitly identifying coupling points, integration risks, and the contracts that must be frozen before parallel development."*

### Technical Documentation & Architectural Output (`BK-01`)

#### 1.Verdict on Parallel Independence (`Back 1` vs. `Back 2`)
**Yes — `Back 1` and `Back 2` can be developed in parallel with zero file collisions**, provided three shared data contracts are frozen upfront (`ParameterDefinition`, `RealtimeTelemetryFrame`, and `EvaluacionTriage`) and `backend/runtime.py` (`VITALISRuntime`) acts as the single *Composition Root* wiring both tracks together.

| Track | Scope & Modules | Responsibility |
|---|---|---|
| **Back 1 · Catálogo, Flujo 1 Hz y Hub Multi-Estación** | `backend/registry.py`<br>`backend/realtime.py`<br>`backend/crew_hub.py`<br>`backend/telemetry.py` | Plug & Play 26-parameter catalogue, 3D mesh/animation mapping (`meshNodeId`, `toolAnimationId`), deterministic 1 Hz signal generation (`SimulatedSource` / `OsdrReplaySource`), anomaly injection, and multi-station crew hub (`C001–C004`). |
| **Back 2 · Triage Determinista, Persistencia SQLite WAL y Cola Tierra** | `backend/triage.py`<br>`backend/knowledge.py`<br>`backend/database.py`<br>`backend/sync_tierra.py` | Pure deterministic triage rules, personal pre-flight baseline calculation (`L-92, L-44, L-3`), sensor quality degradation (`calidad < 0.5`), SQLite WAL single-write repository, and prioritized Earth sync queue (`A > B > C > D` with chained `djb2` hash). |
| **Composition Root & API Gateway** | `backend/runtime.py`<br>`backend/server.py`<br>`backend/lis_agent.py` | Wires `StreamEngine (1 Hz) → CrewHub → SQLite WAL → SyncTierraManager`, exposes REST/SSE endpoints, and feeds the grounded snapshot to `L.I.S.` |

#### 2. Frozen Contracts Required Before Parallel Development
1. **Contract 1 — `ParameterDefinition` (`backend/registry.py`):**
   - Keys: `id`, `nombre`, `unidad`, `unidadCanonica`, `sistema`, `sistemaVisual`, `categoria` (`bioquimico-osdr | biologico-fisico | ambiental`), `frecuencia`, `intervaloMs`, `rangoReferencia` (`min, max, criticoMin, criticoMax`), `rangoReferenciaPorSexo`, `meshNodeId`, `toolAnimationId`, `entornos`, `fuenteTrazable`, `fuenteUmbral`, `esDatoRealOSDR`.
2. **Contract 2 — `EvaluacionTriage` (`backend/triage.py`):**
   - Keys: `indicadorId`, `nombre`, `valorActual`, `unidad`, `baselinePreVuelo`, `desviacionPct`, `rangoReferencia`, `nivel` (`NOMINAL | ATENCION | CRITICO`), `reglaDisparada`, `razon`, `accionSugerida`, `fuente`, `calidad`, `degradado` (`bool`), `protocoloDisparadorId`, `meshNodeId`, `toolAnimationId`.
3. **Contract 3 — `RealtimeTelemetryFrame` (`backend/realtime.py`):**
   - Keys: `timestamp` (`ms`), `crewId` (`C001..C004`), `timepointMision` (`L-92..R+194`), `entorno` (`nave | estacion | base-lunar`), `modo` (`simulado | replay-osdr`), `lecturas` (`Dict[paramId, LecturaEvaluada]`), `estadoNodos3D` (`Dict[meshNodeId, EstadoNodo]`).

#### 3. Coupling Points & Integration Risks Mitigated
- **Coupling Point A (`realtime.py` → `triage.py`):** `StreamEngine.tick()` calls `evaluar_lectura_determinista()` for each emitted parameter. Mitigated by keeping `triage.py` a pure, stateless function module.
- **Coupling Point B (`runtime.py` → `database.py` & `sync_tierra.py`):** `VITALISRuntime` is the only caller that persists frames, opens/closes episodes, and enqueues batches for Earth.
- **Integration Risk (Canonical Units & IDs):** Prevented at startup by `validate_registry()` (`backend/registry.py`), which asserts unique IDs, non-empty traceable sources, non-inverted thresholds, and matching canonical units.

---

## BK-02 · Adaptación multi-entorno (*Multi-environment adaptation model*)

> **Original (ES):** `"Analiza la arquitectura del sistema de monitoreo de salud y propón un modelo de adaptación multi-entorno. Define tres contextos operativos nave en tránsito  estación orbital y base de superficie lunar  y determina, para cada uno, qué indicadores fisiológicos y ambientales son relevantes.  utiliza el programa de documentación humana de la nasa"`
>
> **English:** *"Analyse the architecture of the health-monitoring system and propose a multi-environment adaptation model. Define three operational contexts — transit spacecraft, orbital station, and lunar surface base — and determine which physiological and environmental indicators are relevant for each one, using NASA's Human Research Program documentation."*

### Technical Documentation & Multi-Environment Model (`BK-02`)

Implemented in `backend/registry.py` (`ENTORNOS_MISION = ("nave", "estacion", "base-lunar")` and `listar_por_entorno(entorno)`) and exposed in `desktop/vista_sala.py` and `POST /api/runtime/config`.

#### 1. Operational Contexts & NASA HRP Hazard Mapping

| Operational Context (`entorno`) | Gravity & Comms Profile | Dominant NASA HRP Hazards | Active Parameters (`listar_por_entorno`) | Key Physiological Rationale |
|---|---|---|---|---|
| **`nave`**<br>*(Deep-space transit spacecraft, e.g., Mars transit)* | **$0\text{ g}$ microgravity**<br>Up to **22 min** one-way light delay (`44 min` round-trip silence) | • Distance from Earth<br>• Space Radiation (GCR/SPE)<br>• Gravity Fields ($0\text{ g}$)<br>• Isolation & Confinement<br>• Hostile/Closed Environment | **26 / 26 parameters**<br>(17 OSDR CMP + 9 continuous/cabin, including `intracranial_pressure_est`) | Sustained $0\text{ g}$ drives cephalad fluid shift and **SANS** (*Spaceflight-Associated Neuro-ocular Syndrome*), requiring non-invasive intracranial/ocular estimation (`intracranial_pressure_est`), strict `cabin_co2` monitoring, `radiation_dose`, and full autonomy via local triage + SBAR Earth queue. |
| **`estacion`**<br>*(Orbital space station, e.g., ISS / Lunar Gateway)* | **$0\text{ g}$ microgravity**<br>Near-real-time LEO link or intermittent deep-space relay | • Gravity Fields ($0\text{ g}$)<br>• Hostile/Closed Environment<br>• Space Radiation<br>• Isolation & Confinement | **26 / 26 parameters**<br>(17 OSDR CMP + 9 continuous/cabin, including `intracranial_pressure_est`) | Continuous $0\text{ g}$ deconditioning (cardiovascular rounding, bone/calcium turnover `calcium` & `alkaline_phosphatase`, SANS `intracranial_pressure_est`) and closed-cabin `cabin_co2` pockets. |
| **`base-lunar`**<br>*(Lunar surface habitat, e.g., Artemis Base Camp)* | **$0.16\text{ g}$ partial gravity**<br>$~1.3\text{ s}$ delay (or blackout on lunar far side) | • Gravity Fields ($0.16\text{ g}$ transitions)<br>• Hostile Environment (regolith/EVA)<br>• Space Radiation | **25 / 26 parameters**<br>(17 OSDR CMP + 8 continuous/cabin; **omits `intracranial_pressure_est`**) | Partial gravity ($0.16\text{ g}$) restores a hydrostatic gradient compared to $0\text{ g}$, so `intracranial_pressure_est` is filtered out by `listar_por_entorno("base-lunar")`, while EVA cardiopulmonary load (`heart_rate`, `spo2`, `respiratory_rate`, `systolic_bp`, `diastolic_bp`), renal/hydration markers (`creatinine`, `urea_nitrogen_bun`, `calcium`), and surface `radiation_dose` remain critical. |

---

## BK-03 · Documentación de los 17 analitos OSDR (*Documentation of the 17 NASA OSDR `OSD-575` CMP analytes*)

> **Original (ES):** `"Documenta los 17 analitos del panel metabólico completo (CMP) del dataset NASA OSDR OSD-575. Para cada analito, especifica: función clínica, unidad, rango de referencia, método de laboratorio de obtención y relevancia . Añade ejemplos de uso en viajes ya realizados"`
>
> **English:** *"Document the 17 analytes of the Comprehensive Metabolic Panel (CMP) from the NASA OSDR OSD-575 dataset. For each analyte, specify: clinical function, unit, reference range, laboratory acquisition method, and spaceflight relevance. Include examples of use from completed spaceflight missions."*

### Technical Documentation of the 17 NASA OSDR `OSD-575` Analytes (`BK-03`)

All 17 analytes are normalized from **NASA Open Science Data Repository Study `OSD-575`** (*SpaceX Inspiration4 Blood Serum Comprehensive Metabolic Panel*, crew `C001–C004`, 7 mission timepoints: pre-flight `L-92, L-44, L-3` and post-flight `R+1, R+45, R+82, R+194`) in `recursos/datos/seed/osdr-inspiration4-cmp.json` and registered in `backend/registry.py` (`PARAMETROS_OSDR`).

| # | Analyte ID (`registry.py`) | Name (EN / ES) | Unit | `OSD-575` Reference Range | Lab Acquisition Method | Clinical Function & Spaceflight Relevance (NASA HRP) | Real Spaceflight Example (`OSD-575` Inspiration4 / ISS) |
|---|---|---|---|---|---|---|---|
| 1 | `albumin` | Albumin (*Albúmina*) | `g/dL` | `3.6 – 5.1` | Colorimetric (Bromocresol Green / Purple, venous serum or point-of-care cartridge) | Main plasma oncotic protein and negative acute-phase reactant. Tracks plasma volume contraction ($10\text{–}15\%$ shift in early microgravity), nutritional status, and hepatic synthesis. | In `OSD-575`, `C001` maintains `4.2–4.7 g/dL` across `L-92` to `R+194`, serving as a stable oncotic baseline during fluid redistribution. |
| 2 | `alkaline_phosphatase` | Alkaline Phosphatase (*Fosfatasa alcalina*, ALP) | `U/L` | `36.0 – 130.0` | Kinetic enzymatic assay ($p$-nitrophenyl phosphate substrate) | Marker of osteoblastic bone turnover and hepatobiliary integrity. In $0\text{ g}$, skeletal unloading accelerates bone resorption ($1\text{–}1.5\%$/month) followed by coupled ALP shifts. | Used on ISS and Inspiration4 (`OSD-575`) alongside calcium to track skeletal remodeling after orbital unloading. |
| 3 | `alt` | Alanine Aminotransferase (*ALT*) | `U/L` | `9.0 – 46.0` | Kinetic UV enzymatic assay (IFCC) | Cytosolic hepatocellular enzyme. Detects subclinical hepatic stress from spaceflight radiation, cephalad venous congestion, or onboard medication metabolism. | In `OSD-575`, `C003` at `R+1` records `19 U/L` (within `9–46 U/L`), confirming absence of acute hepatocellular injury post-splashdown. |
| 4 | `ast` | Aspartate Aminotransferase (*AST*) | `U/L` | `10.0 – 40.0` | Kinetic UV enzymatic assay (IFCC) | Enzyme present in liver, myocardium, and skeletal muscle. Elevated AST with normal ALT in spaceflight indicates **musculoskeletal strain** from resistive exercise (ARED) or EVA exertion. | In `OSD-575`, `C003` at `R+1` shows `18 U/L`; monitored in ISS crews after high-load resistive countermeasure sessions. |
| 5 | `total_bilirubin` | Total Bilirubin (*Bilirrubina total*) | `mg/dL` | `0.2 – 1.2` | Diazo colorimetric assay | Heme catabolism and hepatobiliary clearance marker. Crucial for monitoring **space anemia** (neocytolysis / increased red blood cell destruction in microgravity). | Inspiration4 (`OSD-575`) and ISS studies showed hemolysis/erythrocyte shifts upon entry and return from $0\text{ g}$. |
| 6 | `calcium` | Total Calcium (*Calcio*) | `mg/dL` | `8.6 – 10.3` | Colorimetric (Arsenazo III / $o$-cresolphthalein complexone) | Essential for neuromuscular excitability, cardiac conduction, and bone matrix. Microgravity bone demineralization dumps calcium into blood/urine, raising **renal stone risk** (*nephrolithiasis*). | Monitored across all 7 `OSD-575` timepoints; hypercalcemia/hypercalciuria is a primary NASA HRP Gravity Hazard risk. |
| 7 | `carbon_dioxide` | Total Carbon Dioxide (*$\text{CO}_2$ total / Bicarbonato*) | `mmol/L` | `20.0 – 32.0` | Enzymatic PEPC / ion-selective electrode | Reflects serum bicarbonate ($\text{HCO}_3^-$) and acid-base compensation. Detects chronic metabolic compensation for elevated cabin partial pressure of $\text{CO}_2$ (`cabin_co2`). | In closed spacecraft habitats (ISS/Dragon), mild hypercapnia shifts serum bicarbonate; tracked across `L-92..R+194` in `OSD-575`. |
| 8 | `chloride` | Chloride (*Cloruro*) | `mmol/L` | `98.0 – 110.0` | Indirect ion-selective electrode (ISE) | Major extracellular anion regulating osmolarity, fluid balance, and acid-base status alongside sodium and bicarbonate. | Used in `OSD-575` to evaluate post-landing dehydration and electrolyte replacement protocols. |
| 9 | `creatinine` | Creatinine (*Creatinina*) | `mg/dL` | `0.6 – 1.35`<br>*(Sex-specific `[POR VALIDAR]`: M `0.7–1.3`, F `0.5–0.95`)* | Alkaline picrate (Jaffé kinetic) or enzymatic creatininase | Byproduct of muscle creatine phosphate filtered by the glomerulus. Tracks **renal filtration** and **muscle mass changes** in microgravity. | In `OSD-575`, `C003` records `0.89 mg/dL` at `R+1`. `backend/triage.py` evaluates both the `OSD-575` range and sex-specific bounds. |
| 10 | `egfr_african_american` | eGFR (African American adjustment) | `mL/min/1.73m²` | `≥ 60.0` | Derived calculation (`CKD-EPI` equation from serum creatinine, age, sex) | Estimates glomerular filtration rate to screen for renal impairment resulting from dehydration, contrast/drugs, or obstructive nephrolithiasis in flight. | Included in the official `OSD-575` CMP dataset (`esDerivado=True` in `backend/registry.py`). |
| 11 | `egfr_non_african_american` | eGFR (Standard CKD-EPI) | `mL/min/1.73m²` | `≥ 60.0` | Derived calculation (`CKD-EPI` equation) | Primary functional index of kidney filtration capacity (`abdomen_hepatic_renal` 3D node). Values `< 60` trigger yellow/attention evaluation. | Tracked longitudinally in `OSD-575` (`L-92` to `R+194`) to verify renal recovery after orbital flight. |
| 12 | `globulin` | Globulin (*Globulina*) | `g/dL` | `1.9 – 3.7` | Derived calculation (`Total Protein − Albumin`) | Comprises immunoglobulins and transport proteins. Reflects **immune activation** or inflammation under space radiation and confinement. | Mapped to `systemic_immune_radiation` in `backend/registry.py`; `OSD-575` pairs it with cytokine/immune profiling. |
| 13 | `glucose` | Glucose (*Glucosa*) | `mg/dL` | `65.0 – 99.0` | Enzymatic hexokinase / glucose oxidase (or point-of-care capillary i-STAT) | Primary metabolic fuel for the CNS. Microgravity induces subclinical **insulin resistance** and stress-cortisol glycemic spikes; hypoglycemia is hazardous during EVA. | **Real `OSD-575` anomaly case used in V.I.T.A.L.I.S.:** `C003` rises from pre-flight baseline `71.3 mg/dL` to **`103 mg/dL` (+44.4%)** at `R+1` (and `36 mg/dL` at `R+45`). |
| 14 | `potassium` | Potassium (*Potasio*) | `mmol/L` | `3.5 – 5.3` | Ion-selective electrode (ISE) | Major intracellular cation governing **myocardial action potentials**. Hypokalemia or hyperkalemia predisposes astronauts to cardiac arrhythmias. | Mapped to `thorax_heart` in `backend/registry.py`. During Apollo 15, potassium deficit contributed to in-flight cardiac arrhythmias. |
| 15 | `total_protein` | Total Protein (*Proteína total*) | `g/dL` | `6.1 – 8.1` | Biuret colorimetric method | Sum of albumin and globulins; evaluates hemoconcentration from $0\text{ g}$ diuresis, nutritional adequacy, and systemic immune state. | Monitored across all 4 Inspiration4 crewmates (`C001–C004`) in `OSD-575`. |
| 16 | `sodium` | Sodium (*Sodio*) | `mmol/L` | `135.0 – 146.0` | Ion-selective electrode (ISE) | Primary determinant of extracellular osmolality and cerebral water balance. Dysnatremia directly impacts **neuro-cognitive performance** and intracranial pressure. | Mapped to `head_neuro_ocular` in `backend/registry.py`; audited in `OSD-575` where `24 / 475` total panel values fall outside reference bounds. |
| 17 | `urea_nitrogen_bun` | Blood Urea Nitrogen (*Nitrógeno ureico, BUN*) | `mg/dL` | `7.0 – 25.0` | Enzymatic urease / glutamate dehydrogenase | Hepatic urea cycle endpoint excreted by the kidneys. Elevations indicate **dehydration** (reduced thirst reflex in $0\text{ g}$) or accelerated muscle protein catabolism. | Evaluated alongside `creatinine` in `OSD-575` (`abdomen_hepatic_renal` node) to distinguish prerenal dehydration from intrinsic renal stress. |

---

## BK-04 · Contrato de integración front-back (*Front-end / Back-end REST integration contract*)

> **Original (ES):** `"Redacta un contrato de integración entre el frontend y el backend en formato Markdown, especificando: los endpoints REST con sus firmas de request/response."`
>
> **English:** *"Write a front-end / back-end integration contract in Markdown format, specifying the REST endpoints with their request and response signatures."*

### Technical Specification: REST & SSE Integration Contract (`backend/server.py`, `127.0.0.1:8780`) (`BK-04`)

#### 1. System Health & Catalogue
- **`GET /api/health`**
  - **Response `200 OK`:**
    ```json
    {
      "ok": true,
      "engine": "python-fastapi-sqlite",
      "project": "V.I.T.A.L.I.S.",
      "agent": "L.I.S. (Life-support In Space)",
      "database": "SQLite WAL (data/vitalis.db)",
      "dataset": "NASA OSDR OSD-575 (Inspiration4 CMP)",
      "jarvisVoiceCloneReady": false
    }
    ```
- **`GET /api/parameters?entorno={nave|estacion|base-lunar}&sistema={sistema}`**
  - **Response `200 OK`:**
    ```json
    {
      "ok": true,
      "total": 26,
      "osdr": 17,
      "simulados": 9,
      "parametros": [
        {
          "id": "glucose",
          "nombre": "Glucosa",
          "unidad": "mg/dL",
          "categoria": "bioquimico-osdr",
          "rangoReferencia": { "min": 65.0, "max": 99.0, "criticoMin": null, "criticoMax": null },
          "meshNodeId": "abdomen_hepatic_renal",
          "toolAnimationId": "anim_capillary_analyzer",
          "entornos": ["nave", "estacion", "base-lunar"],
          "esDatoRealOSDR": true
        }
      ]
    }
    ```

#### 2. Deterministic Triage & OSDR Baseline
- **`GET /api/osdr?crewId={C001..C004}&indicadorId={id}`**
  - **Response `200 OK`:** Returns either the full `dataset` + `cabina` + `guias` + `protocolos` bundle or the specific crewmember `baseline` (`mediaPreVuelo`, `desviacionPreVuelo`, `puntosPreVuelo`) and `anomalias`.
- **`POST /api/triage`**
  - **Request Body:**
    ```json
    {
      "crewId": "C003",
      "indicadorId": "glucose",
      "valor": 103.0,
      "calidad": 0.95,
      "entorno": "nave",
      "sexo": "F"
    }
    ```
  - **Response `200 OK`:**
    ```json
    {
      "indicadorId": "glucose",
      "valorActual": 103.0,
      "unidad": "mg/dL",
      "baselinePreVuelo": 71.33,
      "desviacionPct": 44.39,
      "nivel": "ATENCION",
      "reglaDisparada": "FUERA_RANGO_REFERENCIA_OSDR",
      "razon": "Valor 103.0 mg/dL fuera del rango de referencia (65.0–99.0 mg/dL).",
      "accionSugerida": "Repetir medición y registrar contexto...",
      "fuente": "OSDR OSD-575 (rango de referencia incluido en el dataset)",
      "calidad": 0.95,
      "degradado": false,
      "protocoloDisparadorId": null,
      "meshNodeId": "abdomen_hepatic_renal",
      "toolAnimationId": "anim_capillary_analyzer"
    }
    ```

#### 3. Real-Time 1 Hz Telemetry, Multi-Station Hub & Runtime Control
- **`GET /api/telemetry?crewId=C003&timepoint=R+1`** → `200 OK` single `RealtimeTelemetryFrame`.
- **`GET /api/telemetry/stream?crewId=C003&timepoint=R+1`** → `200 OK` (`text/event-stream` SSE pushing 1 Hz JSON frames).
- **`POST /api/telemetry`** → `202 Accepted` (`{"aceptado": true, "alertas": N}`) or `400 Bad Request` on invalid frame.
- **`GET /api/telemetry/hub`**
  - **Response `200 OK`:**
    ```json
    {
      "ok": true,
      "tripulantes": {
        "C001": { "crewId": "C001", "estadoEnlace": "online", "aislada": false, "nivelMaximo": "NOMINAL", "alertasActivas": [] }
      },
      "runtime": { "iniciado": true, "crewIdActiva": "C001", "entorno": "nave", "modo": "simulado" }
    }
    ```
- **`POST /api/telemetry/anomaly`**
  - **Request Body:** `{"crewId": "C001", "parametroId": "spo2", "nivel": "CRITICO", "duracionMs": 30000, "limpiar": false}`
  - **Response `200 OK`:** `{"ok": true, "anomaliasActivas": {...}, "frame": {...}}`
- **`POST /api/runtime/config`**
  - **Request Body:** `{"crewId": "C002", "entorno": "base-lunar", "modo": "replay-osdr", "aislarCrewId": "C004", "aislada": true}`
  - **Response `200 OK`:** `{"ok": true, "runtime": {...}}`

#### 4. Persistence: Measurements, Aggregated Series, Episodes & Protocols
- **`GET /api/measurements?crewId=C003`** & **`POST /api/measurements`** / **`POST /api/mediciones`**
  - Evaluates via `evaluar_lectura_determinista()`, writes to SQLite (`mediciones_locales` + `sensor_measurements`), and enqueues in `SyncTierraManager`.
- **`GET /api/series?crewId=C001&parametroId=heart_rate&resolucion={1min|1h}&desde={ms}&hasta={ms}`**
  - **Response `200 OK`:** `{"crewId": "C001", "total": N, "series": [{"bucketMs": ..., "min": ..., "max": ..., "media": ..., "muestras": ...}]}`
- **`GET /api/episodios?crewId=C001&soloAbiertos=false`** → `200 OK` (`{"total": N, "episodios": [...], "eventos": [...]}`).
- **`GET /api/protocolos?id={id}&parametroId={param}&nivel={ATENCION|CRITICO}`** → `200 OK` (`{"estado": "local", "total": N, "protocolos": [...]}`).

#### 5. Asynchronous Earth Link (`SyncTierraManager`) & Full Backup
- **`GET /api/sync/status`** → Returns pending counts by priority (`A, B, C, D`), `estadoRed` (`online | offline | degradado`), and last `djb2` chain hash.
- **`POST /api/sync/network`** → Request: `{"estado": "offline" | "online" | "degradado"}`.
- **`POST /api/sync/flush`** → Flushes pending queue in strict **`A > B > C > D`** priority order.
- **`GET /api/tierra`** & **`POST /api/tierra`** → Inspects or receives hash-chained downlink batches (`201 Created`, `{"ack": true, "id": "..."}`).
- **`GET /api/export?crewId={optional}`** → Complete JSON backup of all SQLite tables (`medicionesLocales`, `medicionesSensor`, `seriesAgregadas`, `episodios`, `eventosEmergencia`, `bitacora`, `colaSincronizacion`, `evaluacionesMentales`).

---

## BK-05 · Pipeline de ingesta y sincronización (*End-to-end ingestion and synchronization pipeline*)

> **Original (ES):** `"Continúa la implementación del pipeline de ingesta y sincronización:. El objetivo es un flujo de datos funcional de extremo a extremo, manteniendo la invariante de que repositories es el único punto de escritura en la base de datos local."`
>
> **English:** *"Continue implementing the ingestion and synchronization pipeline. The goal is a functional end-to-end data flow while maintaining the invariant that the repository layer is the single point of write access to the local database."*

### Technical Documentation of the End-to-End Pipeline (`BK-05`)

Implemented across `backend/runtime.py` (`VITALISRuntime`), `backend/database.py` (the single SQLite WAL write repository boundary), `backend/crew_hub.py` (`CrewHub`), and `backend/sync_tierra.py` (`SyncTierraManager`).

```
[SimulatedSource / OsdrReplaySource (1 Hz)]
                  │
                  ▼
     [StreamEngine.tick() (realtime.py)]
                  │  Evaluates every reading via pure backend/triage.py
                  ▼
     [VITALISRuntime._procesar_tick_crew() (runtime.py)]
                  │
      ┌───────────┼───────────────────────────────┐
      ▼           ▼                               ▼
[CrewHub]   [backend/database.py]        [SyncTierraManager]
(RAM/SSE)   (SINGLE SQLITE WRITE POINT)  (Priority Queue A>B>C>D)
                  │                               │
                  ├─► guardar_frame_bd()          ├─► encolar_evento()   [Priority A: CRITICO SBAR]
                  ├─► agregar_y_persistir_series()├─► encolar_medicion() [Priority A/B/C]
                  ├─► abrir_episodio() / cerrar() ├─► encolar_frame()    [Priority B/C]
                  └─► registrar_evento_emergencia()└─► encolar_bitacora()[Priority D]
                                                          │
                                                          ▼
                                             [Chained djb2 Hash → lotes.jsonl]
```

#### Key Architectural Invariants Enforced in Code:
1. **Single Write Boundary (`backend/database.py`):** Neither `StreamEngine`, `CrewHub`, nor the PySide6 UI views execute raw `INSERT`/`UPDATE` SQL statements. Every write passes through the repository functions in `backend/database.py` under `_DB_LOCK` (`threading.RLock()`) and `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`.
2. **Automatic Episode Lifecycle & SBAR Escalation (`VITALISRuntime._detectar_emergencia_y_episodios`):**
   - When a parameter transitions into `ATENCION` or `CRITICO`, `abrir_episodio()` opens or updates a persistent clinical episode.
   - When it transitions into `CRITICO`, `registrar_evento_emergencia()` creates a structured record and immediately calls `sync.encolar_evento(evt_id, "CRITICO")` at **Priority `A`**.
   - When the parameter returns to `NOMINAL`, `cerrar_episodio()` stamps `fin_ms`.
3. **Multi-Resolution Time-Series Rollups & Sliding Window Pruning:**
   - Raw 1 Hz frames are persisted every 5 seconds (or immediately on any `ATENCION`/`CRITICO` alert) into `sensor_measurements` and pruned to a 15-minute rolling window (`podar_ventana()`).
   - Every tick updates in-memory accumulators that flush `1min` and `1h` min/max/mean rollups (`agregar_y_persistir_series()`) into `telemetry_series`.
4. **Tamper-Evident Priority Queue to Earth (`SyncTierraManager`):**
   - Items are dequeued in strict priority order **`A` (critical emergency/SBAR) > `B` (attention/yellow) > `C` (nominal telemetry) > `D` (routine logbook)**.
   - Every transmitted batch computes a deterministic **`djb2` chained hash** (`djb2_hash(f"{prev_hash}|{id}|{prioridad}|{tipo}|{creadoEn}|{payload_json}")`), ensuring that when the link to Earth (`online`) is restored after a 22-minute Mars transit delay, the Flight Surgeon can verify the exact chronological integrity of all onboard events.
