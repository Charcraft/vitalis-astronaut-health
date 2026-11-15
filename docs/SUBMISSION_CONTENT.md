# NASA Space Apps — project page content (prepared, not submitted)

Ready-to-paste answers for the Space Apps project form, matching the *Project Submission Guide* (English only, public links without login). **This repository does not submit anything to the NASA Space Apps site;** a team member pastes these answers and presses "Submit for Judging" before **Sunday, November 15, 2026, 11:59 p.m. (local time of the Local Event)**.

## Project Name

```
V.I.T.A.L.I.S. — Vital Information Telemetry and Life-support In Space
```

## High-Level Project Summary

```
V.I.T.A.L.I.S. is an offline-first health-monitoring application that lets astronauts assess their own health on long-duration missions and act on it — even when no doctor on Earth can answer in time.

On a long mission — a lunar base, a Mars transit (up to ~22 minutes one-way), any link loss — astronauts are not doctors and cannot always wait for Earth. V.I.T.A.L.I.S. turns a health decision into three steps: a guided measurement (including how to take it in microgravity), a comparison against the astronaut's own baseline built from NASA's open spaceflight data (OSDR OSD-575), and a single green-yellow-red call with a concrete next action and a cited source. An interactive 3D body of 172 anatomical meshes makes the affected organs pulse in their triage colour, and an on-board assistant, L.I.S., speaks English and Spanish, never invents a number, warns calmly on yellow and urgently on red, and can run the whole app by voice.

Routine mode tracks indicators, wellbeing (NASA behavioral-health tests, sleep, decompression) and mission schedule. Emergency mode becomes a step-by-step protocol with a CPR metronome, procedural animations, an SBAR report and a prioritised queue to Earth. It runs fully offline on a touch workstation or tablet, and is not tied to one mission: station, Moon, Mars or deep space.

It does not diagnose and is not a medical device.
```

## Link to Project Demo

```
TO BE ADDED BY THE TEAM — public link (no login) to a ≤ 30-second video or a ≤ 7-slide deck in English.
```

## Link to Final Project

```
https://github.com/Charcraft/vitalis-astronaut-health
```
(Run it with `pip install -r requirements.txt && python vitalis_desktop.py`.)

## Detailed Project Description

```
WHAT IT DOES
V.I.T.A.L.I.S. is native, offline-first software for astronaut self-assessment on any space mission. It covers 26 plug-and-play parameters — 17 real analytes from NASA OSDR study OSD-575 and 9 continuous vital/cabin signals — organised around the five hazards of human spaceflight defined by NASA's Human Research Program: space radiation, isolation and confinement, distance from Earth, gravity fields and hostile/closed environments.

For every indicator the app explains how to measure it in microgravity and why it matters, and shows its trajectory and status on an interactive OpenGL 3D body (172 meshes) where each organ can be touched.

HOW IT WORKS
1. Guided measurement and live Overview: live waveforms behind the vital signs, hospital-style heartbeat audio that follows the BPM, and 0 g procedures with the failure modes that cause false readings.
2. Personal baseline: each reading is compared with the astronaut's own longitudinal data from OSD-575 (crew C001–C004, timepoints L-92 to R+194), not only with population ranges.
3. Deterministic triage: a pure, unit-tested Python rules engine returns level, reason, rule, action and source for every value; poor signal quality degrades the level. No generative model produces a number.
4. L.I.S., the on-board assistant: grounded on the local database, with memory per astronaut, bilingual voice, local speech recognition and the ability to control the whole app; a validator rejects any number it was not given and a deterministic fallback works offline.
5. Escalation and Mission Control: yellow triggers calm proactive guidance; red triggers an intermittent soft alarm, the emergency protocol and a prioritised A>B>C>D queue to Earth with chained hashes; Mission Control shows crew stations at 1 Hz (simulated or OSD-575 replay).
6. Emergency protocols: step-by-step checklists with a CPR metronome and vector ALSP animations (AED, IV access, airway, drugs).
7. Wellbeing (NASA BHP): logbook, routine, PVT-B reaction test, Stroop cognition battery, sleep/circadian hygiene, badges, 4-4-4-4 decompression and a DSN link with simulated Earth–Mars delay.
8. Offline-first: SQLite persistence on the crew workstation, no cloud. Touch-first, dark/light, English/Spanish. A tablet can be used as a touch client of the same software.

WHY IT MATTERS
On long missions astronauts carry much of the responsibility for noticing changes in themselves. V.I.T.A.L.I.S. gives the crew what they lack: a structured way to measure and a defensible way to decide. It does not diagnose and does not replace a flight surgeon.

BENEFITS
- Shorter decisions in an emergency through touch checklists and real-time timers.
- Every threshold traces to a source or is explicitly tagged [TO BE VALIDATED]; nothing is invented.
- Auditable: deterministic triage and 38 automated tests.
- The same offline-first design applies to remote Earth clinics with intermittent connectivity.

WHAT WE HOPE TO ACHIEVE
A working prototype of the complete loop — measure, compare, decide, act, log — plus behavioral well-being, ready to be validated with real flight-surgeon input.

TOOLS AND TECHNOLOGIES
Python 3.13, PySide6 (Qt 6), VTK 9.7 (OpenGL), FastAPI, Uvicorn, SQLite (WAL), NumPy, Pydantic, faster-whisper, edge-tts, sounddevice, OpenCV (optional). Tablet mode over WebSocket with an HTML/JS client.
```

## Use of Super Intelligence (SI)

```
Yes. SI coding agents (the Antigravity agent and a second coding agent) wrote and refactored most of the Python code, the tests and the English documentation from prompts written by the team; the team directed every iteration, ran the software on a workstation and on a tablet, and reviewed the results. SI-assisted web research located official NASA and space-agency sources, which were verified against the original pages. Inside the product, an optional cloud or local language model only phrases explanations: it never decides a triage level, a validator rejects any number not present in the local data, and a deterministic fallback works offline. Speech uses edge-tts / Windows SAPI and local faster-whisper at run time.

The idea, scope, clinical indicators and thresholds were not delegated. No data, image or video in the repository was generated by SI (screenshots are captures of the running app) and no NASA branding is used. The complete, dated prompt record is public in docs/prompts/ and the disclosure in docs/AI_USE.md of the repository.
```

## NASA Data

```
1. NASA Open Science Data Repository (OSDR) — study OSD-575, Inspiration4 comprehensive metabolic panel
   https://osdr.nasa.gov/bio/repo/data/studies/OSD-575
   Real longitudinal blood chemistry of four crew members (17 analytes, 7 timepoints L-92 to R+194), normalised in recursos/datos/seed/osdr-inspiration4-cmp.json. Used for personal baselines, reference ranges, charts, OSD-575 replay mode and triage.

2. NASA Human Research Program — 5 Hazards of Human Spaceflight
   https://www.nasa.gov/hrp/hazards/
   Organising framework: every indicator maps to one of the five hazards.

3. NASA Human Research Program — Risks of Human Spaceflight
   https://www.nasa.gov/hrp/risks/
   Traces hazards to physiological risks and escalation criteria.

4. NASA HRP behavioral health and performance resources
   Basis of the Wellbeing module (reaction time, sleep, isolation and confinement); thresholds without a primary source are tagged [TO BE VALIDATED].
```

## Space Agency Partner Data and Other References

```
SPACE AGENCY PARTNER RESOURCES
- Canadian Space Agency, "Monitoring Radiation for Astronaut Health"
  https://www.asc-csa.gc.ca/eng/news/articles/2026/2026-02-26-monitoring-radiation-astronaut-health.asp
  Rationale for the cumulative radiation-dose indicator.
- Canadian Space Agency, "Why Do We Conduct Science Experiments in Space?"
  https://www.asc-csa.gc.ca/eng/eng/iss/science/why-do-we-conduct-science-experiments-in-space.asp

3D ANATOMY (CC BY 4.0)
- BodyParts3D, Database Center for Life Science; packaged by open-anatomy-3d (https://github.com/MervinR07/open-anatomy-3d)
- Human Reference Atlas 3D reference objects (HuBMAP), eyes by Kristen Browne (NIH/NIAID) — https://humanatlas.io/3d-reference-library
- Full credits: recursos/modelos/ATTRIBUTION.md

OPEN-SOURCE LIBRARIES
PySide6 (LGPLv3), VTK (BSD-3), FastAPI (MIT), Uvicorn (BSD-3), Pydantic (MIT), httpx (BSD-3), NumPy (BSD-3), faster-whisper (MIT), sounddevice (MIT), soundfile (BSD-3), edge-tts (GPLv3), websockets (BSD-3), OpenCV (Apache-2.0).

CONTENT
All clinical reference ranges are cited, or labelled [TO BE VALIDATED], in docs/INDICATORS.md and docs/DATA_SOURCES.md. No NASA logos or mission identifiers; no images of people under 18.
```

## Pre-submission checklist

- [ ] All fields in English; demo ≤ 30 s video or ≤ 7 slides (English or English subtitles), public link, no login.
- [ ] Both links open in a private window without registration; the repository is public.
- [ ] All team members are confirmed at the same Local Event.
- [ ] Terms and "Confirm All Work is Original" boxes ticked; banner confirms the submission.
