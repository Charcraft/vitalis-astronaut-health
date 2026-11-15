# Demo video script — exactly 2:00

Timecoded narration for the guided tour (`python scripts/demo_tour.py`). The tour is light-themed, has no captions and runs exactly 120 seconds, so the narration can be recorded over it or read live. Speak in **English** (the NASA Space Apps form requires English; a Spanish voice-over needs English subtitles). About 270 words, ~2.3 words per second.

| Time | On screen | Narration |
|---|---|---|
| 0:00–0:03 | Title card | *V.I.T.A.L.I.S. — Vital Information Telemetry and Life-support In Space.* |
| 0:03–0:08 | Overview: live vitals with waveforms, 3D body turning, heartbeat tone | "It puts an astronaut's live vitals and a 3D body on one screen — fully offline, because on long missions Earth cannot always answer." |
| 0:08–0:21 | 3D Body: the six systems in turn | "Six body systems, each with indicators built on NASA's OSD-575 flight data. Touch one and the body reframes around it." |
| 0:21–0:34 | Ten organs, one by one: heart, lungs, liver, kidneys, brain, eyes, stomach, pancreas, intestine, bones | "Ten organs, from the heart to the brain and the eyes, each with its measurements and a traffic-light status." |
| 0:34–0:38 | Side view, layered view, zoom | "Side view, layers, zoom — all by touch." |
| 0:38–0:46 | Measure: keypad, 103 mg/dL, evaluation | "Measuring is guided, step by step for zero gravity. The reading is compared with the astronaut's own baseline." |
| 0:46–0:54 | Yellow warning, alert panel | "Now, a problem. A heart-rate drift raises a yellow warning — calm, with actions the astronaut can take." |
| 0:54–1:06 | Red state: lungs pulse, alarm, alert panel, protocol suggested | "Then oxygen saturation drops. The alert turns red, the lungs pulse, a soft intermittent alarm sounds, and the panel proposes the exact protocol." |
| 1:06–1:14 | Emergency: respiratory protocol, animated steps; SBAR sent | "Emergency mode opens the protocol, with animated steps adapted to zero gravity, and sends a structured SBAR report to Earth." |
| 1:14–1:32 | Cardiovascular (CPR metronome), neurological, trauma protocols | "Cardiovascular, neurological and trauma protocols follow — with a CPR metronome and clear, step-by-step guidance." |
| 1:32–1:42 | ALSP tools: defibrillator, IV access, airway, drugs | "Procedural animations show each tool: the defibrillator, IV access, the airway, and medication." |
| 1:42–1:48 | L.I.S. answers "Any anomalies?" | "L.I.S., the on-board assistant, summarises the situation using only local data — it never invents a number." |
| 1:48–1:52 | Mission Control: events and Earth queue | "Mission Control tracks the events and a prioritised queue to Earth." |
| 1:52–1:55 | Back to normal; Wellbeing (reaction test) | "When values recover, the system resets — and wellbeing tools keep the crew sharp." |
| 1:55–2:00 | Closing card with repository | "Measure, compare, decide, act. V.I.T.A.L.I.S. — open source, offline, for any mission." |

## Notes

* **Mission-agnostic:** if you want one extra sentence, add to 0:03–0:08: "…for a station, the Moon, Mars or deep space."
* **Not a medical device:** the closing card shows the disclaimer; do not describe the software as diagnosing.
* **SI disclosure:** if the narration is synthetic speech, say so in the project form (and, for video, a visible watermark is required for SI-generated *images or video*; the tour contains none).
* **Reproduce:** `python scripts/demo_tour.py` plays the same 120 s tour on a throw-away database; any screen recorder can capture it.
