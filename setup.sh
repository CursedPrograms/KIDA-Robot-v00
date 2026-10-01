#!/bin/bash
# KIDA Auto Setup Script
# Sets up virtualenv, installs packages, and configures Pi as hotspot KIDAv00

set -e  # Exit on any error

echo "=== Installing system packages (picamera2, ffmpeg, SPI/I2C) ==="
# gpio-requirements.txt is a shell script of apt/raspi-config steps, not a pip list
bash gpio-requirements.txt

echo "=== Setting up Python environment ==="
# psdenv is the environment run.sh uses; it needs the system site packages
# because picamera2 comes from apt
python3 -m venv --system-site-packages psdenv
source psdenv/bin/activate

echo "=== Installing Python requirements ==="
pip install -r requirements.txt

echo "=== Updating system and installing hotspot services ==="
sudo apt update
sudo apt install -y hostapd dnsmasq

echo "=== Stopping services temporarily ==="
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq

echo "=== Configuring static IP for wlan0 ==="
sudo bash -c 'cat >> /etc/dhcpcd.conf <<EOF

interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
EOF'

echo "=== Creating hostapd config ==="
sudo mkdir -p /etc/hostapd
sudo bash -c 'cat > /etc/hostapd/hostapd.conf <<EOF
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
EOF'

echo "=== Pointing hostapd to config ==="
sudo sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

echo "=== Backing up dnsmasq config and creating new one ==="
sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak
sudo bash -c 'cat > /etc/dnsmasq.conf <<EOF
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.50,255.255.255.0,24h
EOF'

echo "=== Enabling hotspot services ==="
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl enable dnsmasq
sudo systemctl restart dhcpcd
sudo systemctl restart hostapd
sudo systemctl restart dnsmasq

echo "=== Starting KIDA Flask server ==="
python3 run.py