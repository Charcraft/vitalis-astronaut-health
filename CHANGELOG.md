# Changelog

## [1.2.0]

### Added
* **Tablet mode** (`tablet/`, `vitalis_tablet.py`): a tablet can act as the touch screen, keyboard, speaker and microphone of the software — dirty-region capture, JPEG over WebSocket, touch with inertia, pinch-zoom of the 3D viewer, keyboard sync, audio/microphone bridge. 16 automated tests and a layout/touch audit of every view.
* **Wellbeing module (NASA Behavioral Health & Performance)** with 8 sub-modules: Logbook, Routine, PVT-B, Cognition (Stroop), Sleep, Badges, Decompression (4-4-4-4 breathing + soundscapes) and DSN link; deterministic evaluator with `[TO BE VALIDATED]` thresholds; SQLite tables and export.
* Proactive L.I.S. warnings on **yellow** (calm, with actions) and **red** (urgent), a configurable intermittent soft red alarm, live Overview waveforms and a BPM-synchronised hospital-style heartbeat tone.
* Database panels in Mission Control: events & SBAR, mission log and the Earth queue (A > B > C > D, chained hashes).

### Fixed
* *Measure*: the numeric keypad overlapped in short windows; keys compact below 860 px and the column scrolls by touch.
* Voice and proactive alerts consistency (configured voice honoured, offline SAPI fallback), settings persistence, sharp multi-resolution icon.

## [1.1.0]
* 3D viewer with **172 meshes** (BodyParts3D + HRA eyes), FOV framing, X-ray skin, organ picking and triage pulsing.
* Proactive assistant, red-state alarm and configurable settings, touch-first UX.

## [1.0.0]
* Unified Python backend (SQLite WAL, 26-parameter registry, deterministic triage, 1 Hz runtime, Earth sync, FastAPI), Mission Control, English/Spanish packs, ALSP procedural animations.

## Pre-release
* Design mock-up, OSD-575 pipeline, first web prototype (archived) and the decision to ship native software (PySide6 + VTK).
