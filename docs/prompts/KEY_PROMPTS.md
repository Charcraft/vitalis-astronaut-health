# Key prompts — hackathon evidence of Super Intelligence (SI) use

> A curated highlight of the prompts that most shaped **V.I.T.A.L.I.S.**, drawn verbatim from the full per-harness records in [`antigravity.md`](antigravity.md) and [`coding-agent-2.md`](coding-agent-2.md). This file exists to let a judge quickly verify **how** the team used SI tools: the team directed every step, the tools executed, and safeguards against fabricated data were explicit in the prompts themselves.

---

## How to read this file

Each entry shows the original prompt (Spanish, typos kept), an English translation, what it produced, and **why it is evidence of responsible use**. Full chronological detail and the remaining prompts are in the per-harness files.

---

## 1 · Product kickoff and the NASA data pipeline — `AG-03`

> **Original:** `hermano necesito que empieces a trabajar en el software, apegado al diseño que creaste necesito que investigues como utilizar la base de dat[os] de la nasa, revisa la forma optima sin hacerlo tardar, empieza a crearlo y hazlo de manera estructurada en el proyecto crea la carpeta correctamante`
>
> **English:** Start working on the software, faithful to the design you created. Research how to use NASA's database in the optimal way without slowing down, start building it in a structured way and create the folder properly.

**Produced:** the first prototype and the OSD-575 pipeline (`scripts/explorar-osdr.py`, `scripts/normalizar-osdr.py`, `recursos/datos/seed/osdr-inspiration4-cmp.json`).

**Evidence of good use:** the prompt anchors the work to real NASA data and asks for the optimal, structured approach — the team set the goal, the tool executed it.

---

## 2 · Architecture contract for the two backend teammates — `AG-04`

> **Original (abridged):** `necesito que generes en un solo md para darles el contexto de todo el stack teconlogico … el software tiene que mostrar un modelo 3D del cuerpo Humano … la IA no es indispensable para el software y es añadido, preocupate en que sea adaptable y escalable por los parametros poco a poco`
>
> **English:** Generate one Markdown file giving the whole technology-stack context … the software must show a 3D human body … an AI helper is an add-on, not essential; make everything adaptable and scalable as parameters are integrated gradually.

**Produced:** `BRIEF-BACKEND-AGENTES.md` — the plug-and-play contract behind `backend/registry.py`.

**Evidence of good use:** the team explicitly declared **AI as optional**, keeping the core product deterministic and human-owned.

---

## 3 · The in-app agent must never invent data — `AG-05`

> **Original:** `… tiene que tener personalidad, seguridad de que responda correctamente en base a los datos, recuerde de forma real y no invente nada de los datos, sea un asistente y que sea capaz de pedir ayuda si es necesario dentro del software`
>
> **English:** … it must have personality, be sure to answer correctly from the data, remember for real and **invent nothing from the data**, and be able to ask for help from within the software.

**Produced:** the grounding/memory/help-request design of **L.I.S.** (`backend/lis_agent.py`, the anti-hallucination validator).

**Evidence of good use:** the anti-fabrication requirement is written into the prompt itself — the strongest single piece of evidence of responsible SI use.

---

## 4 · Switch to Python and a native architecture — `AG-11`

> **Original:** `necesito que armes el software completo que no sea una pagina web, que sea un software hecho correctamente, revisa el cambio correcto de lenguaje, utilizaremos python y haz correctamente el backend, que se mantenga la interfaz`
>
> **English:** Build the complete software — not a web page, a properly made application … we'll use Python; build the backend correctly and keep the interface.

**Produced:** `backend/` (FastAPI + SQLite + deterministic triage) in Python.

**Evidence of good use:** a human architectural decision (offline-first, single process) made the team direct the tool, not vice versa.

---

## 5 · Truly native, not a browser app — `AG-12`

> **Original:** `el software tiene que ser nativo de pc no de chrome no tiene que ser web recuerda que correra localmente y se tiene que mostrar como una aplicacion real pasa todo lo que tenemos hasta ahora a una app real`
>
> **English:** The software must be native to the PC, not Chrome, not web — it runs locally and must look like a real application.

**Produced:** the PySide6 + VTK desktop application (`vitalis_desktop.py`, `desktop/`); the web version was archived on branch `archivo/web`.

**Evidence of good use:** a conscious scope/architecture decision (D29) owned by the team and executed by the tool.

---

## 6 · Integrate the teammates' backend without breaking anything — `AG-20`

> **Original:** `revisa el repositorio y revisa la nueva estructura del backend, necesitamos implementar la estructura nueva, pintar las vistas que no se muestran con ese nuevo back y adaptarlo sin que se rompa cuidadosamente` · `no, sigue integrando el back cuidadosamente, sin romper nada, nosotros tenemos el front`
>
> **English:** Review the repository and the new backend structure; implement it, paint the missing views and adapt it carefully without breaking anything. — No: keep integrating the backend carefully; we own the front end.

**Produced:** `backend/` modules and the Mission Control view (`desktop/vista_sala.py`).

**Evidence of good use:** collaborative human hand-off — the team merged two people's backend work, directing the tool to integrate rather than rewrite.

---

## 7 · Proactive but calm assistance on a yellow state — `AG-23`

> **Original:** `necesito que cuando que los datos indiquen estado amarillo tambien avise como en estado de alerta roja, pero sin alarmar tanto y dando indicaciones de que puede hacer para que mejore su cuadro`
>
> **English:** When the data indicate a yellow state it should also warn, like in red alert but without alarming so much, and give indications of what can be done to improve the situation.

**Produced:** proactive, calm, non-pharmacological guidance on yellow alerts.

**Evidence of good use:** the prompt encodes safety (no alarmism) and non-prescriptive guidance — clinical restraint by design.

---

## 8 · Add the Wellbeing module carefully — `AG-30`

> **Original:** `necesito ahora que revises la version que esta en descargas, esta version solo agrega la parte emocional/mental, necesito que agreguemos esta informacion pero a nuestro diseño actual de forma cuidadosa y que no se rompa`
>
> **English:** Review the version in Downloads — it only adds the emotional/mental part. Add this information into our current design carefully, without breaking it.

**Produced:** the Wellbeing (NASA BHP) module with 8 sub-modules (`desktop/salud_mental.py`).

**Evidence of good use:** a teammate's contribution integrated as a whole, preserving the existing design — collaborative, incremental.

---

## 9 · Audit the 3D model and fill gaps with open, licence-clean models — `CC-01`

> **Original:** `revisa el estado actual del modelo 3D revisa que este todo correctamente, los sistemas importantes del cuerpo humano, que esten todos los organos importantes hechos, te conectaras con el mcp de blender y haz los modelos de los organos que hagan falta`
>
> **English:** Check the current state of the 3D model … connect to the Blender MCP and build any missing organ models.

**Produced:** the audit of the 3D asset and the decision to complement missing organs with open, licence-clean models (HuBMAP Human Reference Atlas, CC BY 4.0) instead of hand-made ones.

**Evidence of good use:** the outcome prioritised correct licensing and verifiable sources over arbitrary generation — documented in `recursos/modelos/ATTRIBUTION.md`.

---

## 10 · The desktop app is the product; archive the web — `CC-04`

> **Original:** `necesito que elimines todo el proyecto web, lo guardes pero no como principal ya que el principal es el de escritorio … solo nos quedamos con todo lo de escritorio`
>
> **English:** Remove the whole web project: save it separately but not as the main one, since the main one is the desktop app.

**Produced:** the web prototype preserved on branch `archivo/web` and the repository reduced to the desktop product.

**Evidence of good use:** a product decision (D29) made by the team; the tool executed it without destroying prior work.

---

## 11 · Clean, touch-first UI for astronauts — `CC-05`

> **Original:** `necesito que ahora quites ruido en el ui/ux dejalo mas limpio … para que sea una vista correcta para los astronautas, ya que esta pensada para que sea mas visual y el programa tiene que ser completamente touch`
>
> **English:** Remove UI/UX noise … so it works for astronauts — it is meant to be visual and the program must be fully touch.

**Produced:** the single Settings view, larger typography and `≥ 52 px` touch targets.

**Evidence of good use:** the prompt grounds design in the real user (an astronaut in microgravity) — human-centred requirements, not decorative ones.

---

## 12 · Run on the tablet with nothing left out — `CC-08`

> **Original:** `tengo mi tablet conectada, quiero que la aplicacion corra en la tablet, optimizalo para el hardware y no dejes ninguna funcion fuera`
>
> **English:** My tablet is connected; I want the application to run on the tablet, optimised for the hardware, with no function left out.

**Produced:** after measuring the device, the agent proposed a native port, a web rewrite, or a **remote touch screen of the real app**; the last was chosen — `tablet/` with dirty-region capture and full touch/audio/microphone mapping.

**Evidence of good use:** the tool surfaced options with trade-offs and the team chose the one that preserved 100 % of the functions — no scope was silently dropped.

---

## What these prompts collectively show

1. **Human direction, not AI ideation.** The challenge, the product concept and the scope came from the team; every prompt is the team steering the tool toward a concrete, already-decided goal.
2. **No fabricated data.** The strongest prompt (`AG-05`) makes "invent nothing from the data" an explicit requirement, and the triage engine stayed a pure, tested function.
3. **Clinical restraint.** Prompts asked for calm, non-prescriptive, non-alarming guidance; dosis and thresholds are labelled `[TO BE VALIDATED]`, never asserted.
4. **Licensing and source integrity.** The 3D work prioritised open, verifiable, licence-clean assets over generated ones.
5. **Collaboration.** Prompts repeatedly integrate teammates' work "carefully, without breaking anything", preserving authorship and prior decisions.

The complete record — every prompt in chronological order, with what each one produced — is in [`antigravity.md`](antigravity.md) and [`coding-agent-2.md`](coding-agent-2.md).
