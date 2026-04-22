[![Twitter: @NorowaretaGemu](https://img.shields.io/badge/X-@NorowaretaGemu-blue.svg?style=flat)](https://x.com/NorowaretaGemu)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
  
 <div align="center">
  <a href="https://ko-fi.com/cursedentertainment">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="ko-fi" style="width: 20%;"/>
  </a>
</div>
<div align="center">
  <img alt="Python" src="https://img.shields.io/badge/python%20-%23323330.svg?&style=for-the-badge&logo=python&logoColor=white"/>
</div>

<div align="center">
  <img alt="Raspberry Pi" src="https://img.shields.io/badge/-Raspberry_Pi-323330?style=for-the-badge&logo=raspberry-pi&logoColor=white"/>

</div>

<div align="center">
  <img alt="Git" src="https://img.shields.io/badge/git%20-%23323330.svg?&style=for-the-badge&logo=git&logoColor=white"/>
  <img alt="Shell" src="https://img.shields.io/badge/Shell-%23323330.svg?&style=for-the-badge&logo=gnu-bash&logoColor=white"/>
</div>

---

# KIDA (v00): Kinetic Interactive Drive Automaton

## 📖 Overview

<details>
<summary><b>Overview</b></summary>

KIDA v00 is the foundational entry in the Kinetic series, built on the Raspberry Pi 3 Model B. v00 is a versatile teleoperated and autonomous scout designed for robust remote monitoring and computer vision tasks.

Core Features
- [x] Multi-Protocol Control: Web interface (Flask :5003), VNC, or direct keyboard control.
- [x] Live Camera Feed: MJPEG stream with photo capture and H264 video recording; files auto-download to the browser.
- [x] Always-On Face Analysis: DeepFace gender/age detection runs in a background thread during every mode — not a separate mode.
- [x] Reactive Autonomy: Ultrasonic obstacle avoidance and 3-channel infrared line follower.
- [x] QR Drive Mode: Point printed QR codes at the camera to drive, play music, switch modes, trigger light painting, dance, sleep, and more.
- [x] Dance Mode: Press the DANCE button or scan the DANCE QR code — KIDA plays music and performs a 20-step choreography (march, spins, moonwalk, finale) with HSV LED effects. Motors and LEDs are owned exclusively by the dance thread.
- [x] Sleep Mode: Low-power idle with amber LED breathing, camera suspended, face detection paused. Any key or QR code wakes it.
- [x] Light Painting: Long-exposure single-frame capture (5 / 10 / 20 s) with LED lockout; progress shown on screen and in the web UI.
- [x] Real Audio Waveform: `AudioAnalyzer` reads the current MP3 with pydub and streams RMS amplitude bars to the web UI via `/audio_amps` — no more fake sine wave.
- [x] WS2812 LED Strip (8 LEDs over SPI): Colour-coded direction feedback, rhythm pulse during music, amber breathing during sleep, HSV chase during dance.
- [x] Tank Control Scheme: Independent left/right motor control via QA / WS keys or the on-screen tank pad.
- [x] RIFT Integration: Zeroconf peer discovery; detects any service on `localhost:5000`.

</details>

---

<details>
<summary><b>Keybindings</b></summary>

### ⚙️ Control Scheme
* <kbd>1</kbd> **WASD mode** — coordinated steering
* <kbd>2</kbd> **Tank mode** — independent left / right motor control

### 🏎️ Movement Controls

| Input | **Mode 1: WASD** | **Mode 2: Tank** |
| :--- | :--- | :--- |
| <kbd>Q</kbd> | — | Left motor forward |
| <kbd>A</kbd> | Rotate left | Left motor backward |
| <kbd>W</kbd> | Move forward | Right motor forward |
| <kbd>S</kbd> | Move backward | Right motor backward |
| <kbd>D</kbd> | Rotate right | — |
| <kbd>X</kbd> | Cycle speed (0.4 → 0.6 → 0.8 → 1.0) | Same |

### 🤖 Mode Controls

| Input | Action |
| :--- | :--- |
| <kbd>TAB</kbd> | Cycle USER → AUTONOMOUS → LINE |
| <kbd>U</kbd> | User control mode |
| <kbd>O</kbd> | Autonomous obstacle-avoid mode |
| <kbd>L</kbd> | Line follower mode |

### 📷 Camera Controls

| Input | Action |
| :--- | :--- |
| <kbd>C</kbd> | Take photo (auto-downloads to browser) |
| <kbd>V</kbd> | Toggle video recording |

### 🎵 Media

| Input | Action |
| :--- | :--- |
| <kbd>M</kbd> | Play music |
| <kbd>Space</kbd> | Stop music |

### 💃 Dance & Sleep (web UI / QR / keyboard)

| Input | Action |
| :--- | :--- |
| <kbd>N</kbd> | Toggle dance mode |
| <kbd>P</kbd> | Toggle sleep mode |
| Any key (while sleeping) | Wake KIDA |

</details>

> [!TIP]
> Use **Mode 2** for heavy terrain or precise pivoting, and **Mode 1** for smooth, cinematic strafing.

---

## 📷 QR Drive Mode

<details>
<summary><b>QR Drive Mode — all codes and usage</b></summary>

Switch KIDA to **QR DRIVE** mode (tab in the web UI or `setMode('QR')`), then hold printed QR codes in front of the camera.

Generate printable PNG cards for all codes:
```bash
python generate_qr_codes.py          # saves to ./qrcodes/
python generate_qr_codes.py ./my/dir # custom output directory
```
Or open `http://<kida-ip>:5003/qr_codes` in a browser and print the page directly.

### HOLD actions — robot acts **while the QR code is visible**

| QR Code | Action |
| :--- | :--- |
| `KIDA:forward` | Drive forward |
| `KIDA:backward` | Drive backward |
| `KIDA:left` | Turn left |
| `KIDA:right` | Turn right |

### ONE-SHOT actions — fire **once per new detection**

| QR Code | Action |
| :--- | :--- |
| `KIDA:play_music` | Start playing music |
| `KIDA:stop_music` | Stop music |
| `KIDA:next_song` | Skip to next track |
| `KIDA:mode_user` | Exit QR mode → USER control |
| `KIDA:mode_autonomous` | Exit QR mode → obstacle-avoid |
| `KIDA:mode_line` | Exit QR mode → line follower |
| `KIDA:light_paint` | Trigger 10 s long-exposure shot |
| `KIDA:dance` | Toggle dance mode |
| `KIDA:sleep` | Enter sleep mode |
| `KIDA:wake` | Wake from sleep |
| `KIDA:stop` | Emergency stop |

QR decoding priority: **pyzbar** (faster) → **OpenCV QRCodeDetector** (fallback).

</details>

---

## 💃 Dance Mode

<details>
<summary><b>Dance Mode</b></summary>

Press the **♫ DANCE** button in the web UI, scan `KIDA:dance`, or press <kbd>N</kbd>.

- Music starts automatically.
- A 20-step choreography thread takes exclusive ownership of motors and LEDs.
- Sequence includes: march, side-shake, spin-out, charge-and-retreat, wiggle, moonwalk, and a finale spin.
- LED effects: HSV chase during spins, rainbow sweep during forward/backward, gentle breathe during stops.
- Dance auto-stops when the song ends.
- Main loop is completely hands-off while dance is active — user inputs and drive modes are suspended.

</details>

---

## 💤 Sleep Mode

<details>
<summary><b>Sleep Mode</b></summary>

Press the **💤 SLEEP** button in the web UI, scan `KIDA:sleep`, or press <kbd>P</kbd>.

- Motors stop immediately.
- Camera capture is suspended (saves CPU and battery).
- Face detection is paused.
- LEDs enter a slow **amber breathing** pattern (~0.25 Hz).
- Raspberry Pi pygame screen shows a minimal dark overlay with a pulsing KIDA logo.
- Wake: press **☀ WAKE** in the web UI, scan `KIDA:wake`, or press **any key** on a connected keyboard.

</details>

---

## Related Projects

- [KIDA-Robot-v01](https://github.com/CursedPrograms/KIDA-Robot-v01)
- [WHIP-Robot-v00](https://github.com/CursedPrograms/WHIP-Robot-v00)
- [NORA-Robot-v00](https://github.com/CursedPrograms/NORA-Robot-v00)
- [DREAM/ComCentre](https://github.com/CursedPrograms/DREAM)
- [RIFT](https://github.com/CursedPrograms/RIFT)

---

<div align="center">
  <img src="images/bg.jpg" alt="KIDA Robot" width="400"/>
</div>
<br>

## Prerequisites
<details>
<summary><b>Prerequisites</b></summary>

### Software
- [Raspberry Pi OS](https://www.raspberrypi.com/software/operating-systems/)

## Hardware

### Compute
| **Component** | **Details** |
|-----------|---------|
| Main Board | Raspberry Pi 3B |
| GPIO Hat | Freenove Tank Robot HAT v2 |

### Chassis & Motion
| **Component** | **Details** |
|-----------|---------|
| Chassis | Robot Tank Chassis |
| Motors | 2× 5v DC Motors |

### User Controllers
| **Component** | **Details** |
|-----------|---------|
| Interface | PC, Android, iPhone |
| Controller | Wireless Keyboard |

### Cameras
| **Component** | **Details** |
|-----------|---------|
| Camera 0 | Raspberry Pi Camera |

### Sensors
| **Component** | **Details** |
|-----------|---------|
| Ultrasonic Sensors | HC-SR04|
| Line Follower | 3-Channel Line Tracking Sensor |

### Power System
| **Component** | **Details** |
|-----------|---------|
| Battery | 2s 18650|

</details>

---

# Schematics
## ⚡ Technical Pinouts

> [!IMPORTANT]
> This section describes the GPIO pin assignments for the KIDA robot.


KIDA uses the V2 robot Hat from the [Freenove Tank Robot](https://github.com/Freenove/Freenove_Tank_Robot_Kit_for_Raspberry_Pi): 

<details>
<summary><b>Freenove Tank Robot HAT v2 GPIO Configuration</b></summary>

## Ultrasonic Sensor (HC-SR04)

| Signal       | GPIO Pin |
|-------------|----------|
| TRIGGER_PIN | 27       |
| ECHO_PIN    | 22       |

---

## Servos

| Signal       | GPIO Pin |
|-------------|----------|
| Servo0 | 12       |
| Servo1    | 13       |
| Servo1    | 19       |

---

## LEDpixel

| Signal       | GPIO Pin |
|-------------|----------|
| LEDpixel | 10      |

---

## Infrared Sensors

| Sensor | GPIO Pin |
|--------|----------|
| IR01   | 16  (IR01) |
| IR02   | 26  (IR02) |
| IR03   | 21  (IR03) |

---

## Motor Pins

**Left Motor:**

| Signal | GPIO Pin |
|--------|----------|
| IN1    | 23 (M1+) |
| IN2    | 24 (M1-) |

**Right Motor:**

| Signal | GPIO Pin |
|--------|----------|
| IN1    | 6  (M2+) |
| IN2    | 5  (M2-) |

</details>

*Note:* These pins correspond to the constructor defaults:

---

## 🌐 Connectivity & Controls

<details>
<summary><b>Connectivity & Controls</b></summary>

### Network Configuration
| Parameter | Value |
| :--- | :--- |
| **SSID** | `NORA` |
| **Password** | `12345678` |

* `localhost:5002`

### RIFT Integration
To connect via [RIFT](https://github.com/CursedPrograms/RIFT), ensure KIDA01 is active on:
* `localhost:5003`
- Opening this address in any web browser on the same network, will also launch the **HTML Remote Controller** for manual overrides.


</details>

---

<div align="center">
  <img src="images/screenshot.png" alt="KIDA Robot" width="600"/>
</div>
<br>

---

## Setup:

### Environment Setup

<details>
<summary><b>Environment Setup</b></summary>

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

</details>

---

## How to run:

<details>
<summary><b>How to run:</b></summary>

**1. Standard Execution**
- Run the main application using the Python interpreter:

```bash
python run.py
```

**2. Using Shell Scripts**
- If you prefer using shell scripts, first ensure the files have the necessary execution permissions:

```bash
chmod +x make_executables.sh
```

- To launch the main environment:

```bash
./run.sh
```

#### 🤖 Autonomous Behaviors
- To execute a single autonomous behavior, run the corresponding script:

#### Line Follower:

```bash
./run_linefollower.sh
```

#### Obstacle Detection:

```bash
./run_obstacle_detection.sh
```

</details>

*Note:* You can also just double click on any *.sh

> [!IMPORTANT]
> Ensure you have granted permissions via chmod before attempting to run the .sh files for the first time.

---

<br>
<div align="center">
© Cursed Entertainment 2026
</div>
<br>
<div align="center">
<a href="https://cursed-entertainment.itch.io/" target="_blank">
    <img src="https://github.com/CursedPrograms/cursedentertainment/raw/main/images/logos/logo-wide-grey.png"
        alt="CursedEntertainment Logo" style="width:250px;">
</a>
</div>
