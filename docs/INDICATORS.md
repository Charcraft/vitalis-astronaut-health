# Physiological indicator catalogue

This document feeds the triage engine (`backend/registry.py` cites it as the traceable source of each threshold; the `§N` markers in the code refer to the indicator numbers below).

**Rule:** no threshold is presented as validated unless it has a primary source. Everything else is tagged `[TO BE VALIDATED]` (shown as `[POR VALIDAR]` in the Spanish UI/sources), `[ASSUMPTION]` or `[INFERENCE]`.

**Traffic light.** 🟢 green: within the crew member's usual range, no action. 🟡 yellow: outside the usual range → repeat the measurement, log context, tell the CMO. 🔴 red: outside the clinical range or abrupt change → start the protocol and contact the flight surgeon.

**Methodology note.** The app compares against the **personal baseline** of each crew member, not only population ranges, because "normal" ranges shift in microgravity and two healthy astronauts can have different baselines `[ASSUMPTION]`.

| # | Indicator | Unit | Hazard | Self-measurable | MVP priority |
|---|---|---|---|---|---|
| 1 | Resting heart rate | bpm | Gravity | Yes | High |
| 2 | Blood pressure | mmHg | Gravity | With cuff | High |
| 3 | Oxygen saturation (SpO₂) | % | Hostile/closed environment | Yes | High |
| 4 | Respiratory rate | breaths/min | Hostile/closed environment | Yes | Medium |
| 5 | Body temperature | °C | Environment / immune | Yes | High |
| 6 | Capillary glucose | mg/dL | Nutrition | With glucometer | Medium |
| 7 | Sleep | h | Isolation | Yes | High |
| 8 | Mood | scale | Isolation | Yes | High |
| 9 | Body mass | kg | Gravity | With space scale | Medium |
| 10 | Exercise load | min / kJ | Gravity | Yes | Medium |
| 11 | Accumulated radiation dose | mSv | Radiation | No (dosimeter) | Low |
| 12 | Visual acuity / symptoms (SANS) | — | Gravity | With optotype | Low |
| 13 | Reaction time (PVT) | ms | Isolation / radiation | Yes (on-screen test) | High |
| 14 | Hydration (urine colour) | scale 1–8 | Gravity | Yes | Low |
| 15 | Skin symptoms and lesions | text/image | Environment | Yes (camera) | Medium |

## Data sheets

### 1 · Resting heart rate (bpm)
* **How:** radial/carotid pulse for 30 s × 2, or chest strap; seated after 5 min of rest. In microgravity the crew member must be restrained to avoid floating and distorting the reading.
* **Why:** detects cardiovascular deconditioning, stress, fever, arrhythmia. In microgravity the heart becomes rounder and plasma volume drops.
* **Earth reference (adult, rest):** 60–100 bpm (athletes 40–60). **In flight:** resting HR tends to stay or fall slightly; a sustained rise is an alert `[TO BE VALIDATED]`.
* 🟢 50–90 and within ±10 of baseline · 🟡 90–110, >15 above baseline, or <50 in a non-athlete · 🔴 >110 at rest, <40, or palpable irregularity.

### 2 · Blood pressure (mmHg)
* **How:** arm cuff at heart level, seated, after 5 min, two readings 1 min apart. **Microgravity needs an automated device and an anchor point.**
* **Why:** cardiovascular risk is named in the challenge; also detects hypovolaemia and orthostatic intolerance.
* **Earth reference:** normal <120/<80 · elevated 120–129/<80 · stage 1 130–139/80–89 · stage 2 ≥140/≥90 · crisis ≥180/≥120. **In flight:** systolic often slightly lower; the real problem is orthostatic hypotension **on return** `[TO BE VALIDATED]`.
* 🟢 within ±15 mmHg of baseline and <140/90 · 🟡 change >15 mmHg or 140–179/90–119 · 🔴 ≥180/120, or <90/60 with symptoms.

### 3 · Oxygen saturation, SpO₂ (%)
* **How:** finger pulse oximeter, no nail polish, warm still hand; wait 30 s.
* **Why:** detects hypoxia from life-support failure, oxygen leak or lung problems — the most critical indicator in a closed environment.
* **Earth reference:** ≥95 % normal; 90–94 % needs attention; <90 % emergency. **In flight:** slightly lower readings possible (atelectasis) `[TO BE VALIDATED]`.
* 🟢 ≥95 % · 🟡 90–94 % or drop >3 points · 🔴 <90 % or abrupt drop >5 points → **hypoxia protocol**.

### 4 · Respiratory rate (breaths/min)
* **How:** count for 60 s at rest, without telling the subject. **Why:** early sign of hypoxia, acidosis, anxiety, infection. **Earth reference:** 12–20. **In flight:** no major change expected `[ASSUMPTION]`.
* 🟢 12–20 · 🟡 20–24 or 10–11 · 🔴 >24 or <10.

### 5 · Body temperature (°C)
* **How:** oral, tympanic or axillary — always the same route. **Why:** earliest sign of infection in a closed environment with altered microbiota and immunity. **Earth reference:** 36.1–37.2 °C oral. **In flight:** core temperature may be slightly raised at baseline `[TO BE VALIDATED]`.
* 🟢 36.0–37.3 · 🟡 37.4–38.0 · 🔴 >38.0 or <35.0.

### 6 · Capillary glucose (mg/dL)
* **How:** capillary glucometer, lateral fingertip, clean dry hands. **Why:** the challenge names inadequate nutrition; detects hypoglycaemia (dangerous in an EVA) and hyperglycaemia. **Earth reference (fasting):** 70–99 normal; 100–125 prediabetes; ≥126 diabetes; <70 hypoglycaemia. **In flight:** altered insulin sensitivity and diet `[TO BE VALIDATED]`.
* 🟢 70–140 · 🟡 141–180 or 60–69 · 🔴 >180, <60, or any value with symptoms.
* In the app, OSD-575 supplies the real reference range (65–99 mg/dL) and the personal baseline.

### 7 · Sleep (hours, quality 1–5)
* **How:** self-report on waking, optionally wrist actigraphy. **Why:** sleep deficit is the most accessible predictor of cognitive decline and operational error. **Reference:** 7–9 h. **In flight:** ISS crews sleep less than recommended on average `[TO BE VALIDATED]`.
* 🟢 7–9 h with quality ≥3 · 🟡 6–7 h or quality 2 · 🔴 <6 h, or <5 h several nights in a row.

### 8 · Mood
* **How:** a short 6-item questionnaire adapted from POMS (tension, depressed mood, anger, vigour, fatigue, confusion), scale 1–5, once a day. **Why:** the only indicator that directly covers isolation and confinement. **Reference:** no absolute "normal"; deviation from one's own baseline matters. `[INFERENCE]` — the exact scale must be chosen with a source.
* 🟢 no deviation · 🟡 1–2 point deviation sustained 3 days · 🔴 >2 points or negative ideation → intervention and psychological support.

### 9 · Body mass (kg)
* **How:** oscillation-based body mass measurement device in microgravity; conventional scale on the Moon/Mars. **Why:** unintentional loss reflects muscle/bone loss and calorie imbalance. **Reference:** <2 % weekly variation.
* 🟢 ±2 % · 🟡 2–4 % · 🔴 >4 % in a week or >7 % in a month. `[INFERENCE]` thresholds, to be validated.

### 10 · Exercise load (min, kJ)
* **How:** session log (exercise is both countermeasure and data). **Why:** main countermeasure against bone and muscle loss; its absence matters as much as an abnormal value. **Reference:** daily target from the mission countermeasure plan `[ASSUMPTION]`.
* 🟢 target met · 🟡 50–99 % · 🔴 <50 % for 3 days.

### 11 · Accumulated radiation dose (mSv)
* **How:** personal dosimeter reading (passive). **Why:** direct indicator of hazard #1. **Reference:** career limit to be set from a primary source `[TO BE VALIDATED]`.
* **Blocked until the official source is confirmed**; otherwise shown as an informational reading without a traffic light.

### 12 · Visual acuity and symptoms (SANS)
* **How:** fixed-distance acuity test with a printed/calibrated optotype plus a symptom questionnaire (blurred vision, flashes, headache). **Why:** Spaceflight-Associated Neuro-ocular Syndrome is among the best-documented long-mission complications.
* 🟢 no change · 🟡 one-line change or mild symptoms · 🔴 loss ≥2 lines or new persistent symptoms. `[TO BE VALIDATED]` — prevalence and criteria must be cited.

### 13 · Reaction time and sustained attention (ms, hit rate)
* **How:** 60–90 s on-screen test (PVT-B), same time each day. **Why:** detects fatigue, sleep deficit, CNS radiation effects and CO₂-related cognitive decline. **Reference:** individual baseline from the first 3 days.
* 🟢 within 10 % of baseline · 🟡 10–25 % slower · 🔴 >25 % slower or repeated errors. `[INFERENCE]` — calibrated against the person's own baseline, not an external table.

### 14 · Hydration (urine colour, 1–8)
* **How:** observation and selection in the app. **Why:** dehydration worsens orthostatic intolerance and renal-stone risk, a known in-flight risk.
* 🟢 1–3 · 🟡 4–5 · 🔴 6–8.

### 15 · Skin symptoms and lesions
* **How:** guided questionnaire (where, since when, itching/pain/discharge) plus optional camera photo. **Why:** the challenge mentions camera input; detects allergic reactions, skin infections and suit injuries.
* 🟢 mild and localised · 🟡 spreading or increasing · 🔴 with fever, blisters or breathing difficulty (possible anaphylaxis). `[INFERENCE]` — decision tree to be reviewed.

## What the app never does

* Diagnose.
* Say "you have an infection".
* Recommend a specific drug or dose.

It may say: *"this value, together with this one and this symptom, meets criteria for a flight surgeon to review immediately. Meanwhile, this is what you should do."*
