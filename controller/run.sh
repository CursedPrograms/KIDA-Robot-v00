#!/bin/bash
# run.sh — launch the KIDA remote controller (creates its own venv on first run)
#
# Usage: ./run.sh <robot-ip-or-url> [--port 5003] [--fullscreen]
#    or: ROBOT_URL=http://192.168.1.50:5003 ./run.sh

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

python3 main.py "$@"
