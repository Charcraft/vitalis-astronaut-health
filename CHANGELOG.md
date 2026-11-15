# Changelog

## [1.2.0] — 2026-11-15

### Added
* **Android tablet mode** (`tablet/`, `vitalis_tablet.py`): the real app runs on the PC and an Android tablet is its touch screen, keyboard, speaker and microphone — dirty-region capture, JPEG over WebSocket (`adb reverse`), touch with inertia, pinch-zoom of the 3D viewer, Android keyboard sync, audio/microphone bridge. 16 automated tests and a layout/touch audit of every view.
* **Wellbeing module (NASA Behavioral Health & Performance)** with 8 sub-modules: Logbook, Routine, PVT-B, Cognition (Stroop), Sleep, Badges, Decompression (4-4-4-4 breathing + soundscapes) and DSN link; deterministic evaluator with `[TO BE VALIDATED]` thresholds; SQLite tables and export.
* Proactive L.I.S. warnings on **yellow** (calm, with actions) and **red** (urgent), a configurable intermittent soft red alarm, live Overview waveforms and a BPM-synchronised hospital-style heartbeat tone.
* Database panels in Mission Control: events & SBAR, mission log and the Earth queue (A > B > C > D, chained hashes).

### Fixed
* *Measure*: the numeric keypad overlapped at ~800 px window height; keys compact below 860 px and the column scrolls by touch.
* Voice and proactive alerts consistency (configured voice honoured, offline SAPI fallback), settings persistence, sharp multi-resolution icon.

## [1.1.0] — 2026-11-15
* 3D viewer with **172 meshes** (BodyParts3D + HRA eyes), FOV framing, X-ray skin, organ picking and triage pulsing.
* Proactive assistant, red-state alarm and configurable settings, touch-first UX.

## [1.0.0] — 2026-11-15
* Unified Python backend (SQLite WAL, 26-parameter registry, deterministic triage, 1 Hz runtime, Earth sync, FastAPI), Mission Control, English/Spanish packs, ALSP procedural animations.

## Pre-release — 2026-11-14
* Design mock-up, OSD-575 pipeline, first web prototype (archived) and the decision to ship a **native desktop application** (PySide6 + VTK).
