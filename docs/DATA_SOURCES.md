# Data sources, references and licences

Every threshold, range or figure in the application traces to a source below, or is tagged `[TO BE VALIDATED]` / `[ASSUMPTION]` / `[INFERENCE]`. Only de-identified public data are used.

## NASA data and resources (required for a Global Award)

| # | Resource | How it is used |
|---|---|---|
| 1 | **NASA Open Science Data Repository (OSDR) — study OSD-575**, Inspiration4 comprehensive metabolic panel — <https://osdr.nasa.gov/bio/repo/data/studies/OSD-575> | Real longitudinal blood chemistry of four crew members (anonymised C001–C004): 17 analytes, 7 timepoints L-92 … R+194. Normalised to `recursos/datos/seed/osdr-inspiration4-cmp.json` by `scripts/normalizar-osdr.py`. Drives personal baselines, OSD-575 replay mode, charts and triage. |
| 2 | NASA Human Research Program — *5 Hazards of Human Spaceflight* — <https://www.nasa.gov/hrp/hazards/> | Organising framework: every indicator maps to one of the five hazards. |
| 3 | NASA HRP — *Risks of Human Spaceflight* — <https://www.nasa.gov/hrp/risks/> | Traces hazards to physiological risks and escalation criteria. |
| 4 | NASA HRP — behavioral health & performance resources | Basis of the Wellbeing module (PVT-B, sleep, isolation/confinement). Thresholds not backed by a primary source are tagged `[TO BE VALIDATED]`. |
| 5 | NASA Space Apps 2026 challenge resources — *Health Monitoring Software* — <https://www.spaceappschallenge.org/2026/challenges/health-monitoring-software/> | Challenge statement and objectives. |

OSD-575 context: *Inspiration4 data access through the NASA OSDR* — <https://pmc.ncbi.nlm.nih.gov/articles/PMC11094041>; *The NASA OSDR: Biomedical FAIR Data* — <https://ntrs.nasa.gov/citations/20230014168>.

## Space agency partner references

* Canadian Space Agency — *Monitoring Radiation for Astronaut Health* — <https://www.asc-csa.gc.ca/eng/news/articles/2026/2026-02-26-monitoring-radiation-astronaut-health.asp> (cumulative-dose indicator rationale).
* Canadian Space Agency — *Why Do We Conduct Science Experiments in Space?* — <https://www.asc-csa.gc.ca/eng/eng/iss/science/why-do-we-conduct-science-experiments-in-space.asp>.

## 3D anatomy (172 meshes)

| Source | Licence | Use |
|---|---|---|
| BodyParts3D 4.0 (Database Center for Life Science) — <https://dbarchive.biosciencedbc.jp/data/bodyparts3d/LATEST/> | CC BY 4.0 | Underlying male anatomy (about 2,200 meshes grouped into named structures). |
| open-anatomy-3d (pipeline and packaging of BodyParts3D) — <https://github.com/MervinR07/open-anatomy-3d> | CC BY 4.0 / MIT | Decimated, grouped and compressed male body used as the base. |
| Human Reference Atlas 3D Reference Objects (HuBMAP / Indiana University), `eye-male-left/right` v1.3, model by Kristen Browne (NIH/NIAID) — <https://humanatlas.io/3d-reference-library> | CC BY 4.0 | Eyes with sclera, cornea, lens, retina, macula and optic disc (needed to explain SANS); extra organ complements. |

Full credit text and file-level provenance: [`recursos/modelos/ATTRIBUTION.md`](../recursos/modelos/ATTRIBUTION.md) and [`LICENSE-MODELS.md`](../recursos/modelos/LICENSE-MODELS.md). The runtime pack is `desktop/assets/anatomy-male.{bin,json}`; the catalogue is `recursos/modelos/catalog.json`. CC BY-SA sources (Z-Anatomy, Écorché) were audited and **not** used to keep the repository's licensing clean.

## Open-source libraries

PySide6 (LGPLv3), VTK (BSD-3-Clause), FastAPI (MIT), Uvicorn (BSD-3-Clause), Pydantic (MIT), httpx (BSD-3-Clause), NumPy (BSD-3-Clause), faster-whisper (MIT), sounddevice (MIT), soundfile (BSD-3-Clause), edge-tts (GPLv3), websockets (BSD-3-Clause), OpenCV (Apache-2.0, optional).

## Clinical references

Population reference ranges (heart rate, blood pressure, SpO₂, respiratory rate, temperature, glucose, sleep) are standard adult clinical ranges; in-flight adjustments are `[TO BE VALIDATED]`. See [`INDICATORS.md`](INDICATORS.md) for per-indicator status.

## Content that is not included

No NASA logos, flags or mission identifiers are used. No images or recordings of people under 18. No identifiable astronaut data. No copyrighted media; voice assets are generated at run time.
