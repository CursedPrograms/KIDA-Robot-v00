# KIDA PowerShell Setup Script
# Windows Version: Creates Wi-Fi hotspot and Python environment

# Exit on any errors
$ErrorActionPreference = "Stop"

Write-Host "=== Setting up Python virtual environment ==="
python -m venv venv

Write-Host "=== Activating virtual environment ==="
& .\venv\Scripts\Activate.ps1

Write-Host "=== Installing Python requirements ==="
pip install -r requirements.txt
pip install -r gpio-requirements.txt

Write-Host "=== Creating Windows Wi-Fi hotspot ==="
# Enable hosted network (requires admin)
netsh wlan set hostednetwork mode=allow ssid=KIDAv00 key=12345678
netsh wlan start hostednetwork

Write-Host "=== Hotspot started: SSID=KIDAv00, Password=12345678 ==="

Write-Host "=== Starting KIDA Flask server ==="
python run.py