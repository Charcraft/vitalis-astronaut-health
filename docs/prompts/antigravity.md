# Prompts — Antigravity agent (Google Antigravity CLI)

Harness used for the **product build**: backend, assistant, native desktop port, integration of the teammates' backend, Wellbeing module and releases v1.0.0 → v1.2.0.
Sessions: `29fa4496` (Nov 14 afternoon), `10bbbb85` (Nov 14 evening – Nov 15 early), `fcd8028d` (Nov 15). Times are local (UTC−6). Original prompts are in Spanish (typos kept); API keys and e-mail addresses are redacted.

---

## Phase 1 — Design and first prototype (Nov 14, 12:33 – 15:21)

### AG-01 · 12:33 — Mock-up of the views in Figma
> **Original:** `[Figma URL] entra a este figma en conjunto y empieza a hacer las vistas de el proyecto de maquetado y deiseño sin molestar a los otros usuarios`
>
> **English:** Open this shared Figma file and start building the project's mock-up and design views without disturbing the other users.

**Produced:** the six-screen mock-up delivered as a Figma plugin (commit `706a7d4`, decision D24).

### AG-02 · 13:17 — Visual direction
> **Original:** `regeneralo, tiene que ser vista de dashboard, la vista del modelo 3D, sin ruido visual, maneja un color monocromatico, no satures la vision de los datos tiene que ser mas minimalistas, utiliza las skills de diseño, tienes que hacerlo de forma rapida`
>
> **English:** Regenerate it: it must be a dashboard view plus the 3D-model view, with no visual noise, monochrome colour, don't saturate the data — more minimalist; use the design skills and do it fast.

**Produced:** the monochrome, low-noise visual language that became `desktop/theme.py` (dark `#07080A/#0B0D11/#181B22` and light themes).

### AG-03 · 14:03 — Start the software and the NASA data pipeline
> **Original:** `hermano necesito que empieces a trabajar en el software, apegado al diseño que creaste necesito que investigues como utilizar la base de dat[os] de la nasa, revisa la forma optima sin hacerlo tardar, empieza a crearlo y hazlo de manera estructurada en el proyecto crea la carpeta correctamante`
>
> **English:** Start working on the software, faithful to the design you created. Research how to use NASA's database in the optimal way without slowing down, start building it in a structured way and create the folder properly.

**Produced:** the first working prototype (a web app, later archived) and the OSD-575 pipeline: `scripts/explorar-osdr.py`, `scripts/normalizar-osdr.py`, `recursos/datos/seed/osdr-inspiration4-cmp.json`.

### AG-04 · 14:50 — Stack brief for the two backend teammates
> **Original (abridged):** `necesito que sepas lo que tenemos pensado actualmente … el plan es que el software muestre en tiempo real los datos biologicos fisicos … necesito que generes en un solo md para darles el contexto de todo el stack teconlogico … dos seran el back … el md es para el agente. tambien … el software tiene que mostrar un modelo 3D del cuerpo Humano … se tienen que ver animaciones de cada herramienta util … implementaremos una inteligencia artificial que sirva de ayuda … la IA no es indispensable para el software y es añadido, preocupate en que sea adaptable y escalable por los parametros poco a poco que se van a integrar`
>
> **English (abridged):** Learn the current plan: the software shows physical/biological data in real time. Generate one Markdown file giving the whole technology-stack context to the team — two people will build the backend and database, and the file is for their agents. The software must show a 3D human body (so the backend must be ready to load it), clearly show the data, and play animations for each useful tool. An AI helper will be an add-on, not essential; make everything adaptable and scalable as parameters are integrated gradually.

**Produced:** `BRIEF-BACKEND-AGENTES.md` — the backend/DB/real-time/3D/optional-AI contract that shaped the plug-and-play parameter registry (`backend/registry.py`) and the later backend integration.

## Phase 2 — The assistant (AURA → L.I.S.) (Nov 14, 15:21 – 17:12)

### AG-05 · 15:21 — Requirements of the in-app agent
> **Original:** `tenemos visto que vamos a implementar una IA para que sea un agente dentro del proyecto que funcione como asistente que recuerde a cada astronauta, les de indicaciones utiles de acuerdo a la informacion de la base de datos, de indicaciones, tenga voz, y tenga una cara, … tiene que tener personalidad, seguridad de que responda correctamente en base a los datos, recuerde de forma real y no invente nada de los datos, sea un asistente y que sea capaz de pedir ayuda si es necesario dentro del software`
>
> **English:** We'll implement an AI as an agent inside the project: an assistant that remembers each astronaut, gives useful instructions based on the database, has a voice and a face and a personality; it must answer correctly from the data, remember for real and invent nothing, and be able to ask for help from within the software.

**Produced:** the grounding/memory/help-request design of the agent (decision D26) → `backend/lis_agent.py`, astronaut memory tables, `/api/help-requests`.

### AG-06 · 15:47 — Build the agent interface and test with real data
> **Original:** `necesito que vayamos creando a AURA, crea una interfaz de mientras, creale la cara y hagamos pruebas reales antes de implementarlo en el sowftware, carga un poco de la base de datos de la nasa que nos abrieron, para que tengamos ejemplos reales`
>
> **English:** Let's build AURA: create a stand-in interface and a face, and run real tests before implementing it in the software; load some of the NASA database so we have real examples.

**Produced:** a standalone agent test bench fed with OSD-575 samples.

### AG-07 · 16:02 — A floating, page-aware, controllable assistant
> **Original:** `cambia la cara imagen de AURA, necesito que AURA sea como tal un asistente flotante que sepa en que pagina estas y pueda navegar a la pagina que desees ver este siempre en escucha, sea capaz de controlar el software, sus configuraciones tienen que estar en una parte configurable de cada aspecto de AURA en el apartado de configuraciones de la app …`
>
> **English:** Change AURA's face. AURA must be a floating assistant that knows which page you are on, can navigate wherever you ask, is always listening and can control the software; every aspect must be configurable in the app's settings.

**Produced:** the floating dock that follows the user across views and the intent layer that drives navigation/settings (`desktop/lis_dock.py`, `AppState` control signals).

### AG-08 · 16:17 — Voice, personality and local-LLM compatibility
> **Original:** `revisa la voz de [my personal assistant] que tengo en mi pc … necesito que utilicemos esa voz …, mejores la diccion, velocidad, e interaccion, mas natural y humana … asistente coridal y formal, pero adaptada a nuestro proyecto dame una opcion de cara de astronauta, y tambien tiene que ser compatible con llms locales, y que se enseñe que modelo minimo necesario para que corra correctamente sin que de errores de invencion de datos`
>
> **English:** Check the voice of my personal assistant on my PC and reuse it; improve diction, speed and interaction to sound more natural and human, cordial and formal but adapted to our project; give me an astronaut-face option; it must work with local LLMs and show the minimum model needed to run without making up data.

**Produced:** text-to-speech pipeline with local fallbacks (`desktop/voice_engine.py`), local-LLM discovery with a minimum-model recommendation (`/api/local-llm`).

### AG-09 · 16:53 — Holographic face, project name, API-key auto-selection
> **Original:** `la cara de astronauta esta bien fea, hazla holografica tambien no como un humano solo un astronauta con cara pero no humana, … cambio el nombre completo del proyecto a V.I.T.A.L.I.S.: Vital Information Telemetry and Life-support In Space, necesito que mejores la informacion que muestras, quita el exceso de informacion y tiene que ser corta, tambien agrega que puedes agregar una api key y en automatico tome el mejor modelo de la api valido y util …`
>
> **English:** The astronaut face looks ugly: make it holographic, not human — an astronaut with a non-human face. The project's full name is now **V.I.T.A.L.I.S.: Vital Information Telemetry and Life-support In Space**. Cut excess information and keep it short; also let the user paste an API key and automatically pick the best valid model.

**Produced:** the project name and the holographic `RostroLIS` widget (`desktop/widgets.py`); `detectar_mejor_modelo_cloud()` (`/api/cloud-llm`).

### AG-10 · 17:12 — Agent name
> **Original:** `L.I.S. (Life-support In Space) este sera el nombre del Agente de IA de V.I.T.A.L.I.S` · **English:** L.I.S. (Life-support In Space) will be the name of V.I.T.A.L.I.S.'s AI agent.

**Produced:** the agent identity used everywhere (AURA → L.I.S.).

## Phase 3 — From a web prototype to a native desktop app (Nov 14, 17:55 – 18:37)

### AG-11 · 17:55 — Switch to Python and a native architecture
> **Original:** `necesito que armes el software completo que no sea una pagina web, que sea un software hecho correctamente, revisa el cambio correcto de lenguaje, utilizaremos python y haz correctamente el backend, que se mantenga la interfaz, y lo iremos mejorando, el panel principal debe mostrar el modelo 3D, implementemos todo y lo iremos mejorando poco a poco`
>
> **English:** Build the complete software — not a web page, a properly made application. Check the language change: we'll use Python; build the backend correctly, keep the interface, and the main panel must show the 3D model. Implement everything and improve it step by step.

**Produced:** `backend/` (FastAPI + SQLite + triage) in Python.

### AG-12 · 18:12 — Truly native
> **Original:** `el software tiene que ser nativo de pc no de chrome no tiene que ser web recuerda que correra localmente y se tiene que mostrar como una aplicacion real pasa todo lo que tenemos hasta ahora a una app real`
>
> **English:** The software must be native to the PC, not Chrome, not web — it runs locally and must look like a real application. Move everything we have so far into a real app.

**Produced:** the PySide6 + VTK desktop application (`vitalis_desktop.py`, `desktop/`) — decision D29; the web version was archived on branch `archivo/web`.

## Phase 4 — Agent quality and behaviour (Nov 14, 18:59 – 20:37)

### AG-13 · 18:59 — Improve the agent for the real problem
> **Original:** `ahora busca mejoras en el agente del software de acuerdo a la problematica` · **English:** Now look for improvements to the software's agent in line with the challenge.

**Produced:** grounding validator and deterministic fallback hardening.

### AG-14 · 19:13 — Configure the cloud model as default (key redacted)
> **Original:** `[REDACTED_API_KEY] ahi esta la api para el modelo necesito que la configures como predeterminada` · **English:** Here is the API key for the model; configure it as the default.

**Produced:** cloud model auto-selection from a user-provided key. **The key is stored only in the user's local settings and is never part of this repository.**

### AG-15 · 19:38 – 19:55 — Free control of the app, diction, floating panel UI
> **Original:** `necesito que revises que el modelo sea libre y controle todo el software correctamente` · `necesito que mejores la diccion y omitas que el modelo diga puntuaciones` · `mejora la UI del panel la cara del agente en el programa recuerda que tiene que ser flotante que te siga`
>
> **English:** Make sure the model can freely and correctly control the whole software; improve diction and stop it from reading out punctuation; improve the agent panel/face UI — it must float and follow you.

**Produced:** the broader command set of L.I.S., speech text normalisation (`normalizar_texto_para_voz`), the redesigned floating panel.

### AG-16 · 20:17 – 20:37 — Concise, non-technical language, screen awareness, settings
> **Original:** `tienes que mejorar las palabras y que la informacion sea concisa … no tiene que hablar con palabras tecnicas … que tiene que ser conciso pero sin que sea robotoci` · `revisa que el agente tenga la capacidad de ver que esta viendo el astronauta en la pantalla` · `coloca todas las opciones de configuracion utiles de lis, necesito que le coloques una voz opcional que sea mas rapida`
>
> **English:** Improve the wording: concise, no technical jargon, but not robotic. The agent must be able to see what the astronaut is looking at on screen. Add all useful L.I.S. settings, including an optional faster voice.

**Produced:** screen-context snapshot (`construir_snapshot_contexto`), L.I.S. configuration section, faster voice option.

## Phase 5 — Themes, voice and languages (Nov 14, 23:02 – 23:46)

### AG-17 · 23:02 — Dark and light modes
> **Original:** `agrega la configuracion de modo oscuro y modo claro y que se aplique correctamente` · **English:** Add dark/light mode settings and apply them correctly.

**Produced:** hot-swappable themes (`MainWindow.aplicar_tema`, `desktop/theme.py`).

### AG-18 · 23:16 — The agent can do everything the user can
> **Original:** `revisa todas las variables de coherencia del modelo, necesito que sea capaz de hacer todo lo que se le pida en el software, como pedirle que lea las instrucciones de uso de los protocolos de emergencia en voz alta, tambien revisa la herramienta de escuchar por microfono`
>
> **English:** Review all coherence variables of the model; it must be able to do whatever is asked in the software, such as reading emergency-protocol instructions aloud; also check the microphone-listening tool.

**Produced:** protocol read-aloud intents; local speech-to-text (`faster-whisper`).

### AG-19 · 23:46 — Bilingual speech
> **Original:** `enfocate completamente en que la voz de la IA separe correctamente el idioma en el que habla, haz que hable 2 idiomas en ingles y en español correctamente haz pruebas a fondo y rectifica todo que funcione correctamente`
>
> **English:** Focus entirely on the AI voice separating the language it speaks: make it speak two languages, English and Spanish, correctly; test thoroughly.

**Produced:** per-segment language detection and bilingual UI packs (`desktop/i18n.py`, `desktop/locales/en.json|es.json`) — decision D30.

## Phase 6 — Backend integration and v1.0.0 (Nov 15, 00:29 – 01:12)

### AG-20 · 00:29 / 00:41 — Integrate the teammates' backend
> **Original:** `revisa el repositorio y revisa la nueva estructura del backend, necesitamos implementar la estructura nueva, pintar las vistas que no se muestran con ese nuevo back y adaptarlo sin que se rompa cuidadosamente` · `no, sigue integrando el back cuidadosamente, sin romper nada, nosotros tenemos el front, tenemos que implementarlo correctamente y agregar las vistas de forma correcta a lo que tenemos`
>
> **English:** Review the repository and the new backend structure; implement it, paint the views that don't show with the new backend and adapt it carefully without breaking anything. — No: keep integrating the backend carefully; we own the front end, so implement it correctly and add the views properly to what we have.

**Produced:** `backend/database.py`, `registry.py`, `triage.py`, `realtime.py`, `crew_hub.py`, `sync_tierra.py`, `runtime.py`, `telemetry.py` and the Mission Control view (`desktop/vista_sala.py`) — decision D31.

### AG-21 · 01:09 — Release v1.0.0
> **Original:** `guarda la version correcamente como la version 1.0.0 y commitealo correctamente` · **English:** Save this properly as version 1.0.0 and commit it correctly.

**Produced:** commit `4b196ed` (`v1.0.0`).

## Phase 7 — Proactive assistance and alarms (Nov 15, 01:12 – 02:23)

### AG-22 · 01:12 — Declutter the 3D view
> **Original:** `listo ahora trabajemos en mejoras, la vista de los datos en la vista modelo 3D la informacion esta amontonada visualmente, arreglalo` · **English:** Now improvements: in the 3D model view the information is visually crowded — fix it.

**Produced:** redistributed labels/data in the 3D view (no overlaps).

### AG-23 · 01:29 — Yellow-state assistance
> **Original:** `necesito que ahora mejores la asistencia de la IA, necesito que cuando que los datos indiquen estado amarillo tambien avise como en estado de alerta roja, pero sin alarmar tanto y dando indicaciones de que puede hacer para que mejore su cuadro`
>
> **English:** Improve the AI assistance: when the data indicate a yellow state it should also warn, like in red alert but without alarming so much, and give indications of what can be done to improve the situation.

**Produced:** proactive calm warnings on yellow (`notificar_alerta_proactiva`).

### AG-24 · 01:47 / 02:01 — Red-state alarm and its settings
> **Original:** `para el modo emergencia estado rojo quiero que agreguemos una alarma con sonido intermitente que no alarme pero si de a entender la emergencia` · `agrega la config de la alarma en las configuraciones`
>
> **English:** For red emergency state, add an intermittent-sound alarm that doesn't panic but makes the emergency understood; add the alarm configuration to settings.

**Produced:** the soft intermittent red alarm with tone, volume, interval and silence controls (`desktop/voice_engine.py`, `desktop/main_window.py`, Settings).

### AG-25 · 02:10 — Consistency of the configured voice
> **Original:** `revisa porque al inyectar un estado critico contesta con una voz diferente a la configurada` · **English:** Check why, when injecting a critical state, it answers with a voice different from the configured one.

**Produced:** fix keeping the configured voice for proactive alerts (v1.1.0 notes).

## Phase 8 — Complete the views and live monitor (Nov 15, 02:23 – 03:54)

### AG-26 · 02:23 / 02:27 — Cover the whole data model
> **Original:** `ahora revisa la base de datos y analiza si nos falta alguna vista por mostrar de acuerdo a la maquetacion de la base de datos` · `implementemos una por una de manera correcta sin romper nada`
>
> **English:** Review the database and analyse whether any view is missing according to the database layout; implement them one by one without breaking anything.

**Produced:** `desktop/paneles_bd.py` — events & SBAR, mission log and Earth-queue panels.

### AG-27 · 03:06 — Live waveforms and hospital-style heartbeat audio
> **Original:** `en la vista de overview quiero que agregues graficas en tiempo real conectado a los datos de los parametros que se muestra en el apartado de donde se muestran los numeros, mostrados de fondo, agregues sonido en tiempo real como un hospital que se toman en tiempo real los datos importantes como la frecuencia cardiaca, y aumente la velocidad de acuerdo a al bpm`
>
> **English:** In Overview add real-time charts connected to the displayed parameters, shown behind the numbers; add real-time hospital-monitor sound for key data such as heart rate, speeding up with the BPM.

**Produced:** `QPainter` background waveforms and the BPM-synchronised monitor tone (`desktop/widgets.py`, `voice_engine.reproducir_latido_monitor`).

### AG-28 · 03:29 — Navigation, Mission Control layout, touch sizing
> **Original:** `quita la notificacion de monitor ya que eso ya lo hace el heart rate, tambien mejora la navegacion y interaccion dentro del software, acomoda de mejor manera Mission Control, una forma de ver y entender mejor que mueve cada informacion, sin saturarlo en una sola vista, de manera simple, la pestaña settings cambiala por un icono, y recuerda que todo tiene que ser adaptado para que sea touch tenlo en cuenta para el tamaño adecuado de interaccion con cada boton y visualizacion de textos`
>
> **English:** Remove the monitor notification (heart rate already does it); improve navigation and interaction; rearrange Mission Control so it is easier to understand what drives each piece of information, simply and without saturating one view; replace the Settings tab with an icon; everything must be touch-adapted, with adequate button and text sizes.

**Produced:** Mission Control in five touch steps, gear-icon Settings, ≥52 px touch targets.

### AG-29 · 03:54 — Release v1.1.0
> **Original:** `haz el commit a mi repositorio de nasa space apps actualiza completamente el repo con el estado actual real y la informacion que ya es una app utilizable` · **English:** Commit to my NASA Space Apps repository, fully updating it with the real current state, now a usable app.

**Produced:** commits `8298639`–`a7b7c36` (v1.1.0).

## Phase 9 — Wellbeing module and final fixes (Nov 15, 04:03 – 04:43)

### AG-30 · 04:03 — Add the emotional/behavioural module
> **Original:** `necesito ahora que revises la version que esta en descargas, esta version solo agrega la parte emocional/mental, necesito que agreguemos esta informacion pero a nuestro diseño actual de forma cuidadosa y que no se rompa`
>
> **English:** Review the version in Downloads — it only adds the emotional/mental part. Add this information into our current design carefully, without breaking it.

**Produced:** the Wellbeing (NASA BHP) module with 8 sub-modules (`desktop/salud_mental.py`, `evaluar_salud_mental_determinista`).

### AG-31 · 04:25 — Restore speech and alerts
> **Original:** `revisa porque ahora no habla ni da avisos de nada el agente, arreglalo y commitealo completo seria nuestra version final real` · **English:** Check why the agent no longer speaks or warns; fix it and commit everything — this would be our real final version.

**Produced:** voice/alert fixes and test isolation (release v1.2.0, commit `ba860cb`).

### AG-32 · 04:43 — Persistence and icon
> **Original:** `revisa la persisntencia de las configuraciones, y el icono del programa` · **English:** Check settings persistence and the program icon.

**Produced:** persistence fixes (`escalaUI`, voice, API key, factory reset) and a sharp multi-resolution icon.
