# V.I.T.A.L.I.S. — Vital Information Telemetry and Life-support In Space

**Offline-first health-monitoring software that lets astronauts assess their own health on any space mission and act on it — including when no doctor can answer in time.**

> Built by Team **ROCKET** for the NASA International Space Apps Challenge *Create Health Monitoring Software for Astronauts on Space Missions* (Brazilian Space Agency / AEB).
> **Not a medical device.** V.I.T.A.L.I.S. does not diagnose, prescribe or replace a flight surgeon. See [Clinical safety](#clinical-safety).

| Overview (live vitals + 3D body) | 3D Body (organ-level triage) | Measure (guided, touch keypad) |
|---|---|---|
| ![Overview](docs/screenshots/overview.png) | ![3D body](docs/screenshots/body-3d.png) | ![Measure](docs/screenshots/measure.png) |
| **Wellbeing (NASA BHP)** | **Mission Control** | **Emergency protocols** |
| ![Wellbeing](docs/screenshots/wellbeing.png) | ![Mission Control](docs/screenshots/mission-control.png) | ![Emergency](docs/screenshots/emergency.png) |

---

## The problem

Wherever crews fly beyond quick help — a long stay on a space station, a lunar base, a transit to Mars, a deep-space or analog mission — a medical question cannot always wait for Earth. The further away the crew, the longer the round trip: on the Moon it is seconds, on a Mars transit up to ~22 minutes one-way, and any mission can lose its link. Astronauts are not doctors, yet when a crewmate shows chest pain the crew must decide alone. NASA's Human Research Program groups spaceflight risks into five hazards — **space radiation, isolation and confinement, distance from Earth, gravity fields, and hostile/closed environments** — and the challenge asks for a *visual tool that helps astronauts assess their own health and provides guidance on treatments and health improvements*.

## Not just for Mars, not just one mission

V.I.T.A.L.I.S. is mission-agnostic by design:

| Where | How it applies |
|---|---|
| Low Earth orbit / space station | Routine self-assessment, countermeasure tracking, emergency protocols, Earth sync with short delay |
| Moon and lunar base | The *environment* selector (ship · station · lunar base) changes which parameters and protocols matter |
| Mars and deep space | Full autonomy: offline operation, delayed/queued Earth link, on-board assistant, no cloud |
| Analog missions, polar stations, ships | Same measurement-baseline-triage loop with intermittent connectivity |
| Remote clinics on Earth | The deterministic, auditable triage and offline design transfer directly |

The parameter catalogue is **plug-and-play** (adding an indicator is adding one registry entry), thresholds are traceable and replaceable, and baselines come from whatever longitudinal data a mission has. NASA OSD-575 (Inspiration4) is the **real-data demonstration dataset** used to prove the loop — it is not a limit of the software.

## What V.I.T.A.L.I.S. does

1. **Guided measurement.** For each indicator the app explains *how to measure it in microgravity*, why it matters, and which failure modes give a false reading (e.g. air bubbles in a capillary cartridge at 0 g).
2. **Personal baseline.** Readings are compared against each astronaut's own trajectory, built from **NASA OSDR study OSD-575** (Inspiration4 comprehensive metabolic panel, crew C001–C004, timepoints L-92 … R+194), not only against population ranges.
3. **Deterministic traffic-light triage.** A pure, unit-tested Python rules engine (`backend/triage.py`) returns *level · reason · rule · action · source* for every value. No generative model ever produces a number.
4. **Interactive 3D body.** A VTK/OpenGL viewer with **172 anatomical meshes**; organs with out-of-range indicators pulse in their triage colour and can be touched for details.
5. **L.I.S. (Life-support In Space).** A floating on-device assistant that is grounded on the local data, remembers each astronaut, speaks English/Spanish, can drive the whole app by voice or text, warns calmly on *yellow* and urgently on *red*, and can request help. A strict validator rejects any number it was not given, and a deterministic fallback works with no network.
6. **Emergency mode.** Step-by-step protocols with a CPR metronome, procedural ALSP animations (AED, IV access, airway, drugs), an intermittent (non-alarming) red-state sound alarm, SBAR reports and a prioritised **A > B > C > D** queue to Earth with chained hashes.
7. **Wellbeing (NASA Behavioral Health & Performance).** Mission logbook, daily routine, PVT-B reaction test, Stroop cognition battery, sleep/circadian hygiene, badges, guided 4-4-4-4 decompression with Earth soundscapes, and a DSN link with simulated Earth–Mars delay.
8. **Mission Control.** Station and crew state at 1 Hz (simulated or OSD-575 replay), scenario injection, events/SBAR, mission log and the Earth sync queue.
9. **Fully touch-first, dark/light, bilingual (EN/ES) and offline** — SQLite on the crew workstation, no cloud.
10. **Also usable from a tablet** as a touch screen of the very same software ([`tablet/`](tablet/README.md)).

## Quick start

Requirements: Windows 10/11 (where it is developed and tested), Python ≥ 3.11 (3.13 tested), a GPU with OpenGL 3.2+.

```bash
git clone https://github.com/Charcraft/vitalis-astronaut-health.git
cd vitalis-astronaut-health
pip install -r requirements.txt
python vitalis_desktop.py          # starts the software (or double-click run-vitalis.bat)
```

Useful commands:

```bash
python vitalis_desktop.py --version                     # V.I.T.A.L.I.S. 1.2.0
python vitalis_desktop.py --test-init                   # headless start-up check of all subsystems
python -m unittest tests/test_new_backend_integration.py -v   # backend, triage, DB, Earth sync, BHP, touch UX
python -m unittest tests/test_tablet.py -v                    # tablet bridge: touch, text, audio, protocol
python scripts/auditoria_tablet.py                      # layout/touch audit of every view at touch-screen size
python scripts/normalizar-osdr.py                       # re-download and normalise NASA OSD-575
python scripts/demo_tour.py                             # exactly-2-minute guided tour (3D body, protocols, how the system reacts to a problem)
```

The local API (`FastAPI`, `127.0.0.1:8780`) starts with the app and exposes `/api/parameters`, `/api/triage`, `/api/telemetry/hub`, `/api/series`, `/api/episodios`, `/api/tierra`, `/api/export`, …

### On a tablet

The same software can be used from an Android tablet as a touch screen with its own keyboard, speaker and microphone: run `run-vitalis-tablet.bat` (or `python vitalis_tablet.py`). See [`tablet/README.md`](tablet/README.md).

## Documentation

| Document | What it explains |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the software works end-to-end (modules, data flow, triage, L.I.S., Earth sync, tablet bridge) |
| [`docs/TECH_STACK.md`](docs/TECH_STACK.md) | Every technology used, why, and what we deliberately did not use |
| [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) | NASA data used, other references, 3D model licences |
| [`docs/INDICATORS.md`](docs/INDICATORS.md) | The 15 clinical indicators, thresholds and their validation status |
| [`docs/AI_USE.md`](docs/AI_USE.md) | How Super Intelligence (SI) tools were used and what was never delegated |
| [`docs/prompts/`](docs/prompts/README.md) | **The prompts used with each AI harness during development, in order**, and the structure each one produced |
| [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | Timecoded narration for the exactly-2-minute guided demo (`scripts/demo_tour.py`) |
| [`docs/SUBMISSION_CONTENT.md`](docs/SUBMISSION_CONTENT.md) | The project-page answers prepared for the NASA Space Apps form (nothing has been submitted by this repository) |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history |

## Repository layout

```
vitalis_desktop.py      Main entry point (starts runtime, local API and the Qt interface)
vitalis_tablet.py       Tablet entry point (same software, touch client)
backend/                Triage engine, SQLite layer, 1 Hz runtime, Earth sync, L.I.S. agent, FastAPI
desktop/                PySide6 UI: views, 3D viewer, widgets, voice engine, i18n (en/es)
tablet/                 Touch-client bridge for tablets
recursos/datos/         seed (real NASA OSD-575), knowledge (protocols, guides), mock (cabin sensors)
recursos/modelos/       3D model catalogue, attribution and licences
tests/  scripts/        Automated tests and utilities (OSDR pipeline, touch audit)
docs/                   English documentation and screenshots
```

## Clinical safety

- The tool **never diagnoses, never names a drug or dose as advice, and is not a medical device.** The disclaimer is permanently visible in the app footer.
- Every numeric threshold either cites a source (see [`docs/INDICATORS.md`](docs/INDICATORS.md), [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md)) or is explicitly tagged **`[TO BE VALIDATED]`** (shown as `[POR VALIDAR]` in the Spanish sources/UI), **`[ASSUMPTION]`** or **`[INFERENCE]`**.
- Only de-identified public data are used (OSD-575 crew are anonymised as C001–C004 by the source).

## Credits and licences

Code: MIT ([`LICENSE`](LICENSE)). 3D anatomy: CC BY 4.0 with upstream credits in [`recursos/modelos/ATTRIBUTION.md`](recursos/modelos/ATTRIBUTION.md). NASA OSDR data are public. This project does not use NASA logos or mission identifiers. AI-assisted work is disclosed in [`docs/AI_USE.md`](docs/AI_USE.md).
