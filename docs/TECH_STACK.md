# Technology stack

Native desktop application, 100 % Python, offline-first. Versions below are the ones verified on the development machine (Windows 11).

## Constraints that drive the stack

| Constraint | Consequence |
|---|---|
| Mars transit: ~22 min one-way delay, no reliable link | **Offline-first**: everything runs locally; the cloud is never required. |
| Touch-first crew workstation, low latency | Native Qt UI (no browser, no Electron), ≥ 52 px touch targets. |
| Interactive anatomy, organ-level picking | VTK/OpenGL renderer with 172 real meshes, with a vector fallback. |
| Auditable by a jury | Pure deterministic triage engine, SQLite traceability, reproducible `unittest` suites. |
| Open source | Every main dependency is open source; AI features have a deterministic local fallback. |

## Application

| Layer | Technology | Why |
|---|---|---|
| Runtime | **Python 3.13** (≥ 3.11) | One language for UI, signal processing, local server and data scripts. |
| UI framework | **PySide6 6.12** (Qt 6, QSS themes) | Stable native window, dark/light themes, touch sizing, `QPainter` live charts. |
| 3D anatomy | **VTK 9.7** OpenGL via `QVTKRenderWindowInteractor`, NumPy | 172 meshes (`desktop/assets/anatomy-male.{bin,json}`), `vtkCellPicker`, depth peeling, FOV framing. |
| Live charts | `QPainter` (`desktop/widgets.py`) | Background waveforms behind vitals/cabin values and longitudinal OSD-575 charts, no web stack. |
| Audio / voice | **sounddevice**, **soundfile**, **faster-whisper** (local STT), **edge-tts** (TTS), Windows SAPI fallback, optional XTTS v2 | Hospital-style BPM tone, soft intermittent red alarm, biophilic `.wav` soundscapes, bilingual speech. |
| Local database | **SQLite (WAL)** | Persists OSD-575, measurements, 1 Hz series and aggregates, SBAR episodes, mission log, settings. |
| Local API | **FastAPI 0.141 + Uvicorn 0.52** (`127.0.0.1:8780`), httpx, Pydantic 2 | REST/SSE for parameters, triage, telemetry hub, series, episodes, Earth queue, export. |
| Assistant | `backend/lis_agent.py` | Grounded answers, numeric validator, deterministic fallback; optional cloud/local LLM. |
| Tablet bridge | FastAPI WebSocket, OpenCV (optional) JPEG, HTML/JS client (Canvas, Pointer Events, Web Audio, `getUserMedia`) | Runs the same app on an Android tablet over USB. |

## Data

| Dataset / resource | Use |
|---|---|
| **NASA OSDR OSD-575** (Inspiration4 CMP) | 17 real analytes × 4 crew × 7 timepoints; personal baselines and reference ranges. |
| NASA Human Research Program (5 hazards, risks) | Organising framework for indicators and escalation. |
| Open 3D anatomy (BodyParts3D, HRA, open-anatomy-3d; CC BY 4.0) | The 172-mesh body model. See [`DATA_SOURCES.md`](DATA_SOURCES.md). |

## What we deliberately did not use

| Discarded | Reason |
|---|---|
| Web app / Electron / cloud hosting | Adds latency and a network dependency. (An earlier Next.js prototype was archived and replaced by the native app on 2026-11-14.) |
| Mandatory embedded LLM | Multi-GB downloads break reproducibility; L.I.S. uses an optional API plus a deterministic local fallback. |
| Remote multi-tenant authentication | Crew stations (C001–C004) switch instantly with local isolation. |
| Docker / Kubernetes / microservices | The whole system starts with one command. |

## Commands

```bash
pip install -r requirements.txt
python vitalis_desktop.py                         # app
python vitalis_desktop.py --test-init             # headless subsystem check
python -m unittest tests/test_new_backend_integration.py -v
python -m unittest tests/test_tablet.py -v
python vitalis_tablet.py                          # tablet mode
```
