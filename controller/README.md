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
| W+A, W+D, S+A, S+D | arc turn while ARC is on (inside wheel slows to 40% instead of stopping); straight while it's off |
| Q A / W S (scheme 2) | left / right track |
| X / 1 / 2 / T | speed / WASD scheme / QA-WS scheme / ARC on-off |
| C / V / F | photo / video on-off / save faces |
| Esc | close (the robot is told to stop) |

Mouse: the tabs, d-pad (hold to drive), on-screen joystick (drag; release
stops), speed 1–4, scheme + ARC, PHOTO/REC, SAVE FACES/SCAN, PLAY/SKIP — all
as on the robot.

Gamepad (Xbox, PlayStation, Switch Pro, most others; plug in any time) — the
same on the robot, this controller and the web dashboard:

| Button | |
|---|---|
| Left stick | drive (analog) — both sticks drive the tracks in the QA/WS scheme |
| D-pad | drive like WASD (arc turns follow ARC) |
| A / B | cycle speed / stop (back to USER mode) |
| X / Y | photo / ARC on-off |
| LB / RB | previous / next mode |
| Back / Start | save faces / play-pause music |

The controller keeps reading the gamepad while another window is focused.
In the web dashboard, press a gamepad button once with the page open — browsers
only report a pad after that.

The robot stops a remote drive it hasn't heard about for 0.8 s, so a dropped
connection or closed window never leaves it driving.
