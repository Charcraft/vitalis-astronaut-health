# tablet/ — V.I.T.A.L.I.S. on a tablet

The software (PySide6 + VTK + SQLite + L.I.S.) runs **entirely on the PC**; the tablet is its screen, touch, keyboard, speaker and microphone. There is no second interface: what you see on the tablet is the real window, with the **172 3D meshes**, all eight views, Wellbeing (NASA BHP), Mission Control, the L.I.S. panel, the red alarm and every setting.

## Use (Windows + tablet over USB)

1. On the tablet: *Settings → Developer options → USB debugging*, and accept the authorisation prompt.
2. Close the regular instance if it is open (both share `data/vitalis.db`).
3. Run `run-vitalis-tablet.bat` (or `python vitalis_tablet.py`).
4. Chrome opens on the tablet; tap **Iniciar** (full screen, landscape, sound and microphone).

Options: `--lan` (also listen on the local network without USB; open `http://<PC-IP>:8781` — no password, trusted networks only), `--mostrar-en-pc` (keep the app window visible on the PC), `--tam 2000x1200 --dpr 1.5` (force the tablet size), `--sin-adb`.

## How it works

| Piece | File | What it does |
|---|---|---|
| Launcher | `vitalis_tablet.py` | Reads the tablet's resolution and density through ADB, sets Qt's density to the tablet's (sharp text, no resampling), creates the real app, the server, the bridge and the audio redirection. "Restart" from Settings relaunches this launcher. |
| Qt bridge | `bridge.py` | Composes the window (dirty regions + VTK 3D + pop-up menus) and sends JPEG patches with acknowledgement-based flow control; maps touch, drag with inertia, pinch (3D zoom) and the Android keyboard to Qt events. |
| Server | `server.py` | FastAPI/uvicorn: page, WebSocket (`/ws?v=2`), a single active client. Listens on `127.0.0.1` only by default (USB with `adb reverse`). |
| Audio | `audio_bridge.py` | Replaces `sounddevice` so the BPM tone, red alarm, L.I.S. voice and soundscapes play on the tablet and dictation uses its microphone. |
| Client | `web/index.html` | Canvas, pointers, keyboard, Web Audio, microphone, full screen, reconnection. |
| ADB | `adb.py` | Detects the tablet, opens the USB tunnel and grants Chrome the microphone permission. |

## Tests and audit

* `python -m unittest tests/test_tablet.py -v` — touch, scrolling in lists, text entry, audio and microphone, protocol, and pixel-exact equivalence of partial repainting.
* `python scripts/auditoria_tablet.py` — opens all 29 views/sub-panels at touch-screen size and writes screenshots plus an overlap / clipping / touch-target report to `logs/auditoria-tablet/`. Current result: 0 overlaps, 0 clipped controls, 0 touch targets under 44 px.

## Known limits

* The tablet needs the PC (not a standalone Android app): the PC runs the backend, the 3D renderer and offline speech.
* *Settings → Text size* (`escalaUI`) does not apply in tablet mode: density is set by the tablet.
* The first use of the microphone may ask Chrome for permission once for `localhost`.
