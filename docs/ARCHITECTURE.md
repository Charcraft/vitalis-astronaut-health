# Architecture — how V.I.T.A.L.I.S. works

V.I.T.A.L.I.S. is a **single-process, offline-first desktop application** written in Python. One command (`python vitalis_desktop.py`) starts the data runtime, a local API and the Qt user interface. There is no cloud service, container or web server to deploy.

```
                          ┌──────────────────────── desktop/ (PySide6 + VTK) ────────────────────────┐
 touch / mouse / voice ─► │ main_window  ─ views (Overview, 3D Body, Measure, History, Wellbeing,     │
                          │ Mission Control, Emergency, Settings) ─ L.I.S. dock ─ avisos (alerts)     │
                          │ viewer3d (172 meshes) ─ voice_engine (BPM audio, alarm, TTS, STT)         │
                          └───────────────▲───────────────────────────────┬───────────────────────────┘
                                          │ Qt signals (state.py)         │ direct calls
                          ┌───────────────┴───────────────────────────────▼───────────────────────────┐
                          │ backend/                                                                   │
                          │  registry.py  catalogue of 26 plug-and-play parameters                    │
                          │  triage.py    deterministic rules engine (pure functions)                 │
                          │  runtime.py   1 Hz loop → telemetry.py → crew_hub.py (C001–C004)          │
                          │  database.py  SQLite WAL (data/vitalis.db)                                │
                          │  sync_tierra.py  Earth queue A>B>C>D with chained djb2 hashes             │
                          │  lis_agent.py L.I.S. grounding, validator, deterministic fallback         │
                          │  server.py    FastAPI REST/SSE on 127.0.0.1:8780                          │
                          └───────────────▲───────────────────────────────────────────────────────────┘
                                          │ seed / knowledge / mock (recursos/datos)
                                  NASA OSDR OSD-575 · protocols · cabin sensors
```

## 1. Data layer (`backend/database.py`, `recursos/datos/`)

* **`seed/osdr-inspiration4-cmp.json`** — real NASA OSDR **OSD-575** comprehensive metabolic panel for four Inspiration4 crew members (anonymised **C001–C004**), seven timepoints (L-92, L-44, L-3, R+1, R+45, R+82, R+194). Produced by `scripts/normalizar-osdr.py` and never edited by hand.
* **`knowledge/`** — emergency protocols (ES/EN), ALSP equipment, trigger-to-protocol maps, indicator guides.
* **`mock/`** — simulated cabin sensors. **Mock data is never mixed with real data**; every value carries its origin (`osdr` or `simulado`).
* **SQLite (WAL)** stores OSDR analytes, manual measurements, the 1 Hz sensor stream with `1min`/`1h` aggregates, triage episodes, SBAR events, the mission log, the Earth queue, mental-health assessments, gamification, astronaut memory and settings.

## 2. Parameter registry (`backend/registry.py`)

A *plug-and-play* catalogue of **26 parameters** — 17 real OSDR analytes and 9 continuous/cabin signals — each with unit, system, data source, relevant environments (ship / station / lunar base), the 3D mesh it maps to, the animation that teaches the measurement, a normal range, and a traceable source. Adding a parameter is adding one entry; triage, the 3D viewer and the UI pick it up.

## 3. Triage engine (`backend/triage.py`)

`evaluar_lectura_determinista(crew, parameter, value, quality, environment, sex)` is a **pure function**:

1. Compares the value with the reference range of the parameter and with the astronaut's **personal baseline** (pre-flight mean of L-92, L-44, L-3).
2. Applies the rule set (critical / attention / nominal), including sex-specific hypotheses tagged `[TO BE VALIDATED]`.
3. **Degrades the level when signal quality is below 0.5** (noisy microgravity readings are never trusted blindly).
4. Returns `level, rule, reason, action, source, unit`.

Because it is deterministic and covered by unit tests, a jury (or a flight surgeon) can audit any decision. No language model is involved in producing a number.

## 4. Real-time runtime and Mission Control (`backend/runtime.py`, `crew_hub.py`, `telemetry.py`)

A 1 Hz loop publishes frames for stations **C001–C004** in either *simulated* or *OSD-575 replay* mode and for three environments (ship, station, lunar base). Anomalies can be injected for demos. The crew hub evaluates every frame with the triage engine, keeps active alerts per crew member and supports isolating a station. The **Mission Control** view exposes this in five touch steps (Station & live · Scenario · Events & SBAR · Mission log · Earth queue).

## 5. Earth link (`backend/sync_tierra.py`)

Events, measurements and log entries are queued with priority **A > B > C > D** and written to `lotes.jsonl` with a **chained djb2 hash**, so loss or tampering is detectable. The link can be switched online/offline; on reconnection the queue flushes in priority order. Delay to Earth (Mars case) is simulated and labelled `[ASSUMPTION]`.

## 6. L.I.S. — the on-board assistant (`backend/lis_agent.py`, `desktop/lis_dock.py`, `desktop/voice_engine.py`)

* **Grounding.** A snapshot of the current screen, crew member, timepoint, environment, alerts and recent measurements is built from the database; the assistant only talks about that.
* **No invented numbers.** A post-generation validator rejects any numeral not present in the snapshot; a deterministic JSON fallback answers with no network. An optional cloud or local (Ollama-compatible) model can be configured, but is never required.
* **Control of the app.** Intents map to navigation, 3D focus, measurements, settings, emergency protocols, SBAR, alarm silencing, theme and language.
* **Proactive.** On **yellow** it advises calmly with concrete actions; on **red** it is urgent and the alarm sounds (intermittent soft tone, configurable).
* **Voice.** English/Spanish segments are detected and voiced separately; speech-to-text is local (`faster-whisper`); text-to-speech uses `edge-tts` with an offline Windows SAPI fallback. A local voice-clone server is supported but not included.

## 7. User interface (`desktop/`)

Eight touch-first views (targets ≥ 52 px, verified ≥ 44 px on a tablet-size audit), dark and light themes (QSS), English/Spanish packs (`desktop/locales/*.json`), live waveforms drawn with `QPainter`, and a **shared VTK viewer** reused by Overview and 3D Body. The viewer builds 172 meshes from a binary pack (`desktop/assets/anatomy-male.{bin,json}`), renders the skin as translucent X-ray, picks organs with `vtkCellPicker`, frames the body by field of view, lowers quality while the camera moves, and pulses organs that have out-of-range indicators in their triage colour.

## 8. Wellbeing / NASA BHP (`desktop/salud_mental.py`)

Eight sub-modules (Logbook, Routine, PVT-B, Cognition/Stroop, Sleep, Badges, Decompression, DSN link) persisted in SQLite and evaluated by `evaluar_salud_mental_determinista()`. Thresholds are tagged `[TO BE VALIDATED]` where no primary source was available.

## 9. Tablet bridge (`tablet/`)

The same desktop app runs on the PC; the tablet is its screen. The window is rendered at the tablet's resolution and density (read through ADB), only *dirty regions* are captured (Qt `render()` plus a VTK frame grab), JPEG-encoded and sent over a WebSocket (`adb reverse`, localhost) with acknowledgement-based flow control. Touch, drag with inertia, pinch-zoom of the 3D viewer, the Android keyboard, speaker audio and microphone are mapped back to the real widgets. See [`tablet/README.md`](../tablet/README.md).

## 10. Testing

* `tests/test_new_backend_integration.py` — triage, registry, database, 1 Hz runtime, Earth sync, BHP evaluator, i18n, touch-size geometry.
* `tests/test_tablet.py` — touch gestures, scrolling, text entry, audio/microphone shims, protocol, pixel-exact partial repaint.
* `scripts/auditoria_tablet.py` — opens every view/sub-panel at tablet size and reports overlaps, clipped controls and touch targets < 44 px.
