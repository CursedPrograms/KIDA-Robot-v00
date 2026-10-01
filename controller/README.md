# KIDA v00 — Remote Controller

The same window as the robot's `scripts/ui.py`, running on another PC.

It imports the robot's own `scripts/hud_layout.py` (layout + fonts) and
`scripts/render_helpers.py` (every draw call), so a visual change made once
shows up on both. Only the data source differs: camera, stats and state come
from the robot's Flask server (port 5003), and every key/click is sent back as
the same command string `ui.py` already processes.

## Run

```bash
./run.sh 192.168.1.50                 # Linux / macOS
run.bat 192.168.1.50                  # Windows
python main.py http://192.168.1.50:5003 --fullscreen
```

First run creates `controller/venv` with just `pygame` + `requests`.

## Controls (identical to ui.py)

| Key | |
|---|---|
| TAB / U / O / L | cycle mode / user / autonomous / line follow |
| M / Space | play music / stop music |
| W A S D (scheme 1) | drive — held keys are resent; release stops |
| Q A / W S (scheme 2) | left / right track |
| X / 1 / 2 | speed / WASD scheme / QA-WS scheme |
| C / V / S | photo / video on-off / save faces |
| Esc | close (the robot is told to stop) |

Mouse: the tabs, d-pad (hold to drive), speed 1–4, scheme, PHOTO/REC,
SAVE FACES/SCAN, PLAY/SKIP — all as on the robot.

The robot stops a remote drive it hasn't heard about for 0.8 s, so a dropped
connection or closed window never leaves it driving.
