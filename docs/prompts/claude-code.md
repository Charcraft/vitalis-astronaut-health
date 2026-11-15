# Prompts — Claude Code (Anthropic)

Harness used for the **3D anatomy, de-web-ification, touch UX, tablet version and delivery**. Sessions `1cdd536e` (Nov 14 evening – Nov 15 early) and `e8d6880d` (Nov 15). Times are local (UTC−6). Original prompts are in Spanish (typos kept); e-mail addresses are redacted. Only the prompts that created or reshaped a part of the project are listed.

---

## Phase 1 — 3D anatomical viewer (Nov 14, 18:49 – 20:12)

### CC-01 · 18:49 — Audit the 3D model and fill the gaps
> **Original:** `revisa el estado actual del modelo 3D revisa que este todo correctamente, los sistemas importantes del cuerpo humano, que esten todos los organos importantes hechos, te conectaras con el mcp de blender y haz los modelos de los organos que hagan falta`
>
> **English:** Check the current state of the 3D model: that everything is right, that the important body systems and all important organs exist; connect to the Blender MCP and build any missing organ models.

**Produced:** the audit of the 3D asset, and the decision to complement missing organs with open, licence-clean models (HuBMAP Human Reference Atlas, CC BY 4.0) instead of hand-made ones — see [`recursos/modelos/ATTRIBUTION.md`](../../recursos/modelos/ATTRIBUTION.md).

### CC-02 · 19:35 — Correct measurements and one view per system
> **Original:** `sigue revisando lo faltante, actualiza el modelo 3D y verifica medidas que se vean correctamente los organos, y sistemas, necesito que en el proyecto separe correctamente las vistas de cada sistema`
>
> **English:** Keep reviewing what's missing; update the 3D model and verify measurements so organs and systems display correctly; separate the views of each system properly in the project.

**Produced:** the six system views of the 3D body (cardiovascular, respiratory, neuro-ocular/SANS, metabolic-renal, musculoskeletal, immune-radiation) and the 172-mesh pack.

### CC-03 · 19:58 / 20:02 — Load and optimise the model in the desktop viewer
> **Original:** `en el proyecto de escritorio vitalis desktop revisa si ya cargaste correctamente el modelo` · `necesito que optimices el modelo 3D completo en la vista del programa, mejoralo y optimizalo`
>
> **English:** In the desktop project, check the model is loaded correctly; optimise the whole 3D model in the program's view and improve it.

**Produced:** `desktop/viewer3d.py` (VTK, 172 meshes), the binary mesh pack `desktop/assets/anatomy-male.{bin,json}`, depth-peeling/multisample tuning and the performance notes behind decision D34.

### CC-04 · 20:12 — Desktop is the product; archive the web version
> **Original:** `necesito que elimines todo el proyecto web, lo guardes pero no como principal ya que el principal es el de escritorio, asi que elimina todo guardalo por aparte todo el proyecto de web, pero eliminalo de la carpeta principal y solo nos quedamos con todo lo de escritorio`
>
> **English:** Remove the whole web project: save it separately but not as the main one, since the main one is the desktop app. Delete it from the main folder and keep only the desktop project.

**Produced:** the web prototype preserved on branch `archivo/web` (commit `b6b3b24`) and the repository reduced to the desktop product (commit `80a311b`, decision D29).

## Phase 2 — Clean, touch-first, alert-aware UI (Nov 14, 20:25 – 21:16)

### CC-05 · 20:25 — Declutter for astronauts, touch-only
> **Original:** `necesito que ahora quites ruido en el ui/ux dejalo mas limpio en el diseño solo los datos importantes, agregues todas las configuraciones utiles y necesarias en una seccion y muestres menos informacion, agrandando un poco las letras y datos que se muestran ya hecha la limpieza, para que sea una vista correcta para los astronautas, ya que esta pensada para que sea mas visual y el programa tiene que ser completamente touch`
>
> **English:** Remove UI/UX noise: a cleaner design with only the important data; put every useful setting in one section; show less information with slightly larger text and data, so it works for astronauts — it is meant to be visual and the program must be fully touch.

**Produced:** the single Settings view, larger typography and touch targets (`ALTO_TOQUE = 52`), the reduced Overview.

### CC-06 · 21:01 — Show the problem organs, alerts and calmer navigation
> **Original:** `necesito que optimices la forma de visualizar y que se muestre correctamente los organos que estan en el estado actual, haz crea notificaciones interactuables, que los organos que estan teniendo problemas resalten, optimiza el modelo 3D aun mas quita todo lo que no se necesite ver, mejora la forma la utilidad de navegacion del modelo que sea fijo para observar y no rote exageradamente el modelo y no sea tosco, mejoralo`
>
> **English:** Optimise how the organs in the current state are displayed; create interactive notifications; make organs that have problems stand out; optimise the 3D model further and remove anything unnecessary; improve navigation so the model is fixed for observation and doesn't rotate excessively or feel clumsy.

**Produced:** `desktop/avisos.py` (alert list, pop-up, per-alert actions *see in 3D / measure / protocol / mark reviewed*), organ pulsing in triage colour, and the observation camera (vertical-axis orbit with limits and eased transitions) in `viewer3d.py`.

### CC-07 · 21:16 — Coherence between model, alerts and triage colours
> **Original:** `revisa la coherencia del modelo con los avisos, mejora el sistema de notificaciones, y mejora aun mas que se muestren solo los organos si estan en un estado de necesidad mayor para que se de a entender que necesita atencion, tambien haz la muestra del estado con el triage muestreo de colores de estado, y que todo tenga coherencia, revisa que sea touch el proyecto, y busca mejoras y sigue mejorandolo de acuerdo a las necesidades reales de la problematica conforme a lo que ya hemos logrado`
>
> **English:** Check coherence between the model and the alerts; improve notifications and highlight organs only when need is greater so it is clear what needs attention; show state with the triage colour sampling; keep everything coherent and verify the project is touch-ready; keep improving it according to the real needs of the challenge.

**Produced:** one shared source of truth for alerts, 3D highlighting and the Overview summary (`backend/triage.py` levels → `desktop/avisos.py` → `viewer3d.marcar_problemas`), plus the touch-geometry regression tests.

## Phase 3 — Tablet version (Nov 15, 05:09)

### CC-08 · 05:09 — Run the app on the tablet
> **Original:** `tengo mi tablet conectada, quiero que la aplicacion corra en la tablet, optimizalo para el hardware y no dejes ninguna funcion fuera, hazlo correctamente y revisa que sea touch correctamente, las vistas no se solapen y todo coincida con el diseño original en desktop`
>
> **English:** My tablet is connected; I want the application to run on the tablet, optimised for the hardware, with no function left out. Do it properly and verify touch works, views don't overlap and everything matches the original desktop design.

**Outcome:** after reading the device over ADB and measuring that the UI is ~16 000 lines of Qt plus VTK and offline speech, the agent proposed a native Android port, a full web rewrite, or a **remote touch screen of the real app**. The last was chosen because it guarantees 100 % of the functions and the original design.
**Produced:** [`tablet/`](../../tablet/README.md) — dirty-region capture, JPEG over WebSocket, touch/keyboard/audio/microphone mapping, `tests/test_tablet.py` (16 tests) and `scripts/auditoria_tablet.py`, which found and fixed a real overlap in the *Measure* keypad at tablet height.
