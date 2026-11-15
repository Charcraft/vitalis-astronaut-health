# Prompts — Angel Marco Cobos (Backend 2: data layer, rules, persistence)

Harness used for the **deterministic data and rules layer** of V.I.T.A.L.I.S.
(AEGIS): the OSD-575 client, the reference thresholds, the pure triage engine,
the local persistence and sync queue, and the medical protocols.

- **Model:** DeepSeek V4 Pro.
- **Session:** 2026-11-14, 15:47 – 21:27 (local time, UTC−6).
- **Role:** "Backend 2" — everything that must be **deterministic and offline**:
  no network, no remote database, no AI in the critical path.

Each entry shows the original prompt (Spanish), an English translation, what it
produced, and why it evidences responsible use of Super Intelligence (SI).

---

## BA-01 · 15:47 — Split Backend 1 / Backend 2 (ownership, verified against the repo)

> **Original:** `revisa el estado REAL del repositorio con git ls-tree y git status, no te fíes de lo que dice el brief. Toma BRIEF-BACKEND-AGENTES.md y hazme un reparto de archivos por dueño: un archivo, un dueño, sin que dos personas sean dueñas del mismo. Detecta qué archivos NO existen todavía y cualquier desajuste de datos, por ejemplo cuántos indicadores trae realmente el seed. Devuélveme una tabla de dueños y una lista de discrepancias verificadas.`
>
> **English:** Check the REAL state of the repository with `git ls-tree` and
> `git status`; do not trust what the brief says. Take `BRIEF-BACKEND-AGENTES.md`
> and produce a per-file ownership split — one file, one owner, no two people
> owning the same file. Detect which files do not exist yet and any data
> mismatch, e.g. how many indicators the seed actually contains. Return an
> ownership table plus a list of verified discrepancies.

**Produced:** `docs/03-plan/10-reparto-backend.md` and
`team/angel_marco/plan-backend-2.md`; detected 10 files that did not exist and a
17-vs-19 indicator mismatch in the seed.

**Why it evidences responsible use:** the prompt forces the tool to ground the
plan in the actual repository state instead of trusting the brief — the split was
built on verified facts, not assumptions.

---

## BA-02 · 17:56 — Implement Backend 2 (deterministic, traceable, tested)

> **Original:** `implementa la capa de datos y reglas de Back 2 siguiendo team/angel_marco/plan-backend-2.md. Reglas duras: (1) cero cifras inventadas — todo umbral lleva su fuente trazable, y si no la hay se marca [SUPUESTO] o [POR VALIDAR]; (2) el evaluador de triage es una función pura, sin red, sin base de datos y sin IA; (3) contrasta los umbrales 1:1 contra el seed osdr-inspiration4-cmp.json y verifica con un script cuántas lecturas caen fuera de rango; (4) escribe tests para nominal, atención, crítico y borde exacto. No implementes la capa sync si Back 1 ya la va a cubrir.`
>
> **English:** Implement the Back 2 data and rules layer following
> `team/angel_marco/plan-backend-2.md`. Hard rules: (1) zero invented figures —
> every threshold carries its traceable source, otherwise mark it `[SUPUESTO]` or
> `[POR VALIDAR]`; (2) the triage evaluator is a pure function — no network, no
> database, no AI; (3) check the thresholds 1:1 against the
> `osdr-inspiration4-cmp.json` seed and verify with a script how many readings
> fall out of range; (4) write tests for nominal, attention, critical and exact
> boundary cases. Do not implement the sync layer if Back 1 already covers it.

**Produced:** `osdr/client.ts` (O(1) index + pre-flight baseline),
`rules/thresholds.ts` (traceable thresholds), `rules/triage.ts` (`evaluar`),
`db/{errors,types,dexie,repositories}.ts`, `ai/snapshot.ts`, `api/osdr` and
`api/ai-context` — 61 own tests, later 66/66.

**Why it evidences responsible use:** determinism and traceability are written
into the prompt itself. The triage engine stayed a pure, tested function; the
thresholds were validated 1:1 against the seed (24 out-of-range readings verified
by script); and no AI sits in the decision path.

---

## BA-03 · 20:15 — Medical protocols in plain language, sourced and flagged

> **Original:** `investiga en fuentes oficiales (NASA HRP — hazards y riesgos, y el dataset OSDR OSD-575) y redacta los 4 protocolos en lenguaje simple para tripulación no médica. Reglas: cita la fuente de cada paso; no recomiendes fármacos ni dosis; no emitas diagnósticos; marca como [POR VALIDAR] (validado: false) cualquier paso clínico que no respaldes con una fuente primaria. Si no encuentras fuente para algo, no lo escribas como hecho.`
>
> **English:** Research official sources (NASA HRP — hazards and risks, and the
> OSDR OSD-575 dataset) and write the 4 protocols in plain language for a
> non-medical crew. Rules: cite the source of each step; do not recommend drugs
> or doses; do not issue diagnoses; mark any clinical step you cannot back with a
> primary source as `[POR VALIDAR]` (`validado: false`). If you find no source for
> something, do not write it as fact.

**Produced:** `protocolos.json` (4 protocols), `knowledge/client.ts`
(`protocoloPara`/`listarProtocolos`), `api/protocolos` — 8 tests.

**Why it evidences responsible use:** the prompt enforces source citation, plain
language, and a ban on prescription/diagnosis; adapted clinical content is
explicitly flagged `[POR VALIDAR]` rather than asserted.

---

## BA-04 · 21:27 — Sex-specific reference ranges (only where it matters, no invention)

> **Original:** `implementa rangos de referencia por sexo biológico SOLO donde de verdad afecta (creatinina). Reglas: (1) no inventes ninguna cifra; (2) verifica la fuente por fetch (ej. UCSF Health) y registra la URL y la fecha de consulta; (3) si un parámetro solo es sexo-dependiente según una fuente sin cifras (ej. BUN), NO lo implementes y déjalo documentado; (4) marca los rangos como [POR VALIDAR] por la adaptación a contexto espacial. Escribe tests para ambos sexos.`
>
> **English:** Implement biological-sex reference ranges ONLY where it truly
> matters (creatinine). Rules: (1) invent no figures; (2) verify the source by
> fetch (e.g. UCSF Health) and record the URL and consultation date; (3) if a
> parameter is only sex-dependent per a source without figures (e.g. BUN), do NOT
> implement it and leave it documented; (4) mark the ranges `[POR VALIDAR]` due to
> the space-context adaptation. Write tests for both sexes.

**Produced:** the `Sexo` type and `rangoReferenciaPorSexo`; creatinine M/F range
(source UCSF Health, verified by fetch, `[POR VALIDAR]`); `tripulacion.json`
`[SUPUESTO]` + `sexoDe()` — 9 tests.

**Why it evidences responsible use:** the prompt forbids invention, requires
fetch-verification with URL and date, and prefers restraint (BUN left out because
its sex-dependence could not be confirmed with figures) over completeness.

---

## What these prompts collectively show

1. **Determinism where it matters.** Back 2 built the pure, testable core
   (triage, thresholds, persistence) with no AI in the decision path.
2. **No fabricated numbers.** "Cero cifras inventadas" and "sin inventar" are
   explicit requirements; unverified values are labelled, never asserted.
3. **Source integrity.** Thresholds, protocols and ranges are traced to cited,
   fetch-verified sources (NASA HRP, OSDR OSD-575, UCSF Health).
4. **Restraint.** Only what could be supported was implemented (BUN left out);
   adapted clinical content is flagged `[POR VALIDAR]`, never presented as fact.
