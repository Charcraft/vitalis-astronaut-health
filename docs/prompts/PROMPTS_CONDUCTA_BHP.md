# V.I.T.A.L.I.S. Desktop — Prompts Clave de Desarrollo
## Módulo de Salud Conductual y Rendimiento Operativo (NASA BHP)

Este documento recopila y analiza los **5 prompts más relevantes y determinantes** formulados durante el ciclo de diseño e implementación del módulo de Salud Conductual en **V.I.T.A.L.I.S. Desktop**. Cada una de estas directivas marcó un punto de inflexión arquitectónico, funcional o estético, transformando una idea inicial en una estación médica de grado aeroespacial.

---

## 1. El Mandato Fundacional: Salud Conductual y Gamificación de Misión
> **Prompt del usuario:**  
> *«okey ahora esa parte la hicieron compañeros pero ahora me toca mi parte ya esta la salud fisico ahora necesitamos hacer la salud mental de los astronautas»*  
> *(Complementado con: «Su herramienta podría incitar a los astronautas a tomar medidas o completar acciones específicas de vez en cuando como parte de la rutina de la misión. Un sistema de gamificación para ayudar a los astronautas a realizar tareas que apoyen su salud»)*

* **Contexto:** El sistema contaba con monitorización de signos vitales fisiológicos, pero carecía de una suite dedicada a la salud mental y psicológica para misiones de aislamiento prolongado.
* **Impacto técnico y arquitectónico:**
  - Nacimiento del módulo `desktop/salud_mental.py` bajo los lineamientos científicos de **NASA BHP (Behavioral Health and Performance)** y el estándar **NASA Human Research Program (HRP Hazard #2: Confinamiento)**.
  - Creación del subsistema de gamificación operativa (`backend/gamificacion_mental.py` y `data/gamificacion_mental.json`) con cálculo de puntaje diario (FRS), racha de misión y vitrina de insignias operativas.
* **Resultado:** Estableció los cimientos teóricos y clínicos de todo el módulo.

---

## 2. El Punto de Inflexión Arquitectónico: De "Vista Genérica" a 3 Columnas
> **Prompt del usuario:**  
> *«se ve asi muy IA aparte de que se sale de los margenes y todo va en una misma vista en ves de que se divida en secciones dentro del modulo para que veas masomenos como son los demas modulos te adjunto una foto»*

* **Contexto:** El primer prototipo presentaba un flujo vertical continuo ("scroll infinito") con tarjetas apiladas y márgenes desbordados, alejándose del lenguaje visual del resto del software.
* **Impacto técnico y arquitectónico:**
  - Reestructuración total a la arquitectura en **3 columnas simétricas** estándar de V.I.T.A.L.I.S.:
    1. **Columna izquierda (320 px):** Saludo y 4 filas de indicadores verticales con líneas de tendencia (Vigilancia PVT, Sueño circadiano, Preparación de vuelo FRS y Racha de misión).
    2. **Columna central (elástica):** `QStackedWidget` con subsecciones modulares gobernadas por una `BarraSegmentada` táctil inferior.
    3. **Columna derecha (330 px):** Tarjeta de Foco Clínico con dictamen de triage inmediato, reglas de vuelo operativas y monitor de enlace con la Tierra.
* **Resultado:** Eliminó la sensación de "código genérico" y armonizó la interfaz con el estándar aeroespacial del proyecto.

---

## 3. La Regla de Automatización: Rutina Reactiva Real (Sin Checklist Manual)
> **Prompt del usuario:**  
> *«ahora que la rutina de mision se vaya completando conforme vas haciendo la rutina no que tu lo puedas marcar como completado»*

* **Contexto:** Las tareas de rutina diaria tenían casillas de verificación que el tripulante podía pulsar libremente para sumar puntos sin haber completado las acciones.
* **Impacto técnico y arquitectónico:**
  - Eliminación del marcado manual o arbitrario ("hacer trampa").
  - Transformación del sistema en un **motor reactivo en tiempo real**:
    - La prueba de vigilancia psicomotora solo se valida al concluir el **Test PVT-B** o la **Batería Stroop**.
    - El ejercicio resistivo ARED se acredita al sincronizar telemetría de esfuerzo.
    - La hidratación de 2.5 L se valida mediante registro cefálico de volemia.
    - La descompresión cognitiva se completa al ejecutar el ciclo de respiración 4x4 o escuchar audio biofílico terrestre.
* **Resultado:** Rigor operativo e integridad de datos clínicos para el Oficial Médico (CMO).

---

## 4. Humanización y Estándar de Cabina: Bitácora Confidencial para Tablet
> **Prompt del usuario:**  
> *«okey ahora creo que la bitacora es de lo mas importante me gustaria que la desarrollaramos aun mas y que sea mas util para el astronauta mas personal que al momento de entrar al modulo de conducta lo reciba un ¡ Hola (nombre del astronauta! y su bitacora y los registros que ha hecho...»*  
> *(Y su refinamiento estético: «la bitacora no se ve como bitacora se ve como un formulario cualquiera no uses emojis y no amontones cosas por que quita los margenes»)*

* **Contexto:** La bitácora se asemejaba a una encuesta web comercial saturada de emojis informales y widgets apretados con colisiones visuales.
* **Impacto técnico y arquitectónico:**
  - Implementación del protocolo **NASA Crew Journal (Estudio de aislamiento Jack Stuster)**:
    - Saludo formal personalizado dinámico (ej. *«¡Hola, Comandante Connor!»*).
    - Eliminación total de emojis en favor de insignias monoespaciadas (`[ CONFIDENCIAL ]`, `[ SOL R+45 ]`).
    - Clasificación taxonómica en 5 ámbitos operativos (*Hábitat, Operaciones, Tripulación, Tierra, Descanso*) y 5 disposiciones anímicas.
    - Historial cronológico filtrable y contenedor con `QScrollArea` elástico, eliminando desbordamientos en tablets táctiles.
* **Resultado:** Un cuaderno de vuelo íntimo, respetuoso del secreto médico y cómodo para interacción táctil con guantes o dedos en microgravedad.

---

## 5. La Innovación de Espacio Profundo: Enlace DSN Asíncrono y Cápsula Terrestre
> **Prompt del usuario:**  
> *«okey alguna otra secccion que recomiendes poner? ya para terminar y dar un toque de creatividad e innovacion?»*  
> *(Seguido de la selección final: «esta bien la OPCION 1»)*

* **Contexto:** La mayoría de los módulos médicos en software de ciencia ficción asumen telecomunicaciones instantáneas irrealistas con la base en la Tierra.
* **Impacto técnico y arquitectónico:**
  - Incorporación de la física real de misiones interplanetarias a Marte:
    - **Retardo orbital:** Latencia de viaje de 14m 20s (28m 40s de RTT total).
    - **Red de Espacio Profundo (NASA DSN):** Sincronización con estación terrestre *Madrid DSS-63* y contador regresivo en vivo hacia la próxima ventana de pase de antena.
    - **Cápsula familiar entrante:** Reproductor táctil en cabina para audios recibidos desde Houston (*Hogar Connor*), con barra de avance y transcripción de voz confidencial.
    - **Terminal de grabación de salida:** Micrófono de cabina con vúmetro LED animado de 12 niveles, selector de canal seguro (Familia, Capcom, BHP), notas escritas y encolado cifrado RSA-4096.
* **Resultado:** Diferenciador de innovación y realismo aeroespacial que aporta el soporte afectivo y humano indispensable para la tripulación.

---

## Resumen Ejecutivo de Impacto

| Nº | Directiva Clave | Área de Impacto | Resultado en V.I.T.A.L.I.S. |
|---|---|---|---|
| **1** | Módulo de salud mental y gamificación | Dominio funcional y clínico | Implementación de NASA BHP, FRS, racha de misión e insignias. |
| **2** | Diseño en 3 columnas y subsecciones | Arquitectura de UI | 3 columnas estándar, `BarraSegmentada` táctil y tarjeta de foco. |
| **3** | Rutina reactiva sin marcado manual | Lógica de negocio y telemetría | Validación automática al completar tests o protocolos reales. |
| **4** | Cuaderno de bitácora sin emojis para tablet | Experiencia de usuario (UX) | NASA Crew Journal confidencial, ámbitos y diseño táctil limpio. |
| **5** | Enlace DSN asíncrono con retardo | Innovación y realismo científico | Comunicaciones por paquetes vía DSN, cápsulas de voz y vúmetro. |
