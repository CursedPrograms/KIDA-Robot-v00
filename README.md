[![Twitter: @NorowaretaGemu](https://img.shields.io/badge/X-@NorowaretaGemu-blue.svg?style=flat)](https://x.com/NorowaretaGemu)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
  
  <br>
<div align="center">
  <a href="https://ko-fi.com/cursedentertainment">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="ko-fi" style="width: 20%;"/>
  </a>
</div>
  <br>

<div align="center">
  <img alt="Python" src="https://img.shields.io/badge/python%20-%23323330.svg?&style=for-the-badge&logo=python&logoColor=white"/>
</div>
<div align="center">
    <img alt="Git" src="https://img.shields.io/badge/git%20-%23323330.svg?&style=for-the-badge&logo=git&logoColor=white"/>
  <img alt="PowerShell" src="https://img.shields.io/badge/PowerShell-%23323330.svg?&style=for-the-badge&logo=powershell&logoColor=white"/>
  <img alt="Shell" src="https://img.shields.io/badge/Shell-%23323330.svg?&style=for-the-badge&logo=gnu-bash&logoColor=white"/>
  <img alt="Batch" src="https://img.shields.io/badge/Batch-%23323330.svg?&style=for-the-badge&logo=windows&logoColor=white"/>
  </div>
  <br>

# KIDA (v00): Kinetic Interactive Drive Automaton

- Pi 3
- Freenove Robotics Hat
- Ultrasonic Sensor
- PI Camera
- Line Follower
- 5v DC Motor

# KIDA Pinout Configuration

This document describes the GPIO pin assignments for the KIDA robot.

## Ultrasonic Sensor (HC-SR04)

| Signal       | GPIO Pin |
|-------------|----------|
| TRIGGER_PIN | 27       |
| ECHO_PIN    | 22       |

---

## Infrared Sensors

| Sensor | GPIO Pin |
|--------|----------|
| IR01   | 16       |
| IR02   | 26       |
| IR03   | 21       |

---

## Motor Pins

**Left Motor:**

| Signal | GPIO Pin |
|--------|----------|
| IN1    | 24       |
| IN2    | 23       |

**Right Motor:**

| Signal | GPIO Pin |
|--------|----------|
| IN1    | 5        |
| IN2    | 6        |

*Note:* These pins correspond to the constructor defaults:

```python
def __init__(self, left_pins=(24, 23), right_pins=(5, 6)):

📡 SSID: KIDAv00
🔒 Password: 12345678
🌐 Access your site at: http://192.168.4.1:5000

sudo apt update
sudo apt install hostapd dnsmasq -y

sudo systemctl stop hostapd
sudo systemctl stop dnsmasq

sudo nano /etc/dhcpcd.conf

sudo nano /etc/dhcpcd.conf

sudo nano /etc/hostapd/hostapd.conf

interface=wlan0
driver=nl80211
ssid=KIDAv00
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0

wpa=2
wpa_passphrase=12345678
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP

sudo nano /etc/default/hostapd

#DAEMON_CONF=""

DAEMON_CONF="/etc/hostapd/hostapd.conf"

sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak

sudo nano /etc/dnsmasq.conf

interface=wlan0
dhcp-range=192.168.4.2,192.168.4.50,255.255.255.0,24h

sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl enable dnsmasq


## How to Run:

```bash
python3 -m venv venv
source venv/bin/activate
```

### Install Requirements

Using Python directly:

```bash
pip install -r requirements.txt
```
Or run: 
- `install_requirements.bat`

  
  <br>

### Run main.py

Using Python directly:

```bash
python main.py
```

Using provided scripts:

Windows:
- `.\run.bat`
or
- `.\run.ps1`

Unix-like systems (Linux/macOS):
- `.\run.sh`
  <br>  

## Requirements:

```bash
pygame
numpy
psutil
pydub
gpiozero
av
python-prctl
Flask
Pillow
qrcode
spidev
tensorflow-aarch64

```

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
